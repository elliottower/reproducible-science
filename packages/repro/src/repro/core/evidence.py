"""What a claim offers, and how a value is addressed inside an artifact.

One contract over several formats: a locator names a value, an evidence assertion names the
value a manuscript reports for it."""

from __future__ import annotations

import decimal
import enum
import json
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from repro.core.artifacts import Digest

SCHEMA_VERSION = "repro/1"

_SHA256_HEX = r"^[a-f0-9]{64}$"


# ---------------------------------------------------------------------------------- evidence


class _EvidenceBase(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    artifact: str
    """Id of the artifact this value is asserted to come from. The artifact carries the pin;
    evidence never repeats a digest, so there is one source of truth per file."""


# --------------------------------------------------------------------------------- locators

#: Scalar types a row predicate may hold. Deliberately not a string expression language: a
#: string predicate needs a parser, coercion rules, and an escaping grammar, and every
#: implementation would disagree about the edges.
PredicateValue = str | int | float | bool


class Locator(BaseModel):
    """Where a value sits in an artifact.

    One contract over several file formats, rather than one pointer syntax pretending every
    file is a tree. JSON Pointer works because JSON has a single tree data model and a
    pointer resolves to at most one value; it says nothing about table keys, multidimensional
    indices, or database rows. Each variant below addresses its format the way that format
    already addresses itself.

    The invariant every variant shares: a locator resolves to **exactly one scalar**. Zero is
    absent, two or more is ambiguous, and a container is not a value. No backend may quietly
    take the first match.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    contract: Literal[1] = 1
    """Version of the locator contract, carried so a stored decision says which rules it was
    resolved under."""

    def canonical(self) -> str:
        """Canonical JSON: sorted keys, no whitespace, no coercion.

        Hashed separately from the artifact, so a decision binds both what was read and how
        it was addressed. Changing a selector changes the digest even where the file does
        not.
        """
        return json.dumps(
            self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )

    @property
    def digest(self) -> Digest:
        return Digest.of_text(self.canonical())


class TreeLocator(Locator):
    """RFC 6901 JSON Pointer into JSON, or into YAML restricted to a JSON-compatible tree."""

    kind: Literal["tree"] = "tree"
    pointer: str


class TableLocator(Locator):
    """A column plus a predicate that must match exactly one row."""

    kind: Literal["table"] = "table"
    column: str
    where: dict[str, PredicateValue] = Field(default_factory=dict)
    delimiter: str = ""

    @model_validator(mode="after")
    def _predicate_must_select(self):
        if not self.where:
            raise ValueError(
                "a table locator needs a `where` predicate; to address by "
                "position use kind: table_position"
            )
        return self


class TablePositionLocator(Locator):
    """A column plus a row index. Weaker on purpose, and reported as such.

    Sorting, filtering or inserting a row changes what row 37 means, so a positional address
    has no semantic identity. The artifact pin still makes it reproducible, which is why this
    is a distinct locator carrying a warning rather than a refusal.
    """

    kind: Literal["table_position"] = "table_position"
    column: str
    row: int = Field(ge=0)
    delimiter: str = ""


class ArrayLocator(Locator):
    """A named array plus a multidimensional index, for `.npy` and `.npz`."""

    kind: Literal["array"] = "array"
    array: str | None = None
    """Required for `.npz`, which holds many arrays; omitted for `.npy`, which holds one."""
    index: tuple[int, ...]


class SqliteLocator(Locator):
    """A table, a column, and a predicate that must match exactly one row."""

    kind: Literal["sqlite"] = "sqlite"
    table: str
    column: str
    where: dict[str, PredicateValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _predicate_must_select(self):
        if not self.where:
            raise ValueError("a sqlite locator needs a `where` predicate")
        return self


ValueLocator = Annotated[
    TreeLocator | TableLocator | TablePositionLocator | ArrayLocator | SqliteLocator,
    Field(discriminator="kind"),
]


class QuoteEvidence(_EvidenceBase):
    """Assertion: this passage occurs in this artifact."""

    kind: Literal["quote"] = "quote"

    text: str
    section: str | None = None
    """Where the source puts it, as the source names it. Recorded, never verified."""

    page: int | None = None
    """Verified when present, for paginated sources."""


class ComparisonMode(enum.StrEnum):
    """How a reported number is compared with a stored one."""

    PRINTED_PRECISION = "printed_precision"
    """Compare at the precision the manuscript printed. `3.20` requires two decimals to
    agree; `3.2` requires one. This is why `reported` is a string."""

    ABSOLUTE = "absolute"
    """Agree when |stored - reported| <= tolerance."""

    RELATIVE = "relative"
    """Agree when |stored - reported| <= tolerance * |reported|."""


class MetricEvidence(_EvidenceBase):
    """Assertion: this artifact holds this value at this location."""

    kind: Literal["metric"] = "metric"

    name: str
    reported: str
    """The value exactly as the manuscript prints it, as a string.

    A string because YAML parses `3.20` to the float `3.2`, discarding the precision the
    manuscript chose, and because binary floats do not represent decimal fractions exactly.
    Parsed with `decimal.Decimal`."""

    pointer: str
    """RFC 6901 JSON Pointer: `/comparisons/primary/delta`.

    JSON Pointer rather than a dotted path because a dotted path cannot distinguish a mapping
    key containing a period from a nesting level, nor list index `0` from mapping key `"0"`,
    and specifying an escape grammar for a new selector language is work already done."""

    mode: ComparisonMode = ComparisonMode.PRINTED_PRECISION
    tolerance: str = "0"
    """As a decimal string, for the same reason as `reported`. Ignored for
    `printed_precision`."""

    @property
    def value(self) -> decimal.Decimal:
        return decimal.Decimal(self.reported)

    @property
    def tolerance_value(self) -> decimal.Decimal:
        return decimal.Decimal(self.tolerance)

    @property
    def locator(self) -> TreeLocator:
        """`metric` is sugar for a tree locator, and resolves through the same adapter."""
        return TreeLocator(pointer=self.pointer)


class TableCellEvidence(_EvidenceBase):
    """Assertion: this table holds this value in this cell.

    Most published result artifacts are delimited tables rather than JSON, so addressing a
    cell is what a manuscript's own tables usually need. A cell is named by its column and by
    one of two ways of picking the row.
    """

    kind: Literal["table"] = "table"

    name: str
    reported: str
    """The value exactly as the manuscript prints it, as a string. See `MetricEvidence`."""

    column: str
    """Header name of the column holding the value."""

    row: int | None = None
    """Zero-based index among data rows, excluding the header."""

    where: dict[str, str] = Field(default_factory=dict)
    """Select the row whose named columns hold these values: `{"model": "LASSO-Cox"}`.

    Preferred over `row`, because a row index silently addresses a different cell when a table
    is reordered or a row is inserted, and a table that has been reordered is exactly the case
    a checker exists to notice. A selector matching no rows, or more than one, is reported
    rather than resolved."""

    delimiter: str = ""
    """Override the delimiter. Empty means infer it from the file's suffix and contents."""

    mode: ComparisonMode = ComparisonMode.PRINTED_PRECISION
    tolerance: str = "0"

    @property
    def value(self) -> decimal.Decimal:
        return decimal.Decimal(self.reported)

    @property
    def tolerance_value(self) -> decimal.Decimal:
        return decimal.Decimal(self.tolerance)

    @property
    def addresses_one_row(self) -> bool:
        """Exactly one row selector must be given."""
        return (self.row is None) != (not self.where)

    @property
    def locator(self) -> TableLocator | TablePositionLocator:
        """`table` is sugar for one of the two table locators."""
        if self.row is not None:
            return TablePositionLocator(column=self.column, row=self.row, delimiter=self.delimiter)
        return TableLocator(column=self.column, where=dict(self.where), delimiter=self.delimiter)


class ValueEvidence(_EvidenceBase):
    """Assertion: this artifact holds this value at this locator.

    The general form. `metric` and `table` remain as shorthand for the two commonest cases,
    and every kind resolves through the same adapters, so a manifest never has to choose
    between a convenient spelling and a supported one.
    """

    kind: Literal["value"] = "value"

    name: str
    reported: str
    """The value exactly as the manuscript prints it, as a string. See `MetricEvidence`."""

    locator: ValueLocator
    """Which value, in the addressing its format already has. Kept separate from `reported`,
    `mode` and `tolerance`: a locator identifies a stored value and says nothing about what
    it should be."""

    mode: ComparisonMode = ComparisonMode.PRINTED_PRECISION
    tolerance: str = "0"

    @property
    def value(self) -> decimal.Decimal:
        return decimal.Decimal(self.reported)

    @property
    def tolerance_value(self) -> decimal.Decimal:
        return decimal.Decimal(self.tolerance)


Evidence = Annotated[
    QuoteEvidence | MetricEvidence | TableCellEvidence | ValueEvidence, Field(discriminator="kind")
]
"""Every kind of evidence, discriminated on `kind`.

`protocol` was a third variant and is not one. Its integrity check is the artifact pin, which
every artifact already carries, and its content check -- that a registered document states a
given hypothesis -- is a quotation against the plan. What remains distinct about a protocol is
temporal: whether a confirmatory run postdates its registration. That needs a run record, is
unimplemented, and is not smuggled in as a third evidence kind in the meantime.
"""
