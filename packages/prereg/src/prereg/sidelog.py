"""The log kept beside a plan frozen whole: `PREREG.log`, and its anchor `PREREG.log.head`.

A plan frozen whole cannot hold its own log, so notes and deviations go in a file of their own.
It is append-only by construction: the first entry carries the plan's digest, and each later
entry carries the digest of the entry before it, so removing or rewording an entry breaks every
entry after it.

    2026-10-06T14:03:11+00:00  tolerance now from fixtures           no results seen  ·<digest>

Chaining alone cannot see an entry removed from the end, because the entries that remain still
follow one another. The anchor is the witness to the length: a small file holding the number of
entries and the digest of the last, rewritten on each append, as the results ledger's
`ledger.head` is. Neither file is frozen. Someone who removes the last entry and edits the
anchor to match leaves a pair that verifies; `prereg check --staged` refuses that at a commit,
and the commit history is what shows it afterwards.
"""

from __future__ import annotations

import json
import pathlib

from provenance_core import atomic_write, exclusive_lock, sha256_of_text

from prereg.log import LOG_MARK


class LogError(Exception):
    """The log does not verify, so nothing is appended to it."""


def log_path(plan: pathlib.Path) -> pathlib.Path:
    """`PREREG.log` for `PREREG.md`."""
    return plan.with_suffix(".log")


def anchor_path(plan: pathlib.Path) -> pathlib.Path:
    """`PREREG.log.head` for `PREREG.md`."""
    return plan.with_suffix(".log.head")


def lines_of(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.strip()]


def entries(plan: pathlib.Path) -> list[str]:
    """The log's entries, in order. Empty where nothing has been logged."""
    path = log_path(plan)
    return lines_of(path.read_text()) if path.is_file() else []


def read_anchor(text: str) -> tuple[int, str]:
    """The count and head an anchor records. `ValueError` where it is not an anchor."""
    held = json.loads(text)
    try:
        return int(held["count"]), str(held["head"])
    except (KeyError, TypeError) as e:
        raise ValueError(f"not a log anchor: {e}") from e


def _chain(found: list[str], digest: str) -> list[str]:
    previous = digest
    for i, line in enumerate(found, start=1):
        if line.rpartition(LOG_MARK)[2] != previous:
            if i == 1:
                return [f"the first entry does not carry this plan's digest, {digest[:16]}…"]
            return [
                f"log entry {i} does not follow the one before it: an entry has been "
                f"edited, reordered or removed"
            ]
        previous = sha256_of_text(line)
    return []


def _against_anchor(plan: pathlib.Path, found: list[str]) -> tuple[list[str], bool]:
    """What the anchor says the entries are not, and whether the log has only grown past it."""
    where = anchor_path(plan)
    if not where.is_file():
        return ([f"{where.name} is missing, and it is what records the log's length"], False)
    try:
        count, head = read_anchor(where.read_text())
    except ValueError as e:
        return ([f"{where.name} cannot be read: {e}"], False)
    if len(found) < count:
        gone = count - len(found)
        removed = "an entry has" if gone == 1 else f"{gone} entries have"
        return (
            [
                f"the log records {count} entries and holds {len(found)}: {removed} been removed "
                f"from the end"
            ],
            False,
        )
    if count and sha256_of_text(found[count - 1]) != head:
        return (["the log's last recorded entry is not the one recorded"], False)
    if len(found) > count:
        return (
            [
                f"the log records {count} entries and holds {len(found)}: the entries past the "
                f"record were not written by `prereg log`, which brings the record up to date"
            ],
            True,
        )
    return ([], False)


def problems(plan: pathlib.Path, digest: str) -> list[str]:
    """Where the log does not follow from the plan frozen as `digest`, or from its anchor."""
    found = entries(plan)
    if not found and not anchor_path(plan).is_file():
        return []
    return _chain(found, digest) or _against_anchor(plan, found)[0]


def append(plan: pathlib.Path, digest: str, time: str, event: str, access: str) -> None:
    """Add one entry, chained to the entry before it, or to the plan where it is the first.

    The lock covers the read as well as the write: two callers that read the same last entry
    would each chain to it, and the second write would hold only its own.

    Nothing is appended to a log that does not verify. The anchor is the only witness to the
    last entry, and an append rewrites it, so building on a shortened log would erase the one
    record that it was shortened. A log that has only grown past its anchor, as a write killed
    between the two files leaves it, is appended to and the anchor recounted.
    """
    path = log_path(plan)
    with exclusive_lock(path):
        existing = entries(plan)
        if existing or anchor_path(plan).is_file():
            found, grown = _against_anchor(plan, existing)
            found = _chain(existing, digest) or ([] if grown else found)
            if found:
                raise LogError(f"{path} does not verify, so nothing was appended: {found[0]}")
        previous = sha256_of_text(existing[-1]) if existing else digest
        # Two spaces between fields, as in the log an earlier freeze kept in the plan: the access
        # level is the field that separates an amendment from a deviation, and it must not run
        # into the note.
        line = f"{time}  {event:<36}  {access}  {LOG_MARK}{previous}"
        # The log, then the anchor: a crash between them leaves the anchor behind the log, which
        # the next append repairs. The reverse would report a complete log as shortened.
        atomic_write(path, "".join(f"{entry}\n" for entry in [*existing, line]))
        anchor = {"count": len(existing) + 1, "head": sha256_of_text(line)}
        atomic_write(anchor_path(plan), json.dumps(anchor, indent=2) + "\n")
