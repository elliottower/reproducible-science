"""Registrations frozen by a commit line instead of by `prereg freeze`.

An older convention fixes a registration by committing the document and then, in the commit
that follows, writing the first commit's SHA into the document itself:

    **Commit SHA:** b96d10a

The document at the named commit therefore does not hold its own SHA: that line read
`_pending_`, or whatever placeholder the author used. So the commit record is left out of both
sides of the comparison, and the rest of the document is compared with the file as it was at
the commit it names.

A `**Status:**` line in the document's header is part of the same record. The commit that
writes the SHA often rewrites it from a draft to a frozen status, so it is masked as well, and
a status that differs from the frozen one is reported without counting as an edit.

Leaving the record out is also the limit of the check. Text written onto the record line after
the hash is not compared, as a `**Status:**` line is not hashed in a plan `prereg freeze` froze.

Nothing here writes: the documents are someone's registrations, and the check only reads them
and the history of the repository they sit in.
"""

from __future__ import annotations

import difflib
import pathlib
import re
from dataclasses import dataclass

from provenance_core.gitref import try_run

from prereg.plan import PREREG

_KEY = r"(?:commit sha|freeze sha|freeze commit)"

#: `**Commit SHA:** b96d10a` and `**Freeze SHA**: `8401d54``. Bold and at the start of a line,
#: which is what separates a document's own record from a mention of some commit in its prose
#: (`**Parent document:** PREREGISTRATION.md (commit SHA: b96d10a)`).
RECORD = re.compile(rf"^\*\*{_KEY}(?::\*\*|\*\*:)[ \t]*(.*)$", re.I)

#: `## Commit SHA`, with the commit on the next line that is not blank.
HEADING = re.compile(rf"^#{{1,6}}[ \t]+{_KEY}[ \t]*$", re.I)

#: A value that names a commit: a hash of 7 to 40 digits, bare, in backticks or in bold.
#: Anything else (`_pending_`, `[TO BE FILLED AFTER COMMIT]`) names none yet.
HASH = re.compile(r"^[*`]*([0-9a-f]{7,40})(?![0-9a-z])", re.I)

#: `**Status:** FROZEN at commit `a38196b``. The commit that records the freeze often rewrites
#: this line too, from a draft to a frozen status, so in the header it is part of the record.
STATUS = re.compile(r"^\*\*status(?::\*\*|\*\*:)", re.I)

FENCE = re.compile(r"^(```|~~~)")

UNCHANGED = "unchanged"
APPENDED = "appended"
CHANGED = "changed"
PENDING = "pending"
UNKNOWN = "unknown commit"

#: What a commit record is compared as, on both sides.
MASK = "(the commit line)"
STATUS_MASK = "(the status line)"

Lines = list[tuple[int, str]]


@dataclass(frozen=True)
class Pinned:
    """One commit-pinned document and what comparing it with its commit found."""

    path: pathlib.Path
    status: str
    commit: str
    detail: tuple[str, ...] = ()


def split_record(text: str) -> tuple[Lines, list[str], list[str]]:
    """The document's numbered lines with its freeze record masked, the commit values the record
    holds, and its status lines.

    A record line stays in place as a mask, so the lines around it keep their positions and a
    placeholder compares equal to the hash that replaced it. A record inside a fenced block is an
    example of the convention, in a README or a template, and is left as it is.

    A `**Status:**` line is part of the record only in the header: before the first heading
    that follows the title. One below that is the plan's own text and is compared.
    """
    body: Lines = []
    values: list[str] = []
    statuses: list[str] = []
    fenced = awaiting = started = False
    header = True
    for number, line in enumerate(text.splitlines(), 1):
        if FENCE.match(line):
            fenced, awaiting = not fenced, False
        elif not fenced:
            record = RECORD.match(line)
            if record or (awaiting and line.strip()):
                awaiting = False
                values.append(record.group(1).strip() if record else line.strip())
                line = MASK
            elif header and STATUS.match(line):
                statuses.append(line.strip())
                line = STATUS_MASK
            else:
                awaiting = awaiting or bool(HEADING.match(line))
                # A heading on the first line that is not blank is the title; any other ends
                # the header.
                header = header and not (started and line.startswith("#"))
        started = started or bool(line.strip())
        body.append((number, line))
    while body and not body[-1][1].strip():
        body.pop()
    while body and not body[0][1].strip():
        body.pop(0)
    return body, values, statuses


def _count(n: int) -> str:
    return f"{n} line" if n == 1 else f"{n} lines"


def _appended(old: list[str], new: list[str]) -> bool:
    """Whether `new` is `old` with lines added at its end.

    A log kept in a fenced block grows above its closing fence, so where the frozen text ends on
    a fence the added lines may sit directly above it.
    """
    if len(new) <= len(old):
        return False
    if new[: len(old)] == old:
        return True
    return bool(FENCE.match(old[-1])) and new[-1] == old[-1] and new[: len(old) - 1] == old[:-1]


def compare(
    path: pathlib.Path, commit: str, frozen: str, current: Lines, statuses: list[str]
) -> Pinned:
    """Compare a document's lines with its text at the commit it names.

    A header status line that differs from the frozen one is reported and is not an edit.
    """
    was, _, frozen_statuses = split_record(frozen)
    note = (
        ("the status line was updated after the freeze, which is not an edit to the frozen text",)
        if statuses != frozen_statuses
        else ()
    )
    old = [line for _, line in was]
    new = [line for _, line in current]
    if old == new:
        return Pinned(path, UNCHANGED, commit, note)
    if _appended(old, new):
        added = f"{_count(len(new) - len(old))} added after the frozen text"
        return Pinned(path, APPENDED, commit, (added, *note))

    edits = [
        op
        for op in difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes()
        if op[0] != "equal"
    ]
    added = sum(j2 - j1 for _, _, _, j1, j2 in edits)
    removed = sum(i2 - i1 for _, i1, i2, _, _ in edits)
    _, i1, i2, j1, j2 = edits[0]
    # The line number is the working file's, which is the one an editor can open. An edit that
    # only removes has no line of its own there, so it is placed at the line that now follows.
    line = current[j1][0] if j1 < len(current) else len(current) + 1
    detail = [f"{_count(added)} added, {removed} removed", f"first difference at line {line}:"]
    if i2 > i1:
        detail.append(f"- {old[i1][:100]}")
    if j2 > j1:
        detail.append(f"+ {new[j1][:100]}")
    return Pinned(path, CHANGED, commit, (*detail, *note))


def check_document(
    here: pathlib.Path, path: pathlib.Path, body: Lines, values: list[str], statuses: list[str]
) -> Pinned:
    """Compare one document with the file at the commit its record names."""
    named = next((m.group(1) for m in map(HASH.match, values) if m), None)
    if named is None:
        return Pinned(path, PENDING, "", (f"the commit line names no commit: {values[0]}",))
    if try_run("rev-parse", "--verify", "--quiet", f"{named}^{{commit}}", cwd=here) is None:
        # Not `changed`: a shallow clone, a rewritten history and a commit of another repository
        # all land here, and none of them says the document was edited.
        why = f"{named} is not a commit in this repository, so nothing was compared"
        return Pinned(path, UNKNOWN, named, (why,))
    frozen = try_run("show", f"{named}:./{path.as_posix()}", cwd=here)
    if frozen is None:
        why = f"{path} is not in commit {named}, so nothing was compared"
        return Pinned(path, UNKNOWN, named, (why,))
    return compare(path, named, frozen, body, statuses)


def check_below(here: pathlib.Path) -> list[Pinned]:
    """Every commit-pinned markdown document git tracks at or below `here`, checked.

    Tracked files only: a document git does not track cannot have been in the commit it names.
    """
    listed = try_run("ls-files", "-z", "--", "*.md", cwd=here)
    found = []
    for name in sorted(filter(None, (listed or "").split("\0"))):
        path = pathlib.Path(name)
        if path.name == PREREG or not (here / path).is_file():
            continue
        body, values, statuses = split_record((here / path).read_text())
        if values:
            found.append(check_document(here, path, body, values, statuses))
    return found
