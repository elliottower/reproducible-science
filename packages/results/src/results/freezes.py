"""The freezes `prereg` recorded, read as data, and where each sits in this ledger's order.

`results claim --frozen-at` once took any reference git could resolve and dated the freeze by
its commit date. A commit date is whatever the committer's clock or `GIT_COMMITTER_DATE` said,
so a plan frozen after the outcomes were seen, in a commit dated a year earlier, made a
confirmatory claim pass. What dates a freeze is the record `prereg freeze` wrote beside the
plan, `.prereg/<file>.json`: the full commit, the instant of the freeze, and, where a ledger
existed, how many of its events it held then and the digest of the last. The position is the
part no clock can move. An event the ledger held at the freeze came before it, and one it did
not came after, and the chain fixes which is which.

This module reads those records and never imports `prereg`, as `prereg` reads the ledger and
never imports this package.
"""

from __future__ import annotations

import json
import pathlib
import re
from dataclasses import dataclass

from provenance_core import sha256_of_text
from provenance_core.gitref import try_run

from results.timeline import precedes

RECORDS = ".prereg"
SKIPPED = {".git", "node_modules", ".venv", "venv", "site-packages"}

#: A full commit id, SHA-1 or SHA-256.
FULL_COMMIT = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")


@dataclass(frozen=True)
class Freeze:
    """One freeze record."""

    record: pathlib.Path
    commit: str
    frozen_at: str
    #: How many events this ledger held at the freeze, where the record names this ledger and
    #: its digest of the last of them still matches. None where it cannot be placed that way.
    position: int | None
    #: Why the record's position in the ledger could not be used, where it names one.
    misplaced: str = ""


def lines_of(ledger: pathlib.Path) -> list[str]:
    """The ledger's events as written, one per line."""
    return [line for line in ledger.read_text().splitlines() if line.strip()]


def _place(record: pathlib.Path, held: dict, ledger: pathlib.Path, lines: list[str]):
    """The record's position in `ledger`, or None and why where it names one but cannot be
    placed there."""
    where = held.get("ledger")
    if not isinstance(where, dict):
        return None, ""
    named = (record.parent.parent / str(where.get("path", ""))).resolve()
    if named != ledger.resolve():
        return None, ""
    events = where.get("events")
    if not isinstance(events, int) or events < 0 or events > len(lines):
        return None, f"it records {events} ledger events, and the ledger holds {len(lines)}"
    head = where.get("head") or ""
    if events and sha256_of_text(lines[events - 1]) != head:
        return None, f"event {events} of the ledger is not the event it recorded as the last"
    return events, ""


def read_all(project: pathlib.Path, ledger: pathlib.Path) -> list[Freeze]:
    """Every freeze record in the repository holding `project`, or below `project` outside one."""
    top = try_run("rev-parse", "--show-toplevel", cwd=project)
    base = pathlib.Path(top) if top else project
    lines = lines_of(ledger) if ledger.is_file() else []
    found = []
    for record in sorted(base.rglob(f"{RECORDS}/*.json")):
        if any(part in SKIPPED for part in record.relative_to(base).parts):
            continue
        try:
            held = json.loads(record.read_text(errors="replace"))
        except (OSError, ValueError):
            continue
        if not isinstance(held, dict) or not isinstance(held.get("commit"), str):
            continue
        position, misplaced = _place(record, held, ledger, lines)
        found.append(
            Freeze(record, held["commit"], str(held.get("frozen_at", "")), position, misplaced)
        )
    return found


def named(freezes: list[Freeze], commit: str) -> Freeze | None:
    """The freeze recorded at exactly `commit`, or None."""
    return next((f for f in freezes if f.commit == commit), None)


def index_of(lines: list[str], kind: str, test) -> int | None:
    """The position of the first event of `kind` passing `test`, or None."""
    for i, line in enumerate(lines):
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get("event") == kind and test(event):
            return i
    return None


def run_index(lines: list[str], run_id: str) -> int | None:
    """The position of the latest run recorded under `run_id`, which a claim rests on."""
    found = None
    for i, line in enumerate(lines):
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get("event") == "run" and event.get("run_id") == run_id:
            found = i
    return found


def before(freeze: Freeze, index: int | None, stamp: str | None) -> bool | None:
    """Whether the freeze came before the event at `index` of the ledger, stamped `stamp`.

    By position where the record places the freeze in this ledger: the event came after it
    exactly when the ledger did not yet hold it. Otherwise by the instant the record gives,
    which `prereg freeze` wrote from the clock, as the ledger writes its own. Never by a commit
    date. None where neither can say.
    """
    if freeze.position is not None and index is not None:
        return index >= freeze.position
    if freeze.misplaced:
        return None
    if freeze.frozen_at and stamp:
        return precedes(freeze.frozen_at, stamp)
    return None
