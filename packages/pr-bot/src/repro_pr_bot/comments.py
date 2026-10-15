"""The comments the pull-request bot posts, the marker each carries, and the replies it reads.

A comment is rendered entirely from its `Marker`, which it carries at its end as an HTML
comment holding base64 JSON. Rendering from the marker alone means that what a comment says
and what the bot later reads back from it cannot disagree, and comparing two markers says
whether a comment needs editing. A marker is believed only in a comment the bot wrote: anyone
can paste one into a comment of their own.

A reply is a number from 1 to 4 at its start, after any quoted lines, with any words after
the number taken as the reason.
"""

from __future__ import annotations

import base64
import binascii
import datetime
import enum
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

#: Opens the hidden marker. The version is in the name, so a later layout is a new name.
MARKER_OPEN = "<!-- repro-bot:v1 "
MARKER_CLOSE = " -->"
#: The marker as the last line of a body. Only that one is read: a marker anywhere else is text
#: someone put there.
_MARKER = re.compile(r"(?:\A|\n)<!-- repro-bot:v1 ([A-Za-z0-9+/=]+) -->\r?\n?\Z")
#: Characters that open or close an HTML comment, which no echoed text may carry.
_COMMENT_SYNTAX = re.compile(r"<!--|-->|--!>")
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")

#: Characters of a value shown in a comment.
MAX_SHOWN = 200
#: Characters of a reason kept from a reply.
MAX_REASON = 500
#: GitHub refuses a comment body over 65,536 characters. A body is kept well under it.
MAX_BODY = 60_000


class Answer(enum.IntEnum):
    """The four answers a reply can give."""

    YES = 1
    """The paper should change: the result file is right."""
    NO = 2
    """The result file is wrong."""
    IGNORE = 3
    NOT_A_CLAIM = 4

    @property
    def recorded(self) -> str:
        """What the confirmation says was recorded."""
        return {
            Answer.YES: "accepted",
            Answer.NO: "result file disputed",
            Answer.IGNORE: "ignored",
            Answer.NOT_A_CLAIM: "not a claim",
        }[self]

    @property
    def sets_aside(self) -> bool:
        return self in (Answer.IGNORE, Answer.NOT_A_CLAIM)


class Reply(BaseModel):
    """A reply read as an answer."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    answer: Answer
    reason: str = ""


class Decision(BaseModel):
    """The answer that holds for one comment: the latest reply from someone with write access."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    answer: Answer
    reason: str = ""
    by: str = Field(min_length=1)
    """The GitHub login of the person who replied."""
    at: datetime.datetime
    reply: int
    """The id of the reply."""
    committed: str = ""
    """The commit that wrote the `set_aside` entry, where one was written."""


class Marker(BaseModel):
    """Everything a comment says, and what identifies the assertion it is on."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    claim: str
    assertion: str = ""
    key: str = Field(pattern=r"^[0-9a-f]{64}$")
    digest: str = Field(pattern=r"^[0-9a-f]{16}$")
    headline: str
    option: str
    """What answer 1 says the paper should do."""
    placed: Literal["review", "issue"]
    """On a line of the diff, or in the pull request's conversation."""
    state: Literal["open", "fixed", "set-aside", "gone"] = "open"
    fork: bool = False
    manifest: str = "repro.yaml"
    """The manifest checked, from the top of the repository."""
    artifact: str = ""
    text: str = ""
    """The passage a `set_aside` entry for the claim would name, and its artifact."""
    fixed_at: str = ""
    """The head commit at which the assertion passed again."""
    decision: Decision | None = None

    @property
    def ref(self) -> str:
        """The short name a reply in the conversation uses to say which comment it answers."""
        return f"r-{self.key[:8]}"


# ------------------------------------------------------------------------------- the marker


def encode(marker: Marker) -> str:
    data = marker.model_dump_json(exclude_none=True).encode("utf-8")
    return MARKER_OPEN + base64.b64encode(data).decode("ascii") + MARKER_CLOSE


def decode(body: str) -> Marker | None:
    """The marker on the last line of a comment, or None where there is none that reads."""
    found = _MARKER.search(body or "")
    if found is None:
        return None
    try:
        return Marker.model_validate_json(base64.b64decode(found[1], validate=True))
    except (binascii.Error, ValueError, ValidationError):
        return None


# -------------------------------------------------------------------------------- rendering


def clean(text: str) -> str:
    """Text read from a pull request, safe to echo: no control characters, and nothing that
    opens or closes an HTML comment, so no echoed text can carry a marker."""
    text = _CONTROL.sub(" ", text)
    while _COMMENT_SYNTAX.search(text):
        text = _COMMENT_SYNTAX.sub(lambda found: found[0].replace("-", "\u2010"), text)
    return text


def _code(text: object) -> str:
    """A value as inline code on one line: GitHub renders nothing inside it, so a value read
    from the pull request cannot mention anyone or open a comment."""
    flat = " ".join(clean(str(text)).split())
    shown = flat if len(flat) <= MAX_SHOWN else f"{flat[:MAX_SHOWN]}..."
    ticks = "`" * (max((len(run) for run in re.findall(r"`+", shown)), default=0) + 1)
    pad = " " if shown.startswith("`") or shown.endswith("`") or ticks != "`" else ""
    return f"{ticks}{pad}{shown}{pad}{ticks}"


def _plain(text: str) -> str:
    """A label as text that renders as itself: Markdown and HTML characters escaped, and an @
    that mentions nobody."""
    flat = " ".join(clean(text).split())[:MAX_SHOWN]
    escaped = re.sub(r"([\\`*_{}\[\]()#+!|<>~])", r"\\\1", flat)
    return escaped.replace("@", "@\u200b")


def headline(
    label: str,
    kind: str,
    printed: str | None,
    stored: str | None,
    file: str,
    passage: bool,
) -> str:
    """The first line of a comment: what the manuscript prints and what the file holds."""
    said = _plain(label)
    shown = _code(printed) if printed is not None else "the value"
    in_file = _code(file) if file else "its file"
    if kind == "stale":
        return (
            f"{said}: {shown} reads {in_file}, which a declared command writes and which has "
            "changed since that command was last re-run"
        )
    if passage:
        return f"{said}: the passage {shown} is not in {in_file}"
    if kind == "mismatch":
        now = f" (now {_code(stored)})" if stored is not None else ""
        return f"{said}: {shown} no longer matches {in_file}{now}"
    if kind == "not-found":
        return f"{said}: {shown} is not found in {in_file} at the declared address"
    return f"{said}: {shown} could not be checked against {in_file}"


def option(kind: str, stored: str | None, passage: bool) -> str:
    """Answer 1, as the comment words it."""
    if kind == "stale":
        return "Yes, run the command again and update the paper"
    if kind == "mismatch" and stored is not None and not passage:
        return f"Yes, the paper should say {_code(stored)}"
    return "Yes, the paper should change"


def _decision_said(marker: Marker) -> str:
    decision = marker.decision
    if decision is None:
        return ""
    by = f"@{decision.by}"
    reason = f": {_code(decision.reason)}" if decision.reason else ""
    if decision.answer is Answer.YES:
        return (
            f"Recorded: {by} accepts the file's value{reason}. The claim fails until the "
            "paper prints it; the manuscript is not edited."
        )
    if decision.answer is Answer.NO:
        return (
            f"Recorded: {by} says the result file is wrong{reason}. Nothing in `repro.yaml` "
            "was changed, and the claim keeps failing."
        )
    said = "ignored" if decision.answer is Answer.IGNORE else "not a claim"
    where = (
        f" `set_aside` entry committed in {decision.committed[:7]}."
        if decision.committed
        else " No `set_aside` entry was committed."
    )
    return f"Recorded: {said} by {by}{reason}.{where}" + (
        f" {SET_ASIDE}" if decision.committed else ""
    )


SET_ASIDE = "Set aside in `repro.yaml` for `repro numbers`; `repro verify` still reports this claim."
FORK = (
    "This pull request comes from a fork, so the bot only comments here: it commits nothing "
    "to the fork's branch. An answer of 3 or 4 is recorded in this comment, and the "
    "`set_aside` entry is for someone to add to `repro.yaml`."
)


def _shrunk(marker: Marker, step: int) -> Marker:
    """The marker with less of what was echoed from the pull request, step by step."""
    if step == 1:
        # The passage is what makes a body long; without it no entry can be written.
        return marker.model_copy(update={"artifact": "", "text": ""})
    cut = 1000 if step == 2 else 100
    return marker.model_copy(
        update={
            "claim": marker.claim[:cut],
            "assertion": marker.assertion[:cut],
            "headline": marker.headline[: cut * 2],
            "option": marker.option[: cut * 2],
        }
    )


def render(marker: Marker) -> str:
    """The comment's body, from its marker alone, under `MAX_BODY` characters: where it would
    be longer, the echoed passage is dropped, then the echoed names are cut."""
    body = _render(marker)
    for step in (1, 2, 3):
        if len(body) <= MAX_BODY:
            break
        marker = _shrunk(marker, step)
        body = _render(marker)
    return body


def _render(marker: Marker) -> str:
    if marker.state != "open":
        closed = {
            "fixed": f"Fixed: the claim passes at {marker.fixed_at[:7] or 'the latest commit'}.",
            "set-aside": SET_ASIDE,
            "gone": "This assertion is no longer in `repro.yaml`.",
        }[marker.state]
        lines = [f"~~{marker.headline}~~", "", closed]
    else:
        if marker.placed == "review":
            ask = "Reply in this thread with a number:"
        else:
            ask = (
                f"Reply in this conversation with a number, quoting this comment or starting "
                f"with `{marker.ref}`:"
            )
        lines = [
            f"**{marker.headline}**",
            "",
            ask,
            f"1. {marker.option}",
            "2. No, the result file is wrong",
            "3. Ignore this one",
            "4. Not a claim",
        ]
    if said := _decision_said(marker):
        lines += ["", said]
    if marker.fork and marker.state == "open":
        lines += ["", FORK]
    lines += [
        "",
        f"<sub>repro bot · {marker.ref} · claim {_code(marker.claim)}"
        + (f" · {_code(marker.assertion)}" if marker.assertion else "")
        + "</sub>",
        encode(marker),
    ]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------------- replies

_ANSWER = re.compile(r"([1-4])(?![0-9])(?!\.[0-9])(?:[\s.:,;)\-–—]+(.*))?", re.DOTALL)
NOT_AN_ANSWER = "Not recorded: reply 1–4, with any reason after the number."
NOT_ALLOWED = (
    "Not recorded: only someone with write access to this repository can answer."
)


def _unquoted(body: str) -> str:
    """The reply without the lines it quotes."""
    return "\n".join(
        line for line in body.splitlines() if not line.lstrip().startswith(">")
    )


_MENTION = re.compile(r"@repro(?:-bot)?\b[\s,:]*")


def _own(body: str, ref: str) -> str:
    """A reply's own text: without quoted lines, a leading `ref` or a leading `@repro`."""
    text = _unquoted(body).strip()
    if ref and text.startswith(ref):
        text = text[len(ref) :].lstrip(" :,-")
    if found := _MENTION.match(text):
        text = text[found.end() :]
    return text.strip()


def asks(body: str, ref: str = "") -> bool:
    """Whether a reply that gives no answer was meant as one: it is addressed to `@repro`, or
    its own text starts with something number-like. Only such a reply is told to answer 1–4."""
    text = _unquoted(body).strip()
    if ref and text.startswith(ref):
        text = text[len(ref) :].lstrip(" :,-")
    return bool(_MENTION.match(text)) or bool(re.match(r"[#(]?[0-9]", text))


def parse(body: str, ref: str = "") -> Reply | None:
    """The answer a reply gives, or None where it gives none.

    The reply's own text, after any quoted lines and a leading `ref`, starts with a number from
    1 to 4, alone or followed by a separator and the reason. `12`, `1.5` and `yes` give none.
    """
    text = _own(body, ref)
    found = _ANSWER.fullmatch(text)
    if found is None:
        return None
    reason = " ".join(clean(found[2] or "").split())[:MAX_REASON]
    return Reply(answer=Answer(int(found[1])), reason=reason)


def refers_to(body: str, ref: str) -> bool:
    """Whether a comment in the conversation is in the thread of the comment named `ref`: it
    quotes that comment, or its own text starts with the name."""
    if any(
        line.lstrip().startswith(">") and ref in line
        for line in (body or "").splitlines()
    ):
        return True
    return _unquoted(body or "").strip().startswith(ref)


__all__ = [
    "FORK",
    "NOT_ALLOWED",
    "NOT_AN_ANSWER",
    "SET_ASIDE",
    "Answer",
    "Decision",
    "Marker",
    "Reply",
    "asks",
    "clean",
    "decode",
    "encode",
    "headline",
    "option",
    "parse",
    "refers_to",
    "render",
]
