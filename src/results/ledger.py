"""Append-only JSONL ledger: every event is one line, hash-chained to the previous.

**Threat model.** The chain detects accidental damage and casual editing: a crashed write, a
bad sync, a file opened in an editor, a line changed by hand. It does not defend against an
adversary who can write to the directory, because such an adversary can rewrite the anchor as
readily as the ledger. Defending against that needs an external anchor -- a git note, an
OSF registration, a timestamp authority -- and the head digest here is what you would publish
to one.

Saying this plainly matters more than the mechanism. A hash chain is often read as proof of
tamper-resistance when it delivers tamper-*evidence*, and only against a party who does not
hold the pen.

**What the anchor buys.** A chain of `prev_hash` links proves each line follows the one before
it. It does not prove that the last line is the last line ever written: cut the file at any
line boundary and the remainder is a valid chain. Recording the length and head digest
separately turns truncation from undetectable into detected, and turns silent deletion of the
whole ledger into a reported error rather than a clean run.
"""
from __future__ import annotations

import datetime
import enum
import hashlib
import json
import os
import pathlib
import tempfile

LEDGER = "ledger.jsonl"
ANCHOR = "ledger.head"
ZERO = "0" * 64

#: Bumped when the canonical serialization changes. Recorded in the anchor so a ledger written
#: under one rule is not silently verified under another.
CANON_VERSION = 1


class ResultsError(Exception):
    """Base for every error this package raises."""


class NoLedgerRootError(ResultsError):
    """No `.results/` directory governs this location.

    Raised rather than exited, so importing this package into a test, a notebook or an agent
    hook cannot take the host process down. Only the CLI turns it into an exit code.
    """

    def __init__(self, directory: str = "") -> None:
        self.directory = directory
        super().__init__(f"no .results/ in {directory or 'this directory'} or above; "
                         "`results init` makes one")


class ChainError(ResultsError):
    """The ledger could not be read as a chain."""


class ChainStatus(enum.StrEnum):
    """What verification found. Distinct causes, because they have distinct remedies."""

    INTACT = "intact"
    TRUNCATED = "truncated"
    """The chain is internally consistent and shorter than the anchor records."""
    EXTENDED = "extended"
    """Longer than the anchor records: appended to without the anchor being updated."""
    EDITED = "edited"
    """A line's content does not hash to what the next line's prev_hash expects."""
    REORDERED = "reordered"
    """Sequence numbers are not consecutive from zero."""
    CORRUPT = "corrupt"
    """A line is not JSON, or is missing chain fields."""
    NO_ANCHOR = "no_anchor"
    """No anchor file. The chain verifies internally; its length is unattested."""
    ABSENT = "absent"
    """No ledger. Not a pass -- there is nothing to verify."""


def sha256_of_file(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_of_str(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def canonical(event: dict) -> str:
    """The one serialization a line is hashed as.

    Pinned here rather than left implicit at each call site: two orderings of the same event
    hash differently, and a chain verified under a different rule than it was written under
    fails for a reason nobody can act on.
    """
    return json.dumps(event, separators=(",", ":"), sort_keys=True, ensure_ascii=False)


# ---------------------------------------------------------------------------------- reading

def _lines(ledger: pathlib.Path) -> list[str]:
    return [ln.strip() for ln in ledger.read_text(encoding="utf-8").splitlines() if ln.strip()]


def last_hash(ledger: pathlib.Path) -> str:
    """The hash of the last line as stored, or a zero hash if the ledger is empty."""
    if not ledger.exists() or ledger.stat().st_size == 0:
        return ZERO
    lines = _lines(ledger)
    return sha256_of_str(lines[-1]) if lines else ZERO


def read_ledger(ledger: pathlib.Path) -> list[dict]:
    """Every event, or raise `ChainError` naming the line that is not one."""
    if not ledger.exists():
        return []
    events = []
    for i, raw in enumerate(_lines(ledger), start=1):
        try:
            events.append(json.loads(raw))
        except json.JSONDecodeError as e:
            raise ChainError(f"{ledger}: line {i} is not valid JSON: {e}") from e
    return events


# ---------------------------------------------------------------------------------- anchor

def anchor_path(ledger: pathlib.Path) -> pathlib.Path:
    return ledger.with_name(ANCHOR)


def read_anchor(ledger: pathlib.Path) -> dict | None:
    p = anchor_path(ledger)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        raise ChainError(f"{p}: anchor is unreadable: {e}") from e


def write_anchor(ledger: pathlib.Path, count: int, head: str) -> dict:
    """Record how long the chain is and where it ends.

    Written atomically and after the ledger line, so a crash between the two leaves the anchor
    behind the ledger -- reported as `extended`, which is recoverable -- rather than ahead of
    it, which would report a complete ledger as truncated.
    """
    anchor = {"canon_version": CANON_VERSION, "count": count, "head": head,
              "updated": now_iso()}
    _atomic_write(anchor_path(ledger), json.dumps(anchor, indent=2, sort_keys=True) + "\n")
    return anchor


def _atomic_write(path: pathlib.Path, text: str) -> None:
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        pathlib.Path(tmp).unlink(missing_ok=True)
        raise


# --------------------------------------------------------------------------------- writing

def append_event(ledger: pathlib.Path, event: dict) -> dict:
    """Write one event and advance the anchor. Returns a new event; the argument is not
    mutated, so the object a caller holds cannot drift from the line on disk."""
    lines = _lines(ledger) if ledger.exists() else []
    record = {**event,
              "seq": len(lines),
              "timestamp": now_iso(),
              "prev_hash": sha256_of_str(lines[-1]) if lines else ZERO}
    line = canonical(record)
    # Append then anchor: a crash between them under-counts, which verification reports as
    # `extended` and a re-anchor repairs. The reverse would report a whole ledger as truncated.
    with open(ledger, "a", encoding="utf-8") as f:
        f.write(line + "\n")
        f.flush()
        os.fsync(f.fileno())
    write_anchor(ledger, len(lines) + 1, sha256_of_str(line))
    return record


# ------------------------------------------------------------------------------ verifying

def verify(ledger: pathlib.Path) -> tuple[ChainStatus, list[str]]:
    """What the chain is, and every problem found.

    Reports the first structural fault as the status, because a chain that was edited and then
    truncated is edited: the earlier fault explains the later one.
    """
    if not ledger.exists():
        return ChainStatus.ABSENT, [f"{ledger} does not exist"]

    lines = _lines(ledger)
    anchor = read_anchor(ledger)
    problems: list[str] = []

    if not lines:
        detail = "ledger is empty"
        if anchor and anchor.get("count"):
            detail += f"; the anchor records {anchor['count']} events"
            return ChainStatus.TRUNCATED, [detail]
        return ChainStatus.TRUNCATED, [detail]

    prev, status = ZERO, ChainStatus.INTACT
    for i, raw in enumerate(lines):
        try:
            ev = json.loads(raw)
        except json.JSONDecodeError as e:
            problems.append(f"line {i + 1}: not valid JSON: {e}")
            return ChainStatus.CORRUPT, problems
        if "prev_hash" not in ev:
            problems.append(f"line {i + 1}: no prev_hash")
            status = ChainStatus.CORRUPT
        elif ev["prev_hash"] != prev:
            problems.append(
                f"line {i + 1}: prev_hash expected {prev[:16]}…, got {str(ev['prev_hash'])[:16]}…")
            if status is ChainStatus.INTACT:
                status = ChainStatus.EDITED
        if "seq" in ev and ev["seq"] != i:
            problems.append(f"line {i + 1}: seq is {ev['seq']}, expected {i}")
            if status is ChainStatus.INTACT:
                status = ChainStatus.REORDERED
        prev = sha256_of_str(raw)

    if anchor is None:
        problems.append("no anchor: the chain is internally consistent and its length is "
                        "unattested, so truncation cannot be ruled out")
        return (ChainStatus.NO_ANCHOR if status is ChainStatus.INTACT else status), problems

    if anchor.get("canon_version") != CANON_VERSION:
        problems.append(f"anchor written under canon_version {anchor.get('canon_version')}, "
                        f"this is {CANON_VERSION}")
    count, head = anchor.get("count"), anchor.get("head")
    if isinstance(count, int) and count != len(lines):
        problems.append(f"anchor records {count} events, ledger holds {len(lines)}")
        if status is ChainStatus.INTACT:
            status = ChainStatus.TRUNCATED if len(lines) < count else ChainStatus.EXTENDED
    elif head and head != prev:
        problems.append(f"anchor head {str(head)[:16]}… does not match the last line "
                        f"{prev[:16]}…")
        if status is ChainStatus.INTACT:
            status = ChainStatus.EDITED

    return status, problems


def verify_chain(ledger: pathlib.Path) -> tuple[bool, list[str]]:
    """Backward-compatible view: did verification find the chain intact?

    A ledger with no anchor is not reported as intact. It was written before anchoring existed
    or the anchor was removed, and in both cases its length is unattested.
    """
    status, problems = verify(ledger)
    return status is ChainStatus.INTACT, problems


def reanchor(ledger: pathlib.Path) -> dict:
    """Record the current length and head as authoritative.

    For a ledger written before anchoring, and for repairing an under-count after a crash.
    It cannot recover a truncated ledger: re-anchoring a shortened chain records the shortened
    chain, which is why it is a separate deliberate call and not something verification does.
    """
    lines = _lines(ledger) if ledger.exists() else []
    return write_anchor(ledger, len(lines), sha256_of_str(lines[-1]) if lines else ZERO)
