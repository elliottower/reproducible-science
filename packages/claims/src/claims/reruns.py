"""The record of re-runs, read: where it is, what it holds, and what a record's files rest on.

`repro reproduce` runs each declared command and appends what it found to
`.repro/reproductions.jsonl`. Nothing here runs a command or writes that file. This is the
half a reader of the record needs: the path, the entries parsed back into the model they were
written from, the digest an output is compared by, and which records lie upstream of one.
`claims.stale`, `claims.why` and `claims.record` read the record through this module, and
`repro.reproduce` and `repro.regenerate`, which write it, take the same names from here.
"""

from __future__ import annotations

import collections
import json
import pathlib

from provenance_core import ZERO, sha256_of_text
from pydantic import ValidationError

from claims.exceptions import ReproError
from claims.models import Digest, RegenerationRecord, ReproductionReport, RerunRecordState
from claims.resolve import resolve_pointer

#: Where each invocation's record is appended, beside the manifest. One JSON object per line.
RECORD = pathlib.Path(".repro") / "reproductions.jsonl"

#: The record's head file: how many entries it holds and the hash of the last. Not
#: `ledger.head`, which is the head of the record of checks kept in the same folder.
HEAD = RECORD.with_name("reproductions.head")


class RecordUnreadableError(ReproError):
    """A line of the record of re-runs is not a report `repro reproduce` wrote."""

    def __init__(self, path: pathlib.Path, line: int, detail: str) -> None:
        self.path = path
        self.line = line
        super().__init__(f"{path}:{line}: {detail}")


def reruns(root: pathlib.Path) -> tuple[ReproductionReport, ...]:
    """Every invocation in the project's record of re-runs, oldest first. Empty where the
    project has no record."""
    path = root / RECORD
    if not path.is_file():
        return ()
    reports = []
    for number, line in enumerate(path.read_text(encoding="utf-8").split("\n"), start=1):
        if not line.strip():
            continue
        try:
            reports.append(ReproductionReport.model_validate_json(line))
        except ValidationError as e:
            first = e.errors()[0]
            where = ".".join(str(x) for x in first["loc"]) or "(top level)"
            raise RecordUnreadableError(path, number, f"{where}: {first['msg']}") from e
    return tuple(reports)


def entries(path: pathlib.Path) -> list[str]:
    """The record's entries as stored, one per line. Split at line feeds only, as
    `provenance_core.chain` reads a chain: an entry can quote a passage holding U+2028."""
    if not path.is_file():
        return []
    return [line.strip() for line in path.read_text(encoding="utf-8").split("\n") if line.strip()]


def read_head(root: pathlib.Path) -> dict | None:
    """The head file, or None where there is none or it is not a JSON object."""
    path = root / HEAD
    if not path.is_file():
        return None
    try:
        head = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return head if isinstance(head, dict) else {}


def chain(root: pathlib.Path) -> RerunRecordState:
    """Whether the record of re-runs is the chain `repro reproduce` wrote.

    The status is the first fault's, as in the `results` ledger: a record edited and then cut
    is edited. Read without a lock, so nothing is written beside the record: `repro stale` and
    `repro verify` leave the working tree as they found it.
    """
    lines = entries(root / RECORD)
    head = read_head(root)
    if not lines:
        if head and head.get("count"):
            return RerunRecordState(
                status="truncated",
                problems=(f"the record is empty and its head file records {head['count']}",),
            )
        return RerunRecordState(status="absent")

    status, problems = "intact", []

    def fault(found: str, said: str) -> None:
        nonlocal status
        problems.append(said)
        if status == "intact":
            status = found

    unchained, chained, prev = 0, False, ZERO
    for number, raw in enumerate(lines, start=1):
        try:
            entry = json.loads(raw)
        except json.JSONDecodeError:
            entry = None
        if not isinstance(entry, dict):
            fault("corrupt", f"entry {number} is not a JSON object")
        elif "prev_hash" not in entry and "seq" not in entry:
            if chained:
                fault("corrupt", f"entry {number} carries no chain fields after entries that do")
            else:
                unchained += 1
        else:
            chained = True
            if entry.get("prev_hash") != prev:
                fault(
                    "edited",
                    f"entry {number - 1} does not hash to what entry {number} recorded for the "
                    "entry before it"
                    if number > 1
                    else "entry 1 records an entry before it",
                )
            if entry.get("seq") != number - 1:
                fault("reordered", f"entry {number} is numbered {entry.get('seq')!r}")
        prev = sha256_of_text(raw)

    if not chained:
        return RerunRecordState(
            status="unchained" if status == "intact" else status,
            entries=len(lines),
            unchained=unchained,
            problems=tuple(problems),
        )
    if head is None:
        if status == "intact":
            status = "no_anchor"
        problems.append(f"no {HEAD.name}, so entries cut from the end would not be found")
    elif head.get("count") != len(lines):
        if status == "intact":
            longer = isinstance(head.get("count"), int) and len(lines) > head["count"]
            status = "extended" if longer else "truncated"
        problems.append(
            f"the head file records {head.get('count')} entries, the record holds {len(lines)}"
        )
    elif head.get("head") != prev:
        fault("edited", f"entry {len(lines)} does not hash to what the head file records")
    return RerunRecordState(
        status=status, entries=len(lines), unchained=unchained, problems=tuple(problems)
    )


def _drop(document: object, pointer: str) -> object:
    """Remove one JSON Pointer's target, if it resolves. Returns the document."""
    if pointer in ("", "/"):
        return document
    parent_pointer, _, last = pointer.rpartition("/")
    parent = resolve_pointer(document, parent_pointer)
    key = last.replace("~1", "/").replace("~0", "~")
    if isinstance(parent, dict):
        parent.pop(key, None)
    elif isinstance(parent, list) and key.isdigit() and int(key) < len(parent):
        parent.pop(int(key))
    return document


def canonical_digest(path: pathlib.Path, volatile: tuple[str, ...]) -> Digest:
    """The artifact's digest, after removing any volatile fields.

    Falls back to the file's own digest where the artifact is not JSON or names no volatile
    fields, so the strict comparison stays the default.
    """
    if not volatile:
        return Digest.of_file(path)
    try:
        document = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        # Volatile fields are addressed as JSON Pointers, so a non-JSON artifact cannot have
        # them removed. Comparing the raw bytes is the honest fallback.
        return Digest.of_file(path)
    for pointer in volatile:
        document = _drop(document, pointer)
    return Digest.of_text(
        json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    )


def upstream(
    record: RegenerationRecord, producers: dict[str, RegenerationRecord]
) -> dict[str, int]:
    """Every record upstream of this one, by id, with how many steps away it is.

    `producers` maps an artifact to the record that writes it. Breadth first and each record
    once, so the distance is the shortest, a record reached by two routes is listed once, and a
    cycle ends the walk. The record itself is listed only where a cycle leads back to it.
    """
    found: dict[str, int] = {}
    pending = collections.deque([(record, 0)])
    while pending:
        current, distance = pending.popleft()
        for wanted in current.inputs:
            producer = producers.get(wanted.artifact)
            if producer is not None and producer.id not in found:
                found[producer.id] = distance + 1
                pending.append((producer, distance + 1))
    return found


__all__ = [
    "HEAD",
    "RECORD",
    "RecordUnreadableError",
    "canonical_digest",
    "chain",
    "entries",
    "read_head",
    "reruns",
    "upstream",
]
