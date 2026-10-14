"""Every number a manuscript prints, and whether a declared assertion accounts for it.

`repro verify` reports on the claims a manifest declares, and the author chose which to
declare: forty verified of forty says nothing of the numbers no claim was written for. This
reads the manuscript's text and counts every number in it, so the denominator is the text's.
Executes nothing and writes nothing.

**Which text.** An artifact a claim reads its own sentence from: one a `quote` reads in a claim
that also offers an assertion of another kind, or one a prose address reads. A `quote` standing
alone in its claim is a quotation from a source, and that source is not inventoried.

**What a number is.** The text is the one a quotation resolves against, `passage_fold` over
what `citations` extracts, and a number is what `claims.adapters.prose.numerals` reads in it:
digits with an optional sign, grouping commas, a decimal point and an exponent. `2,364` is one
number and `12,13` is two; `10-12` is two; a percent sign is kept with its number and is not
part of its value. A cardinal written as one word is a number with the value the prose
adapter reads from it. Nothing is dropped: digits that are not a quantity are counted under
the rule that says what they are, `claims.models.NumberRule`.

**Bound.** One occurrence is bound where it lies inside a place the passage of a `quote`
occurs and an assertion of the same claim carries a `reported` value that is this number,
digit for digit at the printed precision, or where it lies in the value a prose address
selects. A `reported` value is what the manuscript prints, so one declared with a `conversion`
binds the printed number and not the stored one, and an `aggregate` also binds its `count`. The same digits reported by some other claim bind nothing: that occurrence is
unbound and marked `reported_elsewhere`, where the value has two digits or a decimal point; a
single digit matching some reported value is counted apart and not marked.
"""

from __future__ import annotations

import bisect
import decimal
import re
from collections.abc import Iterator
from typing import NamedTuple

from citations.exceptions import SourceUnreadableError
from citations.verify import extract_uncached, passage_fold

from claims.adapters.prose import CARDINALS, located, numerals
from claims.exceptions import ArtifactMissingError, ArtifactUnreadableError, ReproError
from claims.models import (
    AggregateEvidence,
    ArtifactRef,
    Claim,
    CorrespondenceEvidence,
    Digest,
    Manifest,
    NumberForm,
    NumberRule,
    NumbersReport,
    PrintedNumber,
    ProseLocator,
    QuoteEvidence,
    SetAsideCount,
    Standing,
    TextInventory,
    ValueEvidence,
)

#: Words shown on either side of a number.
CONTEXT_WORDS = 4

#: `2,364` and `1,234,567.5`: commas that group digits in threes. Any other comma between
#: digits separates two numbers.
_GROUPED = re.compile(r"[+-]?\d{1,3}(?:,\d{3})+(?:\.\d+)?(?:e[+-]?\d+)?")
_WORD = re.compile(r"[a-z]+(?:-[a-z]+)*")
_YEAR = re.compile(r"(?:18|19|20)\d\d")
_DATE = re.compile(r"(?<![\d-])\d{4}-\d{2}-\d{2}(?![\d-])")
_DOI = re.compile(r"(?<![\d.])10\.\d{4,9}/")
#: A standard, a preprint or a book named by its series and number: `rfc 6901`, `iso 8601`.
_DOCUMENT = re.compile(
    r"(?<![a-z])(?:rfc|iso(?:/iec)?|iec|ieee|ansi|ecma|fips|pep|arxiv|doi|isbn|issn|pmid|pmcid)"
    r"(?:: ?|[ -])?(\d+(?:[.:/-]\d+)*)"
)
#: An em or en dash set against the digit after it. `passage_fold` writes both as a hyphen, so
#: the text is folded a second time with these replaced by a character it leaves alone, to
#: tell the dash that ends a clause from the hyphen that joins a name.
_DASH_BEFORE_DIGIT = re.compile("[\u2014\u2013](?=\\d)")
_BAR = "\u2015"
_CITATION = re.compile(r"\[[1-9]\d*(?:\s?[,;-]\s?[1-9]\d*)*\]")
_LIST_MARKER = re.compile(r"\(\d{1,2}\)")
_LABEL = re.compile(
    r"(?<![a-z])(?:sections?|sec\.|§|figures?|figs?\.?|tables?|tab\.|equations?|eqs?\.?|eqn\.?"
    r"|appendix|appendices|chapters?|pages?|pp?\.|algorithms?|listings?|theorems?|lemmas?"
    r"|propositions?|corollary|corollaries|definitions?|footnotes?|steps?|lines?)"
    r" ?\(?(\d+(?:\.\d+)*(?:-\d+(?:\.\d+)*)?)"
)
#: Letters and then a digit, immediately after a number: the digits open a longer name.
_MORE_DIGITS = re.compile(r"[a-z]+\d")
_ORDINAL = re.compile(r"(?:st|nd|rd|th)(?![a-z0-9])")

Span = tuple[int, int]


class UnknownArtifactError(ReproError):
    """A text was named that the manifest does not declare."""

    def __init__(self, unknown: tuple[str, ...], declared: tuple[str, ...]) -> None:
        self.unknown = unknown
        self.declared = declared
        super().__init__(
            f"the manifest declares no artifact {', '.join(repr(u) for u in unknown)}; "
            f"declared: {', '.join(declared) or 'none'}"
        )


class NoTextError(ReproError):
    """No artifact in the manifest is read as the manuscript's text, and none was named."""

    def __init__(self) -> None:
        super().__init__(
            "no claim reads its sentence from a text: no `quote` stands beside another "
            "assertion and no value has a prose address. Name the text with --text <artifact-id>."
        )


class _Token(NamedTuple):
    start: int
    end: int
    value: str | None
    named: bool = False


def _prose(claim: Claim) -> Iterator[tuple[str, ProseLocator]]:
    """Each prose address a claim reads a value at, with the artifact it is in."""
    for evidence in claim.evidence:
        if isinstance(evidence, ValueEvidence) and isinstance(evidence.locator, ProseLocator):
            yield evidence.artifact, evidence.locator
        elif isinstance(evidence, CorrespondenceEvidence):
            for side in evidence.sides:
                if isinstance(side.locator, ProseLocator):
                    yield side.artifact, side.locator


def _quotes(claim: Claim) -> tuple[QuoteEvidence, ...]:
    """The quotations a claim reads its own sentence with: none where it offers nothing else."""
    quotes = tuple(e for e in claim.evidence if isinstance(e, QuoteEvidence))
    return quotes if len(quotes) < len(claim.evidence) else ()


def texts(manifest: Manifest) -> tuple[str, ...]:
    """The artifacts a claim reads its own sentence from, in the order declared."""
    read = {
        artifact
        for claim in manifest.claims
        for artifact in (
            *(quote.artifact for quote in _quotes(claim)),
            *(artifact for artifact, _ in _prose(claim)),
        )
    }
    return tuple(artifact.id for artifact in manifest.artifacts if artifact.id in read)


def _read(value: str | None) -> decimal.DecimalTuple | None:
    """A printed value as its sign, digits and exponent, so `0.5` and `0.50` differ."""
    try:
        return decimal.Decimal(value).as_tuple() if value is not None else None
    except decimal.InvalidOperation:
        return None


def telling(value: decimal.DecimalTuple | None) -> bool:
    """Whether a value has two digits or more, or a decimal point. One digit with no decimal
    point matches some value in most files, so a match on it says nothing."""
    return value is not None and (len(value.digits) > 1 or value.exponent != 0)


def _line_starts(raw: str, folded: str) -> list[int] | None:
    """Where each line of the extracted text starts in the normalized text.

    `passage_fold` joins the lines with one space, and joins a word a hyphen splits across a
    line break with nothing. This walks the lines under that rule, and returns None where what it
    walked is not the normalized text, so no line number is ever a guess.
    """
    pieces = [passage_fold(line) for line in raw.split("\n")]
    starts, at = [], 0
    for number, piece in enumerate(pieces):
        starts.append(at)
        if not piece:
            continue
        after = next((later for later in pieces[number + 1 :] if later), "")
        # A word split across the break: a letter before the hyphen and one opening the next
        # line that holds anything.
        broken = piece.endswith("-") and piece[-2:-1].isalpha() and after[:1].isalpha()
        if broken:
            piece = piece[:-1]
        if not folded.startswith(piece.rstrip(), at):
            return None
        at += len(piece) + (0 if broken else 1)
    return starts


def _dashes(raw: str, folded: str) -> frozenset[int]:
    """Where the normalized text holds a hyphen that was an em or en dash before a digit."""
    marked = passage_fold(_DASH_BEFORE_DIGIT.sub(_BAR, raw))
    if len(marked) != len(folded):
        return frozenset()
    return frozenset(
        found.start() for found in re.finditer(_BAR, marked) if folded[found.start()] == "-"
    )


def _tokens(folded: str, dashes: frozenset[int]) -> list[_Token]:
    """Every number in the text, in order: digits as the prose adapter reads them, and each
    cardinal written as one word. A dash before the digits is punctuation and not a sign: an
    em or en dash, or the last of a run of hyphens."""
    found = []
    for first, end, named in numerals(folded):
        if folded[first] == "-" and (first in dashes or folded[first - 1 : first] == "-"):
            first += 1
        whole = folded[first:end]
        if named:
            found.append(_Token(first, end, None, True))
        elif "," not in whole or _GROUPED.fullmatch(whole):
            found.append(_Token(first, end, whole.replace(",", "")))
        else:
            at = first
            for piece in whole.split(","):
                found.append(_Token(at, at + len(piece), piece))
                at += len(piece) + 1
    for word in _WORD.finditer(folded):
        before, after = folded[word.start() - 1 : word.start()], folded[word.end() : word.end() + 1]
        if word.group() in CARDINALS and not before.isalnum() and not after.isalnum():
            found.append(_Token(word.start(), word.end(), str(CARDINALS[word.group()])))
    return sorted(found, key=lambda token: token.start)


def _run(folded: str, at: int) -> str:
    """The run of non-whitespace characters `at` is in."""
    lo = folded.rfind(" ", 0, at) + 1
    hi = folded.find(" ", at)
    return folded[lo : len(folded) if hi == -1 else hi]


def _joined(folded: str, start: int, dashes: frozenset[int]) -> bool:
    """Whether a hyphen or underscore joins the digits to a part before them that holds a
    letter: `gpt-4`, and `9750` in `i7-9750h`."""
    at = start - 1
    if folded[at:start] not in ("-", "_") or at in dashes:
        return False
    lo = at
    while lo > 0 and folded[lo - 1].isalnum():
        lo -= 1
    return any(character.isalpha() for character in folded[lo:at])


def _rule(
    folded: str, token: _Token, marked: dict[NumberRule, list[Span]], dashes: frozenset[int]
) -> NumberRule | None:
    """The first rule that reads this token as something other than a quantity."""
    start, end = token.start, token.end
    text = folded[start:end]

    def within(rule: NumberRule) -> bool:
        return any(lo <= start and end <= hi for lo, hi in marked[rule])

    run = _run(folded, start)
    if "://" in run or run.startswith("www."):
        return NumberRule.LINK
    if within(NumberRule.DATE):
        return NumberRule.DATE
    if within(NumberRule.DOCUMENT) or run.startswith(("doi:", "arxiv:")) or _DOI.search(run):
        return NumberRule.DOCUMENT
    if token.named or _joined(folded, start, dashes) or _MORE_DIGITS.match(folded, end):
        return NumberRule.NAME
    if text.count(".") > 1:
        return NumberRule.VERSION_OR_SECTION
    for rule in (NumberRule.CITATION, NumberRule.LABEL, NumberRule.LIST_MARKER):
        if within(rule):
            return rule
    if text.isdigit() and _ORDINAL.match(folded, end):
        return NumberRule.ORDINAL
    if _YEAR.fullmatch(text) and folded[end : end + 1] != "%":
        return NumberRule.YEAR
    if text == "one":
        return NumberRule.THE_WORD_ONE
    return None


def _marked(folded: str) -> dict[NumberRule, list[Span]]:
    """The stretches of the text the rules that read their surroundings apply to."""
    return {
        NumberRule.DATE: [found.span() for found in _DATE.finditer(folded)],
        NumberRule.DOCUMENT: [found.span(1) for found in _DOCUMENT.finditer(folded)],
        NumberRule.CITATION: [found.span() for found in _CITATION.finditer(folded)],
        NumberRule.LABEL: [found.span(1) for found in _LABEL.finditer(folded)],
        NumberRule.LIST_MARKER: [found.span() for found in _LIST_MARKER.finditer(folded)],
    }


def _places(passage: str, folded: str) -> list[Span]:
    """Every place a passage occurs in the text, both normalized as a quotation is."""
    wanted = passage_fold(passage)
    found, at = [], folded.find(wanted) if wanted else -1
    while at != -1:
        found.append((at, at + len(wanted)))
        at = folded.find(wanted, at + 1)
    return found


def _context(folded: str, start: int, end: int) -> str:
    """The run a number is in and `CONTEXT_WORDS` runs on either side."""
    lo, hi = start, end - 1
    for _ in range(CONTEXT_WORDS + 1):
        lo = folded.rfind(" ", 0, lo)
        if lo == -1:
            break
    for _ in range(CONTEXT_WORDS + 1):
        hi = folded.find(" ", hi + 1)
        if hi == -1:
            break
    return folded[lo + 1 : len(folded) if hi == -1 else hi]


def _reported(claim: Claim) -> set[decimal.DecimalTuple]:
    """Each value a claim's assertions say the manuscript prints.

    An `aggregate` says two: the statistic it reports, and how many members it is over, which
    the manifest declares as `count` and refuses to load where the list is another length.
    """
    stated = [getattr(evidence, "reported", None) for evidence in claim.evidence]
    stated += [str(e.count) for e in claim.evidence if isinstance(e, AggregateEvidence)]
    return {read for value in stated if (read := _read(value)) is not None}


def _inventory(
    manifest: Manifest, artifact: ArtifactRef, reported: set[decimal.DecimalTuple]
) -> tuple[TextInventory, list[SetAsideCount]]:
    """One text: every number in it, with where it stands against the manifest."""
    artifact_id, path = artifact.id, manifest.resolve(artifact)
    if not path.is_file():
        raise ArtifactMissingError(artifact_id, path)
    try:
        raw = extract_uncached(path)
    except SourceUnreadableError as e:
        raise ArtifactUnreadableError(path, e.detail) from e
    folded = passage_fold(raw)
    starts = _line_starts(raw, folded)
    dashes = _dashes(raw, folded)

    # What binds: the claim, the stretch of text, and the values it binds there. None is the
    # value a prose address selects, which the assertion reads whatever it holds.
    binding: list[tuple[str, Span, set[decimal.DecimalTuple] | None]] = []
    for claim in manifest.claims:
        values = _reported(claim)
        for quote in _quotes(claim):
            if quote.artifact == artifact_id and values:
                binding += [(claim.id, place, values) for place in _places(quote.text, folded)]
        for named, locator in _prose(claim):
            if named == artifact_id:
                before, after = passage_fold(locator.before), passage_fold(locator.after)
                binding += [(claim.id, place, None) for place in located(folded, before, after)[0]]

    entries = [entry for entry in manifest.set_aside if entry.artifact == artifact_id]
    aside = [_places(entry.text, folded) for entry in entries]
    counted = [0] * len(entries)
    marked = _marked(folded)

    numbers = []
    for token in _tokens(folded, dashes):
        start, end = token.start, token.end
        value = _read(token.value)
        percent = folded[end : end + 1] == "%"
        claims = tuple(
            dict.fromkeys(
                claim_id
                for claim_id, (lo, hi), values in binding
                if lo <= start and end <= hi and (values is None or value in values)
            )
        )
        held = next(
            (
                index
                for index, places in enumerate(aside)
                if any(lo <= start and end <= hi for lo, hi in places)
            ),
            None,
        )
        rule, reason = None, ""
        if claims:
            standing = Standing.BOUND
        elif held is not None:
            standing, reason = Standing.SET_ASIDE_WITH_A_REASON, entries[held].reason
            counted[held] += 1
        elif rule := _rule(folded, token, marked, dashes):
            standing = Standing.SET_ASIDE_BY_RULE
        else:
            standing = Standing.UNBOUND
        # A name, a link, a document's identifier and a version hold digits and no value.
        valued = rule not in (
            NumberRule.NAME,
            NumberRule.LINK,
            NumberRule.DOCUMENT,
            NumberRule.VERSION_OR_SECTION,
        )
        elsewhere = standing is Standing.UNBOUND and value in reported
        told = telling(value)
        numbers.append(
            PrintedNumber(
                text=folded[start : end + 1 if percent else end],
                value=token.value if value is not None and valued else None,
                offset=start,
                line=bisect.bisect_right(starts, start) if starts else None,
                context=_context(folded, start, end),
                standing=standing,
                rule=rule,
                claims=claims,
                reason=reason,
                form=NumberForm.CARDINAL_WORD if folded[start].isalpha() else NumberForm.DECIMAL,
                reported_elsewhere=elsewhere and told,
                reported_elsewhere_one_digit=elsewhere and not told,
            )
        )

    return (
        TextInventory(artifact=artifact_id, path=artifact.path.as_posix(), numbers=tuple(numbers)),
        [
            SetAsideCount(artifact=artifact_id, text=entry.text, reason=entry.reason, numbers=n)
            for entry, n in zip(entries, counted, strict=True)
        ],
    )


def numbers(manifest: Manifest, only: tuple[str, ...] = ()) -> NumbersReport:
    """Count every number the manuscript's text prints and say where each stands.

    `only` names the text artifacts to read in place of the ones `texts` finds. Executes
    nothing and writes nothing.
    """
    declared = {artifact.id: artifact for artifact in manifest.artifacts}
    if unknown := tuple(name for name in only if name not in declared):
        raise UnknownArtifactError(unknown, tuple(declared))
    read = tuple(dict.fromkeys(only)) or texts(manifest)
    if not read:
        raise NoTextError

    reported = {value for claim in manifest.claims for value in _reported(claim)}
    inventories, aside = [], []
    for artifact_id in read:
        inventory, counted = _inventory(manifest, declared[artifact_id], reported)
        inventories.append(inventory)
        aside += counted
    # An entry naming a text that was not read accounts for nothing, and is listed as that.
    aside += [
        SetAsideCount(artifact=entry.artifact, text=entry.text, reason=entry.reason, numbers=0)
        for entry in manifest.set_aside
        if entry.artifact not in read
    ]
    return NumbersReport(
        project=manifest.project,
        manifest_digest=Digest.of_text(manifest.model_dump_json()).value,
        texts=tuple(inventories),
        set_aside=tuple(aside),
    )


__all__ = ["CONTEXT_WORDS", "NoTextError", "UnknownArtifactError", "numbers", "telling", "texts"]
