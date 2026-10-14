"""The verification engine.

The engine reads no artifacts itself. It resolves each artifact's pin once, dispatches each
evidence assertion to the backend registered for its kind, and records what came back. What
it adds on top of the backends is the part that has to be uniform:

  * **Pins are checked before evidence.** A source that moved is known before any decision is
    computed against it, and those decisions are marked non-authoritative rather than being
    silently reported as if the declared file had been read.
  * **A backend that cannot run is not a claim that failed.** `BackendUnavailableError`
    becomes `execution=unavailable` with the backend's own reason attached.
  * **A defect is not a scientific outcome.** Any other exception becomes
    `execution=failed`, which flattens to `error` and never to `unchecked`. Letting a
    `TypeError` become an abstention is the same failure this package exists to prevent, one
    level up.
  * **Every decision names the toolchain that read the bytes**, and the digest of what that
    toolchain produced. See `claims.toolchain` for why the backend's protocol version is not
    that.
"""

from __future__ import annotations

import decimal
import fractions
import math
import pathlib
import statistics
from collections.abc import Mapping
from typing import Protocol

from claims.adapters.base import Occurrence
from claims.adapters.prose import GROUPED, placed
from claims.adapters.reads import once, reading_once
from claims.exceptions import (
    ArtifactUnreadableError,
    BackendUnavailableError,
    UnknownEvidenceKindError,
)
from claims.models import (
    AggregateEvidence,
    ArtifactRef,
    ArtifactState,
    Claim,
    ClaimAssessment,
    ComparisonMode,
    ComparisonStatus,
    Conversion,
    CorrespondenceEvidence,
    CorrespondenceSide,
    Decision,
    DecisionMember,
    DecisionSide,
    Digest,
    Evidence,
    ExecutionStatus,
    ExtractionStatus,
    Locator,
    Manifest,
    MetricEvidence,
    NumberForm,
    Ordering,
    OrderingReason,
    PairTie,
    ProseLocator,
    QuoteEvidence,
    Reason,
    RegistrationAuthority,
    Statistic,
    TableCellEvidence,
    Tie,
    Validity,
    ValueEvidence,
    VerificationReport,
    Warning_,
)
from claims.resolve import Resolution, resolve
from claims.toolchain import (
    DISTRIBUTION,
    UNKNOWN,
    adapter_version,
    binary_version,
    text_reader,
)

#: The distribution that ships `claims.adapters`, which is what reads a JSON pointer, a
#: delimited cell, a SQLite row or an array element. Its name on PyPI, because that is what
#: `importlib.metadata` answers to.
ADAPTER_DISTRIBUTION = DISTRIBUTION


class Backend(Protocol):
    """Evaluates one kind of evidence assertion against the artifacts it names.

    `paths` holds one entry per artifact the assertion reads, keyed by id. Every kind but
    `correspondence` reads one, and takes it with `paths[evidence.artifact]`. A mapping rather
    than a path because an assertion whose two sides are both artifacts has no single file to
    be handed, and giving it one would make the engine pick a side.
    """

    kind: str
    version: str
    """The protocol version of this interface, written by hand."""
    tool: str
    """What performs the extraction: a binary's name, or an installed distribution's."""

    @property
    def tool_version(self) -> str:
        """The version `tool` reports, or `toolchain.UNKNOWN`."""
        ...

    def check(
        self, claim: Claim, evidence: Evidence, paths: Mapping[str, pathlib.Path]
    ) -> Decision: ...


#: Weakest first. A decision over two artifacts is no more authoritative than the worse of
#: them, and taking the better one would report a comparison against a file that moved as
#: though the declared bytes had been read.
_VALIDITY_RANK = {
    Validity.ARTIFACT_ABSENT: 0,
    Validity.BROKEN_PIN: 1,
    Validity.UNPINNED_ARTIFACT: 2,
    Validity.AUTHORITATIVE: 3,
}


def _base(
    claim: Claim,
    evidence: Evidence,
    backend: Backend,
    extraction_digest: str = UNKNOWN,
    text: pathlib.Path | None = None,
) -> dict:
    """The fields every decision carries, whichever stage it stopped at.

    `extraction_digest` defaults to `unknown` rather than to an empty string: a decision the
    engine produced was one an extraction was sought for, and the empty value is reserved for
    a decision no backend produced.

    `text` is the file the assertion reads as text, where it reads one. A text that a library
    reads in this process, a `.docx`, names that library and its version as the tool in place
    of the backend's own.
    """
    named = evidence.artifacts
    reader = text_reader(text) if text is not None else None
    tool, tool_version = reader or (backend.tool, backend.tool_version)
    return {
        "claim_id": claim.id,
        "claim_digest": claim.digest.value,
        "kind": evidence.kind,
        # Left empty where an assertion reads two files or more: `artifact_id` is singular,
        # and filling it with one of them would name a side the engine does not rank. They are
        # recorded in `sides`, or in `members`.
        "artifact_id": named[0] if len(named) == 1 else "",
        "backend": backend.kind,
        "backend_version": backend.version,
        "tool": tool,
        "tool_version": tool_version,
        "extraction_digest": extraction_digest,
    }


def _text(evidence: Evidence, paths: Mapping[str, pathlib.Path]) -> pathlib.Path | None:
    """The file an assertion reads as text: a quotation's, or a prose address's. None for
    every other assertion, and for one whose file is not in `paths`."""
    if isinstance(evidence, QuoteEvidence) or (
        isinstance(evidence, ValueEvidence) and isinstance(evidence.locator, ProseLocator)
    ):
        return paths.get(evidence.artifact)
    return None


# -------------------------------------------------------------------------------- quotations

#: Every state `citations.verify` can return. It answers with five, and only two were mapped, so
#: a passage occurring twice in its source raised `KeyError: 'ambiguous'` from inside the backend
#: and was reported as a defect in the tool rather than as an undecided quotation.
_QUOTE_STATE = {
    "found": (ExtractionStatus.EXTRACTED, ComparisonStatus.MATCH, Reason.PASSAGE_PRESENT),
    "not found": (ExtractionStatus.EXTRACTED, ComparisonStatus.MISMATCH, Reason.PASSAGE_ABSENT),
    # The address matched more than once, which is where `row_ambiguous` sits for a table: the
    # extraction did not single out one thing to compare, so there is no comparison, and no first
    # match is taken. Not `passage_ambiguous`, which says the document states two different
    # numbers: a passage written twice contradicts nothing, and an author told it does goes
    # looking for a defect in the manuscript when the fix is a `prefix` or `suffix` on the quote
    # assertion. One that singles out no occurrence is this state too, and `citations` says so
    # in the detail: the record names text on either side and still has not said which it means.
    "ambiguous": (
        ExtractionStatus.INVALID,
        ComparisonStatus.NOT_APPLICABLE,
        Reason.QUOTATION_AMBIGUOUS,
    ),
    # Not `passage_ambiguous` either: that says the document states two numbers where one was
    # asserted. This says the extractors on this machine do not settle what text the document
    # holds, which accuses nothing and asks for a better reader.
    "indeterminate": (
        ExtractionStatus.INVALID,
        ComparisonStatus.NOT_APPLICABLE,
        Reason.EXTRACTORS_DISAGREE,
    ),
    # Not `passage_absent`. The stages were right and the reason was not, so an author whose
    # extractor never ran was told their quotation is missing from the source -- the "nothing ran"
    # against "not there" collapse this package exists to keep apart.
    "unchecked": (
        ExtractionStatus.NOT_ATTEMPTED,
        ComparisonStatus.NOT_APPLICABLE,
        Reason.EXTRACTOR_MISSING,
    ),
}

#: Every warning `citations.verify` can put on a result. `page unchecked` was not here, and a
#: warning with no entry is dropped, so the one warning that says a check was skipped was the
#: one `repro verify` never showed.
_QUOTE_WARNINGS = {
    "short": Warning_.SHORT,
    "truncated": Warning_.TRUNCATED,
    "normalized": Warning_.NORMALIZED,
    "page": Warning_.WRONG_PAGE,
    "page unchecked": Warning_.PAGE_UNCHECKED,
}


def _page_unchecked(page: int | None, state: str, warnings: list[str], paginated: bool) -> str:
    """Why a declared page was not checked on a passage that was found, or empty where it was.

    `citations` gives the warning `page unchecked` for each of these. Before 0.5.6 it gave it
    only where a source declares its own extractor, which a manifest cannot do, and the two
    cases a manifest reaches were silent: a source that is not read page by page had its page
    dropped before the passage was looked for, and a passage that matches only with spacing
    ignored was returned before the page was looked at. Both are still worked out here, so
    the answer is the same against an earlier `citations` of the series this package accepts.
    """
    if page is None or state != "found" or "page" in warnings:
        return ""
    if not paginated:
        return f"page {page} was not checked: the artifact is not read page by page"
    if "normalized" in warnings:
        return f"page {page} was not checked: the passage matched only with spacing ignored"
    if "page unchecked" in warnings:
        return f"page {page} was not checked: the extractor cannot be asked for one page"
    return ""


class QuoteBackend:
    """Assertion: this passage occurs in this artifact.

    A passage that is absent from a source that was read successfully is a `mismatch`: the
    artifact was extracted and does not contain what the assertion says it contains. That is
    a different fact from a source that could not be read, which is `unavailable`.
    """

    kind = "quote"
    version = "1"
    tool = "pdftotext"

    @property
    def tool_version(self) -> str:
        return binary_version(self.tool)

    def check(
        self, claim: Claim, evidence: Evidence, paths: Mapping[str, pathlib.Path]
    ) -> Decision:
        if not isinstance(evidence, QuoteEvidence):
            raise TypeError(f"QuoteBackend received {type(evidence).__name__}")
        try:
            # Imported here rather than at module scope so an absent `citations` reports as a
            # backend that could not run, which is what the caller can act on.
            from citations.exceptions import SourceUnreadableError
            from citations.verify import check_one, extract, is_paginated
        except ImportError as e:
            raise BackendUnavailableError("quote", f"citations is not installed: {e}") from e

        path = paths[evidence.artifact]
        result = check_one(
            evidence.text, path, evidence.page, prefix=evidence.prefix, suffix=evidence.suffix
        )
        # The page of a passage that was not found is not a second finding beside it.
        named = [w for w in result.warnings if w != "page unchecked" or result.state == "found"]
        # Asked only of a source that was read: `is_paginated` opens the file to tell text from
        # a format with pages.
        paginated = result.state == "found" and is_paginated(path)
        unchecked = _page_unchecked(evidence.page, result.state, named, paginated)
        if unchecked and "page unchecked" not in named:
            named.append("page unchecked")
        warnings = tuple(_QUOTE_WARNINGS[w] for w in named if w in _QUOTE_WARNINGS)

        if result.state == "unchecked":
            # The extractor could not produce text. Distinguishing this from an absent
            # passage is the reason the three stages are separate.
            raise BackendUnavailableError("quote", result.detail or "no text extracted")

        try:
            # `extract` memoizes per file, so this is the text `check_one` has just read
            # rather than a second run of `pdftotext`. It is the whole document: a digest over
            # the matched passage alone would be silent on an extractor that changed how it
            # reads every other page.
            extraction_digest = Digest.of_text(extract(path)).value
        except SourceUnreadableError:
            extraction_digest = UNKNOWN

        base = _base(claim, evidence, self, extraction_digest, text=path)
        extraction, comparison, reason = _QUOTE_STATE[result.state]
        if Warning_.WRONG_PAGE in warnings:
            # `page` is documented as verified when present, and the passage is not on the
            # page the manifest asserts. Reporting `match` with a warning made the assertion
            # unenforceable: no policy reads decision warnings, so it graded as verified.
            comparison, reason = ComparisonStatus.MISMATCH, Reason.WRONG_PAGE
        return Decision(
            **base,
            execution=ExecutionStatus.COMPLETED,
            extraction=extraction,
            comparison=comparison,
            reason=reason,
            detail=result.detail or unchecked,
            warnings=warnings,
        )


# ------------------------------------------------------------------------------- values

#: How a resolution maps onto the extraction stage and a reason. `format_unsupported` is not
#: here: a format with no adapter means the check never ran, which is an execution fact.
_RESOLUTION_STATE = {
    Resolution.ABSENT: (ExtractionStatus.ABSENT, None),
    Resolution.COLUMN_ABSENT: (ExtractionStatus.ABSENT, Reason.COLUMN_ABSENT),
    Resolution.AMBIGUOUS: (ExtractionStatus.INVALID, Reason.ROW_AMBIGUOUS),
    Resolution.NOT_SCALAR: (ExtractionStatus.INVALID, Reason.SELECTOR_NOT_SCALAR),
    Resolution.SELECTOR_INVALID: (ExtractionStatus.INVALID, Reason.ROW_SELECTOR_INVALID),
    Resolution.NUMBER_AS_WORD: (ExtractionStatus.INVALID, Reason.NUMBER_AS_WORD),
    Resolution.PASSAGE_AMBIGUOUS: (ExtractionStatus.INVALID, Reason.PASSAGE_AMBIGUOUS),
}

#: Which "not there" reason fits each addressing scheme.
_ABSENT_REASON = {
    "tree": Reason.POINTER_ABSENT,
    "table": Reason.ROW_ABSENT,
    "table_position": Reason.ROW_ABSENT,
    "sqlite": Reason.ROW_ABSENT,
    "array": Reason.POINTER_ABSENT,
    "sheet": Reason.ROW_ABSENT,
    "prose": Reason.PASSAGE_ABSENT,
}


def compare_decimal(
    stored: decimal.Decimal, evidence: MetricEvidence | TableCellEvidence | ValueEvidence
) -> bool:
    """Does the stored value agree with the reported one, under the declared conversion and
    mode?"""
    return agrees(
        stored, evidence.value, evidence.conversion, evidence.mode, evidence.tolerance_value
    )


def agrees(
    stored: decimal.Decimal,
    reported: decimal.Decimal,
    conversion: Conversion | None = None,
    mode: ComparisonMode = ComparisonMode.PRINTED_PRECISION,
    tolerance: decimal.Decimal = decimal.Decimal(0),
) -> bool:
    """Does a stored value agree with a printed one: converted first, then compared under
    `mode`. The comparison every numeric assertion makes, with no evidence attached, so a
    caller holding two numbers and no assertion compares them as the engine does."""
    return _agree(_compared(stored, conversion), reported, mode, tolerance)


def _compared(stored: decimal.Decimal, conversion: Conversion | None) -> decimal.Decimal:
    """The stored value in the unit it is compared in.

    Converted first and rounded after: a file holding 0.0426 printed as a percentage is 4.26,
    which is 4.3 at one decimal, where rounding the fraction to 0.04 first would print 4. A
    non-finite value has no unit and is returned as it is, for `_agree` to refuse.
    """
    return conversion.apply(stored) if conversion is not None and stored.is_finite() else stored


def _held(
    stored: decimal.Decimal | str, compared: decimal.Decimal, conversion: Conversion | None
) -> str:
    """A stored value as a detail shows it: with what it is under a declared conversion."""
    if conversion is None:
        return f"{stored}"
    return f"{stored} ({_plain(compared)} {conversion.said})"


def _places(count: int) -> str:
    """A number of decimal places, in words a detail can use. A value printed to the tens
    has fewer than none, which is said as it is."""
    return f"{count} decimal place{'' if count == 1 else 's'}"


def _misplaced(
    evidence: MetricEvidence | TableCellEvidence | ValueEvidence | AggregateEvidence,
) -> str | None:
    """What to say where `places` is declared and `reported` is written to another number of
    them, or None. Two statements about the manuscript disagree, and no rounding of the
    file's value settles which is meant: `4.20` is not a number reported to one place."""
    printed_places = -_exponent(evidence.value)
    if evidence.places is None or printed_places == evidence.places:
        return None
    return (
        f"{evidence.name}: manuscript prints {evidence.reported}, which is "
        f"{_places(printed_places)}, and {_places(evidence.places)} is declared"
    )


def _grouping(locator: Locator, raw: str) -> str:
    """What to add where a prose locator read digits grouped by commas without being asked to.

    The outcome is `value_not_numeric` either way; this only says what would read it."""
    if (
        isinstance(locator, ProseLocator)
        and locator.form is NumberForm.DECIMAL
        and GROUPED.fullmatch(raw)
    ):
        return (
            f"; the commas group its digits, so declare `form: grouped` on the locator to "
            f"read it as {raw.replace(',', '')}"
        )
    return ""


def _digest(path: pathlib.Path) -> str:
    """The sha256 of a file, computed once per file in a verification.

    The pins are hashed through this, so a comparison of two files later in the same
    verification reads the digests the pins were checked against and hashes nothing again."""
    return once(("digest", path.resolve()), lambda: Digest.of_file(path).value)


def same_file(left: pathlib.Path, right: pathlib.Path) -> str | None:
    """`path` where two declared paths resolve to one file, `bytes` where two files hold the
    same bytes, and None otherwise.

    Two artifact ids may name one file, or two copies of it, and a value read through each is
    then one value read twice. Sizes are compared before any digest is looked up."""
    try:
        if left.resolve() == right.resolve():
            return "path"
        if left.stat().st_size != right.stat().st_size:
            return None
        return "bytes" if _digest(left) == _digest(right) else None
    except OSError:
        return None


def _line(occurrence: Occurrence) -> str:
    """Where an occurrence is, as a report names it: its line, or the words around it."""
    if occurrence.line is not None:
        return f"line {occurrence.line}"
    return f'"{occurrence.context}"'


def _one_place(readings: list, paths: Mapping[str, pathlib.Path]) -> str | None:
    """What to say where two sides read a value at one place in one file, or None.

    Two locators that differ only in `form`, or in anchors one of which contains the other,
    can select the same printed value, and so can one locator under two artifact ids naming
    one file. The value is then compared with itself and agrees whatever the document prints,
    and the place the manifest meant for one of the sides is never read. The static check on
    canonical locators cannot see this, so it is made on what the sides selected, in the file
    each side resolved to.

    Where one side's anchors also match places the other does not read, the pair is still
    refused: dropping the shared place to force a comparison would compare what the manifest
    did not address. The detail says which place is shared and which are not, so the author
    can narrow the anchors that match more than one."""
    read = [
        (side, extracted)
        for side, _, extracted, _ in readings
        if extracted is not None and extracted.occurrences
    ]
    for at, (left, mine) in enumerate(read):
        for right, theirs in read[at + 1 :]:
            one = left.artifact == right.artifact
            alias = None if one else same_file(paths[left.artifact], paths[right.artifact])
            if not one and alias is None:
                continue
            shared = [
                (here, there)
                for here in mine.occurrences
                for there in theirs.occurrences
                if here.start < there.end and there.start < here.end
            ]
            if not shared:
                continue
            where = (
                left.artifact
                if one
                else f"{left.artifact} and {right.artifact}, which are one file"
                if alias == "path"
                else f"{left.artifact} and {right.artifact}, which hold the same bytes"
            )
            here, there = shared[0]
            said = f"sides {left.name} and {right.name} read the same place in {where}"
            extra = {
                left.name: [o for o in mine.occurrences if all(o is not h for h, _ in shared)],
                right.name: [o for o in theirs.occurrences if all(o is not t for _, t in shared)],
            }
            broad = [name for name, others in extra.items() if others]
            if not broad:
                return (
                    f"{said}, {placed(here)}, so the value would be compared with itself; "
                    f"give each side anchors that select a place of its own"
                )
            also = "; ".join(
                f"{name} also matches {', '.join(_line(o) for o in extra[name])}" for name in broad
            )
            if len(broad) == 2:
                return (
                    f"{said}: both match {_line(here)}; {also}. Narrow the anchors of "
                    f"{left.name} and {right.name} so each selects only the place it is meant for"
                )
            wide = broad[0]
            narrow, (theirs_at, mine_at) = (
                (right.name, (there, here)) if wide == left.name else (left.name, (here, there))
            )
            return (
                f"{said}: {narrow} reads {_line(theirs_at)}, which {wide}'s anchors also match "
                f"at {_line(mine_at)}; {also}. Narrow {wide}'s anchors so they select only the "
                f"place {wide} is meant for"
            )
    return None


def _as_printed(side: CorrespondenceSide, printed: str, raw: str) -> str | decimal.Decimal:
    """A side's value as a detail shows it: as printed under `grouped`, and otherwise as the
    decimal it was read as, which is how it was always shown."""
    if isinstance(side.locator, ProseLocator) and side.locator.form is NumberForm.GROUPED:
        return printed
    return decimal.Decimal(raw)


def _unit(raw: str, conversion: Conversion | None) -> tuple[decimal.Decimal, Conversion | None]:
    """A value under its side's conversion, and the conversion, as `_held` takes them."""
    return _compared(decimal.Decimal(raw), conversion), conversion


def _plain(converted: decimal.Decimal) -> str:
    """A converted value with no exponent: 0.5 as a percentage is written 50, where `str`
    writes the same decimal as 5E+1."""
    return format(converted, "f")


def _exponent(value: decimal.Decimal) -> int:
    """The power of ten a finite decimal's last digit sits at.

    `Decimal.as_tuple().exponent` is `int | Literal["n", "N", "F"]`: the strings tag NaN and
    the infinities, which have no precision for a comparison to be coarser or finer than.
    Every backend refuses a non-finite value with `value_not_numeric` before comparing, so
    reaching this with one is a defect in a backend rather than a fact about an artifact, and
    §5 says a defect is an `error` and never a scientific outcome. Raising is how it becomes
    one. Returning a number instead would compare two values at a precision nothing chose.
    """
    exponent = value.as_tuple().exponent
    if not isinstance(exponent, int):
        raise ValueError(
            f"{value} has no exponent: a non-finite value is refused before any comparison, "
            f"so reaching the comparison with one is a defect"
        )
    return exponent


def _tie(
    compared: decimal.Decimal | fractions.Fraction, reported: decimal.Decimal
) -> tuple[decimal.Decimal, decimal.Decimal] | None:
    """The two values at the precision `reported` prints that `compared` lies exactly halfway
    between, lower first, or None where it is nearer one of them.

    Decided in exact rationals, for a stored decimal and for a statistic that may be no
    decimal at all: the value in units of the printed precision is a whole number and a half,
    or it is not. No float is formed and nothing is within a tolerance of a tie, so 4.25 is
    one at one place and 4.2500001 is not.
    """
    if isinstance(compared, decimal.Decimal) and not compared.is_finite():
        return None
    quantum = _exponent(reported)
    units = fractions.Fraction(compared) / fractions.Fraction(10) ** quantum
    if units.denominator != 2:
        return None
    below = math.floor(units)

    def at_precision(count: int) -> decimal.Decimal:
        # Zero carries no sign: the neighbor above -0.5 is 0.
        return decimal.Decimal((int(count < 0), tuple(map(int, str(abs(count)))), quantum))

    return at_precision(below), at_precision(below + 1)


def _tied(
    compared: decimal.Decimal | fractions.Fraction,
    printed: decimal.Decimal,
    mode: ComparisonMode,
) -> Tie | None:
    """The record of a tie, where the comparison is at a printed precision and met one."""
    if mode is not ComparisonMode.PRINTED_PRECISION:
        return None
    neighbors = _tie(compared, printed)
    if neighbors is None:
        return None
    lower, upper = neighbors
    return Tie(lower=_plain(lower), upper=_plain(upper), printed=_plain(printed))


def _agree(
    stored: decimal.Decimal,
    reported: decimal.Decimal,
    mode: ComparisonMode,
    tolerance: decimal.Decimal,
) -> bool:
    """Do two decimals agree under one mode? The arithmetic, with no evidence attached.

    Split out because a correspondence has two extracted values and no `reported` field to
    read a mode off, and duplicating the `printed_precision` rounding rule is how two
    spellings of the same comparison come to disagree.
    """
    if not stored.is_finite():
        # NaN and the infinities parse out of JSON but cannot equal a printed decimal. The
        # backend flags them before reaching here; this keeps the function total.
        return False
    if mode is ComparisonMode.PRINTED_PRECISION:
        # Round the stored value to the precision the manuscript printed. A paper reporting
        # 3.2 is not contradicted by a file holding 3.20001; a paper reporting 3.20000 is.
        # `quantize` raises whenever the *result* needs more digits than the context carries,
        # which is not only the case where the two values differ wildly: two identical
        # thirty-digit integers also exceed the default precision of 28, and were reported as
        # a mismatch. That is a defect in the arithmetic emitted as a contradicted manuscript,
        # which is the one thing this package must never do. Size the context to the operands.
        #
        # A value exactly halfway between two printed values is rounded up by half the
        # software a manuscript's numbers come out of and to the even neighbor by the other
        # half, so either neighbor agrees. Everywhere else the rounding is half-even, and
        # which rule is used makes no difference away from a tie.
        if (neighbors := _tie(stored, reported)) is not None:
            return reported in neighbors
        with decimal.localcontext() as context:
            context.prec = max(
                context.prec,
                len(stored.as_tuple().digits) + abs(int(reported.as_tuple().exponent)) + 2,
            )
            try:
                return stored.quantize(reported, rounding=decimal.ROUND_HALF_EVEN) == reported
            except decimal.InvalidOperation:
                # Genuinely beyond reach: the two differ by more orders of magnitude than any
                # precision reconciles. They disagree, and saying so is the answer.
                return False
    delta = abs(stored - reported)
    if mode is ComparisonMode.ABSOLUTE:
        return delta <= tolerance
    return delta <= tolerance * abs(reported)


def _agree_exact(
    computed: fractions.Fraction,
    reported: decimal.Decimal,
    mode: ComparisonMode,
    tolerance: decimal.Decimal,
) -> bool:
    """`_agree` for a value that may have no finite decimal expansion.

    A mean of three values is a third of their sum, and dividing in decimals rounds it once
    at whatever precision the context carries before `printed_precision` rounds it again. A
    rational is exact, so the one rounding is the rule's own: half-even to the precision
    `reported` prints, with either neighbor agreeing at an exact tie. On a value that is a
    decimal the two functions agree.
    """
    printed = fractions.Fraction(reported)
    if mode is ComparisonMode.PRINTED_PRECISION:
        # The tie rule a single value is held to, by the function that holds it.
        if (neighbors := _tie(computed, reported)) is not None:
            return reported in neighbors
        quantum = fractions.Fraction(10) ** _exponent(reported)
        # `round` of a rational is exact and takes a tie to the even neighbor.
        return round(computed / quantum) * quantum == printed
    delta = abs(computed - printed)
    if mode is ComparisonMode.ABSOLUTE:
        return delta <= fractions.Fraction(tolerance)
    return delta <= fractions.Fraction(tolerance) * abs(printed)


def _aggregate(statistic: Statistic, values: list[fractions.Fraction]) -> fractions.Fraction:
    """One statistic of at least one value, exactly."""
    if statistic is Statistic.MEAN:
        return sum(values, fractions.Fraction(0)) / len(values)
    if statistic is Statistic.MEDIAN:
        # The middle value, or half the sum of the two middle ones, which a rational holds.
        return statistics.median(values)
    if statistic is Statistic.MIN:
        return min(values)
    if statistic is Statistic.MAX:
        return max(values)
    if statistic is Statistic.SUM:
        return sum(values, fractions.Fraction(0))
    return fractions.Fraction(len(values))


#: How many places past the printed precision a statistic with no finite expansion is shown to.
SHOWN_PLACES = 3


def _shown(computed: fractions.Fraction, reported: decimal.Decimal) -> str:
    """A statistic as a report shows it: exactly where it is a terminating decimal, and
    otherwise rounded half-even to `SHOWN_PLACES` past the precision the manuscript prints."""
    places = 0
    scaled = computed
    while scaled.denominator % 2 == 0 or scaled.denominator % 5 == 0:
        scaled *= 10
        places += 1
    if scaled.denominator != 1:
        places = max(0, -_exponent(reported)) + SHOWN_PLACES
        scaled = fractions.Fraction(round(computed * 10**places))
    sign, digits, _ = decimal.Decimal(scaled.numerator).as_tuple()
    return format(decimal.Decimal((sign, digits, -places)), "f")


class ValueBackend:
    """Assertion: this artifact holds this value at this locator.

    One implementation for every numeric kind. `metric` and `table` are shorthands that
    expose a locator, so the addressing rules and the invariant -- exactly one scalar -- do
    not depend on which spelling a manifest used.
    """

    kind = "value"
    version = "2"
    tool = ADAPTER_DISTRIBUTION

    @property
    def tool_version(self) -> str:
        return adapter_version()

    def check(
        self, claim: Claim, evidence: Evidence, paths: Mapping[str, pathlib.Path]
    ) -> Decision:
        if not isinstance(evidence, (MetricEvidence, TableCellEvidence, ValueEvidence)):
            raise TypeError(f"{type(self).__name__} received {type(evidence).__name__}")
        path = paths[evidence.artifact]
        base = _base(claim, evidence, self, text=_text(evidence, paths))
        base["conversion"] = evidence.conversion
        completed = {"execution": ExecutionStatus.COMPLETED}
        no_compare = {"comparison": ComparisonStatus.NOT_APPLICABLE}

        if isinstance(evidence, TableCellEvidence) and not evidence.addresses_one_row:
            # Both or neither given. A manifest that does not say which row it means is
            # malformed rather than a table that disagrees.
            return Decision(
                **base,
                **completed,
                **no_compare,
                extraction=ExtractionStatus.INVALID,
                reason=Reason.ROW_SELECTOR_INVALID,
                detail="give exactly one of `row` or `where`",
            )

        locator = evidence.locator
        base["locator_digest"] = locator.digest.value
        warnings = (Warning_.POSITIONAL_ADDRESS,) if locator.kind == "table_position" else ()

        resolution, extracted, detail = resolve(locator, path)

        if resolution is Resolution.FORMAT_UNSUPPORTED:
            # The check did not run. Reporting it as a missing value would say something
            # about the artifact that was never looked into.
            return Decision(
                **base,
                execution=ExecutionStatus.UNAVAILABLE,
                extraction=ExtractionStatus.NOT_ATTEMPTED,
                **no_compare,
                reason=Reason.FORMAT_UNSUPPORTED,
                detail=detail,
                warnings=warnings,
            )

        if resolution is not Resolution.RESOLVED or extracted is None:
            extraction, reason = _RESOLUTION_STATE[resolution]
            return Decision(
                **base,
                **completed,
                **no_compare,
                extraction=extraction,
                reason=reason or _ABSENT_REASON[locator.kind],
                detail=detail,
                warnings=warnings,
            )

        # The adapter produced a value, so there is an extraction to hash. Recorded before the
        # comparison, and for a value that turns out not to be numeric: what the extractor
        # read is a fact about the extractor whatever the comparison then makes of it.
        base["extraction_digest"] = Digest.of_text(extracted.raw).value
        base["extracted"] = extracted.raw

        try:
            stored = decimal.Decimal(extracted.raw)
        except (decimal.InvalidOperation, ValueError):
            return Decision(
                **base,
                **completed,
                **no_compare,
                extraction=ExtractionStatus.INVALID,
                reason=Reason.VALUE_NOT_NUMERIC,
                detail=f"{' '.join(extracted.trace)} holds {extracted.raw!r}"
                + _grouping(locator, extracted.raw),
                warnings=warnings,
            )
        if not stored.is_finite():
            # `json.loads` accepts NaN, Infinity and -Infinity by default, so a result file
            # can carry one. It is not a quantity a printed value can agree with.
            return Decision(
                **base,
                **completed,
                **no_compare,
                extraction=ExtractionStatus.INVALID,
                reason=Reason.VALUE_NOT_NUMERIC,
                detail=f"{' '.join(extracted.trace)} holds {stored}",
                warnings=warnings,
            )

        compared = _compared(stored, evidence.conversion)
        if evidence.conversion is not None:
            base["converted"] = _plain(compared)
        held = _held(stored, compared, evidence.conversion)
        where = " ".join(extracted.trace) or locator.kind

        if (misplaced := _misplaced(evidence)) is not None:
            return Decision(
                **base,
                **completed,
                extraction=ExtractionStatus.EXTRACTED,
                comparison=ComparisonStatus.MISMATCH,
                reason=Reason.PLACES_MISMATCH,
                detail=misplaced,
                warnings=warnings,
            )

        agrees = compare_decimal(stored, evidence)
        tie = _tied(compared, evidence.value, evidence.mode)
        base["tie"] = tie
        between = f", an exact tie between {tie.lower} and {tie.upper}" if tie else ""
        return Decision(
            **base,
            **completed,
            extraction=ExtractionStatus.EXTRACTED,
            comparison=ComparisonStatus.MATCH if agrees else ComparisonStatus.MISMATCH,
            reason=Reason.VALUE_MATCH if agrees else Reason.VALUE_MISMATCH,
            detail=(
                f"{where} = {held}{between}"
                + (f"; the manuscript prints {evidence.reported}" if tie else "")
                if agrees
                else f"{evidence.name}: manuscript prints {evidence.reported}, "
                f"{path.name} holds {held} at {where}{between}"
            ),
            warnings=warnings,
        )


class MetricBackend(ValueBackend):
    """`kind: metric` -- a JSON Pointer into a structured file."""

    kind = "metric"


class TableBackend(ValueBackend):
    """`kind: table` -- a column plus a row selector in a delimited file."""

    kind = "table"


# --------------------------------------------------------------------------- correspondences


class CorrespondenceBackend:
    """Assertion: two artifacts, or several places, hold the same value.

    An extraction per side precedes one comparison, and the stages report that faithfully. A side that
    does not extract makes the comparison impossible rather than false: a document that never
    states the number does not contradict the file holding it, and reporting that as a
    disagreement would manufacture a finding out of a gap. The decision carries the failing
    side's own reason, so `pointer_absent` and `number_as_word` stay distinguishable.

    When both sides extract and disagree, the decision reports both values and names neither
    as wrong. Which of a specification and a test suite is in error is not something a byte
    comparison establishes.
    """

    kind = "correspondence"
    version = "1"
    #: The format adapters are this distribution, as they are for `ValueBackend`. The
    #: declaration is an approximation for one case: a `prose` side over a paginated source
    #: reaches `citations.verify.extract`, which runs the same `pdftotext` that `QuoteBackend`
    #: declares, and `Decision.tool` is one field where such an assertion has two extractors.
    #: `DecisionSide.extraction_digest` is what catches a change in either of them, since it
    #: moves whenever what a side read moves, whatever did the reading. Naming the tool per
    #: side needs the adapters to report which one they used, which this revision does not
    #: define.
    tool = ADAPTER_DISTRIBUTION

    @property
    def tool_version(self) -> str:
        return adapter_version()

    def check(
        self, claim: Claim, evidence: Evidence, paths: Mapping[str, pathlib.Path]
    ) -> Decision:
        if not isinstance(evidence, CorrespondenceEvidence):
            raise TypeError(f"CorrespondenceBackend received {type(evidence).__name__}")
        base = _base(claim, evidence, self)
        no_compare = {"comparison": ComparisonStatus.NOT_APPLICABLE}

        readings = [(side, *resolve(side.locator, paths[side.artifact])) for side in evidence.sides]
        base["sides"] = tuple(
            DecisionSide(
                name=side.name,
                artifact_id=side.artifact,
                locator_digest=side.locator.digest.value,
                extracted=extracted.raw if extracted is not None else None,
                conversion=side.conversion,
                # Hashed per side before any comparison, and for a value that turns out not
                # to be numeric: what an extractor read is a fact about the extractor whatever
                # the comparison then makes of it.
                extraction_digest=(
                    Digest.of_text(extracted.raw).value if extracted is not None else UNKNOWN
                ),
            )
            for side, _, extracted, _ in readings
        )
        # The decision-level field covers both extractions, in the order the manifest declares
        # the sides, so it moves whenever either side's extraction moves. Which of the two
        # moved is on the sides; leaving this `unknown` would say the extraction was sought
        # and not obtained, and it was sought twice.
        base["extraction_digest"] = Digest.of_text(
            "\x00".join(s.extraction_digest for s in base["sides"])
        ).value

        unsupported = [(s, d) for s, r, _, d in readings if r is Resolution.FORMAT_UNSUPPORTED]
        if unsupported:
            side, detail = unsupported[0]
            return Decision(
                **base,
                execution=ExecutionStatus.UNAVAILABLE,
                extraction=ExtractionStatus.NOT_ATTEMPTED,
                **no_compare,
                reason=Reason.FORMAT_UNSUPPORTED,
                detail=f"{side.name}: {detail}",
            )

        completed = {"execution": ExecutionStatus.COMPLETED}
        unresolved = [
            (s, r, d) for s, r, e, d in readings if r is not Resolution.RESOLVED or e is None
        ]
        if unresolved:
            # Reported in the order the manifest declares the sides, which is a fact about the
            # manifest and not a ranking. Every failing side appears in the detail.
            side, resolution, _ = unresolved[0]
            extraction, reason = _RESOLUTION_STATE[resolution]
            return Decision(
                **base,
                **completed,
                **no_compare,
                extraction=extraction,
                reason=reason or _ABSENT_REASON[side.locator.kind],
                detail="; ".join(f"{s.name} ({s.artifact}): {d}" for s, _, d in unresolved),
            )

        if (shared := _one_place(readings, paths)) is not None:
            return Decision(
                **base,
                **completed,
                **no_compare,
                extraction=ExtractionStatus.EXTRACTED,
                reason=Reason.SIDES_READ_ONE_PLACE,
                detail=shared,
            )

        numbers: list[decimal.Decimal] = []
        for side, _, extracted, _ in readings:
            raw = extracted.raw if extracted is not None else ""
            try:
                number = decimal.Decimal(raw)
            except (decimal.InvalidOperation, ValueError):
                number = decimal.Decimal("NaN")
            if not number.is_finite():
                return Decision(
                    **base,
                    **completed,
                    **no_compare,
                    extraction=ExtractionStatus.INVALID,
                    reason=Reason.VALUE_NOT_NUMERIC,
                    detail=f"{side.name} ({side.artifact}) holds {raw!r}"
                    + _grouping(side.locator, raw),
                )
            numbers.append(number)

        # Each side in the unit it declares, and the comparison is over those: a document
        # printing 4.2 beside a file holding 0.0424 as a percentage compares 4.2 with 4.24.
        stored = numbers
        numbers = [
            _compared(n, side.conversion) for n, side in zip(stored, evidence.sides, strict=True)
        ]
        base["sides"] = tuple(
            recorded.model_copy(update={"converted": _plain(number)})
            if recorded.conversion is not None
            else recorded
            for recorded, number in zip(base["sides"], numbers, strict=True)
        )

        # One place per side, or one per spelling where a side's anchors select one number
        # printed to several precisions: `8.3` in an abstract and `8.30` in a table are one
        # number and two precisions, and each is compared at its own.
        places: list[tuple[CorrespondenceSide, str, str, decimal.Decimal]] = []
        for side, _, extracted, _ in readings:
            occurrences = extracted.occurrences if extracted is not None else ()
            spelled = list({o.printed: o for o in reversed(occurrences)}.values())[::-1]
            if len(spelled) > 1:
                places += [
                    (
                        side,
                        f"{side.name} at line {o.line}"
                        if o.line is not None
                        else f"{side.name} printing {o.printed}",
                        _held(_as_printed(side, o.printed, o.raw), *_unit(o.raw, side.conversion)),
                        _compared(decimal.Decimal(o.raw), side.conversion),
                    )
                    for o in spelled
                ]
                continue
            raw = extracted.raw if extracted is not None else ""
            printed = occurrences[0].printed if occurrences else raw
            places.append(
                (
                    side,
                    side.name,
                    _held(_as_printed(side, printed, raw), *_unit(raw, side.conversion)),
                    _compared(decimal.Decimal(raw), side.conversion),
                )
            )

        # Every pair of places on different sides, each compared as two sides are.
        # `printed_precision` compares a pair at the coarser of its two precisions, so a
        # document printing 0.65 agrees with a file holding 0.6478 and the answer does not
        # depend on which side the manifest wrote first. A larger exponent is the coarser value.
        # Pairs and not one reference: an abstract printing 8.3 and a section printing 8.4 each
        # agree with a stored 8.35, and disagree with each other. A declared tolerance applies
        # to every pair, place against place as well as place against file.
        disagree: list[tuple[str, str]] = []
        ties: list[PairTie] = []
        for at, (left, named, _, a) in enumerate(places):
            for right, other, _, b in places[at + 1 :]:
                if right is left:
                    continue
                coarse, fine = (a, b) if _exponent(a) >= _exponent(b) else (b, a)
                if not _agree(fine, coarse, evidence.mode, evidence.tolerance_value):
                    disagree.append((named, other))
                if (tie := _tied(fine, coarse, evidence.mode)) is not None:
                    ties.append(PairTie(sides=(named, other), tie=tie))
        agrees = not disagree
        # `tie` is the first, as it was the only one when a correspondence had two sides.
        base["tie"] = ties[0].tie if ties else None
        if len(places) == 2:
            (_, left, a, _), (_, right, b, _) = places
            between = (
                f", an exact tie between {ties[0].tie.lower} and {ties[0].tie.upper}"
                if ties
                else ""
            )
            detail = f"{evidence.name}: {left} {a}, {right} {b}{between}"
        else:
            base["ties"] = tuple(ties)
            base["disagreements"] = tuple(disagree)
            # Each place with its artifact, since several sides may be places in one document,
            # then each pair that met a tie, and each pair that disagrees, so the report says
            # which places to reconcile.
            detail = f"{evidence.name}: " + ", ".join(
                f"{named} ({side.artifact}) {value}" for side, named, value, _ in places
            )
            detail += "".join(
                f"; {paired.sides[0]} and {paired.sides[1]} an exact tie between "
                f"{paired.tie.lower} and {paired.tie.upper}"
                for paired in ties
            )
            detail += "".join(f"; {left} and {right} disagree" for left, right in disagree)
        return Decision(
            **base,
            **completed,
            extraction=ExtractionStatus.EXTRACTED,
            comparison=ComparisonStatus.MATCH if agrees else ComparisonStatus.MISMATCH,
            reason=Reason.VALUE_MATCH if agrees else Reason.VALUE_MISMATCH,
            detail=detail,
            warnings=(
                (Warning_.POSITIONAL_ADDRESS,)
                if any(side.locator.kind == "table_position" for side in evidence.sides)
                else ()
            ),
        )


# -------------------------------------------------------------------------------- aggregates


class AggregateBackend:
    """Assertion: the printed value is a statistic of the values its members hold.

    As many extractions as there are members precede one comparison. A member that does not
    extract makes the comparison impossible rather than false, as one side of a correspondence
    does: a statistic over the members that did resolve is a statistic over a set the manifest
    did not declare. The decision carries the first failing member's own reason and its detail
    names every member that failed, by its position in the list and its artifact.

    The statistic is computed over rationals, so a mean is the exact quotient and is rounded
    once, by the comparison.
    """

    kind = "aggregate"
    version = "1"
    #: As for `CorrespondenceBackend`: one field where the members may be read by more than
    #: one program, and `DecisionMember.extraction_digest` is what moves when any of them does.
    tool = ADAPTER_DISTRIBUTION

    @property
    def tool_version(self) -> str:
        return adapter_version()

    def check(
        self, claim: Claim, evidence: Evidence, paths: Mapping[str, pathlib.Path]
    ) -> Decision:
        if not isinstance(evidence, AggregateEvidence):
            raise TypeError(f"AggregateBackend received {type(evidence).__name__}")
        base = _base(claim, evidence, self)
        base["statistic"] = evidence.statistic
        base["conversion"] = evidence.conversion
        no_compare = {"comparison": ComparisonStatus.NOT_APPLICABLE}

        def named(position: int, artifact: str) -> str:
            return f"member {position} of {evidence.count} ({artifact})"

        readings = []
        for position, member in enumerate(evidence.members, start=1):
            try:
                found = resolve(member.locator, paths[member.artifact])
            except ArtifactUnreadableError as e:
                # Still a file that could not be parsed, and the engine reports it as one.
                # Raised again so that it says which of the members the file is.
                raise ArtifactUnreadableError(
                    e.path, f"{named(position, member.artifact)}: {e.detail}"
                ) from e
            readings.append((position, member, *found))
        base["members"] = tuple(
            DecisionMember(
                artifact_id=member.artifact,
                locator_digest=member.locator.digest.value,
                extracted=extracted.raw if extracted is not None else None,
                extraction_digest=(
                    Digest.of_text(extracted.raw).value if extracted is not None else UNKNOWN
                ),
            )
            for _, member, _, extracted, _ in readings
        )
        # Over every member's extraction, in the order the manifest lists them, so it moves
        # whenever any member's extraction moves. Which one moved is on the member.
        base["extraction_digest"] = Digest.of_text(
            "\x00".join(m.extraction_digest for m in base["members"])
        ).value
        warnings = (
            (Warning_.POSITIONAL_ADDRESS,)
            if any(member.locator.kind == "table_position" for member in evidence.members)
            else ()
        )

        unsupported = [
            (p, m, d) for p, m, r, _, d in readings if r is Resolution.FORMAT_UNSUPPORTED
        ]
        if unsupported:
            return Decision(
                **base,
                execution=ExecutionStatus.UNAVAILABLE,
                extraction=ExtractionStatus.NOT_ATTEMPTED,
                **no_compare,
                reason=Reason.FORMAT_UNSUPPORTED,
                detail="; ".join(f"{named(p, m.artifact)}: {d}" for p, m, d in unsupported),
                warnings=warnings,
            )

        completed = {"execution": ExecutionStatus.COMPLETED}
        unresolved = [
            (p, m, r, d) for p, m, r, e, d in readings if r is not Resolution.RESOLVED or e is None
        ]
        if unresolved:
            _, member, resolution, _ = unresolved[0]
            extraction, reason = _RESOLUTION_STATE[resolution]
            return Decision(
                **base,
                **completed,
                **no_compare,
                extraction=extraction,
                reason=reason or _ABSENT_REASON[member.locator.kind],
                detail="; ".join(f"{named(p, m.artifact)}: {d}" for p, m, _, d in unresolved),
                warnings=warnings,
            )

        # Each member in the unit the assertion declares, and the statistic is over those.
        converted: list[decimal.Decimal] = []
        not_numeric = []
        for position, member, _, extracted, _ in readings:
            raw = extracted.raw if extracted is not None else ""
            try:
                number = decimal.Decimal(raw)
            except (decimal.InvalidOperation, ValueError):
                number = decimal.Decimal("NaN")
            if number.is_finite():
                converted.append(_compared(number, evidence.conversion))
            else:
                not_numeric.append(
                    f"{named(position, member.artifact)} holds {raw!r}"
                    + _grouping(member.locator, raw)
                )
        if not_numeric:
            return Decision(
                **base,
                **completed,
                **no_compare,
                extraction=ExtractionStatus.INVALID,
                reason=Reason.VALUE_NOT_NUMERIC,
                detail="; ".join(not_numeric),
                warnings=warnings,
            )
        values = [fractions.Fraction(number) for number in converted]

        if evidence.conversion is not None:
            base["members"] = tuple(
                recorded.model_copy(update={"converted": _plain(number)})
                for recorded, number in zip(base["members"], converted, strict=True)
            )

        if (misplaced := _misplaced(evidence)) is not None:
            return Decision(
                **base,
                **completed,
                extraction=ExtractionStatus.EXTRACTED,
                comparison=ComparisonStatus.MISMATCH,
                reason=Reason.PLACES_MISMATCH,
                detail=misplaced,
                warnings=warnings,
            )

        computed = _aggregate(evidence.statistic, values)
        agrees = _agree_exact(computed, evidence.value, evidence.mode, evidence.tolerance_value)
        shown = _shown(computed, evidence.value)
        base["computed"] = shown
        tie = _tied(computed, evidence.value, evidence.mode)
        base["tie"] = tie
        between = f", an exact tie between {tie.lower} and {tie.upper}" if tie else ""
        unit = f" {evidence.conversion.said}" if evidence.conversion is not None else ""
        over = f"{evidence.statistic.value} of {evidence.count}{unit}"
        return Decision(
            **base,
            **completed,
            extraction=ExtractionStatus.EXTRACTED,
            comparison=ComparisonStatus.MATCH if agrees else ComparisonStatus.MISMATCH,
            reason=Reason.VALUE_MATCH if agrees else Reason.VALUE_MISMATCH,
            detail=(
                f"{evidence.name}: {over} = {shown}{between}"
                + (f"; the manuscript prints {evidence.reported}" if tie else "")
                if agrees
                else f"{evidence.name}: manuscript prints {evidence.reported}, "
                f"{over} is {shown}{between}"
            ),
            warnings=warnings,
        )


DEFAULT_BACKENDS: tuple[Backend, ...] = (
    QuoteBackend(),
    MetricBackend(),
    TableBackend(),
    ValueBackend(),
    CorrespondenceBackend(),
    AggregateBackend(),
)


# ------------------------------------------------------------------------------------ engine


def _artifact_state(artifact: ArtifactRef, path: pathlib.Path) -> ArtifactState:
    if not path.exists():
        # Not authoritative, whether or not it was pinned: there are no bytes to be the
        # declared ones. Calling it authoritative made every decision against it claim to
        # describe a file that was never read.
        return ArtifactState(
            artifact_id=artifact.id,
            validity=Validity.ARTIFACT_ABSENT,
            exists=False,
            expected=artifact.digest.value if artifact.digest else None,
        )
    # A path that exists but cannot be hashed -- a directory, a mode-000 file, a dangling
    # symlink -- is a fact about that artifact. Raising suppressed the report for every other
    # claim in the manifest because of one bad path.
    try:
        actual = _digest(path)
    except OSError as e:
        return ArtifactState(
            artifact_id=artifact.id,
            validity=Validity.ARTIFACT_ABSENT,
            expected=artifact.digest.value if artifact.digest else None,
            exists=False,
            detail=f"cannot be read: {e.strerror or e}",
        )
    if not artifact.is_pinned or artifact.digest is None:
        return ArtifactState(
            artifact_id=artifact.id,
            validity=Validity.UNPINNED_ARTIFACT,
            actual=actual,
        )
    if actual != artifact.digest.value:
        return ArtifactState(
            artifact_id=artifact.id,
            validity=Validity.BROKEN_PIN,
            expected=artifact.digest.value,
            actual=actual,
        )
    return ArtifactState(
        artifact_id=artifact.id,
        validity=Validity.AUTHORITATIVE,
        expected=artifact.digest.value,
        actual=actual,
    )


def _ordering(
    claim: Claim, manifest: Manifest, states: dict[str, ArtifactState]
) -> tuple[Ordering, OrderingReason, str, RegistrationAuthority | None]:
    """Did the runs producing this claim's evidence start after its plan was registered?

    Returns an outcome, the reason it was reached, a human-readable detail, and the weakest
    registration authority among the runs that applied. Every condition that stops the check
    yields `unchecked` with its own reason rather than a verdict: an absent record is not
    evidence that a result predates its plan, and reporting it as one would manufacture a
    finding out of a gap.
    """
    if not claim.confirmatory:
        return Ordering.NOT_APPLICABLE, OrderingReason.NOT_CONFIRMATORY, "", None

    produced = {a for e in claim.evidence for a in e.artifacts}
    runs = [r for r in manifest.runs if produced & {o.artifact for o in r.outputs}]
    covered = {o.artifact for r in runs for o in r.outputs}
    uncovered = sorted(produced - covered)
    if uncovered:
        # A claim can cite several artifacts. Taking the runs that produce *any* of them meant
        # adding a run record for one incidental artifact turned an unregistered result into
        # an ordered one, while the artifact carrying the number had no run at all.
        return (
            Ordering.UNCHECKED,
            OrderingReason.NO_RUN_RECORD,
            f"no run record produces {', '.join(uncovered)}",
            None,
        )

    if not runs:
        # A confirmatory claim offering no evidence names no artifacts, so no run produces any
        # and `uncovered` above is empty too. `min()` then raised on an empty iterable and the
        # traceback replaced the finding: the publication policy grades this manifest
        # `claim.no_evidence`, which is the thing the author needs to be told.
        return (
            Ordering.UNCHECKED,
            OrderingReason.NO_EVIDENCE_OFFERED,
            "the claim offers no evidence, so there is nothing to order against a plan",
            None,
        )

    authority = min((r.registration_authority for r in runs), key=lambda a: a.rank)

    def unchecked(reason: OrderingReason, detail: str):
        return Ordering.UNCHECKED, reason, detail, authority

    # More than one run claiming the same artifact with different registrations does not say
    # which one produced the bytes being checked.
    for artifact_id in sorted(produced):
        claimants = [r for r in runs if r.output(artifact_id) is not None]
        if len({(r.registered_plan, r.registered_at) for r in claimants}) > 1:
            return unchecked(
                OrderingReason.AMBIGUOUS_PRODUCING_RUN,
                f"{len(claimants)} runs claim to produce {artifact_id}",
            )

    without_plan = sorted({r.id for r in runs if not r.registered_plan})
    if without_plan:
        return unchecked(
            OrderingReason.NO_REGISTERED_PLAN,
            f"run {', '.join(without_plan)} names no registered plan",
        )

    undated = sorted({r.id for r in runs if r.registered_at is None or r.started_at is None})
    if undated:
        return unchecked(
            OrderingReason.TIMESTAMP_MISSING,
            f"run {', '.join(undated)} records no registration or start time",
        )

    # The plan document, where it is a declared artifact, must be the one that was pinned.
    for run in runs:
        state = states.get(run.registered_plan)
        if state is None:
            # Undeclared, so nothing pins it: the document backing an `ordered` verdict could
            # have been written after the results. Declaring the plan and leaving it unpinned
            # reported `unchecked`, so the more transparent manifest scored strictly worse.
            return unchecked(
                OrderingReason.REGISTERED_PLAN_UNPINNED,
                f"plan {run.registered_plan} is not a declared artifact, so nothing pins the "
                f"document the ordering rests on",
            )
        if state.validity is Validity.BROKEN_PIN:
            return unchecked(
                OrderingReason.REGISTERED_PLAN_CHANGED,
                f"plan {run.registered_plan} is not the document that was "
                f"pinned, so its timestamp attests to nothing",
            )
        if state.validity is not Validity.AUTHORITATIVE:
            return unchecked(
                OrderingReason.REGISTERED_PLAN_UNPINNED,
                f"plan {run.registered_plan} is declared but {state.validity.value}",
            )

    # Each output must be bound to the bytes actually read, not merely to a path.
    for run in runs:
        for artifact_id in sorted(produced & {o.artifact for o in run.outputs}):
            output = run.output(artifact_id)
            if output is None or output.digest is None:
                return unchecked(
                    OrderingReason.RUN_OUTPUT_UNLINKED,
                    f"run {run.id} names {artifact_id} but records no digest "
                    f"for it, so any later file at that path would qualify",
                )
            actual = states[artifact_id].actual if artifact_id in states else None
            if actual is not None and actual != output.digest.value:
                return unchecked(
                    OrderingReason.RUN_OUTPUT_CHANGED,
                    f"{artifact_id} holds {actual[:12]}, but run {run.id} "
                    f"produced {output.digest.value[:12]}",
                )

    # Every run is dated by this point -- the guard above returned otherwise -- but binding
    # the timestamps is what makes that legible, to a reader and to a type checker.
    dated = [
        (r, r.registered_at, r.started_at)
        for r in runs
        if r.registered_at is not None and r.started_at is not None
    ]
    inverted = [
        (r, registered, started) for r, registered, started in dated if started < registered
    ]
    if inverted:
        run, registered_at, started_at = inverted[0]
        return (
            Ordering.VIOLATED,
            OrderingReason.RUN_PRECEDES_REGISTRATION,
            f"run {run.id} started {started_at.isoformat()}, before "
            f"{run.registered_plan} was registered {registered_at.isoformat()}",
            authority,
        )

    pinned = sum(1 for r in runs if r.registered_plan in states)
    detail = (
        f"{len(runs)} run(s) started after registration"
        + (f", {pinned} against a pinned plan" if pinned else "")
        + f"; authority {authority.value}"
    )
    return Ordering.ORDERED, OrderingReason.RUN_FOLLOWS_REGISTRATION, detail, authority


def artifact_states(
    manifest: Manifest,
) -> tuple[dict[str, ArtifactState], dict[str, pathlib.Path]]:
    """Each declared artifact's pin, resolved once, and the path it was read from."""
    states: dict[str, ArtifactState] = {}
    paths: dict[str, pathlib.Path] = {}
    for artifact in manifest.artifacts:
        path = manifest.resolve(artifact)
        paths[artifact.id] = path
        states[artifact.id] = _artifact_state(artifact, path)
    return _aliased(states, paths), paths


def _aliased(
    states: dict[str, ArtifactState], paths: dict[str, pathlib.Path]
) -> dict[str, ArtifactState]:
    """Each state with the other ids that name its file or hold its bytes.

    Two ids for one file make any assertion comparing them compare the file with itself, so
    the report says so before any evidence is read. The digest is the one just computed for
    the pin, so nothing is read twice."""
    resolved = {artifact_id: path.resolve() for artifact_id, path in paths.items()}
    found = {}
    for artifact_id, state in states.items():
        same_path = tuple(
            other
            for other in states
            if other != artifact_id and resolved[other] == resolved[artifact_id]
        )
        same_digest = tuple(
            other
            for other, theirs in states.items()
            if other != artifact_id
            and other not in same_path
            and state.actual is not None
            and theirs.actual == state.actual
        )
        found[artifact_id] = (
            state.model_copy(update={"same_path_as": same_path, "same_digest_as": same_digest})
            if same_path or same_digest
            else state
        )
    return found


def verify(
    manifest: Manifest, backends: tuple[Backend, ...] = DEFAULT_BACKENDS
) -> VerificationReport:
    """Check every evidence assertion in a manifest and report what was found.

    Returns facts. No verdict: see `claims.policy` for whether a given set of facts is
    acceptable, which depends on what the project is for.

    Executes nothing. A manifest may declare commands that regenerate its artifacts; running
    them is `repro.reproduce`, which has to be asked for by name.
    """
    registry: dict[str, Backend] = {b.kind: b for b in backends}
    assessments = []
    # Each artifact is hashed once and parsed once for the whole manifest: the pins are
    # resolved inside the same scope, so a comparison of two files reads their pin digests.
    with reading_once():
        states, paths = artifact_states(manifest)
        for claim in manifest.claims:
            decisions = tuple(
                check_evidence(claim, evidence, manifest, paths, states, registry)
                for evidence in claim.evidence
            )
            ordering, ordering_reason, ordering_detail, authority = _ordering(
                claim, manifest, states
            )
            assessments.append(
                ClaimAssessment(
                    claim_id=claim.id,
                    claim_digest=claim.digest.value,
                    confirmatory=claim.confirmatory,
                    registration=claim.registration,
                    registration_note=claim.registration_note,
                    availability=claim.availability,
                    ordering=ordering,
                    ordering_reason=ordering_reason,
                    ordering_detail=ordering_detail,
                    registration_authority=authority,
                    decisions=decisions,
                )
            )

    return VerificationReport(
        project=manifest.project,
        manifest_digest=Digest.of_text(manifest.model_dump_json()).value,
        artifacts=tuple(states.values()),
        claims=tuple(assessments),
    )


def check_evidence(
    claim: Claim,
    evidence: Evidence,
    manifest: Manifest,
    paths: dict[str, pathlib.Path],
    states: dict[str, ArtifactState],
    registry: dict[str, Backend],
) -> Decision:
    """Evaluate one assertion against the files in `paths`.

    `paths` is a parameter and not read off the manifest so that a re-run can ask the same
    question of the file it has just written: `repro.reproduce` passes the path of the fresh
    output in place of the pinned one, and every rule below applies unchanged.
    """
    backend = registry.get(evidence.kind)
    if backend is None:
        raise UnknownEvidenceKindError(evidence.kind, tuple(registry))

    base = _base(claim, evidence, backend, text=_text(evidence, paths))
    unchecked = {
        "execution": ExecutionStatus.UNAVAILABLE,
        "extraction": ExtractionStatus.NOT_ATTEMPTED,
        "comparison": ComparisonStatus.NOT_APPLICABLE,
    }

    # Every artifact the assertion names, not only the first. An assertion reading two files
    # is unchecked if either is undeclared or absent, and no more authoritative than the worse
    # of the two pins.
    named = evidence.artifacts
    undeclared = [a for a in named if manifest.artifact(a) is None]
    if undeclared:
        return Decision(
            **base,
            **unchecked,
            reason=Reason.ARTIFACT_UNDECLARED,
            detail=f"manifest declares no artifact {', '.join(repr(a) for a in undeclared)}",
        )
    missing = [a for a in named if not states[a].exists]
    if missing:
        return Decision(
            **base,
            **unchecked,
            reason=Reason.ARTIFACT_MISSING,
            detail="; ".join(f"{paths[a]} does not exist" for a in missing),
            validity=min((states[a].validity for a in missing), key=_VALIDITY_RANK.__getitem__),
        )

    try:
        decision = backend.check(claim, evidence, {a: paths[a] for a in named})
    except BackendUnavailableError as e:
        decision = Decision(**base, **unchecked, reason=Reason.EXTRACTOR_MISSING, detail=e.detail)
    except ArtifactUnreadableError as e:
        decision = Decision(**base, **unchecked, reason=Reason.ARTIFACT_UNREADABLE, detail=e.detail)
    except Exception as e:
        # A defect in a backend is a defect, not an abstention. Recording it as `unchecked`
        # would make a TypeError indistinguishable from a missing extractor, which is the
        # confusion this package exists to prevent.
        decision = Decision(
            **base,
            execution=ExecutionStatus.FAILED,
            extraction=ExtractionStatus.NOT_ATTEMPTED,
            comparison=ComparisonStatus.NOT_APPLICABLE,
            reason=Reason.BACKEND_DEFECT,
            detail=f"{type(e).__name__}: {e}",
        )

    validity = min((states[a].validity for a in named), key=_VALIDITY_RANK.__getitem__)
    return decision.model_copy(
        update={
            "validity": validity,
            "artifact_digest": states[named[0]].actual if len(named) == 1 else None,
            # The backend knows which locator addressed which side; only the engine knows what
            # was at each path. Filling the digests here keeps both in one record.
            "sides": tuple(
                side.model_copy(
                    update={
                        "artifact_digest": states[side.artifact_id].actual,
                        "validity": states[side.artifact_id].validity,
                    }
                )
                for side in decision.sides
            ),
            "members": tuple(
                member.model_copy(
                    update={
                        "artifact_digest": states[member.artifact_id].actual,
                        "validity": states[member.artifact_id].validity,
                    }
                )
                for member in decision.members
            ),
        }
    )
