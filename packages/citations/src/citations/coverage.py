"""Is every quotation in the manuscript pinned to a source?

`verify` reads the claims files and asks whether each pinned quotation resolves in the
artifact it names. It takes no manuscript, so it cannot see a quotation that was added to the
paper and never pinned: there is no claim record for it, nothing is checked, and the report
comes back clean. That is the third outcome the rest of this package exists to keep separate --
a check that never ran, reported here rather than collapsed into silence.

Two questions, answered separately because their remedies differ:

    coverage      is this quotation a span of some pinned quote?
                  Uncovered means: pin it, or stop quoting it.

    attribution   does it appear in the artifact of a source cited near it?
                  Unattributed means: the passage is pinned somewhere, but not
                  in the source the sentence credits.

Coverage is deterministic and offline: it reads the manuscript and the claims files and
nothing else. Attribution additionally reads the pinned artifacts, so it needs them on disk
and reports `unresolvable` where they are absent rather than counting a miss.

An ellipsis is omitted text. `"the model ... performs well"` asserts that both fragments
appear, and asserts nothing about what sits between them, so each fragment is required and
contiguity is not. A fragment under `MIN_FRAGMENT` characters is required beside its long
neighbour's match rather than anywhere in the span; `_search` says why.
"""

from __future__ import annotations

import dataclasses
import pathlib
import re
from collections.abc import Sequence
from typing import Literal

from citations.models import ClaimFile
from citations.verify import passage_fold

#: A LaTeX quotation: ``like this''. The non-greedy body stops at the first closing pair, so
#: two quotations in one sentence are two matches rather than one spanning both.
TEX_QUOTE = re.compile(r"``(.+?)''", re.S)

#: A citation command and its comma-separated keys: \cite, \citep, \citet, \parencite...
CITE = re.compile(r"\\[a-zA-Z]*cite[a-zA-Z]*\s*(?:\[[^\]]*\])*\s*\{([^}]*)\}")

#: How far to look for the citation a quotation belongs to. Asymmetric because a passage is
#: introduced before it is cited more often than after, and generous because the nearest key
#: is frequently the wrong one -- "the same document restricts", "which the same paper
#: asserts" both leave the real source several sentences back, behind an intervening cite.
LOOK_BACK = 700
LOOK_FORWARD = 400

#: Below this, a fragment matches noise. Twelve characters is roughly two words: "the model"
#: appears in every paper ever written and its appearing in a source establishes nothing.
MIN_FRAGMENT = 12

#: How far from its long neighbour's match a short fragment may sit and still count, in folded
#: characters -- roughly fifty words on the one side the quotation puts it. "the model" appearing
#: somewhere in a document establishes nothing; "the model" appearing in the fifty words before a
#: sentence the source demonstrably contains is the quotation's own claim about the source.
ANCHOR_WINDOW = 300

#: What an ellipsis may be written as, once folded.
ELLIPSIS = re.compile(r"\s*(?:\.\s*\.\s*\.|…)\s*")

#: Punctuation that belongs to the sentence rather than to the source, stripped from the end
#: of a quotation before comparing. American typesetting puts the sentence's period inside the
#: closing quotation mark, so `pluralism."` is quoting `pluralism`.
#:
#: End only, and only these four. `skeleton` in `verify` records what happens when a
#: normalizer reaches further: stripping every non-alphanumeric character made `p < 0.05`
#: match a source reading `p = 0.05`, and `-0.42` match `0.42`. A trailing comma cannot
#: reverse an inequality or flip a sign.
TRAILING = ",.;:"

Status = Literal["covered", "uncovered", "unresolvable"]


@dataclasses.dataclass(frozen=True)
class Quotation:
    """One quotation as the manuscript writes it, and where."""

    line: int
    raw: str
    text: str
    """`raw` unwrapped and folded: what is actually compared."""

    keys: tuple[str, ...]
    """Citation keys in the neighbourhood, in the order they appear. Not ranked."""

    @property
    def fragments(self) -> list[str]:
        """The parts an ellipsis separates. Each must appear; contiguity is not required."""
        return [f for f in (comparable(p) for p in ELLIPSIS.split(self.text)) if f]


@dataclasses.dataclass(frozen=True)
class Finding:
    """What was concluded about one quotation."""

    quotation: Quotation
    status: Status
    detail: str = ""
    source: str = ""
    """The claims file, or the citation key, the quotation was matched in."""


def comparable(text: str) -> str:
    """A folded passage in the form both sides are compared in.

    Two normalizations beyond `passage_fold`, each narrow enough to name:

    Quotation marks are dropped. LaTeX writes them four ways -- ```", `''`, `` ` ``, `'` --
    and a source that renders them straight is quoting the same words. Only `'` and `"` go;
    an apostrophe inside a word goes with them, consistently on both sides, so `authors'` and
    `authors` compare equal and neither can be confused with a different word.

    Sentence punctuation is dropped from the end. See `TRAILING`.
    """
    return (
        passage_fold(text)
        .strip()
        .strip("'\"")
        .rstrip(TRAILING)
        .strip()
        .replace("'", "")
        .replace('"', "")
    )


def unwrap(tex: str) -> str:
    """A LaTeX quotation body as prose, with markup removed and nothing else changed.

    Only the constructs that appear *inside* a quotation are handled: an emphasis, an escaped
    percent or ampersand, a discretionary hyphen, an inline math span, a brace group. This
    deliberately does not strip punctuation. An earlier tool in this family normalized by
    replacing every non-alphanumeric run with a space, which made `p < 0.05` match a source
    reading `p = 0.05` and `-0.42` match `0.42` -- a reversed inequality and a flipped sign,
    both reported as quoted verbatim by the one check meant to catch a misquotation.
    """
    t = tex
    t = re.sub(r"\\ldots\s*(?:\{\})?|\\dots\s*(?:\{\})?", "…", t)
    t = t.replace("\\-", "")  # discretionary hyphen: a hint to the typesetter, not a character
    # LaTeX's dash ligatures. `--` sets an en dash and `---` an em dash; a source renders them
    # as the character, and `passage_fold` maps that character to a plain hyphen. Longest first, or
    # `---` is eaten as `--` plus a stray hyphen.
    t = t.replace("---", "—").replace("--", "–")
    # Spacing commands set a gap and contribute no character. `\,` between a closing inner
    # quote and the outer one is the usual case: ``... the `gold standard'\,''.
    t = re.sub(r"\\[,;:!]|\\ |\\q?quad\b|\\thinspace\b|\\@", " ", t)
    t = re.sub(r"\\([%&$#_{}])", r"\1", t)  # escaped literals become themselves
    t = re.sub(r"\\[a-zA-Z]+\s*\{([^{}]*)\}", r"\1", t)  # \emph{x}, \textit{x} -> x
    t = re.sub(r"\$([^$]*)\$", r"\1", t)  # inline math keeps its content
    t = t.replace("``", '"').replace("''", '"').replace("`", "'")
    t = re.sub(r"[{}]", "", t)
    return t


def strip_comments(tex: str) -> str:
    """LaTeX with comment text removed, and line count preserved.

    Line numbers are how a reader finds the quotation, so a comment becomes an empty line
    rather than disappearing. An escaped `\\%` is a percent sign and not a comment.
    """
    out = []
    for line in tex.split("\n"):
        out.append(re.sub(r"(?<!\\)%.*$", "", line))
    return "\n".join(out)


def quotations(tex: str) -> list[Quotation]:
    """Every ``...'' in a LaTeX manuscript, with the citation keys near each."""
    body = strip_comments(tex)
    found = []
    for m in TEX_QUOTE.finditer(body):
        window = body[max(0, m.start() - LOOK_BACK) : m.end() + LOOK_FORWARD]
        keys: list[str] = []
        for group in CITE.findall(window):
            for key in group.split(","):
                if (k := key.strip()) and k not in keys:
                    keys.append(k)
        found.append(
            Quotation(
                line=body[: m.start()].count("\n") + 1,
                raw=m.group(1),
                text=passage_fold(unwrap(m.group(1))),
                keys=tuple(keys),
            )
        )
    return found


def pinned_spans(claim_files: list[ClaimFile]) -> list[tuple[str, str]]:
    """Every pinned quotation, folded, with the claims file it came from."""
    pool = []
    for cf in claim_files:
        for claim in cf.claims.values():
            for quote in claim.quotes:
                if text := comparable(unwrap(quote.text)):
                    pool.append((cf.name, text))
    return pool


def _positions(needle: str, span: str) -> list[int]:
    """Every offset in `span` at which `needle` starts."""
    out: list[int] = []
    i = span.find(needle)
    while i != -1:
        out.append(i)
        i = span.find(needle, i + 1)
    return out


def _anchors(fragments: Sequence[str], i: int) -> list[tuple[str, bool]]:
    """The long fragments immediately beside `fragments[i]`, each with whether it precedes it.

    Immediate neighbours only. A short fragment flanked by short ones is not anchored through
    them: an intermediate fragment's own position is no more certain than the anchoring it
    needed, and chaining the windows widens the search back out to the document.
    """
    out = []
    for j, fragment_follows in ((i - 1, True), (i + 1, False)):
        if 0 <= j < len(fragments) and len(fragments[j]) >= MIN_FRAGMENT:
            out.append((fragments[j], fragment_follows))
    return out


def _beside(fragment: str, anchor: str, follows: bool, span: str) -> bool:
    """Does `fragment` occur within `ANCHOR_WINDOW` of a match of `anchor`, on the side the
    quotation puts it?

    `follows` is whether the quotation writes `fragment` after `anchor`, and the window is taken
    on that side of the anchor's match, so an occurrence on the wrong side does not count. Every
    occurrence of the anchor is tried: a pinned span may repeat it, and the quotation asserts
    only that some one of them carries the fragment beside it.
    """
    for start in _positions(anchor, span):
        if follows:
            end = start + len(anchor)
            window = span[end : end + ANCHOR_WINDOW]
        else:
            window = span[max(0, start - ANCHOR_WINDOW) : start]
        if fragment in window:
            return True
    return False


@dataclasses.dataclass(frozen=True)
class _Search:
    """What a decidable quotation requires of a span."""

    fragments: tuple[str, ...]
    """Every fragment, in the order the quotation writes them."""

    def present_in(self, span: str) -> bool:
        """Is every long fragment somewhere in `span`, and every short fragment beside a long
        neighbour's match, on the right side of it and within `ANCHOR_WINDOW`?

        Order among the long fragments is not required. `"a ... b"` claims two spans of one
        document and a source may write them in either order, so nothing here places a long
        fragment relative to another. Only a short fragment is placed, because being placed is
        what makes it worth searching for at all.
        """
        for i, f in enumerate(self.fragments):
            if len(f) >= MIN_FRAGMENT:
                if f not in span:
                    return False
            elif not any(
                _beside(f, anchor, follows, span) for anchor, follows in _anchors(self.fragments, i)
            ):
                return False
        return True


def _search(q: Quotation) -> _Search | Finding:
    """How to look for this quotation, or the finding that ends the question.

    `MIN_FRAGMENT` exists because a short string occurs somewhere in almost any document, so
    finding one there establishes nothing: "the model" appears in every paper ever written. That
    is true of a whole document and false of a small ordered window beside a specific long match,
    so a short fragment is searched for in that window and nowhere else.

    Two earlier rules, and what each got wrong. Dropping a short fragment and answering from the
    rest asserted coverage of text that was never examined: `"no effect ... the calibration error
    falls to 0.031 under the new schedule"` came back `covered` on the strength of its second
    half, while "no effect" appeared in neither the pinned quote nor the source. Refusing the
    whole quotation instead put `"we find ... "` and `"the model ... "` openings, which are
    common, permanently beyond `--strict`, and a check people switch off decides nothing either.

    A quotation is undecidable only where the window cannot be built: no long fragment to anchor
    to, or a short fragment with no long fragment beside it.
    """
    fragments = tuple(q.fragments)
    if not any(len(f) >= MIN_FRAGMENT for f in fragments):
        return Finding(q, "unresolvable", f"under {MIN_FRAGMENT} characters once folded")
    loose = [
        f for i, f in enumerate(fragments) if len(f) < MIN_FRAGMENT and not _anchors(fragments, i)
    ]
    if loose:
        return Finding(
            q,
            "unresolvable",
            f"a fragment is under {MIN_FRAGMENT} characters with no longer fragment beside it to "
            f"anchor the search to, so it was never looked for: "
            f"{', '.join(repr(s) for s in loose[:2])}",
        )
    return _Search(fragments)


def cover(q: Quotation, pool: list[tuple[str, str]]) -> Finding:
    """Is this quotation a span of some pinned quote?

    A quotation that cannot be searched for is `unresolvable`: too short to distinguish from
    noise, which is a different answer from being absent. See `_search`.
    """
    search = _search(q)
    if isinstance(search, Finding):
        return search
    for name, pinned in pool:
        if search.present_in(pinned):
            return Finding(q, "covered", source=name)
    return Finding(q, "uncovered", "no pinned quote contains it")


def _artifact_text(cf: ClaimFile, claims_dir: pathlib.Path, allowed) -> str | None:
    """The pinned artifact's extracted text, folded, or None where it cannot be read.

    Read through `verify.extract`, so a source declaring `extract_cmd` is read by the command
    it names and an attribution check and a quotation check cannot disagree about what the
    document says.
    """
    from citations.exceptions import SourceUnreadableError
    from citations.verify import extract

    if not cf.source.local:
        return None
    path = (claims_dir.parent / cf.source.local).resolve()
    if not path.is_file():
        return None
    try:
        return comparable(extract(path, None, cf.source.extract_cmd, allowed))
    except SourceUnreadableError:
        return None


def attribute(q: Quotation, by_key: dict[str, str], missing: set[str]) -> Finding:
    """Does this quotation appear in the artifact of a source cited near it?

    Matched against every key in the neighbourhood rather than the nearest, because the
    nearest is often not the source. A passage present in either neighbour therefore passes,
    and a quotation attributed to the wrong one of two sources cited in the same paragraph is
    not caught here. Read the sentence for that.
    """
    search = _search(q)
    if isinstance(search, Finding):
        return search
    if not q.keys:
        return Finding(q, "unresolvable", "no citation key within the window")

    readable = [k for k in q.keys if k in by_key]
    if not readable:
        why = (
            "cited nearby but no artifact on disk"
            if any(k in missing for k in q.keys)
            else ("no claims file for any key nearby")
        )
        return Finding(q, "unresolvable", f"{why}: {', '.join(q.keys[:4])}")

    for key in readable:
        if search.present_in(by_key[key]):
            return Finding(q, "covered", source=key)

    # Absent from every source that could be read. That is only an accusation if every source
    # was read: a passage belonging to a neighbour whose artifact would not open has not been
    # looked for, and reporting it as misattributed would blame the manuscript for a missing
    # file. Unreadable neighbours make the question undecided, which is the third outcome.
    if unread := [k for k in q.keys if k in missing]:
        return Finding(
            q,
            "unresolvable",
            f"not in {', '.join(readable)}; and {', '.join(unread[:3])} could not be read, "
            f"so it was never looked for there",
        )
    return Finding(q, "uncovered", f"in none of {', '.join(readable)}")


def artifacts_by_key(
    claim_files: list[ClaimFile], claims_dir: pathlib.Path, allowed
) -> tuple[dict[str, str], set[str]]:
    """Folded artifact text for every citation key whose source can be read, and the keys
    whose source is named and cannot be.

    Keyed by `source.citation` where the file declares one, and by the file's own stem
    otherwise, since a claims file is conventionally named for the key it covers.
    """
    by_key: dict[str, str] = {}
    missing: set[str] = set()
    for cf in claim_files:
        key = (cf.source.citation or cf.name).strip()
        text = _artifact_text(cf, claims_dir, allowed)
        if text is None:
            missing.add(key)
        else:
            by_key[key] = text
    return by_key, missing
