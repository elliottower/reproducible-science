"""What an inventory of the numbers a text prints found."""

from __future__ import annotations

import collections
import enum

from pydantic import BaseModel, ConfigDict

from claims.core.evidence import NumberForm

SCHEMA_VERSION = "repro/1"


class Standing(enum.StrEnum):
    """Where one printed number stands against the manifest. Each number has exactly one."""

    BOUND = "bound"
    """A declared assertion accounts for this occurrence: it lies in the passage of a `quote`
    whose claim reports its value from a file, or it is the value a prose address selects."""
    SET_ASIDE_WITH_A_REASON = "set_aside_with_a_reason"
    """It lies in a passage the manifest lists under `set_aside`, which carries the reason."""
    SET_ASIDE_BY_RULE = "set_aside_by_rule"
    """A named rule reads it as something other than a quantity: a year, a table's number."""
    UNBOUND = "unbound"
    """Printed, and nothing in the manifest accounts for it."""


class NumberRule(enum.StrEnum):
    """Why a run of digits is set aside without the author saying so. Applied in this order,
    and the first that holds is the one named."""

    LINK = "link"
    """Inside a URL."""
    DATE = "date"
    """One of the three parts of a date written `2026-10-13`, or of the two of a year and
    month written `2026-04` (a year from 1800 to 2099, a month from 01 to 12)."""
    DOCUMENT = "document_identifier"
    """The number a document is known by: what follows `rfc`, `iso`, `iec`, `ieee`, `ansi`,
    `ecma`, `fips`, `pep`, `arxiv`, `doi`, `isbn`, `issn`, `pmid` or `pmcid`, as in `rfc 6901`
    and `arxiv 2609.22111`, and the digits of a DOI."""
    NAME = "name"
    """Part of a name: a letter stands immediately before the digits, `v15zw` and `sha256sum`,
    or a hyphen or underscore joins them to a part that holds a letter, `gpt-4` and `9750` in
    `i7-9750h`, or the digits open a run of letters and digits that holds more digits later,
    as a hexadecimal digest does. An em or en dash is punctuation and joins nothing."""
    VERSION_OR_SECTION = "version_or_section"
    """Digits joined by two or more full stops, `0.5.5` and `3.2.1`."""
    CITATION = "citation"
    """Whole numbers from 1 up, alone in square brackets: `[12]`, `[3, 7]`, `[4-6]`."""
    LABEL = "label"
    """The number of a section, figure, table, equation, appendix, chapter, page, algorithm,
    listing, theorem, lemma, proposition, corollary, definition, footnote, step or line: it
    follows that word, and a range written `2-4` after the word is two labels."""
    LIST_MARKER = "list_marker"
    """A whole number of one or two digits alone in parentheses, `(1)`: an item of a list or
    the number of an equation."""
    ORDINAL = "ordinal"
    """Digits with `st`, `nd`, `rd` or `th` attached: `3rd`, `95th`."""
    YEAR = "year"
    """Four digits from 1800 to 2099 with no sign, separator, decimal point or percent sign."""
    THE_WORD_ONE = "the_word_one"
    """The word `one`, which is a pronoun more often than a count. Every other cardinal
    written as one word, `eighteen` and `thirty-five`, is counted as a number."""


class PrintedNumber(BaseModel):
    """One occurrence of a number in a text."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str
    """As printed, after the normalization a quotation is matched under: `2,364`, `-0.42`,
    `24.11%`, `eighteen`."""
    value: str | None = None
    """The decimal it is read as, without grouping commas or a percent sign. None for digits
    no value is read from: a name, a link, a document's identifier, a version."""
    form: NumberForm = NumberForm.DECIMAL
    """Whether it is printed in digits or as a word."""
    offset: int
    """Where it starts in the normalized text."""
    line: int | None = None
    """The line of the extracted text it is on, from 1. None where the lines could not be
    matched to the normalized text."""
    context: str = ""
    """The words on either side."""
    standing: Standing
    rule: NumberRule | None = None
    claims: tuple[str, ...] = ()
    """The claims whose assertions bind it."""
    reason: str = ""
    """The author's reason, where the manifest sets it aside."""
    reported_elsewhere: bool = False
    """Of an unbound number only: some assertion in the manifest reports this value, and
    none accounts for this occurrence. Marked where the value has two digits or more, or a
    decimal point."""
    reported_elsewhere_one_digit: bool = False
    """The same, for a value of one digit and no decimal point. Most manifests report some
    `4`, so the match says little: it is counted and not marked."""


class TextInventory(BaseModel):
    """Every number one text artifact prints, in the order printed."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    artifact: str
    path: str = ""
    numbers: tuple[PrintedNumber, ...] = ()


class SetAsideCount(BaseModel):
    """One `set_aside` entry of the manifest, and how many numbers it accounts for."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    artifact: str
    text: str
    reason: str
    numbers: int
    """0 where the passage is not in the text, or holds no number that is not bound."""


class NumbersReport(BaseModel):
    """What `repro numbers` found. Frozen, and carries no verdict."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = SCHEMA_VERSION
    project: str = ""
    manifest_digest: str = ""
    texts: tuple[TextInventory, ...] = ()
    set_aside: tuple[SetAsideCount, ...] = ()

    @property
    def numbers(self) -> tuple[PrintedNumber, ...]:
        return tuple(number for text in self.texts for number in text.numbers)

    @property
    def counts(self) -> collections.Counter[Standing]:
        return collections.Counter(number.standing for number in self.numbers)

    @property
    def rules(self) -> collections.Counter[NumberRule]:
        """How many numbers each rule set aside, in the order the rules are applied."""
        found = collections.Counter(number.rule for number in self.numbers if number.rule)
        return collections.Counter({rule: found[rule] for rule in NumberRule if found[rule]})
