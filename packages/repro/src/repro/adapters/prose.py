"""The value between two literal anchors in the text of a document.

Every other adapter translates a locator into the addressing its format already has. Prose has
none: a sentence is not a tree, a table, or an indexed array. What a document does have is the
text on either side of a number, and that is the address this adapter resolves -- the author
writes the literal that precedes the value and the literal that follows it, and the adapter
returns what sits between.

Nothing here searches for a number. A pattern that found "the first integer in the paragraph"
would locate a number wherever one appeared and call that verification, which is the failure
`repro.adapters.base` exists to prevent.

The text is the text a quotation resolves against: `citations.verify.extract` produces it and
`citations.verify.fold` normalizes it, so an anchor and a `quote` assertion over the same
document cannot disagree about what the document says.
"""

from __future__ import annotations

import decimal
import pathlib

from repro.adapters.base import Found, Resolution, _no, _ok
from repro.exceptions import ArtifactUnreadableError, BackendUnavailableError
from repro.models import NumberForm, ProseLocator

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


def _is_decimal(text: str) -> bool:
    try:
        decimal.Decimal(text)
    except (decimal.InvalidOperation, ValueError):
        return False
    return True


def _resolve_prose(locator: ProseLocator, path: pathlib.Path) -> Found:
    # Imported here for the reason `QuoteBackend` imports it here: an installation without a
    # working extractor must report a check that did not run, not fail to import the package.
    try:
        from citations.exceptions import SourceUnreadableError
        from citations.verify import extract, fold
    except ImportError as e:  # pragma: no cover - citations is a declared dependency
        raise BackendUnavailableError("prose", f"citations is not installed: {e}") from e

    # `extract` is cached on the path, so a second verification in one process reads the text
    # the first one extracted, whatever the file now holds. The engine hashes every artifact
    # immediately before this runs, so a stale read would produce a decision whose recorded
    # artifact digest does not describe the text it was computed from. `fold` is cached on the
    # string it is given, which is content, and stays as it is.
    uncached = getattr(extract, "__wrapped__", extract)
    try:
        text = fold(uncached(path))
    except SourceUnreadableError as e:
        raise ArtifactUnreadableError(path, e.detail) from e
    if not text:
        raise ArtifactUnreadableError(path, "no text extracted")

    # `fold` trims and collapses whitespace, which is what an anchor wants: the boundary
    # spaces are supplied by `_spans`, and an anchor written across a line break in the
    # manifest matches a document that wrapped it somewhere else.
    before, after = fold(locator.before), fold(locator.after)
    if not before:
        return _no(
            Resolution.SELECTOR_INVALID,
            "`before` is empty after normalization, so it anchors nothing",
        )

    hits = _spans(text, before, after)
    address = (
        f'"{locator.before}" ... "{locator.after}"' if locator.after else f'"{locator.before}"'
    )
    if not hits:
        return _no(
            Resolution.ABSENT,
            f"no value sits between {address} in {path.name}; anchors are literal text, "
            f"matched after the same normalization a quotation is matched under",
        )
    values = sorted(set(hits))
    if len(values) > 1:
        # Repetition is normal in a document and is not ambiguity: a count stated in an
        # abstract and again in a section is one value. Two *different* values between the
        # same anchors is a document contradicting itself, which is a finding rather than a
        # thing to resolve by taking the first.
        return _no(
            Resolution.PASSAGE_AMBIGUOUS,
            f"{address} selects {len(values)} different values in {path.name}: {', '.join(values)}",
        )

    value = values[0]
    seen = f"{len(hits)} occurrence(s)" if len(hits) > 1 else ""
    trace = (address, seen) if seen else (address,)

    if locator.form is NumberForm.CARDINAL_WORD:
        if (number := CARDINALS.get(value)) is not None:
            return _ok(str(number), "cardinal_word", *trace, f'the word "{value}"')
        # A numeral where a word was declared still parses, and refusing it would break a
        # check because someone corrected the prose. Anything else falls through to the
        # backend, which reports it as not numeric.
        return _ok(value, "text", *trace)

    if not _is_decimal(value) and value in CARDINALS:
        return _no(
            Resolution.NUMBER_AS_WORD,
            f'{address} holds "{value}" in {path.name}. Reading a word as a number is a '
            f"semantic decision the engine does not make on its own; declare "
            f"`form: cardinal_word` on the locator to ask for it",
        )
    return _ok(value, "decimal" if _is_decimal(value) else "text", *trace)


def _spans(text: str, before: str, after: str) -> list[str]:
    """Every non-whitespace run that sits between the two anchors.

    Whitespace at an anchor boundary is ignored, on the same grounds `fold` collapses it
    everywhere else: `before: "holds"` and `before: "holds "` address the same value, and a
    manifest should not turn on which one the author typed.
    """
    found: list[str] = []
    n, start = len(text), 0
    while (at := text.find(before, start)) != -1:
        start = at + 1
        cursor = at + len(before)
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
        if after and not text.startswith(after, tail):
            continue
        found.append(text[cursor:end])
    return found
