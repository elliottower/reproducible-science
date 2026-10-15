"""What the two writing workflows do: post the findings, and record a reply.

`post` runs in the workflow `workflow_run` starts after the check, with the findings the check
uploaded. It trusts nothing in them to say which pull request they are about: the number they
give is looked up, and the pull request's head commit must be the commit the check ran on.

`reply` runs on `issue_comment` and `pull_request_review_comment`. It reads the event and the
API, and never the pull request's files except `repro.yaml`, which it reads as data and edits as
text. Neither checks out or executes anything from the pull request.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from repro.bot import setaside
from repro.bot.comments import (
    NOT_ALLOWED,
    NOT_AN_ANSWER,
    Answer,
    Decision,
    Marker,
    decode,
    headline,
    option,
    parse,
    refers_to,
    render,
)
from repro.bot.findings import Finding, Findings, manifest_path
from repro.bot.github import WRITERS, Client, Comment, GitHubError, Pull
from repro.exceptions import ReproError

#: Attempts at committing `repro.yaml` when the branch moves between reading and writing it.
ATTEMPTS = 3
_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


class NotThisRunError(ReproError):
    """The findings do not belong to the pull request they name, at the commit checked."""

    def __init__(self, detail: str) -> None:
        super().__init__(f"{detail}; nothing was posted.")


class Posted(BaseModel):
    """What one `post` did, by comment."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    created: tuple[str, ...] = ()
    edited: tuple[str, ...] = ()
    unchanged: tuple[str, ...] = ()
    fork: bool = False
    problem: str = ""


class Replied(BaseModel):
    """What one `reply` did."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    done: Literal["skipped", "not ours", "not an answer", "not allowed", "recorded"]
    said: str = ""
    committed: str = ""


# -------------------------------------------------------------------------------------- diff


def lines(patch: str) -> set[int]:
    """The lines of the new file a review comment can be placed on: each added or unchanged
    line a hunk of the patch shows."""
    found: set[int] = set()
    at = None
    for row in patch.splitlines():
        if hunk := _HUNK.match(row):
            at = int(hunk[1])
        elif at is not None and not row.startswith(("-", "\\")):
            found.add(at)
            at += 1
    return found


# ------------------------------------------------------------------------------ the comments


def ours(comments: list[Comment]) -> dict[str, tuple[Comment, Marker]]:
    """The comments the bot opened, by the key of the assertion each is on. A reply in a
    thread is not one: it carries no marker. The first comment holding a key is the one."""
    found: dict[str, tuple[Comment, Marker]] = {}
    for comment in comments:
        if not comment.by_bot or comment.in_reply_to is not None:
            continue
        if (marker := decode(comment.body)) is not None:
            found.setdefault(marker.key, (comment, marker))
    return found


def _marker(
    made: Finding,
    placed: Literal["review", "issue"],
    fork: bool,
    manifest: str,
    before: Marker | None,
) -> Marker:
    # An answer is about what was found. Where the finding changed, it no longer holds.
    kept = before.decision if before is not None and before.digest == made.digest else None
    return Marker(
        claim=made.claim,
        assertion=made.assertion,
        key=made.key,
        digest=made.digest,
        headline=headline(
            made.label, made.kind, made.printed, made.stored, made.file, made.passage
        ),
        option=option(made.kind, made.stored, made.passage),
        placed=placed,
        fork=fork,
        manifest=manifest,
        artifact=made.artifact,
        text=made.text,
        decision=kept,
    )


def post(findings: Findings, client: Client, head_sha: str) -> Posted:
    """Comment on each finding, once: a comment already open on the same assertion is edited
    where what it says has changed, and one on an assertion that now passes is marked fixed."""
    if findings.head_sha != head_sha:
        raise NotThisRunError(
            f"the findings are of {findings.head_sha[:7]}, and the run checked {head_sha[:7]}"
        )
    pull = client.pull(findings.pull_request)
    if pull.head_sha != head_sha:
        raise NotThisRunError(
            f"pull request #{pull.number} is at {pull.head_sha[:7]}, not {head_sha[:7]}"
        )
    if findings.problem:
        return Posted(problem=findings.problem)
    fork = pull.head_repository != client.repository
    number = pull.number
    held = ours(client.review_comments(number) + client.issue_comments(number))
    placeable = (
        {path: lines(patch) for path, patch in client.patches(number).items()} if not fork else {}
    )

    created, edited, unchanged = [], [], []
    for made in findings.findings:
        comment, before = held.pop(made.key, (None, None))
        placed: Literal["review", "issue"]
        if before is not None:
            placed = before.placed
        elif made.path is not None and made.line in placeable.get(made.path, ()):
            placed = "review"
        else:
            placed = "issue"
        marker = _marker(made, placed, fork, findings.manifest, before)
        body = render(marker)
        if comment is None:
            if placed == "review":
                client.comment_on_line(number, body, head_sha, made.path or "", made.line or 1)
            else:
                client.comment(number, body)
            created.append(made.key)
        elif comment.body != body:
            client.edit(comment, body)
            edited.append(made.key)
        else:
            unchanged.append(made.key)

    for key, (comment, before) in held.items():
        if key in findings.set_aside:
            update: dict[str, Any] = {"state": "set-aside"}
        elif key in findings.checked:
            update = {"state": "fixed"}
            if before.state != "fixed":
                update["fixed_at"] = head_sha
        else:
            update = {"state": "gone"}
        body = render(before.model_copy(update=update))
        if comment.body != body:
            client.edit(comment, body)
            edited.append(key)
        else:
            unchanged.append(key)
    return Posted(
        created=tuple(created), edited=tuple(edited), unchanged=tuple(unchanged), fork=fork
    )


# --------------------------------------------------------------------------------- a reply


def _thread(
    event_name: str, event: dict, client: Client
) -> tuple[int, Comment, Marker, list[Comment]] | None:
    """The pull request, the bot's comment a reply answers, its marker, and every reply in its
    thread oldest first; None where the reply is in no thread of the bot's."""
    reply = Comment.read(
        "review" if event_name == "pull_request_review_comment" else "issue", event["comment"]
    )
    if event_name == "pull_request_review_comment":
        number = event["pull_request"]["number"]
        if reply.in_reply_to is None:
            return None
        root = client.review_comment(reply.in_reply_to)
        marker = decode(root.body) if root.by_bot and root.in_reply_to is None else None
        if marker is None:
            return None
        thread = [c for c in client.review_comments(number) if c.in_reply_to == root.id]
    elif event_name == "issue_comment":
        if not event.get("issue", {}).get("pull_request"):
            return None
        number = event["issue"]["number"]
        everything = client.issue_comments(number)
        found = [
            (comment, marker)
            for comment, marker in ours(everything).values()
            if marker.placed == "issue" and refers_to(reply.body, marker.ref)
        ]
        if len(found) != 1:
            # None, or a reply quoting two of the bot's comments, which answers neither.
            return None
        root, marker = found[0]
        thread = [c for c in everything if not c.by_bot and refers_to(c.body, marker.ref)]
    else:
        return None
    if all(c.id != reply.id for c in thread):
        thread.append(reply)
    thread.sort(key=lambda c: (c.created_at, c.id))
    return number, root, marker, thread


def latest(thread: list[Comment], ref: str, client: Client) -> tuple[Comment, Answer, str] | None:
    """The latest reply in a thread that gives an answer and is from someone with write
    access: the one that holds."""
    allowed: dict[str, bool] = {}
    for comment in reversed(thread):
        if comment.bot or (given := parse(comment.body, ref)) is None:
            continue
        if comment.login not in allowed:
            allowed[comment.login] = client.permission(comment.login) in WRITERS
        if allowed[comment.login]:
            return comment, given.answer, given.reason
    return None


def _commit(client: Client, pull: Pull, path: str, change, message: str) -> str:
    """Read `path` on the pull request's branch, apply `change` to its text, and commit what
    it returns; the commit's sha, or "" where `change` returns None. A branch that moved
    between the read and the write is read again."""
    for attempt in range(ATTEMPTS):
        content, blob = client.file(path, pull.head_ref)
        source = content.decode("utf-8")
        changed = change(source)
        if changed is None:
            return ""
        try:
            return client.put_file(path, changed.encode("utf-8"), blob, pull.head_ref, message)
        except GitHubError as refused:
            if refused.status not in (409, 422) or attempt == ATTEMPTS - 1:
                raise
    return ""


def reply(event_name: str, event: dict, client: Client) -> Replied:
    """Read one reply and record the answer that holds in its thread."""
    comment = event.get("comment") or {}
    if (comment.get("user") or {}).get("type") == "Bot":
        return Replied(done="skipped")
    found = _thread(event_name, event, client)
    if found is None:
        return Replied(done="not ours")
    number, root, marker, thread = found
    reply_id = comment["id"]

    def answer(text: str) -> None:
        if root.kind == "review":
            client.reply_on_line(number, root.id, text)
        else:
            client.comment(number, f"`{marker.ref}` {text}")

    given = parse(comment.get("body") or "", marker.ref)
    if given is None:
        answer(NOT_AN_ANSWER)
        return Replied(done="not an answer", said=NOT_AN_ANSWER)
    login = (comment.get("user") or {}).get("login", "")
    if client.permission(login) not in WRITERS:
        answer(NOT_ALLOWED)
        return Replied(done="not allowed", said=NOT_ALLOWED)
    holding = latest(thread, marker.ref, client)
    if holding is None or holding[0].id != reply_id:
        # A later reply was already recorded, or this one is not in the thread as read.
        return Replied(done="skipped")
    by, chosen, reason = holding

    pull = client.pull(number)
    fork = pull.head_repository != client.repository
    committed, note = "", ""
    if chosen.sets_aside and fork:
        note = "; this pull request comes from a fork, so nothing was committed"
    elif chosen.sets_aside and not (marker.artifact and marker.text):
        note = (
            f"; {marker.manifest} names no passage of the manuscript for this claim, so no "
            "set_aside entry was written"
        )
    elif marker.artifact and marker.text and not fork:
        path = manifest_path(marker.manifest)
        if chosen.sets_aside:
            made = setaside.entry(
                marker.artifact,
                marker.text,
                number,
                chosen.recorded,
                reason,
                by.login,
                by.created_at,
            )
            committed = _commit(
                client,
                pull,
                path,
                lambda source: (
                    None
                    if setaside.holds(source, marker.artifact, marker.text)
                    else setaside.added(source, made)
                ),
                f"{path}: set aside claim {marker.claim} ({chosen.recorded} by @{by.login} "
                f"on #{number})",
            )
            note = f"; set_aside entry committed in {committed[:7]}" if committed else ""
        else:
            committed = _commit(
                client,
                pull,
                path,
                lambda source: setaside.removed(source, marker.artifact, marker.text),
                f"{path}: claim {marker.claim} is no longer set aside "
                f"({chosen.recorded} by @{by.login} on #{number})",
            )
            note = f"; the set_aside entry was removed in {committed[:7]}" if committed else ""

    decision = Decision(
        answer=chosen,
        reason=reason,
        by=by.login,
        at=by.created_at,
        reply=by.id,
        committed=committed if chosen.sets_aside else "",
    )
    state = marker.state
    if chosen.sets_aside and committed:
        state = "set-aside"
    elif not chosen.sets_aside and state == "set-aside":
        state = "open"
    updated = marker.model_copy(update={"decision": decision, "state": state})
    if render(updated) != root.body:
        client.edit(root, render(updated))
    said = f"recorded: {chosen.recorded} by @{by.login}{note}"
    answer(said)
    return Replied(done="recorded", said=said, committed=committed)


__all__ = [
    "NotThisRunError",
    "Posted",
    "Replied",
    "latest",
    "lines",
    "ours",
    "post",
    "reply",
]
