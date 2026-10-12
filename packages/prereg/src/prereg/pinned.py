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

A document whose commit line names no commit was never frozen, and is reported as pending
until it is. Two kinds stay pending for good, and each says so in its header.

A draft that a later document replaced:

    **Superseded by:** PREREGISTRATION_PHASE6_V2.md

A plan is one chain of drafts, so the draft is reported as superseded and the document at the
end of its chain carries the result: unchanged where it was frozen and holds, pending where the
plan is still awaiting its freeze, changed where the frozen text was edited. The plan is counted
once instead of once per draft. That the draft belongs to that plan is the document's statement
and is not checked, as a withdrawal is not. Where a header carries both lines, the successor is
followed and the withdrawal is not read, including where the successor line names nothing or
names a file this check does not list: the draft stays pending.

The path is read from the draft's own directory and looked up in the whole repository, so a
draft has the same status whichever directory the check runs from. A run in a subfolder still
lists only the documents at or below it, with one exception. A successor above it or beside it
is read to settle the draft, and where the document that ends the chain passes it is not listed.
Where that document is pending, changed or of an unknown commit, the run lists it as well, once,
by its path from the top of the repository and with the drafts that reached it, so the run exits
2 or 1 as a run at the top does: a check does not pass while the plan it depends on has not. A
path that is absolute, or that leaves the repository, names nothing this check can read, and the
draft stays pending.

A chain may end on a `PREREG.md` frozen with `prereg freeze`, which is how a registration moves
from this convention to the tool. That plan is checked as `prereg check` checks it, and the
draft is superseded only where that check passes. Where the plan is not frozen, or was changed
after its freeze, the draft stays pending and says which: such a plan may lie outside what the
run lists, and it is not a document of this check to be listed here, so the draft carries the
result. Neither header line is read on a `PREREG.md` itself.

A plan that was dropped and replaced by nothing:

    **Withdrawn:** 2026-07-20, the mismatched arm was never run

It is reported as withdrawn with the reason it gives. The check cannot tell whether that is
true and says so; what it adds is that the plan is still listed, under its own word, where
deleting the commit line would have removed it from the report without a trace. The report also
names the commit that added the line, with its date, read from the repository's history, or says
that the line is not yet committed. That is information: it changes neither the status nor the
exit code.

Neither line excuses a document that names a commit: that one is compared. Its header is part
of the compared text, so adding either line to it after the freeze is itself an edit, and is
reported as changed.

Leaving the record out is also the limit of the check. Text written onto the record line after
the hash is not compared, as a `**Status:**` line is not hashed in a plan `prereg freeze` froze.

Nothing here writes: the documents are someone's registrations, and the check only reads them
and the history of the repository they sit in.
"""

from __future__ import annotations

import difflib
import pathlib
import posixpath
import re
from collections.abc import Callable
from dataclasses import dataclass

from provenance_core.gitref import run, try_run

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

#: `**Superseded by:** PREREGISTRATION_V2.md`, in the header of a draft that was never frozen.
#: The path is read from the draft's own directory, bare, in backticks or as a markdown link.
SUPERSEDED_BY = re.compile(r"^\*\*superseded by(?::\*\*|\*\*:)[ \t]*(.*)$", re.I)
#: `**Withdrawn:** 2026-07-20, the arm was never run`, in the header of a plan that was dropped.
WITHDRAWN_LINE = re.compile(r"^\*\*withdrawn(?::\*\*|\*\*:)[ \t]*(.*)$", re.I)
_LINK = re.compile(r"^\[[^\]]*\]\(([^)]+)\)")

FENCE = re.compile(r"^(```|~~~)")

UNCHANGED = "unchanged"
APPENDED = "appended"
CHANGED = "changed"
PENDING = "pending"
UNKNOWN = "unknown commit"
SUPERSEDED = "superseded"
WITHDRAWN = "withdrawn"

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
    here: pathlib.Path,
    path: pathlib.Path,
    body: Lines,
    values: list[str],
    statuses: list[str],
    shown: pathlib.Path | None = None,
) -> Pinned:
    """Compare one document with the file at the commit its record names.

    `path` is read from `here`. `shown` is the path the result carries where that differs: the
    document's path from the directory the check was run in.
    """
    shown = path if shown is None else shown
    named = next((m.group(1) for m in map(HASH.match, values) if m), None)
    if named is None:
        return Pinned(shown, PENDING, "", (f"the commit line names no commit: {values[0]}",))
    if try_run("rev-parse", "--verify", "--quiet", f"{named}^{{commit}}", cwd=here) is None:
        # Not `changed`: a shallow clone, a rewritten history and a commit of another repository
        # all land here, and none of them says the document was edited.
        why = f"{named} is not a commit in this repository, so nothing was compared"
        return Pinned(shown, UNKNOWN, named, (why,))
    frozen = try_run("show", f"{named}:./{path.as_posix()}", cwd=here)
    if frozen is None:
        why = f"{shown} is not in commit {named}, so nothing was compared"
        return Pinned(shown, UNKNOWN, named, (why,))
    return compare(shown, named, frozen, body, statuses)


def _header_line(text: str, key: re.Pattern[str]) -> re.Match[str] | None:
    """The bold `key` line in the document's header, matched, or None where there is none.

    The header only, as a `**Status:**` line is read: below the first heading after the title
    the words are the plan's own text. A line inside a fenced block is an example.
    """
    fenced = started = False
    for line in text.splitlines():
        if FENCE.match(line):
            fenced = not fenced
        elif not fenced:
            if started and line.startswith("#"):
                return None
            found = key.match(line)
            if found:
                return found
        started = started or bool(line.strip())
    return None


def _header_value(text: str, key: re.Pattern[str]) -> str | None:
    """What a bold `key` line in the document's header holds, or None where there is none."""
    found = _header_line(text, key)
    return None if found is None else found.group(1).strip()


#: What a `**Withdrawn:**` line can hold without giving a reason: the words a template leaves
#: behind. Compared with the value case-folded and stripped of everything but letters, of any
#: script: a reason written in Cyrillic or in Chinese is a reason.
NOT_A_REASON = frozenset(
    {
        "",
        "no",
        "none",
        "na",
        "notapplicable",
        "nil",
        "tbd",
        "tba",
        "tbc",
        "todo",
        "yes",
        "true",
        "false",
        "pending",
        "unknown",
    }
)


def successor(text: str) -> tuple[str | None, str | None]:
    """The path a document's header names as the document that replaced it, and, where the line
    is there and names nothing, what to say about that."""
    value = _header_value(text, SUPERSEDED_BY)
    if value is None:
        return None, None
    link = _LINK.match(value)
    # Backticks only: an underscore or an asterisk can open a real file name.
    named = (link.group(1) if link else value.strip().strip("`")).strip()
    if not named:
        return None, "its `Superseded by` line names no document"
    return named, None


def withdrawal(text: str) -> tuple[str | None, str | None]:
    """The reason a document's header gives for having been withdrawn, and, where the line is
    there and gives none, what to say about that.

    A reason is words. A line left empty, or holding what a template leaves behind (`no`, `N/A`,
    `TBD`, a dash), would turn a plan awaiting its freeze into one that exits 0, so it is
    refused and the document stays pending.
    """
    value = _header_value(text, WITHDRAWN_LINE)
    if value is None:
        return None, None
    if "".join(c for c in value.casefold() if c.isalpha()) in NOT_A_REASON:
        return None, f"its `Withdrawn` line gives no reason: {value or '(empty)'}"
    return value, None


@dataclass(frozen=True)
class _Document:
    """A commit-pinned document: its result, and what its header says became of it."""

    #: The document's path from the top level of the repository.
    name: str
    result: Pinned
    successor: str | None
    #: The reason a `**Withdrawn:**` line gives, and the line as it is written.
    withdrawn: tuple[str, str] | None
    notes: tuple[str, ...]


def _read(top: pathlib.Path, name: str, shown: pathlib.Path) -> _Document | None:
    """The commit-pinned document at `name` below `top`, checked, or None where the file is not
    one: a `PREREG.md`, which `prereg freeze` freezes, or a file with no commit line."""
    path = top / name
    if path.name == PREREG or not path.is_file():
        return None
    text = path.read_text()
    body, values, statuses = split_record(text)
    if not values:
        return None
    result = check_document(top, pathlib.Path(name), body, values, statuses, shown)
    named, no_successor = successor(text)
    reason, no_reason = withdrawal(text)
    line = _header_line(text, WITHDRAWN_LINE)
    # A header with a `Superseded by` line says the plan was replaced. Where that line names
    # nothing, a withdrawal beside it is not read either, so the document stays pending with the
    # note on the line that could not be followed.
    withdrawn = None
    if reason is not None and line is not None and named is None and no_successor is None:
        withdrawn = (reason, line.string.rstrip())
    notes = tuple(note for note in (no_successor, no_reason) if note)
    return _Document(name, result, named, withdrawn, notes)


def _withdrawn_in(top: pathlib.Path, name: str, line: str) -> str:
    """The commit that added a document's `**Withdrawn:**` line, in words for the report.

    The oldest commit in the file's history, followed across renames, in which the line as it is
    written now appears where it did not before. Git lists the newest first, so that commit is
    the last one listed. Where git cannot answer, the report says so and the document's status
    stands: the line is the document's statement, and its date is a note on it.
    """
    log = try_run("log", "--follow", "--format=%h %cs", f"-S{line}", "--", name, cwd=top)
    if log is None:
        return "git could not say which commit added its `Withdrawn` line"
    if not log:
        return "its `Withdrawn` line is not yet committed"
    commit, date = log.splitlines()[-1].split()
    return f"its `Withdrawn` line was added in {commit}, committed {date}"


def _disposition(
    d: _Document,
    top: pathlib.Path,
    shown: Callable[[str], pathlib.Path],
    document: Callable[[str], _Document | None],
    plan_result: Callable[[pathlib.Path], int | None],
) -> tuple[Pinned, _Document | None]:
    """Report a pending document as superseded or withdrawn where its header says which, and
    name the commit-pinned document its chain ends on where it is superseded by one.

    Only a pending document is looked at: one that names a commit was compared, and its result
    stands. A superseded draft is followed along its chain to the document that declares no
    successor. Each path is read from the directory of the draft that names it and looked up in
    the whole repository, so the answer does not depend on where the check was run.

    A chain ending on another commit-pinned document leaves that document its own result, so a
    chain ending on a plan that was never frozen still reports one pending plan, and a chain
    ending on an edited one still reports the edit. A chain ending on a `PREREG.md` is settled by
    `plan_result`, which is `prereg check` on that plan: 0 unchanged, 1 changed, 2 not frozen,
    None where there is no plan. The draft is superseded only on 0.

    A draft that names a file that is no registration, or a path outside the repository, or
    whose chain comes back to itself, stays pending and says why.
    """
    path = d.result.path
    if d.result.status != PENDING:
        return d.result, None
    if d.successor is None:
        if d.withdrawn is None:
            return Pinned(path, PENDING, "", (*d.result.detail, *d.notes)), None
        reason, line = d.withdrawn
        said = f"a plan never frozen; withdrawn, as the document says and not checked: {reason}"
        return Pinned(path, WITHDRAWN, "", (said, _withdrawn_in(top, d.name, line))), None

    def pending(why: str) -> tuple[Pinned, None]:
        return Pinned(path, PENDING, "", (*d.result.detail, why)), None

    chain = [d]
    while True:
        last = chain[-1]
        named = last.successor
        if last.result.status != PENDING or named is None:
            break
        says = f"says it is superseded by {named}"
        if len(chain) > 1:
            says = f"its chain reaches {last.result.path}, which {says}"
        target = posixpath.normpath(posixpath.join(posixpath.dirname(last.name), named))
        if posixpath.isabs(named) or target == ".." or target.startswith("../"):
            return pending(f"{says}, which is an absolute path or leaves this repository")
        if posixpath.basename(target) == PREREG:
            found = plan_result(top / target)
            if found is None:
                return pending(f"{says}, which is not a registration checked here")
            if found == 2:
                return pending(f"{says}, a plan `prereg check` reports as not frozen")
            if found != 0:
                return pending(f"{says}, a plan `prereg check` reports a finding on")
            drafts = [c.result.path for c in chain[1:]]
            names = ", then ".join(str(p) for p in (*drafts, shown(target)))
            by = (
                f"a draft never frozen; says it is superseded by {names}, "
                "a plan `prereg freeze` froze, which is unchanged"
            )
            return Pinned(path, SUPERSEDED, "", (by,)), None
        step = document(target)
        if step is None:
            return pending(f"{says}, which is not a registration checked here")
        if step in chain:
            names = ", then ".join(str(c.result.path) for c in (*chain[1:], step))
            return pending(f"says it is superseded by {names}, a chain that comes back to itself")
        chain.append(step)
    head = chain[-1]
    names = ", then ".join(str(c.result.path) for c in chain[1:])
    withdrawn = head.result.status == PENDING and head.withdrawn is not None
    status = WITHDRAWN if withdrawn else head.result.status
    at = f" at {head.result.commit}" if head.result.commit else ""
    by = f"a draft never frozen; says it is superseded by {names}, which is {status}{at}"
    return Pinned(path, SUPERSEDED, "", (by,)), head


def check_below(
    here: pathlib.Path, plan_result: Callable[[pathlib.Path], int | None]
) -> list[Pinned]:
    """Every commit-pinned markdown document git tracks at or below `here`, checked.

    Tracked files only: a document git does not track cannot have been in the commit it names.

    The documents listed are the ones at or below `here`, by their paths from `here`. A draft's
    successor is looked up among every document the repository tracks, so one above `here` or
    beside it settles the draft. Where the document that ends such a chain lies outside `here`
    and was not passed, it is listed too, once, by its path from the top of the repository:
    otherwise a run here would exit 0 on a draft whose plan is pending or was edited.
    `plan_result` answers for a `PREREG.md` a draft names: what `prereg check` finds for the
    plan at that path, or None where none is there.
    """
    where = try_run("rev-parse", "--show-toplevel", "--show-prefix", cwd=here)
    if where is None:
        return []
    # The top level, then the path from it to `here`: empty at the top, `exp/` one folder down.
    top_name, _, prefix = where.partition("\n")
    top = pathlib.Path(top_name)
    tracked = set(run("ls-files", "-z", "--full-name", "--", "*.md", cwd=top).split("\0"))
    read: dict[str, _Document | None] = {}

    def shown(name: str) -> pathlib.Path:
        return pathlib.Path(posixpath.relpath(name, prefix or "."))

    def document(name: str) -> _Document | None:
        if name not in read:
            read[name] = _read(top, name, shown(name)) if name in tracked else None
        return read[name]

    below = sorted(name for name in tracked if name and name.startswith(prefix))
    found = []
    outside: dict[str, tuple[_Document, list[pathlib.Path]]] = {}
    for d in map(document, below):
        if d is None:
            continue
        result, head = _disposition(d, top, shown, document, plan_result)
        found.append(result)
        if head is not None and not head.name.startswith(prefix):
            outside.setdefault(head.name, (head, []))[1].append(result.path)
    for name, (head, drafts) in sorted(outside.items()):
        own, _ = _disposition(head, top, shown, document, plan_result)
        if own.status in (PENDING, CHANGED, UNKNOWN):
            reached = ", ".join(str(draft) for draft in drafts)
            note = (
                "outside the folder checked, listed by its path from the top of the repository; "
                f"reached from {reached}"
            )
            found.append(Pinned(pathlib.Path(name), own.status, own.commit, (note, *own.detail)))
    return found
