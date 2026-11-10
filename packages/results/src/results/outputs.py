"""Whether a number a claim prints is one its run wrote.

A claim names a run, and the run names the files it wrote. Nothing compared the two: a claim
saying 0.9913, bound to a run whose output says 0.4213, verified, because the ledger checked
that the run existed and that its files were the bytes recorded, and never read the number.

A number is held by a run where one of the run's output files prints a value that rounds to it
at the precision the claim prints it to: `0.42` is held by `0.4213`. Where the claim prints the
number as a percentage, with `%` or the word `percent` beside it, it is also held by `0.004213`
or `42.13`, a fraction stored for a percentage printed or the reverse; a bare number is
compared as printed, since a scale applied to every number let `0.05` stand for a stored `5`. Both half-up and
half-even rounding are accepted, since software is divided between them. The outputs are read
as text and every number in them is a candidate, so a JSON file, a CSV and a log are read alike;
a file that is not text holds nothing this can read, and a claim resting only on such files is
said to be unchecked rather than wrong.

The check is that some output holds the value, not that the value is the one the sentence is
about: a number the run wrote under another key is held as well. It catches a number the run
never wrote, and says nothing of a number taken from the wrong place in what it did write.
"""

from __future__ import annotations

import decimal
import hashlib
import pathlib
import re

from results.manuscript import NUMBER, canonical, needs_no_claim, percent_after, readable

#: Bytes read from one output. A run's outputs can be large, and a number a claim prints is
#: almost never past the first few megabytes of the file holding it.
MAX_BYTES = 32 * 1024 * 1024

#: A number in an output file: JSON, CSV and plain text print numbers alike.
STORED = re.compile(r"(?<![\w.])-?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?(?![\w])")

#: The changes of unit a manuscript makes between what is stored and what is printed, for a
#: number printed as a percentage. A bare number is compared at the first alone.
SCALES = (decimal.Decimal(1), decimal.Decimal(100), decimal.Decimal("0.01"))

#: A stored value whose exponent is past this is no number a manuscript prints, and rounding it
#: at sixty digits of precision overflows: `1e999999` in an output crashed the check.
MAX_EXPONENT = 100


def run_outputs(events: list[dict], run_id: str) -> list[str]:
    """Every output path the runs recorded under `run_id` name, in ledger order."""
    paths: list[str] = []
    for e in events:
        if e.get("event") == "run" and e.get("run_id") == run_id:
            paths += [o["path"] for o in e.get("outputs", []) if o["path"] not in paths]
    return paths


def recorded_digests(events: list[dict], run_id: str) -> dict[str, set[str]]:
    """Each output path the runs recorded under `run_id` name, with the digests they recorded."""
    found: dict[str, set[str]] = {}
    for e in events:
        if e.get("event") == "run" and e.get("run_id") == run_id:
            for o in e.get("outputs", []):
                found.setdefault(o["path"], set()).add(o.get("sha256", ""))
    return found


def _bytes(path: pathlib.Path) -> tuple[bytes, str] | None:
    """The first `MAX_BYTES` of a file and the digest of all of it, or None where it cannot be
    read."""
    digest, kept = hashlib.sha256(), bytearray()
    try:
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1 << 20), b""):
                digest.update(block)
                kept += block[: max(0, MAX_BYTES - len(kept))]
    except OSError:
        return None
    return bytes(kept), digest.hexdigest()


def _stored(data: bytes) -> set[decimal.Decimal] | None:
    """Every number in one output's bytes, or None where they are not text this can read."""
    if b"\x00" in data[:8192]:
        return None
    text = data.decode("utf-8", errors="replace")
    found = set()
    for match in STORED.finditer(text):
        try:
            value = decimal.Decimal(match.group(0))
        except decimal.DecimalException:
            continue
        if value.is_finite() and abs(value.adjusted()) <= MAX_EXPONENT:
            found.add(value)
    return found


def places(value: str) -> int:
    """Decimal places a canonical number is printed to."""
    exponent = decimal.Decimal(value).as_tuple().exponent
    return -exponent if isinstance(exponent, int) and exponent < 0 else 0


class Held:
    """The numbers one run's outputs print, rounded to whatever precision is asked of them.

    Each output is read only where its bytes are ones the run recorded: an output edited since
    is listed in `changed` and holds nothing, so a claim is never checked against bytes the run
    did not write."""

    def __init__(self, outputs: list[tuple[pathlib.Path, set[str]]]) -> None:
        self.values: set[decimal.Decimal] = set()
        self.read = 0
        self.changed: list[pathlib.Path] = []
        for path, digests in outputs:
            got = _bytes(path)
            if got is None:
                continue
            if got[1] not in digests:
                self.changed.append(path)
                continue
            found = _stored(got[0])
            if found is not None:
                self.read += 1
                self.values |= found
        self._at: dict[tuple[int, int], set[decimal.Decimal]] = {}

    def _rounded(self, digits: int, scales: tuple[decimal.Decimal, ...]) -> set[decimal.Decimal]:
        key = (digits, len(scales))
        if key not in self._at:
            quantum = decimal.Decimal(1).scaleb(-digits)
            rounded = set()
            with decimal.localcontext() as context:
                context.prec = 60
                for value in self.values:
                    for scale in scales:
                        for mode in (decimal.ROUND_HALF_UP, decimal.ROUND_HALF_EVEN):
                            try:
                                rounded.add((value * scale).quantize(quantum, rounding=mode))
                            except decimal.DecimalException:
                                continue
            self._at[key] = rounded
        return self._at[key]

    def holds(self, value: str, percent: bool = False) -> bool:
        """Whether some stored number rounds to `value`, a canonical printed number. With
        `percent`, the number is printed as a percentage, and a stored fraction or percentage
        of it holds it too."""
        try:
            printed = decimal.Decimal(value)
        except decimal.DecimalException:
            return False
        return printed in self._rounded(places(value), SCALES if percent else SCALES[:1])


def held_by(events: list[dict], run_id: str, base: pathlib.Path) -> Held:
    """What the outputs of the runs recorded under `run_id` hold, read from `base`."""
    return Held([(base / path, d) for path, d in recorded_digests(events, run_id).items()])


def printed_numbers(text: str) -> list[tuple[str, bool]]:
    """The numbers in a claim's text that a run would have to have written, canonical and in
    order, each with whether it is printed as a percentage: those
    `results.manuscript.needs_no_claim` does not exempt. Format characters are read past."""
    text = readable(text)[0]
    found: list[tuple[str, bool]] = []
    for match in NUMBER.finditer(text):
        value = canonical(match.group(0))
        if needs_no_claim(match.group(0), text, match.start()) is None:
            entry = (value, percent_after(text, match.end()))
            if entry not in found:
                found.append(entry)
    return found


def owed(text: str) -> list[str]:
    """The values of `printed_numbers`."""
    return list(dict.fromkeys(value for value, _ in printed_numbers(text)))


def missing(text: str, held: Held) -> list[str]:
    """The numbers the claim prints that none of the run's outputs holds."""
    absent = [value for value, percent in printed_numbers(text) if not held.holds(value, percent)]
    return list(dict.fromkeys(absent))


__all__ = ["Held", "held_by", "missing", "owed", "places", "printed_numbers", "run_outputs"]
