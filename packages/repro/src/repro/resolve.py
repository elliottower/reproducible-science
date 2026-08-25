"""Dispatching a locator to the adapter for its format.

One contract over several formats, rather than one pointer syntax pretending every file is a
tree. Each adapter in `repro.adapters` translates a locator into the addressing its format
already has -- a JSON Pointer into JSON, a column and key predicate into a table, a dataset
name and index into an array -- and every adapter enforces the same invariant:

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

import pathlib
from collections.abc import Callable
from typing import Any

from repro.adapters.array import _resolve_array
from repro.adapters.base import ExtractedValue, Found, Resolution, _no
from repro.adapters.prose import CARDINALS as CARDINALS
from repro.adapters.prose import _resolve_prose
from repro.adapters.sqlite import _resolve_sqlite
from repro.adapters.table import _resolve_table, _resolve_table_position, predicate_text
from repro.adapters.table import read_table as read_table
from repro.adapters.table import sniff_delimiter as sniff_delimiter
from repro.adapters.tree import _resolve_tree
from repro.adapters.tree import resolve_pointer as resolve_pointer
from repro.models import ValueLocator

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
    "prose": _resolve_prose,
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


__all__ = [
    "UNSUPPORTED",
    "ExtractedValue",
    "Found",
    "Resolution",
    "predicate_text",
    "read_table",
    "resolve",
    "resolve_pointer",
    "sniff_delimiter",
]
