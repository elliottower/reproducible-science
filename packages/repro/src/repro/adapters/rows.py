"""Selecting one cell of a table, whatever format the table was read from.

Every table adapter reduces its file to a header and a list of rows, each row a mapping from
column name to `cells.Cell`, and resolves a locator here. One implementation means a CSV, a
workbook sheet and a Parquet file holding the same table refuse the same manifests for the same
reasons, which three copies of this logic would drift away from.
"""

from __future__ import annotations

from repro.adapters.base import Found, Resolution, _no, _ok
from repro.adapters.cells import Cell, Container


def _header_faults(header: list[str], column: str, where: dict, name: str) -> Found | None:
    """What is wrong with a header before any row is read, or None.

    Shared by every table, delimited or typed, so a workbook and a CSV holding the same table
    refuse the same manifests with the same reasons.
    """
    repeated = sorted({c for c in header if header.count(c) > 1})
    if repeated:
        # `csv.DictReader` keeps the last field of a repeated header, so one of the columns is
        # unreachable and a predicate naming it reports a present row as absent. Neither is a
        # fact about the data.
        return _no(
            Resolution.SELECTOR_INVALID,
            f"{name} repeats the column name {', '.join(repr(c) for c in repeated)}; "
            f"a repeated header makes one of them unaddressable",
        )
    if column not in header:
        return _no(
            Resolution.COLUMN_ABSENT,
            f"{name} has no column {column!r}; columns are {', '.join(header[:8])}",
        )
    unknown = [k for k in where if k not in header]
    if unknown:
        # Left to the row scan this matches nothing and reads as "no such row", blaming the
        # table for a manifest that named a column the table never had.
        return _no(
            Resolution.SELECTOR_INVALID,
            f"selector names {', '.join(repr(k) for k in unknown)}, which "
            f"{name} has no column for; columns are {', '.join(header[:8])}",
        )
    return None


def _cell_found(cell: Cell, column: str, address: str) -> Found:
    """A selected cell as a resolution. A typed table distinguishes a missing value from text.

    `address` is how the row was picked, `where model='vit'` or `at row 3`.
    """
    if cell is None:
        # The typed readers' null: a Parquet null, an R `NA`, an empty workbook cell, a formula
        # whose result was never computed. Like a NULL in SQLite it asserts nothing, so it is
        # absent rather than the empty string a comparison would call non-numeric.
        return _no(Resolution.ABSENT, f"{column} holds no value {address}")
    if isinstance(cell, Container):
        return _no(Resolution.NOT_SCALAR, f"{column} holds {cell.holds} {address}")
    return _ok(cell, "str", f"{column} {address}")


def index_rows(rows: list[dict[str, Cell]], columns: tuple[str, ...]) -> dict[tuple, list[int]]:
    """Row numbers by the cells each row holds in `columns`, for a table of text cells.

    One pass over the table answers every locator that selects on the same columns, where a
    scan per locator read every row once for each of them.
    """
    index: dict[tuple, list[int]] = {}
    for at, row in enumerate(rows):
        index.setdefault(tuple(row.get(column) for column in columns), []).append(at)
    return index


def resolve_rows(
    header: list[str],
    rows: list[dict[str, Cell]],
    column: str,
    where: dict,
    name: str,
    index: dict[tuple, list[int]] | None = None,
) -> Found:
    """The one row whose key cells equal `where`, and its cell in `column`.

    `where` holds text already, in the convention of the table it is matched against:
    `predicate_text` for delimited text, `cells.render` for a typed table. `index` is
    `index_rows` over the sorted names of `where`, and selects the rows a scan would.
    """
    if failure := _header_faults(header, column, where, name):
        return failure
    if index is None:
        matched = [
            i for i, row in enumerate(rows) if all(row.get(k) == v for k, v in where.items())
        ]
    else:
        matched = index.get(tuple(where[k] for k in sorted(where)), [])
    described = ", ".join(f"{k}={v!r}" for k, v in where.items())
    if not matched:
        return _no(Resolution.ABSENT, f"no row in {name} where {described}")
    if len(matched) > 1:
        return _no(Resolution.AMBIGUOUS, f"{len(matched)} rows in {name} where {described}")
    return _cell_found(rows[matched[0]].get(column), column, f"where {described}")


def resolve_row_at(
    header: list[str], rows: list[dict[str, Cell]], column: str, row: int, name: str
) -> Found:
    """The cell in `column` at data row `row`, counting from zero below the header."""
    if failure := _header_faults(header, column, {}, name):
        return failure
    if row >= len(rows):
        return _no(
            Resolution.ABSENT,
            f"{name} has {len(rows)} data rows; row {row} is past the end",
        )
    return _cell_found(rows[row].get(column), column, f"at row {row}")
