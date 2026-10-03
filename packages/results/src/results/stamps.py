"""Outside timestamps of the ledger's head, and what they prove about the chain.

The anchor file records how long the chain is and where it ends, and whoever can write the ledger
can write the anchor. A timestamp of the head is held by the OpenTimestamps calendars and then by
a Bitcoin block, so it says that a ledger of exactly this length and this last line existed by
the block's date. Every earlier line is covered too, because each line names the hash of the one
before it.

Proofs live under `.results/timestamps/`, one per stamped head, named by the length and the head
so a reader can see what each covers without opening it: `000153-3f9c2a…ots` covers events 1 to
153. They are only ever added. A proof whose head does not match the chain at its length means the
chain was rewritten after it was stamped, which is the one thing a stamp exists to catch.
"""

from __future__ import annotations

import pathlib
import re
from dataclasses import dataclass

from provenance_core import anchor, atomic_write_bytes

from results import ledger

STAMPS = "timestamps"
NAME = re.compile(r"^(\d{6})-([0-9a-f]{16})\.ots$")


@dataclass(frozen=True)
class Stamp:
    path: pathlib.Path
    count: int
    head: str
    status: anchor.Status


@dataclass(frozen=True)
class Reading:
    """What the proofs under `.results/timestamps/` say about this chain, read with no network."""

    dated: Stamp | None
    """The longest stretch of the chain a complete proof covers."""
    pending: Stamp | None
    """The longest stretch a proof covers that Bitcoin has not confirmed yet."""
    contradictions: list[str]


def stamps_dir(lp: pathlib.Path) -> pathlib.Path:
    return lp.parent / STAMPS


def _proofs(lp: pathlib.Path) -> list[tuple[pathlib.Path, int, str]]:
    found = []
    for path in sorted(stamps_dir(lp).glob("*.ots")):
        m = NAME.match(path.name)
        if m:
            found.append((path, int(m.group(1)), m.group(2)))
    return found


def read(lp: pathlib.Path) -> Reading:
    hashes = ledger.line_hashes(lp)
    dated = pending = None
    contradictions = []
    for path, count, short in _proofs(lp):
        if count > len(hashes):
            contradictions.append(
                f"{path.name} dates a chain of {count} events, and the ledger holds {len(hashes)}"
            )
            continue
        head = hashes[count - 1]
        if not head.startswith(short):
            contradictions.append(
                f"{path.name} dates event {count} as {short}…, and the ledger's event {count} "
                f"is {head[:16]}…"
            )
            continue
        try:
            found = Stamp(path, count, head, anchor.status(path.read_bytes(), head))
        except anchor.AnchorError as e:
            contradictions.append(f"{path.name}: {e}")
            continue
        if found.status.is_complete:
            dated = found if dated is None or count > dated.count else dated
        else:
            pending = found if pending is None or count > pending.count else pending
    return Reading(dated, pending, contradictions)


def stamp_head(lp: pathlib.Path) -> pathlib.Path | None:
    """Stamp the head the anchor records, or None where that head is already stamped.

    Refused on a chain that does not verify: a stamp would date the damage.
    """
    status, problems = ledger.verify(lp)
    if status is not ledger.ChainStatus.INTACT:
        raise ledger.ChainError(
            lp,
            f"refusing to timestamp a chain reported as {status.value}: {'; '.join(problems)}",
        )
    recorded = ledger.read_anchor(lp) or {}
    count, head = recorded["count"], recorded["head"]
    path = stamps_dir(lp) / f"{count:06d}-{head[:16]}.ots"
    if path.exists():
        return None
    path.parent.mkdir(exist_ok=True)
    atomic_write_bytes(path, anchor.stamp(head))
    return path


def complete(lp: pathlib.Path) -> list[tuple[Stamp, anchor.Confirmation | None]]:
    """Fetch the rest of every pending proof, and check every complete one against Bitcoin."""
    hashes = ledger.line_hashes(lp)
    out = []
    for path, count, short in _proofs(lp):
        if count > len(hashes) or not hashes[count - 1].startswith(short):
            continue
        head = hashes[count - 1]
        data = anchor.upgrade(path.read_bytes(), head)
        if data != path.read_bytes():
            atomic_write_bytes(path, data)
        found = anchor.status(data, head)
        block = anchor.confirm(data, head) if found.is_complete else None
        out.append((Stamp(path, count, head, found), block))
    return out
