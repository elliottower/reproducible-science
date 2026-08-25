"""CSV, TSV and PSV, addressed by column plus a row predicate."""

from __future__ import annotations

import csv
import io
import pathlib

from repro.adapters.base import Found, Resolution, _no, _ok
from repro.exceptions import ArtifactUnreadableError
from repro.models import (
    PredicateValue,
    TableLocator,
    TablePositionLocator,
)

# ----------------------------------------------------------------------------------- tables

#: Delimiters implied by a suffix, checked before sniffing.
_DELIMITERS = {".csv": ",", ".tsv": "\t", ".psv": "|"}
_TABLE_SUFFIXES = set(_DELIMITERS) | {".txt", ""}


def sniff_delimiter(path: pathlib.Path, sample: str) -> str:
    """The delimiter for a table, from its suffix or from the header line.

    Suffix first, because a `.tsv` whose header happens to contain commas is still tab
    separated and sniffing it would split every row in the wrong place.
    """
    if known := _DELIMITERS.get(path.suffix.lower()):
        return known
    header = sample.splitlines()[0] if sample.splitlines() else ""
    counts = {d: header.count(d) for d in (",", "\t", ";", "|")}
    best = max(counts, key=lambda delimiter: counts[delimiter])
    return best if counts[best] else ","


def read_table(path: pathlib.Path, delimiter: str = "") -> tuple[list[str], list[dict]]:
    """Header and rows. Raises `ArtifactUnreadableError` when the file is not a table."""
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as e:
        raise ArtifactUnreadableError(path, str(e)) from e
    if not text.strip():
        raise ArtifactUnreadableError(path, "file is empty")
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter or sniff_delimiter(path, text))
    rows = list(reader)
    if reader.fieldnames is None:
        raise ArtifactUnreadableError(path, "no header row")
    return list(reader.fieldnames), rows


def predicate_text(value: PredicateValue) -> str:
    """A predicate value as the text a delimited cell would hold.

    Delimited files have no types: every cell is text. Comparing as text and never coercing
    keeps `"001"` distinct from `1`, which for an identifier column is the difference between
    two different rows.
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _table_common(path: pathlib.Path, delimiter: str, column: str) -> tuple:
    if path.suffix.lower() not in _TABLE_SUFFIXES:
        return None, _no(
            Resolution.FORMAT_UNSUPPORTED,
            f"a table locator addresses delimited text; {path.name} is {path.suffix}",
        )
    header, rows = read_table(path, delimiter)
    repeated = sorted({name for name in header if header.count(name) > 1})
    if repeated:
        # `csv.DictReader` keeps the last field of a repeated header, so one of the columns is
        # unreachable and a predicate naming it reports a present row as absent. Neither is a
        # fact about the data.
        return None, _no(
            Resolution.SELECTOR_INVALID,
            f"{path.name} repeats the column name {', '.join(repr(c) for c in repeated)}; "
            f"a repeated header makes one of them unaddressable",
        )
    if column not in header:
        return None, _no(
            Resolution.COLUMN_ABSENT,
            f"{path.name} has no column {column!r}; columns are {', '.join(header[:8])}",
        )
    return (header, rows), None


def _resolve_table(locator: TableLocator, path: pathlib.Path) -> Found:
    loaded, failure = _table_common(path, locator.delimiter, locator.column)
    if failure is not None:
        return failure
    header, rows = loaded

    unknown = [k for k in locator.where if k not in header]
    if unknown:
        # Left to the row scan this matches nothing and reads as "no such row", blaming the
        # table for a manifest that named a column the table never had.
        return _no(
            Resolution.SELECTOR_INVALID,
            f"selector names {', '.join(repr(k) for k in unknown)}, which "
            f"{path.name} has no column for; columns are {', '.join(header[:8])}",
        )

    wanted = {k: predicate_text(v) for k, v in locator.where.items()}
    matched = [
        i
        for i, row in enumerate(rows)
        if all((row.get(k) or "").strip() == v for k, v in wanted.items())
    ]
    described = ", ".join(f"{k}={v!r}" for k, v in wanted.items())
    if not matched:
        return _no(Resolution.ABSENT, f"no row in {path.name} where {described}")
    if len(matched) > 1:
        return _no(Resolution.AMBIGUOUS, f"{len(matched)} rows in {path.name} where {described}")
    cell = (rows[matched[0]].get(locator.column) or "").strip()
    return _ok(cell, "str", f"{locator.column} where {described}")


def _resolve_table_position(locator: TablePositionLocator, path: pathlib.Path) -> Found:
    loaded, failure = _table_common(path, locator.delimiter, locator.column)
    if failure is not None:
        return failure
    _, rows = loaded
    if locator.row >= len(rows):
        return _no(
            Resolution.ABSENT,
            f"{path.name} has {len(rows)} data rows; row {locator.row} is past the end",
        )
    cell = (rows[locator.row].get(locator.column) or "").strip()
    return _ok(cell, "str", f"{locator.column} at row {locator.row}")
