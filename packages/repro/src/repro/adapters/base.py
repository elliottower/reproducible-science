"""The contract every format adapter returns.

Split from `repro.resolve` so an adapter can import it without importing the dispatcher
that imports the adapter. Original module docstring follows.

Resolving a locator to exactly one stored value.

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

import enum

from pydantic import BaseModel, ConfigDict


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
    PASSAGE_AMBIGUOUS = "passage_ambiguous"
    """One pair of anchors selected two different values in one document. A table reports an
    ambiguous row for the same reason, in the vocabulary a table has."""
    NUMBER_AS_WORD = "number_as_word"
    """The locator selected an English cardinal written out. The value is there and is not a
    decimal, and converting it is a semantic decision the manifest has to ask for."""
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
