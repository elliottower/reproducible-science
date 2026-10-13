"""What a claim offers, and how a value is addressed inside an artifact.

One contract over several formats: a locator names a value, an evidence assertion names the
value a manuscript reports for it."""

from __future__ import annotations

import decimal
import enum
import json
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_serializer,
    model_validator,
)

from repro.core.artifacts import Digest

SCHEMA_VERSION = "repro/1"

_SHA256_HEX = r"^[a-f0-9]{64}$"


# ---------------------------------------------------------------------------------- evidence


class _EvidenceBase(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    artifact: str
    """Id of the artifact this value is asserted to come from. The artifact carries the pin;
    evidence never repeats a digest, so there is one source of truth per file."""

    @property
    def artifacts(self) -> tuple[str, ...]:
        """Every artifact this assertion reads.

        One, for every kind but `correspondence`. The engine resolves pins over this rather
        than over `artifact`, so an assertion reading two files has both of them checked.
        """
        return (self.artifact,)


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
    """A column plus a predicate that must match exactly one row.

    Addresses delimited text, and the binary formats that hold one table and nothing else:
    Parquet, Feather and Arrow IPC, Stata `.dta`, SPSS `.sav`, and an R data frame saved as
    `.rds`. `delimiter` means something only to delimited text."""

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
    """A named array plus a multidimensional index, for `.npy`, `.npz`, HDF5 and NetCDF."""

    kind: Literal["array"] = "array"
    array: str | None = None
    """Required for `.npz`, which holds many arrays; omitted for `.npy`, which holds one. In an
    HDF5 or NetCDF file it is the dataset's or variable's path, `/results/accuracy`, and is
    required for the same reason."""
    index: tuple[int, ...]


class SheetLocator(Locator):
    """A sheet of a workbook, a column, and a predicate that must match exactly one row.

    A table locator with one more coordinate, because a workbook holds several tables and a
    column name is unique, at best, within one of them. The first row of the sheet is the
    header, as it is in delimited text.
    """

    kind: Literal["sheet"] = "sheet"
    sheet: str | None = None
    """Required where the workbook has more than one sheet. Omitted for a workbook with one,
    which is what most exported results are; a second sheet added later turns the omission
    into a broken selector rather than a silent read of whichever sheet comes first."""
    column: str
    where: dict[str, PredicateValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _predicate_must_select(self):
        if not self.where:
            raise ValueError("a sheet locator needs a `where` predicate")
        return self


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


class NumberForm(enum.StrEnum):
    """How the text a prose locator selects is read as a number."""

    DECIMAL = "decimal"
    """Digits, parsed with `decimal.Decimal`. The default: no conversion happens."""

    CARDINAL_WORD = "cardinal_word"
    """An English cardinal below one hundred, written out. `eighteen` is read as 18.

    Declared per assertion and never inferred. Reading a word as a number is a semantic
    decision, and the engine makes none on its own: under `decimal` a recognized cardinal is
    refused with its own reason rather than converted."""


class ProseLocator(Locator):
    """The value between two literal anchors in the extracted text of a document.

    Every other locator addresses a data model the format already has. Prose has none, so the
    address is the text on either side of the value: `before` is the literal that precedes it
    and `after` the literal that follows. That is a declared address rather than an inferred
    one -- the author says where the value sits, and no matcher searches the document for a
    number that looks like the right one.

    A capture-group pattern was the alternative and carries what §3.6 rejects elsewhere: a
    string expression language needs a dialect, an escaping grammar, and a backtracking bound,
    and every implementation would disagree about the edges. A braced template (`holds {n}
    fixtures`) needs an escaping grammar for the brace, which LaTeX sources are full of. Two
    literal anchors need neither.

    The value is a run of non-whitespace characters following `before`: the whole run up to
    the next whitespace where `after` begins past it or is empty, and otherwise the run cut at
    the first place inside it where `after` begins. A cell printed against its divider,
    `0.318|`, is addressed with `after: "|"`. A value containing a space is not addressable
    this way, which bounds `cardinal_word` to numbers written as one word.

    An anchor never splits a number: `after` may not begin, and `before` may not end, inside
    a run of digits joined by a decimal point, a grouping comma or underscore, or an exponent.
    `after: "8"` over `0.318` reads nothing, never `0.31`, and `before: "0.3"` never `18`.
    Digits attached to a preceding letter, `v0.5` or `H10`, are a name and not a number. A
    sign belongs to its number unless a digit or a letter precedes it, so `before: "x=-"`
    reads nothing from `x=-0.42` and `before: "10-"` reads `12` from `10-12`.
    """

    kind: Literal["prose"] = "prose"

    before: str = Field(min_length=1)
    """Literal text immediately preceding the value. Matched against the same normalized text
    a quotation resolves against, so an anchor and a quote cannot disagree about the
    document."""

    after: str = ""
    """Literal text immediately following the value, with or without whitespace between.
    Empty means the value runs to the next whitespace, so a character printed against the
    number -- a table divider, a full stop, a percent sign -- is part of what is read unless
    `after` names it."""

    form: NumberForm = NumberForm.DECIMAL


ValueLocator = Annotated[
    TreeLocator
    | TableLocator
    | TablePositionLocator
    | ArrayLocator
    | SheetLocator
    | SqliteLocator
    | ProseLocator,
    Field(discriminator="kind"),
]


Verbatim = Annotated[str, StringConstraints(strip_whitespace=False)]
"""A string kept exactly as written: `citations.models.Verbatim`, defined here to the same
effect. A quotation's `prefix` is the text immediately before the passage, so the space it
ends on is what separates its last word from the passage's first. `citations` is imported
only where a quotation is checked, so that an installation without it reports a backend that
could not run, and importing the type from it here would make every manifest need it to
load."""


class QuoteEvidence(_EvidenceBase):
    """Assertion: this passage occurs in this artifact."""

    kind: Literal["quote"] = "quote"

    text: str

    prefix: Verbatim = ""
    """Text immediately preceding the passage in the artifact, used only to say which
    occurrence is quoted where the passage occurs more than once.

    With `suffix`, the W3C Web Annotation `TextQuoteSelector`, as `citations` records it. A
    passage that occurs once needs neither and is checked without them. Handed to `citations`
    unchanged, so the two are matched as a `citations` record's are: joined to the passage
    and normalized as it is."""

    suffix: Verbatim = ""
    """Text immediately following the passage in the artifact. See `prefix`."""

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


class Conversion(enum.StrEnum):
    """A change of unit between the value a file stores and the value the manuscript prints.

    A closed set of names, each a power of ten. There is no multiplier and no expression: an
    assertion that could state its own arithmetic could make any stored value agree with any
    printed one, and nothing would check the arithmetic."""

    PERCENT = "percent"
    """The file stores a fraction and the manuscript prints a percentage: stored x 100."""

    FRACTION = "fraction"
    """The file stores a percentage and the manuscript prints a fraction: stored / 100."""

    def apply(self, stored: decimal.Decimal) -> decimal.Decimal:
        """The stored value in the unit the manuscript prints, exactly.

        The decimal point moves and no digit changes, so nothing is rounded and no context
        precision applies: 0.0424 as a percentage is 4.24, at any number of digits."""
        sign, digits, exponent = stored.as_tuple()
        if not isinstance(exponent, int):
            raise ValueError(f"{stored} is not finite, so it has no unit to convert")
        return decimal.Decimal((sign, digits, exponent + _PLACES[self]))

    @property
    def said(self) -> str:
        return _SAID[self]


#: How many places each conversion moves the decimal point to the right.
_PLACES = {Conversion.PERCENT: 2, Conversion.FRACTION: -2}

_SAID = {Conversion.PERCENT: "as a percentage", Conversion.FRACTION: "as a fraction"}


class _Convertible(BaseModel):
    """A value that may be declared to sit in another unit than the one it is compared in."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    conversion: Conversion | None = None
    """Applied to the stored value before the comparison. None, the default, compares the
    value as stored."""

    @model_serializer(mode="wrap")
    def _omit_no_conversion(self, handler):
        """Leave the field out where none is declared, so a manifest that declares no
        conversion serializes, and hashes, as it did before the field existed."""
        dumped = handler(self)
        if self.conversion is None:
            dumped.pop("conversion", None)
        return dumped


class MetricEvidence(_EvidenceBase, _Convertible):
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


class TableCellEvidence(_EvidenceBase, _Convertible):
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


class ValueEvidence(_EvidenceBase, _Convertible):
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


class CorrespondenceSide(_Convertible):
    """One of the two values a correspondence compares.

    A side may declare a `conversion`, for a document that prints a percentage of a fraction
    a file stores. The side is then compared as converted."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1)
    """What this side is, in the author's words -- `stated`, `measured`, `table`, `figure`.
    Carried into the decision so a report can say which side held what. The engine attaches
    no meaning to it and ranks neither side."""

    artifact: str
    locator: ValueLocator


class CorrespondenceEvidence(BaseModel):
    """Assertion: these two artifacts hold the same value.

    Every other kind compares an artifact against a literal written in the manifest. A
    documentation claim compares an artifact against an artifact -- a sentence saying the
    suite holds eighteen fixtures, against a count of the fixtures -- and expressing that with
    a literal requires transcribing one side into the manifest, where nothing checks the
    transcription.

    Neither side is privileged. When the two disagree the decision reports both values and
    does not say which is wrong, because nothing in a byte comparison establishes that. The
    same discipline governs the outcome vocabulary in §0.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["correspondence"] = "correspondence"

    name: str
    sides: tuple[CorrespondenceSide, CorrespondenceSide]

    mode: ComparisonMode = ComparisonMode.PRINTED_PRECISION
    """`relative` is rejected: its tolerance is a fraction of the reported value, and with no
    privileged side there is no value to take the fraction of."""

    tolerance: str = "0"

    @property
    def artifacts(self) -> tuple[str, ...]:
        return tuple(side.artifact for side in self.sides)

    @property
    def tolerance_value(self) -> decimal.Decimal:
        return decimal.Decimal(self.tolerance)

    @model_validator(mode="after")
    def _sides_are_distinct(self):
        left, right = self.sides
        if left.name == right.name:
            raise ValueError(
                f"correspondence {self.name!r}: both sides are named {left.name!r}, so a "
                f"report cannot say which held what"
            )
        if (left.artifact, left.locator.canonical()) == (right.artifact, right.locator.canonical()):
            raise ValueError(
                f"correspondence {self.name!r}: both sides address the same value in "
                f"{left.artifact!r}, which agrees with itself whatever it holds"
            )
        if self.mode is ComparisonMode.RELATIVE:
            raise ValueError(
                f"correspondence {self.name!r}: `relative` needs a value to take a fraction "
                f"of, and neither side is the reference; use `absolute` or `printed_precision`"
            )
        return self


Evidence = Annotated[
    QuoteEvidence | MetricEvidence | TableCellEvidence | ValueEvidence | CorrespondenceEvidence,
    Field(discriminator="kind"),
]
"""Every kind of evidence, discriminated on `kind`.

`protocol` was a third variant and is not one. Its integrity check is the artifact pin, which
every artifact already carries, and its content check -- that a registered document states a
given hypothesis -- is a quotation against the plan. What remains distinct about a protocol is
temporal: whether a confirmatory run postdates its registration. That needs a run record, is
unimplemented, and is not smuggled in as a third evidence kind in the meantime.
"""
