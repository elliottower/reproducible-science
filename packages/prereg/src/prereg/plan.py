"""Reading a preregistration, and the digest that makes it evidence.

Split out of `cli.py`, where every one of these lived inside an argparse handler. A plan that
can only be read by running a command is a plan no other tool can check: `repro` verifies that
a confirmatory result postdates its registration, and to do that it has to be able to hash a
plan and read its status without shelling out.

What the hash covers is the subtle part. `plan_of` drops the status block, because those lines
carry the digest itself and a hash cannot cover its own value. `unhashed_content` reports every
other place that exemption could hide something.
"""

from __future__ import annotations

import datetime
import pathlib
import re

from provenance_core import sha256_of_text

PREREG = "PREREG.md"
MARK = "\n---\n\n## Log\n"


def today() -> str:
    return datetime.date.today().isoformat()


def find(start: pathlib.Path | None = None) -> pathlib.Path | None:
    """The PREREG.md governing this directory: here, or the nearest one above."""
    here = (start or pathlib.Path.cwd()).resolve()
    for d in [here, *here.parents]:
        if (d / PREREG).is_file():
            return d / PREREG
    return None


def plan_of(text: str) -> str:
    """What the freeze hashes: the plan, minus its own status block.

    The status lines carry the commit, the hash and the freeze date, and they are written into
    the file by `freeze` itself. Including them would mean the hash covered a value derived
    from the hash, so the check could never pass.
    """
    i = text.find(MARK)
    plan = text if i < 0 else text[:i]
    keep = [
        ln
        for ln in plan.splitlines()
        if not ln.startswith(("**Status:**", "**Plan sha256:**", "**Frozen:**", "**Log:**"))
    ]
    return "\n".join(keep).strip() + "\n"


def sha256_of(s: str) -> str:
    """The shared text hasher. This used a bare `.encode()`, whose default is not guaranteed."""
    return sha256_of_text(s)


def unhashed_content(text: str) -> list[str]:
    """Parts of the plan the hash would not cover, which `freeze` refuses to register.

    Two things are skipped when hashing, both for good reasons, and both exploitable if they
    appear where they are not meant to. The log marker ends the hashed region, so a second one
    in the body leaves everything after it editable without `check` noticing. Marker-prefixed
    lines are skipped because `freeze` writes them, so one in the body is editable the same way.

    Refusing is better than hashing them anyway: changing what the hash covers would invalidate
    every plan already frozen, while refusing only affects plans not yet registered.
    """
    problems = []
    if text.count(MARK) > 1:
        problems.append(
            "the log marker (`---` then `## Log`) appears more than once. Hashing stops at the "
            "first, so the plan after it would not be covered."
        )
    i = text.find(MARK)
    plan = text if i < 0 else text[:i]
    m = STATUS_BLOCK.search(plan)
    body = (plan[: m.start()] + plan[m.end() :]) if m else plan
    stray = [
        ln
        for ln in body.splitlines()
        if ln.startswith(("**Status:**", "**Plan sha256:**", "**Frozen:**"))
    ]
    if stray:
        problems.append(
            "these lines sit outside the status block and are skipped when hashing, so they "
            "could be edited after freezing without `check` noticing:\n      "
            + "\n      ".join(stray[:5])
        )
    return problems


STATUS_BLOCK = re.compile(r"^\*\*Status:\*\*.*?(?=\n[ \t]*\n|\Z)", re.S | re.M)

# A status line may carry a note after its sentence — "third version; see Log".
# The note is plan content and has to survive a freeze; the marker and its own
# value do not.
STATUS_VALUES = [
    re.compile(r"^\*\*Status:\*\*[ \t]*DRAFT[ \t]*—[ \t]*not frozen\.?"),
    re.compile(r"^\*\*Status:\*\*[ \t]*FROZEN at `[^`]*`\.?"),
    re.compile(r"^\*\*Plan sha256:\*\*[ \t]*`[0-9a-f]*`\.?"),
    re.compile(r"^\*\*Frozen:\*\*[ \t]*\d{4}-\d{2}-\d{2}\.?"),
]


def status_note(block: str) -> str:
    """Whatever the status block says beyond the markers' own values."""
    out = []
    for line in block.splitlines():
        for rx in STATUS_VALUES:
            stripped = rx.sub("", line, count=1)
            if stripped != line:
                line = stripped
                break
        if line.strip():
            out.append(line.strip())
    return " ".join(out)


def rewrite_status(text: str, commit: str, digest: str, date: str) -> str:
    """Replace the whole status block, draft or already frozen.

    Matching only the literal draft sentence did nothing on a plan that was
    already frozen, so `--force` printed a new hash, wrote none of it, and left
    the plan failing its own check — silently, with a zero exit code. Matching
    the block also stops a note written after `**Status:**` from being glued onto
    the freeze date, which is what a prefix-only replacement did to it.
    """
    m = STATUS_BLOCK.search(text)
    if m is None:
        return text
    note = status_note(m.group(0))
    block = (
        f"**Status:** FROZEN at `{commit[:12]}`\n**Plan sha256:** `{digest}`\n**Frozen:** {date}"
    )
    if note:
        block += f"\n{note}"
    return text[: m.start()] + block + text[m.end() :]
