"""The value between two literal anchors in the text of a document.

Every other adapter translates a locator into the addressing its format already has. Prose has
none: a sentence is not a tree, a table, or an indexed array. What a document does have is the
text on either side of a number, and that is the address this adapter resolves -- the author
writes the literal that precedes the value and the literal that follows it, and the adapter
returns what sits between.

Nothing here searches for a number. A pattern that found "the first integer in the paragraph"
would locate a number wherever one appeared and call that verification, which is the failure
`claims.adapters.base` exists to prevent.

The text is the text a quotation resolves against: `citations.verify.extract` produces it and
`citations.verify.passage_fold` normalizes it, so an anchor and a `quote` assertion over the same
document cannot disagree about what the document says.
"""

from __future__ import annotations

import bisect
import decimal
import pathlib
import re
from collections.abc import Callable, Iterator

from claims.adapters.base import Found, Resolution, _no, _ok
from claims.adapters.reads import once
from claims.exceptions import ArtifactUnreadableError, BackendUnavailableError
from claims.models import NumberForm, ProseLocator

_UNITS = (
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
    "fifteen sixteen seventeen eighteen nineteen"
).split()

_TENS = "twenty thirty forty fifty sixty seventy eighty ninety".split()


def _cardinals() -> dict[str, int]:
    """English cardinals below one hundred, as one word each.

    The bound is not arbitrary: the value a prose locator selects is a run of non-whitespace
    characters, and every cardinal above ninety-nine is written as several words. Extending
    the table would not make `one hundred and forty-five` addressable.

    The table names a conversion the manifest has to ask for. It is also read under
    `form: decimal`, where a hit means the value is refused with `number_as_word` rather than
    reported as a missing number -- an author who spelled the count out should be told that,
    not sent looking for a broken anchor.
    """
    table = {word: value for value, word in enumerate(_UNITS)}
    for index, tens in enumerate(_TENS):
        base = 20 + index * 10
        table[tens] = base
        for unit in range(1, 10):
            table[f"{tens}-{_UNITS[unit]}"] = base + unit
    return table


CARDINALS = _cardinals()

#: A number as it is printed, for deciding where an anchor may not fall. The digits, grouping
#: underscores, decimal point and exponent are the unsigned part of what `decimal.Decimal`
#: parses, which is what reads the value in `_is_decimal` here and in `claims.verify`. The comma
#: is not: `Decimal("1,234")` is refused. It is here because a document prints `1,234`, and an
#: anchor that cut it at the comma would have `1` read as the value.
#:
#: A match counts only where no letter stands immediately before it. Digits attached to a
#: letter are part of a name -- the version `v0.5`, the label `H10` -- and an anchor may fall
#: among them. Punctuation does not make a name: `x=0.318`, `(0.318` and `p<0.05` hold numbers,
#: and so does a number with letters after it, `5kg`.
#:
#: A sign immediately before the digits belongs to the number where it opens the run or follows
#: a character that is neither a digit nor a letter: `x=-0.42`, `(-0.42)`, `| -0.42|`. After a
#: digit or a letter it is a range, a subtraction or a hyphen, `10-12` and `pre-2020`, and the
#: digits after it are a number of their own. `passage_fold` has already written U+2212 and
#: the dashes as `-` by the time this is read; the character is listed for a caller that has not.
_SIGNS = "+-\u2212"
_NUMBER = re.compile(r"\d+(?:_\d+)*(?:[.,]\d+(?:_\d+)*)*(?:[eE][+-]?\d+)?")

#: `2,364` and `1,234,567.5`: commas that group digits in threes. Any other comma between
#: digits separates two numbers. What `form: grouped` reads, and what `repro numbers` counts
#: as one number.
GROUPED = re.compile(r"[+-]?\d{1,3}(?:,\d{3})+(?:\.\d+)?(?:[eE][+-]?\d+)?")


def numerals(text: str, lo: int = 0, hi: int | None = None) -> Iterator[tuple[int, int, bool]]:
    """Each run of digits in `text[lo:hi]` that is printed as a number: where it starts, its
    sign included, where it ends, and whether a letter stands immediately before it.

    The last is the rule above: with a letter before them the digits are part of a name, and
    no sign is read for a name."""
    for number in _NUMBER.finditer(text, lo, len(text) if hi is None else hi):
        first = number.start()
        if first > 0 and text[first - 1].isalpha():
            yield first, number.end(), True
            continue
        if first > 0 and text[first - 1] in _SIGNS:
            sign = first - 1
            if sign == 0 or not text[sign - 1].isalnum():
                first = sign
        yield first, number.end(), False


def _split(text: str, at: int) -> str:
    """The number `at` falls strictly inside, or the empty string where it splits none."""
    lo = at
    while lo > 0 and not text[lo - 1].isspace():
        lo -= 1
    hi = at
    while hi < len(text) and not text[hi].isspace():
        hi += 1
    for first, end, named in numerals(text, lo, hi):
        if not named and first < at < end:
            return text[first:end]
    return ""


def _is_decimal(text: str) -> bool:
    try:
        decimal.Decimal(text)
    except (decimal.InvalidOperation, ValueError):
        return False
    return True


def _number(value: str, form: NumberForm) -> decimal.Decimal | None:
    """The finite number a selected text is read as under `form`, or None where it is none."""
    if form is NumberForm.CARDINAL_WORD and value in CARDINALS:
        value = str(CARDINALS[value])
    elif form is NumberForm.GROUPED and GROUPED.fullmatch(value):
        value = value.replace(",", "")
    try:
        number = decimal.Decimal(value)
    except (decimal.InvalidOperation, ValueError):
        return None
    return number if number.is_finite() else None


def _exponent(number: decimal.Decimal) -> int:
    """The power of ten a finite decimal's last digit sits at. `_number` returns no other."""
    exponent = number.as_tuple().exponent
    return exponent if isinstance(exponent, int) else 0


def line_starts(raw: str, folded: str, fold: Callable[[str], str]) -> list[int] | None:
    """Where each line of the extracted text starts in the normalized text.

    `fold` is `passage_fold`, passed in because `citations` is imported where a check runs and
    not where this module loads. It joins the lines with one space, and joins a word a hyphen
    splits across a line break with nothing. This walks the lines under that rule, and returns
    None where what it walked is not the normalized text, so no line number is ever a guess.
    """
    pieces = [fold(line) for line in raw.split("\n")]
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


def context(text: str, start: int, end: int, words: int = 4) -> str:
    """The run `text[start:end]` is in and `words` runs on either side."""
    lo, hi = start, end - 1
    for _ in range(words + 1):
        lo = text.rfind(" ", 0, lo)
        if lo == -1:
            break
    for _ in range(words + 1):
        hi = text.find(" ", hi + 1)
        if hi == -1:
            break
    return text[lo + 1 : len(text) if hi == -1 else hi]


def _resolve_prose(locator: ProseLocator, path: pathlib.Path) -> Found:
    # Imported here for the reason `QuoteBackend` imports it here: an installation without a
    # working extractor must report a check that did not run, not fail to import the package.
    try:
        from citations.exceptions import SourceUnreadableError
        from citations.verify import extract_uncached, passage_fold
    except ImportError as e:  # pragma: no cover - citations is a declared dependency
        raise BackendUnavailableError("prose", f"citations is not installed: {e}") from e

    # `extract` is cached on the path, so a second verification in one process reads the text
    # the first one extracted, whatever the file now holds. `extract_uncached` is the named
    # read; this reached it through `extract.__wrapped__` until that attribute stopped existing
    # and the `getattr` fallback quietly returned the cached function instead. The engine hashes every artifact
    # immediately before this runs, so a stale read would produce a decision whose recorded
    # artifact digest does not describe the text it was computed from. `fold` is cached on the
    # string it is given, which is content, and stays as it is. `once` keeps the read for the
    # verification in progress and no longer, so the next verification reads the file again.
    def read() -> tuple[str, str]:
        raw = extract_uncached(path)
        return raw, passage_fold(raw)

    try:
        raw, text = once(("prose", path), read)
    except SourceUnreadableError as e:
        raise ArtifactUnreadableError(path, e.detail) from e
    if not text:
        raise ArtifactUnreadableError(path, "no text extracted")

    # `fold` trims and collapses whitespace, which is what an anchor wants: the boundary
    # spaces are supplied by `located`, and an anchor written across a line break in the
    # manifest matches a document that wrapped it somewhere else.
    before, after = passage_fold(locator.before), passage_fold(locator.after)
    if not before:
        return _no(
            Resolution.SELECTOR_INVALID,
            "`before` is empty after normalization, so it anchors nothing",
        )

    spans, split = located(text, before, after)
    hits = [text[start:end] for start, end in spans]
    address = (
        f'"{locator.before}" ... "{locator.after}"' if locator.after else f'"{locator.before}"'
    )
    if not hits:
        refused = (
            f"; an anchor never splits a number, and these would split {', '.join(split)}"
            if split
            else ""
        )
        return _no(
            Resolution.ABSENT,
            f"no value sits between {address} in {path.name}; anchors are literal text, "
            f"matched after the same normalization a quotation is matched under{refused}",
        )
    # Repetition is normal in a document and is not ambiguity: a count stated in an abstract
    # and again in a section is one value, and so is `8.3` beside `8.30`, or `1,062` beside
    # `1062` under `grouped`. Two *different* numbers between the same anchors is a document
    # contradicting itself, which is a finding rather than a thing to resolve by taking the
    # first. Where any occurrence is no number, occurrences are compared as text.
    read = [_number(hit, locator.form) for hit in hits]
    numbers = [number for number in read if number is not None]
    distinct = len(set(numbers)) if len(numbers) == len(hits) else len(set(hits))
    if distinct > 1:
        starts = line_starts(raw, text, passage_fold)
        where = [
            (f"{hit} at line {bisect.bisect_right(starts, start)}" if starts else hit)
            + f' ("{context(text, start, end)}")'
            for hit, (start, end) in zip(hits, spans, strict=True)
        ]
        return _no(
            Resolution.PASSAGE_AMBIGUOUS,
            f"{address} selects {distinct} different values in {path.name}: {', '.join(where)}",
        )

    # The finest of equal spellings, the first where they are as fine: `8.30` printed anywhere
    # states two places, and the comparison is held to them.
    value = hits[0]
    if len(numbers) == len(hits):
        value = hits[min(range(len(hits)), key=lambda at: _exponent(numbers[at]))]
    printed = list(dict.fromkeys(hits))
    seen = f"{len(hits)} occurrence(s)" if len(hits) > 1 else ""
    if len(printed) > 1:
        seen += f", printed as {', '.join(printed)}"
    trace = (address, seen) if seen else (address,)

    if locator.form is NumberForm.CARDINAL_WORD:
        if (number := CARDINALS.get(value)) is not None:
            return _ok(str(number), "cardinal_word", *trace, f'the word "{value}"')
        # A numeral where a word was declared still parses, and refusing it would break a
        # check because someone corrected the prose. Anything else falls through to the
        # backend, which reports it as not numeric.
        return _ok(value, "text", *trace)

    if locator.form is NumberForm.GROUPED and GROUPED.fullmatch(value):
        # A numeral written without commas falls through and parses, as a numeral does under
        # `cardinal_word`.
        return _ok(value.replace(",", ""), "grouped", *trace, f'the grouped number "{value}"')

    if not _is_decimal(value) and value in CARDINALS:
        return _no(
            Resolution.NUMBER_AS_WORD,
            f'{address} holds "{value}" in {path.name}. Reading a word as a number is a '
            f"semantic decision the engine does not make on its own; declare "
            f"`form: cardinal_word` on the locator to ask for it",
        )
    return _ok(value, "decimal" if _is_decimal(value) else "text", *trace)


def located(text: str, before: str, after: str) -> tuple[list[tuple[int, int]], list[str]]:
    """Where the value after each occurrence of `before` starts and ends, and the numbers an
    anchor would have split.

    The value is a run of non-whitespace characters. With no `after` it is the whole run up to
    the next whitespace. With one, the whole run is taken where `after` begins past it, and
    otherwise the run is cut at the first place inside it where `after` begins: a cell printed
    against its divider, `0.318|`, or a number closing a sentence, `3.14.`, is delimited by
    the anchor that touches it and by nothing the engine guessed.

    Neither anchor may fall inside a number. `after: "8"` does not read `0.318` as `0.31`, the
    first full stop in `3.14.` is passed over for the second, and `before: "0.3"` does not
    read `18`. An occurrence refused on those grounds yields no value, and the number it
    would have split is returned so the report can say why. Digits attached to a preceding
    letter are a name, so `before: "v0."` reads `5` from `v0.5`. A sign is part of its number
    unless a digit or a letter precedes it, so `before: "x=-"` reads nothing from `x=-0.42`
    and `before: "10-"` reads `12` from `10-12`.

    Whitespace at an anchor boundary is ignored, on the same grounds `fold` collapses it
    everywhere else: `before: "holds"` and `before: "holds "` address the same value, and a
    manifest should not turn on which one the author typed.
    """
    found: list[tuple[int, int]] = []
    split: list[str] = []
    n, start = len(text), 0
    while (at := text.find(before, start)) != -1:
        start = at + 1
        cursor = at + len(before)
        if number := _split(text, cursor):
            split.append(number)
            continue
        while cursor < n and text[cursor].isspace():
            cursor += 1
        end = cursor
        while end < n and not text[end].isspace():
            end += 1
        if end == cursor:
            continue
        tail = end
        while tail < n and text[tail].isspace():
            tail += 1
        if not after or text.startswith(after, tail):
            found.append((cursor, end))
            continue
        for stop in range(cursor + 1, end):
            if not text.startswith(after, stop):
                continue
            if number := _split(text, stop):
                split.append(number)
                continue
            found.append((cursor, stop))
            break
    return found, list(dict.fromkeys(split))
