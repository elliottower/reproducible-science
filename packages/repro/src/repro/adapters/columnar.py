"""Binary formats that hold one table: Parquet, Feather, Arrow, Stata, SPSS, and R's `.rds`.

Each is read into the header and rows a delimited file gives, with every cell rendered by
`repro.adapters.cells`, and resolved by `repro.adapters.rows`. A table locator therefore
addresses `results.parquet` exactly as it addresses `results.csv`, and the same table in either
format refuses and resolves the same manifests.

Every reader is an optional extra, and a missing one raises `BackendUnavailableError` naming
it, which the engine reports as `unchecked`:

    .parquet .feather .arrow   pyarrow      reproducible-science[parquet]
    .dta .sav .zsav            pyreadstat   reproducible-science[stata-spss]
    .rds                       rdata        reproducible-science[rds]

**No reader here executes the file.** A pickle is a program, and an `.rds` read by R can be
one: R's deserializer evaluated a promise embedded in the stream when the restored object was
first used (CVE-2024-27322). `rdata` is a parser of R's serialization format written in Python.
It builds the objects the bytes describe and evaluates nothing, and no R process is started.
`pyreadr` would also avoid R, and is not used because it is AGPL.
"""

from __future__ import annotations

import lzma
import pathlib
import zlib

from repro.adapters.cells import Cell, Container, render, shortest_single
from repro.exceptions import ArtifactUnreadableError, BackendUnavailableError

try:  # optional: `pip install "reproducible-science[parquet]"`
    import pyarrow
    import pyarrow.compute
    import pyarrow.feather
    import pyarrow.parquet
except ImportError:  # pragma: no cover - exercised by the extras matrix, not the suite
    pyarrow = None

try:  # optional: `pip install "reproducible-science[stata-spss]"`
    import pyreadstat
except ImportError:  # pragma: no cover
    pyreadstat = None

try:  # optional: `pip install "reproducible-science[rds]"`
    import rdata
except ImportError:  # pragma: no cover
    rdata = None

_ARROW_SUFFIXES = {".parquet", ".feather", ".arrow"}
_READSTAT_SUFFIXES = {".dta", ".sav", ".zsav"}
COLUMNAR_SUFFIXES = _ARROW_SUFFIXES | _READSTAT_SUFFIXES | {".rds"}

Frame = tuple[list[str], list[dict[str, Cell]]]


def read_columnar(path: pathlib.Path, wanted: set[str]) -> Frame:
    """The file's header, and its rows restricted to the `wanted` columns it has.

    Only the columns a locator names are read. A results file can hold thousands of columns,
    and the header alone settles whether the locator names columns the file has.
    """
    suffix = path.suffix.lower()
    if suffix in _ARROW_SUFFIXES:
        return _arrow(path, wanted)
    if suffix in _READSTAT_SUFFIXES:
        return _readstat(path, wanted)
    return _rds(path, wanted)


def _rows(header: list[str], columns: dict[str, list[Cell]], n: int) -> Frame:
    return header, [{name: cells[i] for name, cells in columns.items()} for i in range(n)]


def _addressable(header: list[str], wanted: set[str]) -> list[str]:
    """The wanted columns that occur once. A repeated name is refused before any row is read."""
    return [name for name in header if name in wanted and header.count(name) == 1]


# ------------------------------------------------------------------------------------ arrow


_NO_PYARROW = 'pyarrow is not installed -- pip install "reproducible-science[parquet]"'


def _arrow(path: pathlib.Path, wanted: set[str]) -> Frame:
    if pyarrow is None:
        raise BackendUnavailableError("table", _NO_PYARROW)
    try:
        if path.suffix.lower() == ".parquet":
            header = list(pyarrow.parquet.read_schema(path).names)
            table = pyarrow.parquet.read_table(path, columns=_addressable(header, wanted))
        else:
            table = pyarrow.feather.read_table(path)
            header = list(table.column_names)
    except (pyarrow.ArrowException, OSError) as e:
        raise ArtifactUnreadableError(path, f"not a readable {path.suffix} file: {e}") from e
    columns = {name: _arrow_cells(table.column(name)) for name in _addressable(header, wanted)}
    return _rows(header, columns, table.num_rows)


def _arrow_cells(column) -> list[Cell]:
    """A column as text, by Arrow's own cast.

    Arrow renders a float as the shortest decimal that round-trips at the column's own width,
    so a `float32` 0.1 is `0.1` rather than the 0.10000000149011612 a conversion to a Python
    float produces. A nested column has no text form, and each of its cells is a container.
    """
    if pyarrow is None:  # pragma: no cover - `_arrow` has already raised
        raise BackendUnavailableError("table", _NO_PYARROW)
    kind = column.type
    if pyarrow.types.is_nested(kind) or pyarrow.types.is_union(kind):
        return [
            None if v is None else Container(holds=f"an Arrow {kind}") for v in column.to_pylist()
        ]
    try:
        text = pyarrow.compute.cast(column, pyarrow.string()).to_pylist()
    except pyarrow.ArrowException:
        # Binary that is not UTF-8, an extension type: there is no text to compare.
        return [
            None if v is None else Container(holds=f"an Arrow {kind}") for v in column.to_pylist()
        ]
    return [render(v) for v in text]


# --------------------------------------------------------------------------------- readstat


def _readstat(path: pathlib.Path, wanted: set[str]) -> Frame:
    if pyreadstat is None:
        raise BackendUnavailableError(
            "table",
            'pyreadstat is not installed -- pip install "reproducible-science[stata-spss]"',
        )
    read = pyreadstat.read_dta if path.suffix.lower() == ".dta" else pyreadstat.read_sav
    try:
        _, meta = read(str(path), metadataonly=True, output_format="dict")
        header = list(meta.column_names)
        usecols = _addressable(header, wanted)
        data, meta = read(str(path), usecols=usecols, output_format="dict")
    except (pyreadstat.ReadstatError, pyreadstat.PyreadstatError, OSError) as e:
        raise ArtifactUnreadableError(path, f"not a readable {path.suffix} file: {e}") from e
    # Value labels are not applied: a labelled column is matched and read by its stored code,
    # which is what the file holds. Applying them would make a predicate depend on a label set
    # the analyst can change without touching a single value.
    widths = meta.readstat_variable_types
    columns = {
        name: [
            shortest_single(v)
            if widths.get(name) == "float" and isinstance(v, float)
            else render(v)
            for v in data[name]
        ]
        for name in usecols
    }
    return _rows(header, columns, meta.number_rows or 0)


# -------------------------------------------------------------------------------------- rds


def _rds(path: pathlib.Path, wanted: set[str]) -> Frame:
    if rdata is None:
        raise BackendUnavailableError(
            "table", 'rdata is not installed -- pip install "reproducible-science[rds]"'
        )
    try:
        frame = rdata.read_rds(path)
    except (ValueError, NotImplementedError, EOFError, OSError, zlib.error, lzma.LZMAError) as e:
        raise ArtifactUnreadableError(path, f"not a readable .rds file: {e}") from e
    if type(frame).__name__ != "DataFrame" or not hasattr(frame, "columns"):
        # A model fit, a vector, a list: an .rds holds any one R object. Only a data frame is a
        # table, and a value inside anything else has no address this locator can give.
        raise ArtifactUnreadableError(
            path, f"holds an R object read as {type(frame).__name__}, not a data frame"
        )
    header = [str(c) for c in frame.columns]
    columns = {}
    for name in _addressable(header, wanted):
        series = frame[name]
        # R's `NA` reaches pandas as NaN or `pd.NA` depending on the column type, and
        # `isna` is the one test that recognizes both.
        missing = series.isna().tolist()
        columns[name] = [
            None if absent else render(v)
            for v, absent in zip(series.tolist(), missing, strict=True)
        ]
    return _rows(header, columns, len(frame))
