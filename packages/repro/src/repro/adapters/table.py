"""Tables, addressed by column plus a row predicate.

CSV, TSV and PSV are read here. Parquet, Feather, Stata, SPSS and R data frames are read by
`repro.adapters.columnar` into the same header and rows, and resolved by the same code, so a
table and its export to another format refuse and resolve the same manifests.
"""

from __future__ import annotations

import csv
import io
import pathlib

from repro.adapters.base import Found, Resolution, _no
from repro.adapters.cells import Cell, render
from repro.adapters.columnar import COLUMNAR_SUFFIXES, read_columnar
from repro.adapters.reads import once
from repro.adapters.rows import index_rows, resolve_row_at, resolve_rows
from repro.adapters.sheet import WORKBOOK_SUFFIXES
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


def _delimited(path: pathlib.Path, delimiter: str) -> tuple[list[str], list[dict[str, Cell]]]:
    header, rows = read_table(path, delimiter)
    # Every delimited cell is text. A short row's missing fields come back as None, which here
    # would read as a null; they were always the empty string, and stay so. The `None` key
    # holds a long row's surplus fields, which no header names.
    text = [{k: (v or "").strip() for k, v in row.items() if k is not None} for row in rows]
    return header, text


def _load(path: pathlib.Path, delimiter: str, wanted: set[str]) -> tuple[tuple, Found | None]:
    """A table's header and rows from whichever reader its suffix names, or why not.

    `wanted` is the columns a locator names, which is all a columnar reader reads.
    """
    suffix = path.suffix.lower()
    if suffix in COLUMNAR_SUFFIXES:
        if delimiter:
            return (), _no(
                Resolution.SELECTOR_INVALID,
                f"{path.name} is {suffix}, which has no delimiter to override",
            )
        return read_columnar(path, wanted), None
    if suffix in WORKBOOK_SUFFIXES:
        return (), _no(
            Resolution.FORMAT_UNSUPPORTED,
            f"{path.name} is a workbook, which holds several tables; address it with "
            f"`kind: sheet`, which names the sheet",
        )
    if suffix not in _TABLE_SUFFIXES:
        return (), _no(
            Resolution.FORMAT_UNSUPPORTED,
            f"a table locator addresses delimited text or a columnar file; "
            f"{path.name} is {path.suffix}",
        )
    return once(("delimited", path, delimiter), lambda: _delimited(path, delimiter)), None


def _resolve_table(locator: TableLocator, path: pathlib.Path) -> Found:
    loaded, failure = _load(path, locator.delimiter, {locator.column, *locator.where})
    if failure is not None:
        return failure
    header, rows = loaded
    # Delimited text is matched as text, as it always was; a typed table renders the predicate
    # in the convention its cells were rendered in, so `seed: 2` selects a stored 2.0.
    columnar = path.suffix.lower() in COLUMNAR_SUFFIXES
    key = render if columnar else predicate_text
    wanted = {k: key(v) for k, v in locator.where.items()}
    if columnar:
        # A columnar read holds only the columns one locator named, so it is not shared.
        return resolve_rows(header, rows, locator.column, wanted, path.name)
    columns = tuple(sorted(wanted))
    index = once(("rows", path, locator.delimiter, columns), lambda: index_rows(rows, columns))
    return resolve_rows(header, rows, locator.column, wanted, path.name, index)


def _resolve_table_position(locator: TablePositionLocator, path: pathlib.Path) -> Found:
    loaded, failure = _load(path, locator.delimiter, {locator.column})
    if failure is not None:
        return failure
    header, rows = loaded
    return resolve_row_at(header, rows, locator.column, locator.row, path.name)
