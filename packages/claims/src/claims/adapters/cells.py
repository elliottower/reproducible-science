"""A typed cell as the text a delimited cell would hold.

A delimited file stores text, so the table adapter compares text and returns text. A workbook,
a Parquet file or a Stata file stores a typed value, and the row predicate and the comparison
both need it as text in one convention, or the same table exported two ways would resolve
differently. The convention is the shortest text that reads back as the stored value:

    float     the shortest decimal that round-trips, `0.1` and never `0.1000000000000000055`
    integral  `2` rather than `2.0`, so `where: {seed: 2}` selects a row SPSS stored as 2.0
    boolean   `true` / `false`, which is what `predicate_text` writes for a boolean predicate
    missing   None, which a value cell reports as absent and a key cell never matches

Nothing here rounds. A stored 0.6478999999999999 comes back as that, and the comparison
applies the manuscript's printed precision exactly as it does to a cell of a CSV.
"""

from __future__ import annotations

import datetime
import decimal
import math
import struct

from pydantic import BaseModel, ConfigDict


class Container(BaseModel):
    """A cell holding several values -- a list, a record, a nested frame.

    Not text. Stringifying one produced `[0.91, 0.02]` in the array adapter and compared it as
    though it were a number, so a container is carried as itself and reported as not a scalar.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    holds: str


Cell = str | Container | None


def shortest_single(value: float) -> str:
    """The shortest decimal that reads back as the same 32-bit float.

    Stata stores `float` columns in four bytes, and every reader widens them to a double:
    0.1 comes back as 0.10000000149011612, which is the double nearest the single, not the
    number the analyst wrote. A manuscript printing 0.100000 would then be contradicted by
    digits the file never held.
    """
    packed = struct.pack("<f", value)
    for digits in range(1, 10):
        text = f"{value:.{digits}g}"
        if struct.pack("<f", float(text)) == packed:
            return _integral(text)
    return _integral(repr(value))  # pragma: no cover - nine digits always round-trip a single


def _integral(text: str) -> str:
    return text[:-2] if text.endswith(".0") else text


def render(value: object) -> Cell:
    """One stored value, as text in the convention above.

    Numpy scalars arrive from some readers, and are recognized by duck typing rather than by
    importing numpy, which none of the table readers' extras otherwise need here.
    """
    if value is None:
        return None
    if isinstance(value, Container):
        return value
    item = getattr(value, "item", None)
    if callable(item) and not isinstance(value, (str, bytes, float, int)):
        kind = getattr(getattr(value, "dtype", None), "kind", "")
        if kind == "f":
            # `item()` widens a float32 to a double, which is the defect `shortest_single`
            # exists to undo. Numpy's own `str` is already the shortest for the value's width.
            return _integral(str(value))
        value = item()
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return "nan" if math.isnan(value) else _integral(repr(value))
    if isinstance(value, int | decimal.Decimal):
        return str(value)
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace").strip()
    if isinstance(value, datetime.datetime | datetime.date | datetime.time):
        return value.isoformat()
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list | tuple | dict | set):
        return Container(holds=f"a {type(value).__name__} of {len(value)}")
    return Container(holds=f"a {type(value).__name__}")
