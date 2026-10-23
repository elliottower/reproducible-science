"""Whether a number a claim prints is one its run wrote.

A claim names a run, and the run names the files it wrote. Nothing compared the two: a claim
saying 0.9913, bound to a run whose output says 0.4213, verified, because the ledger checked
that the run existed and that its files were the bytes recorded, and never read the number.

A number is held by a run where one of the run's output files prints a value that rounds to it
at the precision the claim prints it to: `0.42` is held by `0.4213`, and by `42.13` or `0.004213`
where the claim prints a percentage of a stored fraction or the reverse. Both half-up and
half-even rounding are accepted, since software is divided between them. The outputs are read
as text and every number in them is a candidate, so a JSON file, a CSV and a log are read alike;
a file that is not text holds nothing this can read, and a claim resting only on such files is
said to be unchecked rather than wrong.
"""

from __future__ import annotations

import decimal
import pathlib
import re

from results.manuscript import NUMBER, canonical, needs_no_claim

#: Bytes read from one output. A run's outputs can be large, and a number a claim prints is
#: almost never past the first few megabytes of the file holding it.
MAX_BYTES = 32 * 1024 * 1024

#: A number in an output file: JSON, CSV and plain text print numbers alike.
STORED = re.compile(r"(?<![\w.])-?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?(?![\w])")

#: The changes of unit a manuscript makes between what is stored and what is printed.
SCALES = (decimal.Decimal(1), decimal.Decimal(100), decimal.Decimal("0.01"))


def run_outputs(events: list[dict], run_id: str) -> list[str]:
    """Every output path the runs recorded under `run_id` name, in ledger order."""
    paths: list[str] = []
    for e in events:
        if e.get("event") == "run" and e.get("run_id") == run_id:
            paths += [o["path"] for o in e.get("outputs", []) if o["path"] not in paths]
    return paths


def _stored(path: pathlib.Path) -> set[decimal.Decimal] | None:
    """Every number in one output, or None where the file is not text this can read."""
    try:
        with path.open("rb") as handle:
            data = handle.read(MAX_BYTES)
    except OSError:
        return None
    if b"\x00" in data[:8192]:
        return None
    text = data.decode("utf-8", errors="replace")
    found = set()
    for match in STORED.finditer(text):
        try:
            found.add(decimal.Decimal(match.group(0)))
        except decimal.InvalidOperation:
            continue
    return found


def places(value: str) -> int:
    """Decimal places a canonical number is printed to."""
    exponent = decimal.Decimal(value).as_tuple().exponent
    return -exponent if isinstance(exponent, int) and exponent < 0 else 0


class Held:
    """The numbers one run's outputs print, rounded to whatever precision is asked of them."""

    def __init__(self, paths: list[pathlib.Path]) -> None:
        self.values: set[decimal.Decimal] = set()
        self.read = 0
        for path in paths:
            found = _stored(path)
            if found is not None:
                self.read += 1
                self.values |= found
        self._at: dict[int, set[decimal.Decimal]] = {}

    def _rounded(self, digits: int) -> set[decimal.Decimal]:
        if digits not in self._at:
            quantum = decimal.Decimal(1).scaleb(-digits)
            rounded = set()
            with decimal.localcontext() as context:
                context.prec = 60
                for value in self.values:
                    for scale in SCALES:
                        for mode in (decimal.ROUND_HALF_UP, decimal.ROUND_HALF_EVEN):
                            try:
                                rounded.add((value * scale).quantize(quantum, rounding=mode))
                            except decimal.InvalidOperation:
                                continue
            self._at[digits] = rounded
        return self._at[digits]

    def holds(self, value: str) -> bool:
        """Whether some stored number rounds to `value`, a canonical printed number."""
        try:
            printed = decimal.Decimal(value)
        except decimal.InvalidOperation:
            return False
        return printed in self._rounded(places(value))


def held_by(events: list[dict], run_id: str, base: pathlib.Path) -> Held:
    """What the outputs of the runs recorded under `run_id` hold, read from `base`."""
    return Held([base / path for path in run_outputs(events, run_id)])


def owed(text: str) -> list[str]:
    """The numbers in a claim's text that a run would have to have written, canonical and in
    order: those `results.manuscript.needs_no_claim` does not exempt."""
    found = []
    for match in NUMBER.finditer(text):
        value = canonical(match.group(0))
        if needs_no_claim(match.group(0), text, match.start()) is None and value not in found:
            found.append(value)
    return found


def missing(text: str, held: Held) -> list[str]:
    """The numbers the claim prints that none of the run's outputs holds."""
    return [value for value in owed(text) if not held.holds(value)]


__all__ = ["Held", "held_by", "missing", "owed", "places", "run_outputs"]
