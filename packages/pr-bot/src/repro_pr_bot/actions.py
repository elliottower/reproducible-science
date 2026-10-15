"""What the two writing workflows do: post the findings, and record the answers.

`post` runs in the workflow `workflow_run` starts after the check, with the findings the check
uploaded. It trusts nothing in them to say which pull request they are about: the pull request
they name must be at the commit the check ran on, from the repository and branch the run was
of, and they must be about the manifest the workflow names.

`reply` runs on `issue_comment` and `pull_request_review_comment`. It reads the event and the
API, and of the pull request's files only the manifest the workflow names, which it reads as
data and edits as text. Neither checks out or executes anything from the pull request.

Two runs can overlap, and GitHub cancels a run that waits behind another of its concurrency
group. So `reply` records every answer that holds on the pull request and is not yet in its
comment, not only the one that started it, and nothing is ever replaced by an older answer:
a run cancelled, or one that read a thread before a later reply landed, loses nothing.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any, Literal

from claims.exceptions import ReproError
from pydantic import BaseModel, ConfigDict

from repro_pr_bot import setaside
from repro_pr_bot.comments import (
    NOT_ALLOWED,
    NOT_AN_ANSWER,
    SET_ASIDE,
    Answer,
    Decision,
    Marker,
    asks,
    clean,
    decode,
    headline,
    option,
    parse,
    refers_to,
    render,
)
from repro_pr_bot.findings import Finding, Findings, manifest_path
from repro_pr_bot.github import WRITERS, Client, Comment, GitHubError, Pull

#: Attempts at committing the manifest when the branch moves between reading and writing it.
ATTEMPTS = 3
#: The caller workflow `repro ci init --pr-bot` writes for the check, which `reply` starts again
#: after a commit, naming the pull request.
CHECK_WORKFLOW = "repro-pr-bot.yml"
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
    notes: tuple[str, ...] = ()
    """What could not be done and did not stop the run, such as resolving a thread."""


class Replied(BaseModel):
    """What one `reply` did."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    done: Literal["skipped", "not ours", "not an answer", "not allowed", "recorded"]
    said: str = ""
    committed: str = ""
    others: tuple[str, ...] = ()
    """What was recorded in other threads of the pull request on the way."""


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


def ours(
    comments: list[Comment], manifest: str | None = None
) -> dict[str, tuple[Comment, Marker]]:
    """The comments the bot opened, by the key of the assertion each is on. A reply in a
    thread is not one: it carries no marker. The first comment holding a key is the one. With
    `manifest`, a comment whose marker names any other file is not one either."""
    found: dict[str, tuple[Comment, Marker]] = {}
    for comment in comments:
        if not comment.by_bot or comment.in_reply_to is not None:
            continue
        marker = decode(comment.body)
        if marker is not None and (manifest is None or marker.manifest == manifest):
            found.setdefault(marker.key, (comment, marker))
    return found


def _marker(
    made: Finding,
    placed: Literal["review", "issue"],
    fork: bool,
    manifest: str,
    before: Marker | None,
) -> Marker:
    # A passage that had to be cleaned to be echoed would not match the manuscript, so it is
    # not offered for `set_aside`.
    passage = made.text if clean(made.text) == made.text else ""
    return Marker(
        claim=clean(made.claim),
        assertion=clean(made.assertion),
        key=made.key,
        digest=made.digest,
        headline=headline(
            made.label, made.kind, made.printed, made.stored, made.file, made.passage
        ),
        option=option(made.kind, made.stored, made.passage),
        placed=placed,
        fork=fork,
        manifest=manifest,
        artifact=made.artifact if passage else "",
        text=passage,
        # An answer recorded is kept until someone answers again.
        decision=before.decision if before is not None else None,
    )


def _resolve(
    client: Client, number: int, comment: Comment, resolved: bool, notes: list[str]
) -> None:
    if comment.kind != "review":
        return
    try:
        client.resolve_thread(number, comment.id, resolved)
    except GitHubError as refused:
        notes.append(
            f"comment {comment.id}: the thread was not {'re' if resolved else 'un'}"
            f"solved: {refused}"
        )


def _rewrite(client: Client, comment: Comment, made: Marker) -> bool:
    """Edit one of the bot's comments to say what `made` says, keeping the answer it records
    as it is right now: the comment is read again just before the write, so an answer `reply`
    recorded since `post` listed the comments is kept. False where nothing changed or the
    comment is gone."""
    now = client.fresh(comment)
    current = decode(now.body) if now is not None and now.by_bot else None
    if now is None or current is None or current.key != made.key:
        return False
    body = render(made.model_copy(update={"decision": current.decision}))
    if body == now.body:
        return False
    client.edit(now, body)
    return True


def post(
    findings: Findings,
    client: Client,
    head_sha: str,
    head_repository: str,
    head_branch: str,
    manifest: str = "repro.yaml",
) -> Posted:
    """Comment on each finding, once: a comment already open on the same assertion is edited
    where what it says has changed, and one on an assertion that now passes is marked fixed.

    `head_sha`, `head_repository` and `head_branch` are the run's, as `workflow_run` gives
    them, and `manifest` the file the workflow names.
    """
    if findings.head_sha != head_sha:
        raise NotThisRunError(
            f"the findings are of {findings.head_sha[:7]}, and the run checked {head_sha[:7]}"
        )
    if findings.manifest != manifest:
        raise NotThisRunError(
            f"the findings are about {findings.manifest}, not {manifest}"
        )
    pull = client.pull(findings.pull_request)
    if pull.head_sha != head_sha:
        raise NotThisRunError(
            f"pull request #{pull.number} is at {pull.head_sha[:7]}, not {head_sha[:7]}"
        )
    if (pull.head_repository, pull.head_ref) != (head_repository, head_branch):
        raise NotThisRunError(
            f"pull request #{pull.number} is from {pull.head_repository}:{pull.head_ref}, and "
            f"the run checked {head_repository}:{head_branch}"
        )
    if findings.problem:
        return Posted(problem=findings.problem)
    fork = pull.head_repository != client.repository
    number = pull.number
    held = ours(
        client.review_comments(number) + client.issue_comments(number), manifest
    )
    placeable = (
        {path: lines(patch) for path, patch in client.patches(number).items()}
        if not fork
        else {}
    )

    created, edited, unchanged, notes = [], [], [], []

    def latest_of(key: str) -> tuple[Comment | None, Marker | None]:
        """The comment as it is now, read again: an answer may have landed since the list."""
        comment, _ = held.pop(key, (None, None))
        now = client.fresh(comment) if comment is not None else None
        marker = decode(now.body) if now is not None and now.by_bot else None
        return (
            (now, marker) if marker is not None and marker.key == key else (None, None)
        )

    for made in findings.findings:
        comment, before = latest_of(made.key)
        placed: Literal["review", "issue"]
        if before is not None:
            placed = before.placed
        elif made.path is not None and made.line in placeable.get(made.path, ()):
            placed = "review"
        else:
            placed = "issue"
        marker = _marker(made, placed, fork, manifest, before)
        body = render(marker)
        if comment is None:
            if placed == "review":
                client.comment_on_line(
                    number, body, head_sha, made.path or "", made.line or 1
                )
            else:
                client.comment(number, body)
            created.append(made.key)
        elif _rewrite(client, comment, marker):
            edited.append(made.key)
            if before is not None and before.state != "open":
                _resolve(client, number, comment, False, notes)
        else:
            unchanged.append(made.key)

    # Findings past the cap were left out of the file, so an assertion absent from it may still
    # be failing: nothing is closed until the file holds every finding.
    for key in list(held) if not findings.more else []:
        comment, before = latest_of(key)
        if comment is None or before is None:
            continue
        if key in findings.set_aside:
            update: dict[str, Any] = {"state": "set-aside"}
        elif key in findings.checked:
            update = {"state": "fixed"}
            if before.state != "fixed":
                update["fixed_at"] = head_sha
        else:
            update = {"state": "gone"}
        if _rewrite(client, comment, before.model_copy(update=update)):
            edited.append(key)
            if before.state == "open":
                _resolve(client, number, comment, True, notes)
        else:
            unchanged.append(key)
    return Posted(
        created=tuple(created),
        edited=tuple(edited),
        unchanged=tuple(unchanged),
        fork=fork,
        notes=tuple(notes),
    )


# ------------------------------------------------------------------------------- the answers


class _Thread(BaseModel):
    """One of the bot's comments and the replies in its thread, oldest first."""

    model_config = ConfigDict(frozen=True)

    root: Comment
    marker: Marker
    replies: tuple[Comment, ...]


def _threads(
    number: int, client: Client, manifest: str, extra: Comment | None = None
) -> list[_Thread]:
    """Every thread the bot opened on the pull request, read now. `extra` is the reply that
    started the run, counted where the list does not show it yet."""
    review = client.review_comments(number)
    issue = client.issue_comments(number)
    if extra is not None:
        pool = review if extra.kind == "review" else issue
        if all(c.id != extra.id for c in pool):
            pool.append(extra)
    found = []
    for root, marker in ours(review + issue, manifest).values():
        if root.kind == "review":
            replies = [c for c in review if c.in_reply_to == root.id]
        else:
            replies = [
                c for c in issue if not c.by_bot and refers_to(c.body, marker.ref)
            ]
        replies.sort(key=lambda c: (c.created_at, c.id))
        found.append(_Thread(root=root, marker=marker, replies=tuple(replies)))
    return found


def _thread_of(reply: Comment, threads: list[_Thread]) -> _Thread | None:
    """The thread a reply is in, or None where it is in none of the bot's, or quotes two."""
    if reply.kind == "review":
        return next((t for t in threads if t.root.id == reply.in_reply_to), None)
    found = [
        t
        for t in threads
        if t.root.kind == "issue" and refers_to(reply.body, t.marker.ref)
    ]
    return found[0] if len(found) == 1 else None


def latest(
    replies: tuple[Comment, ...] | list[Comment],
    ref: str,
    client: Client,
    allowed: dict[str, bool] | None = None,
) -> tuple[Comment, Answer, str] | None:
    """The latest reply that gives an answer and is from someone with write access: the one
    that holds."""
    allowed = {} if allowed is None else allowed
    for comment in reversed(list(replies)):
        if comment.bot or (given := parse(comment.body, ref)) is None:
            continue
        if comment.login not in allowed:
            allowed[comment.login] = client.permission(comment.login) in WRITERS
        if allowed[comment.login]:
            return comment, given.answer, given.reason
    return None


def _newer(reply: Comment, answer: Answer, reason: str, marker: Marker) -> bool:
    """Whether a reply's answer is not yet the one the comment records: a later reply, or the
    recorded reply edited to say something else. An answer is never replaced by an older one."""
    held = marker.decision
    if held is None:
        return True
    if reply.id == held.reply:
        return (answer, reason) != (held.answer, held.reason)
    return (reply.created_at, reply.id) > (held.at, held.reply)


def _commit(
    client: Client,
    pull: Pull,
    path: str,
    change: Callable[[str], str | None],
    message: str,
) -> str:
    """Read `path` on the pull request's branch, apply `change` to its text, and commit what
    it returns; the commit's sha, or "" where `change` returns None. A branch that moved
    between the read and the write is read again."""
    for attempt in range(ATTEMPTS):
        content, blob = client.file(path, pull.head_ref)
        changed = change(content.decode("utf-8"))
        if changed is None:
            return ""
        try:
            return client.put_file(
                path, changed.encode("utf-8"), blob, pull.head_ref, message
            )
        except GitHubError as refused:
            if refused.status not in (409, 422) or attempt == ATTEMPTS - 1:
                raise
    return ""


def _record(
    number: int,
    thread: _Thread,
    by: Comment,
    chosen: Answer,
    reason: str,
    client: Client,
    pull: Pull,
    manifest: str,
    dispatch: tuple[str, ...],
    trigger: Comment,
) -> tuple[str, str] | None:
    """Record one answer: the manifest, then the comment, then a line in the thread. None
    where, read again, the comment already holds this answer or a later one."""
    root = client.fresh(thread.root)
    marker = decode(root.body) if root is not None and root.by_bot else None
    if root is None or marker is None or not _newer(by, chosen, reason, marker):
        return None
    # Read the thread again right before writing: a later reply that landed since is the one
    # to record, and its own run records it.
    again = next(
        (
            t
            for t in _threads(number, client, manifest, trigger)
            if t.root.id == root.id
        ),
        None,
    )
    holding = latest(again.replies, marker.ref, client) if again is not None else None
    if holding is None or holding[0].id != by.id or holding[1:] != (chosen, reason):
        return None

    fork = pull.head_repository != client.repository
    passage = bool(marker.artifact and marker.text)
    # `state` is "set-aside" where this answer leaves the claim set aside, and empty otherwise.
    committed, note, state = "", "", ""
    if chosen.sets_aside and fork:
        note = "; this pull request comes from a fork, so nothing was committed"
    elif chosen.sets_aside and not passage:
        note = (
            f"; {manifest} names no passage of the manuscript for this claim, so no "
            "set_aside entry was written"
        )
    elif passage and not fork:
        content, _ = client.file(manifest, pull.head_ref)
        source = content.decode("utf-8")
        if chosen.sets_aside and setaside.holds(source, marker.artifact, marker.text):
            note = f"; the passage is already set aside in {manifest}"
            state = "set-aside"
        elif chosen.sets_aside:
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
                manifest,
                lambda text: (
                    None
                    if setaside.holds(text, marker.artifact, marker.text)
                    else setaside.added(text, made)
                ),
                f"{manifest}: set aside claim {marker.claim} ({chosen.recorded} by "
                f"@{by.login} on #{number})",
            )
            note = (
                f"; set_aside entry committed in {committed[:7]}" if committed else ""
            )
            state = "set-aside" if committed else state
        else:
            committed = _commit(
                client,
                pull,
                manifest,
                lambda text: setaside.removed(text, marker.artifact, marker.text),
                f"{manifest}: claim {marker.claim} is no longer set aside "
                f"({chosen.recorded} by @{by.login} on #{number})",
            )
            note = (
                f"; the set_aside entry was removed in {committed[:7]}"
                if committed
                else ""
            )
    if committed:
        note += _dispatched(client, pull, number, dispatch)
    decision = Decision(
        answer=chosen,
        reason=reason,
        by=by.login,
        at=by.created_at,
        reply=by.id,
        committed=committed if chosen.sets_aside else "",
    )
    # Read the comment again right before writing it, and change only the answer and whether
    # it is set aside: whether it is open, fixed or gone otherwise is `post`'s to say.
    now = client.fresh(root)
    current = decode(now.body) if now is not None and now.by_bot else None
    if now is not None and current is not None:
        update: dict[str, Any] = {"decision": decision}
        if state == "set-aside":
            update["state"] = "set-aside"
        elif current.state == "set-aside" and committed and not chosen.sets_aside:
            # The entry this comment was closed by is gone, so the claim is open again.
            update["state"] = "open"
        updated = current.model_copy(update=update)
        if render(updated) != now.body:
            client.edit(now, render(updated))
    said = f"recorded: {chosen.recorded} by @{by.login}{note}"
    if chosen.sets_aside and state == "set-aside":
        said += f". {SET_ASIDE}"
    _say(client, number, root, marker, said)
    return said, committed


def _dispatched(
    client: Client, pull: Pull, number: int, dispatch: tuple[str, ...]
) -> str:
    """Start each workflow named again on the branch: a commit made with the workflow's token
    starts none, and a required check left unrun would hold the merge. The first is the bot's
    own check, which is told the pull request's number."""
    failed = []
    for workflow in dispatch:
        inputs = {"pull_request": str(number)} if workflow == dispatch[0] else {}
        try:
            client.dispatch(workflow, pull.head_ref, inputs)
        except GitHubError:
            failed.append(workflow)
    return f"; could not start {', '.join(failed)} again" if failed else ""


def _say(client: Client, number: int, root: Comment, marker: Marker, text: str) -> None:
    if root.kind == "review":
        client.reply_on_line(number, root.id, text)
    else:
        client.comment(number, f"`{marker.ref}` {text}")


def reply(
    event_name: str,
    event: dict,
    client: Client,
    manifest: str = "repro.yaml",
    dispatch: tuple[str, ...] = (),
) -> Replied:
    """Read one reply, and record every answer on the pull request that is not yet in its
    comment. `manifest` is the file the workflow names, the only one ever committed to, and
    `dispatch` the workflows started again after a commit."""
    manifest = manifest_path(manifest)
    payload = event.get("comment") or {}
    if (payload.get("user") or {}).get("type") == "Bot":
        return Replied(done="skipped")
    kind: Literal["review", "issue"]
    if event_name == "pull_request_review_comment" and event.get("pull_request"):
        kind, number = "review", int(event["pull_request"]["number"])
    elif event_name == "issue_comment" and (event.get("issue") or {}).get(
        "pull_request"
    ):
        kind, number = "issue", int(event["issue"]["number"])
    else:
        return Replied(done="skipped")
    trigger = Comment.read(kind, payload)
    threads = _threads(number, client, manifest, trigger)
    thread = _thread_of(trigger, threads)
    if thread is None:
        return Replied(done="not ours")

    allowed: dict[str, bool] = {}

    def writer(login: str) -> bool:
        if login not in allowed:
            allowed[login] = client.permission(login) in WRITERS
        return allowed[login]

    # An edit is read as the reply it now is, and answered with nothing but the record.
    edited = event.get("action") == "edited"
    given = parse(trigger.body, thread.marker.ref)
    told: Replied | None = None
    if given is None:
        # Only a reply that looks meant as an answer, from someone who could give one, is told
        # how to answer; discussion in the thread is left alone.
        if (
            not edited
            and asks(trigger.body, thread.marker.ref)
            and writer(trigger.login)
        ):
            _say(client, number, thread.root, thread.marker, NOT_AN_ANSWER)
            told = Replied(done="not an answer", said=NOT_AN_ANSWER)
    elif not writer(trigger.login):
        if not edited:
            _say(client, number, thread.root, thread.marker, NOT_ALLOWED)
        return Replied(done="not allowed", said=NOT_ALLOWED)

    pull = client.pull(number)
    mine: tuple[str, str] | None = None
    others = []
    for each in threads:
        holding = latest(each.replies, each.marker.ref, client, allowed)
        if holding is None or not _newer(*holding, each.marker):
            continue
        by, chosen, reason = holding
        done = _record(
            number, each, by, chosen, reason, client, pull, manifest, dispatch, trigger
        )
        if done is None:
            continue
        if each.root.id == thread.root.id and by.id == trigger.id:
            mine = done
        else:
            others.append(done[0])
    if mine is None:
        return (told or Replied(done="skipped")).model_copy(
            update={"others": tuple(others)}
        )
    return Replied(
        done="recorded", said=mine[0], committed=mine[1], others=tuple(others)
    )


__all__ = [
    "CHECK_WORKFLOW",
    "NotThisRunError",
    "Posted",
    "Replied",
    "latest",
    "lines",
    "ours",
    "post",
    "reply",
]
