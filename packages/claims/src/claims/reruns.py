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

from pydantic import ValidationError

from claims.exceptions import ReproError
from claims.models import Digest, RegenerationRecord, ReproductionReport
from claims.resolve import resolve_pointer

#: Where each invocation's record is appended, beside the manifest. One JSON object per line.
RECORD = pathlib.Path(".repro") / "reproductions.jsonl"


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
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            reports.append(ReproductionReport.model_validate_json(line))
        except ValidationError as e:
            first = e.errors()[0]
            where = ".".join(str(x) for x in first["loc"]) or "(top level)"
            raise RecordUnreadableError(path, number, f"{where}: {first['msg']}") from e
    return tuple(reports)


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


__all__ = ["RECORD", "RecordUnreadableError", "canonical_digest", "reruns", "upstream"]
