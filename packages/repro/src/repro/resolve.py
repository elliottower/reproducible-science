"""Resolving a locator to exactly one stored value.

One contract over several formats, rather than one pointer syntax pretending every file is a
tree. Each adapter translates a locator into the addressing its format already has -- a JSON
Pointer into JSON, a column and key predicate into a table, a dataset path and index into an
array -- and every adapter enforces the same invariant:

    0 matches       -> ABSENT
    1 scalar        -> RESOLVED
    2 or more       -> AMBIGUOUS
    a container     -> NOT_SCALAR

No adapter takes the first match, and no adapter falls back to searching a file for the
printed number. A search would find the number wherever it appears and call that
verification, which is the failure the whole package exists to prevent. A format with no
adapter reports `FORMAT_UNSUPPORTED` and stops.

**Values come back as text.** The original representation is preserved rather than parsed to
a binary float, because converting `0.1` to a float and back reintroduces exactly the
third-significant-figure disagreements the comparison is meant to measure.
"""

from __future__ import annotations

import csv
import enum
import io
import json
import pathlib
import sqlite3
from collections.abc import Callable
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict

from repro.exceptions import ArtifactUnreadableError, BackendUnavailableError
from repro.models import (
    ArrayLocator,
    PredicateValue,
    SqliteLocator,
    TableLocator,
    TablePositionLocator,
    TreeLocator,
    ValueLocator,
)


class Resolution(enum.StrEnum):
    """What a locator found."""

    RESOLVED = "resolved"
    ABSENT = "absent"
    AMBIGUOUS = "ambiguous"
    NOT_SCALAR = "not_scalar"
    COLUMN_ABSENT = "column_absent"
    """The artifact has no such column or field. The value could be there and is not."""
    SELECTOR_INVALID = "selector_invalid"
    """The locator names a column, field or array the artifact does not have. The manifest is
    wrong, which is a different fact from the artifact lacking the value."""
    FORMAT_UNSUPPORTED = "format_unsupported"


class ExtractedValue(BaseModel):
    """One stored value, in the representation the artifact used."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    raw: str
    native_type: str
    trace: tuple[str, ...] = ()
    """How the value was reached, for a reader reconstructing the address by hand."""


Found = tuple[Resolution, ExtractedValue | None, str]


def _ok(raw: str, native: str, *trace: str) -> Found:
    return Resolution.RESOLVED, ExtractedValue(raw=raw, native_type=native, trace=tuple(trace)), ""


def _no(resolution: Resolution, detail: str) -> Found:
    return resolution, None, detail


# ------------------------------------------------------------------------------------ trees

_TREE_SUFFIXES = {".json": "json", ".yaml": "yaml", ".yml": "yaml"}
_MISSING = object()


def resolve_pointer(document: object, pointer: str) -> object:
    """RFC 6901 JSON Pointer resolution. Returns `_MISSING` when the pointer does not resolve.

    `~1` is a literal `/` and `~0` a literal `~`, unescaped in that order, so a key containing
    a slash is addressable and a key containing a period is unremarkable.
    """
    if pointer == "":
        return document
    if not pointer.startswith("/"):
        raise ValueError(f"JSON Pointer must start with '/': {pointer!r}")
    node = document
    for raw in pointer[1:].split("/"):
        token = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(node, dict):
            if token not in node:
                return _MISSING
            node = node[token]
        elif isinstance(node, list):
            # RFC 6901 array indices are digits with no leading zeros, so "01" addresses
            # nothing and is not silently read as 1.
            if not token.isdigit() or (len(token) > 1 and token[0] == "0"):
                return _MISSING
            index = int(token)
            if index >= len(node):
                return _MISSING
            node = node[index]
        else:
            return _MISSING
    return node


def _no_duplicate_json_keys(pairs: list[tuple[str, object]]) -> dict:
    """`json.loads` keeps the last of a duplicated key, exactly as PyYAML does.

    The YAML path has rejected this from the start; JSON did not, so one artifact could hold
    two values for one quantity and resolve to whichever came last. That is the finding this
    repository's own regression corpus records against someone else's paper.
    """
    seen: dict[str, object] = {}
    for key, value in pairs:
        if key in seen:
            raise ValueError(f"duplicate key {key!r}")
        seen[key] = value
    return seen


class _StrictYaml(yaml.SafeLoader):
    """SafeLoader that refuses duplicate mapping keys.

    PyYAML keeps the last of a duplicated key, so a file with two `accuracy:` entries resolves
    to one of them with nothing said. An artifact that cannot be read one way only is not one
    a pointer can address.
    """


def _no_duplicate_keys(loader, node, deep=False):
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise yaml.constructor.ConstructorError(
                None, None, f"duplicate key {key!r}", key_node.start_mark
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_StrictYaml.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _no_duplicate_keys)


def _load_tree(path: pathlib.Path) -> object:
    fmt = _TREE_SUFFIXES.get(path.suffix.lower())
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as e:
        raise ArtifactUnreadableError(path, str(e)) from e
    if fmt == "json":
        try:
            return json.loads(text, object_pairs_hook=_no_duplicate_json_keys)
        except json.JSONDecodeError as e:
            raise ArtifactUnreadableError(path, f"not valid JSON: {e}") from e
        except ValueError as e:  # raised by the hook below
            raise ArtifactUnreadableError(path, str(e)) from e
    try:
        return yaml.load(text, Loader=_StrictYaml)
    except yaml.YAMLError as e:
        raise ArtifactUnreadableError(path, f"not valid YAML: {e}") from e


def _resolve_tree(locator: TreeLocator, path: pathlib.Path) -> Found:
    if path.suffix.lower() not in _TREE_SUFFIXES:
        return _no(
            Resolution.FORMAT_UNSUPPORTED,
            f"a tree locator addresses JSON or YAML; {path.name} is "
            f"{path.suffix or 'extensionless'}",
        )
    node = resolve_pointer(_load_tree(path), locator.pointer)
    if node is _MISSING:
        return _no(Resolution.ABSENT, f"{locator.pointer} does not resolve in {path.name}")
    if isinstance(node, (dict, list)):
        return _no(
            Resolution.NOT_SCALAR, f"{locator.pointer} holds a {type(node).__name__}, not a value"
        )
    if node is None:
        return _no(Resolution.ABSENT, f"{locator.pointer} holds null")
    return _ok(str(node), type(node).__name__, locator.pointer)


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


# ---------------------------------------------------------------------------------- sqlite

_SQLITE_SUFFIXES = {".db", ".sqlite", ".sqlite3"}


def _resolve_sqlite(locator: SqliteLocator, path: pathlib.Path) -> Found:
    if path.suffix.lower() not in _SQLITE_SUFFIXES:
        return _no(
            Resolution.FORMAT_UNSUPPORTED,
            f"a sqlite locator addresses a database file; {path.name} is {path.suffix}",
        )
    try:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error as e:
        raise ArtifactUnreadableError(path, str(e)) from e
    try:
        tables = {
            r[0]
            for r in connection.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
            )
        }
        if locator.table not in tables:
            return _no(
                Resolution.SELECTOR_INVALID,
                f"{path.name} has no table {locator.table!r}; tables are "
                f"{', '.join(sorted(tables)[:8])}",
            )
        # Identifiers cannot be bound as parameters, so they are checked against the schema
        # and then quoted. Values are always bound.
        columns = {r[1] for r in connection.execute(f'PRAGMA table_info("{locator.table}")')}
        unknown = [c for c in (locator.column, *locator.where) if c not in columns]
        if unknown:
            return _no(
                Resolution.SELECTOR_INVALID,
                f"{locator.table} has no column {', '.join(repr(c) for c in unknown)}; "
                f"columns are {', '.join(sorted(columns)[:8])}",
            )
        clause = " AND ".join(f'"{k}" IS ?' for k in locator.where)
        query = f'SELECT "{locator.column}" FROM "{locator.table}"' + (
            f" WHERE {clause}" if clause else ""
        )
        try:
            found = connection.execute(query, tuple(locator.where.values())).fetchall()
        except sqlite3.Error as e:
            raise ArtifactUnreadableError(path, str(e)) from e
    finally:
        connection.close()

    described = ", ".join(f"{k}={v!r}" for k, v in locator.where.items())
    if not found:
        return _no(Resolution.ABSENT, f"no row in {locator.table} where {described}")
    if len(found) > 1:
        return _no(Resolution.AMBIGUOUS, f"{len(found)} rows in {locator.table} where {described}")
    value = found[0][0]
    if value is None:
        return _no(Resolution.ABSENT, f"{locator.column} is NULL where {described}")
    if isinstance(value, (bytes, memoryview)):
        return _no(Resolution.NOT_SCALAR, f"{locator.column} holds a blob")
    return _ok(str(value), type(value).__name__, f"{locator.table}.{locator.column}")


# ----------------------------------------------------------------------------------- arrays

_ARRAY_SUFFIXES = {".npy", ".npz"}


def _resolve_array(locator: ArrayLocator, path: pathlib.Path) -> Found:
    if path.suffix.lower() not in _ARRAY_SUFFIXES:
        return _no(
            Resolution.FORMAT_UNSUPPORTED,
            f"an array locator addresses .npy or .npz; {path.name} is {path.suffix}",
        )
    try:
        import numpy
    except ImportError as e:
        raise BackendUnavailableError("array", f"numpy is not installed: {e}") from e

    try:
        loaded = numpy.load(path, allow_pickle=False)
    except (OSError, ValueError) as e:
        raise ArtifactUnreadableError(path, str(e)) from e

    if path.suffix.lower() == ".npz":
        if locator.array is None:
            return _no(Resolution.SELECTOR_INVALID, f"{path.name} holds several arrays; name one")
        if locator.array not in loaded.files:
            return _no(
                Resolution.SELECTOR_INVALID,
                f"{path.name} has no array {locator.array!r}; arrays are "
                f"{', '.join(loaded.files[:8])}",
            )
        array = loaded[locator.array]
    else:
        array = loaded

    if len(locator.index) != array.ndim:
        return _no(
            Resolution.SELECTOR_INVALID,
            f"array has {array.ndim} dimensions; index gives {len(locator.index)}",
        )
    if any(i < 0 for i in locator.index):
        # A negative index resolves from the end in Python, so `-1` silently addressed the
        # last element and `-99` raised out of the adapter as a backend defect. Neither is an
        # address; the same condition on the upper side is a clean `absent`.
        return _no(
            Resolution.SELECTOR_INVALID,
            f"index {locator.index} is negative; an address is not relative to the end",
        )
    if any(i >= n for i, n in zip(locator.index, array.shape, strict=True)):
        return _no(
            Resolution.ABSENT, f"index {locator.index} is outside shape {tuple(array.shape)}"
        )
    value = array[locator.index]
    if value.ndim:
        return _no(Resolution.NOT_SCALAR, f"index resolves to a {value.ndim}-d slice")
    return _ok(str(value), str(array.dtype), f"{locator.array or path.stem}{list(locator.index)}")


# --------------------------------------------------------------------------------- dispatch

#: Formats named here have no adapter. Listing them means an unsupported artifact is reported
#: as unsupported rather than as an unreadable one.
UNSUPPORTED = {
    ".h5": "HDF5",
    ".hdf5": "HDF5",
    ".nc": "NetCDF",
    ".parquet": "Parquet",
    ".xlsx": "XLSX",
    ".xls": "XLS",
    ".arrow": "Arrow",
    ".feather": "Feather",
}

#: Keyed by `Locator.kind`, which is what makes the dispatch below sound: each adapter takes
#: the one variant whose discriminator selects it. The annotation is deliberately loose,
#: because a mapping cannot express "the value whose parameter type matches this key".
_ADAPTERS: dict[str, Callable[[Any, pathlib.Path], Found]] = {
    "tree": _resolve_tree,
    "table": _resolve_table,
    "table_position": _resolve_table_position,
    "sqlite": _resolve_sqlite,
    "array": _resolve_array,
}


def resolve(locator: ValueLocator, path: pathlib.Path) -> Found:
    """Resolve one locator against one artifact, to exactly one value or a reason."""
    if named := UNSUPPORTED.get(path.suffix.lower()):
        return _no(
            Resolution.FORMAT_UNSUPPORTED,
            f"{named} has no adapter in this release; addressing it by guesswork "
            f"would not be verification",
        )
    return _ADAPTERS[locator.kind](locator, path)
