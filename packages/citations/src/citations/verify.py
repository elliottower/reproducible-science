"""Does each quotation appear in the source it cites?

Builds a corpus of quotations checked against a pinned source, so later work quotes from the
corpus rather than from memory.

Four orthogonal things, kept apart.

The pin -- is this the document that was pinned? Checked once per artifact:

    ok           the file's sha256 matches the one recorded
    broken       the file has changed since the quotations were taken
    unpinned     no sha256 was recorded, so nothing can be checked
    missing      the file named by the record is not on disk

The result -- did the passage appear? Exhaustive, four outcomes:

    found          the passage is in the source
    not found      the source was read and the passage is not in it
    indeterminate  readers that both read the source disagree about whether it is in it
    unchecked      no reader could read the source, so no measurement was made

The warnings -- is the quote well formed? A quote can be `found` and still carry one:

    short        the source may qualify it in the next clause
    truncated    every occurrence stops mid-word or mid-number
    normalized   matched only after ignoring punctuation and spacing
    page         found, but not on the page the record claims

The reader -- what turned the bytes into text? Recorded on every result. A pin establishes
that the file has not changed and establishes nothing about the extraction, so a decision that
does not name the program that read the document cannot be compared with a later one taken
with something else. `pdftotext -layout` is preferred; a pure-Python reader stands in where it
is absent, and the substitution is recorded rather than made silently. See `readers.py`.

`indeterminate` is not a milder `not found`. `not found` says the source was read and the
passage is not in it, which is an accusation against the manuscript. `indeterminate` says the
readers on this machine do not settle what text the document holds, which accuses nothing and
asks for a better reader. Against the three-stage model in `docs/SPEC.md` the two sit in
different stages: `not found` is `extraction=extracted, comparison=mismatch`, while
`indeterminate` is `extraction=invalid, comparison=not_applicable` -- the readers ran, and
what they produced does not determine a text to compare against.

`unchecked` means read the source. A mirror-reversed scan or a broken extraction produces the
same signal as a passage that was never there -- so an extraction that failed for an
infrastructure reason says which one, rather than reporting the document as unreadable.
"""

from __future__ import annotations

import dataclasses
import functools
import pathlib
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Literal

from provenance_core import sha256_of_file

from citations import readers
from citations.exceptions import SourceUnreadableError

# Long enough to carry its own qualifiers. "We trained 50" resolves against a sentence that
# continues "...and 5 refits each for 12 layered".
MIN_QUOTE_CHARS = 40

#: How many pages `_find_page` will scan before giving up. Hitting it is reported, never
#: silently folded into "not found on any page" -- the two are different facts.
PAGE_SCAN_LIMIT = 200

#: Suffixes read directly rather than through a PDF extractor. Running `pdftotext` over these
#: returns nothing, which would read as an unreadable source.
TEXT_SUFFIXES = (".txt", ".md", ".tei", ".xml", ".html", ".htm", ".rst")

#: The reader recorded for a source read straight off disk. A `.txt` or `.tei` needs no
#: extractor, so naming one would claim a program ran that did not.
PLAIN_TEXT = "text"

#: The reader recorded when `extract` was replaced by a caller. Naming the substitution keeps
#: the promise the rest of this module makes: a result says what produced the text it was
#: checked against, and "a stub did" is an answer where inventing a reader name is not.
SUBSTITUTED = "substituted"

State = Literal["found", "not found", "indeterminate", "unchecked"]
PinState = Literal["ok", "broken", "unpinned", "missing"]


@dataclass
class Result:
    """`state` is the measurement; `warnings` are notes about the quote itself."""

    state: State
    detail: str = ""  # why, when unchecked, not found, or indeterminate
    warnings: list[str] = field(default_factory=list)
    page_found: int | None = None

    reader: str = ""
    """What turned the source into text. Empty only where nothing was read."""

    fallback: bool = False
    """Whether the preferred reader produced this text. A substitution is recorded, never
    silent: a `not found` taken with pypdf is a different record from one taken with poppler,
    and a report that cannot tell them apart cannot be compared with a later run."""

    fallback_reason: str = ""
    """Why the preferred reader did not produce it -- not installed, or failed on this file."""

    agreement: dict[str, State] = field(default_factory=dict)
    """Each reader's own verdict, when more than one was consulted. Empty on a single-reader
    check, which is the default: an empty mapping means agreement was never measured, not
    that the readers agreed. Availability and agreement are different questions and this
    field answers only the second."""


@dataclass
class Pin:
    """Whether the artifact on disk is the artifact the record describes.

    Separate from `Result` because it is a fact about the source, not about any one quotation.
    A broken pin does not make a quotation `not found` -- the passage may well be in the file
    that is there -- but it does mean every result computed against it describes a document
    the record does not.
    """

    state: PinState
    expected: str = ""
    actual: str = ""

    @property
    def ok(self) -> bool:
        return self.state == "ok"


@dataclass
class Report:
    checked: int = 0
    counts: dict[str, int] = field(default_factory=dict)
    problems: list[tuple[str, str, Result]] = field(default_factory=list)
    broken_pins: list[tuple[str, Pin]] = field(default_factory=list)
    unpinned: list[str] = field(default_factory=list)
    """Sources with no recorded digest. Their quotations resolve against whatever is on disk."""
    skipped: list[tuple[str, str]] = field(default_factory=list)
    """Claims files that would not parse, so their quotations were never examined."""

    readers_used: dict[str, int] = field(default_factory=dict)
    """How many quotations each reader answered. A report that does not say what read its
    sources cannot be compared with one taken on another machine, where a different reader
    may have been the one installed."""

    fallback_reasons: dict[str, str] = field(default_factory=dict)
    """Why the preferred reader did not answer, for each reader that stood in for it. A
    fallback appears here whether it was taken because poppler was absent or because poppler
    failed, so no substitution is invisible in the report."""

    @property
    def unresolved(self) -> int:
        """Quotations no verdict was reached on.

        `indeterminate` counts here and not among the failures. Readers disagreeing about a
        passage leaves the question open in exactly the way an absent extractor does; what it
        does not do is assert that the passage is missing.
        """
        return self.counts.get("unchecked", 0) + self.counts.get("indeterminate", 0)

    @property
    def strict_ok(self) -> bool:
        """What `--strict` means: nothing was left unresolved.

        `ok` is the substantive verdict -- a quotation that is genuinely absent. It
        deliberately ignores an unchecked quote, because a missing extractor says nothing
        about the paper. For CI that is the wrong question: a deleted source, an unpinned
        one, a claims file that would not parse, and a missing `pdftotext` all left a build
        green while nothing had been verified at all.
        """
        return self.ok and not self.unresolved and not self.unpinned and not self.skipped

    @property
    def ok(self) -> bool:
        """Only `not found` and a broken pin are failures. Unchecked and indeterminate are not.

        A run that measured nothing is not a pass, decided here so no caller can report
        success on an empty run.

        `indeterminate` is deliberately not a failure. Two readers disagreeing about a passage
        says the document is not determinate under the readers on this machine; treating that
        as a quotation failure would fail a manuscript for a property of the reader, which is
        the error the outcome exists to prevent. `--strict` still refuses it, through
        `unresolved`, because nothing was established either way.
        """
        if self.checked == 0:
            return False
        if self.broken_pins:
            return False
        return not any(r.state == "not found" for _, _, r in self.problems)


@functools.lru_cache(maxsize=256)
def fold(s: str) -> str:
    """Normalize the way a PDF extractor mangles text, without changing which words appear."""
    s = unicodedata.normalize("NFKC", s)
    # A PDF's embedded fonts can reach the extractor as raw glyph codes, arriving as control
    # characters mid-page. They become separators rather than being deleted: deleting them welds
    # the words on either side into one that appears in neither text, so a passage that is really
    # there stops resolving. `logit\x00difference` deleted is `logitdifference`, which no honest
    # quotation of it can match.
    s = re.sub(r"[\x00-\x08\x0b\x0e-\x1f\x7f]", " ", s)
    s = s.replace("’", "'").replace("‘", "'")
    s = s.replace("“", '"').replace("”", '"')
    s = s.replace("—", "-").replace("–", "-").replace("−", "-")
    s = re.sub(r"-\s*\n\s*", "", s)  # de-hyphenate across a line break
    return " ".join(s.split()).lower()


@functools.lru_cache(maxsize=256)
def skeleton(s: str) -> str:
    """`fold`, with whitespace removed. Nothing else.

    This is the fallback used when a verbatim match fails, so it is only ever applied to a
    passage that is provably not in the source as written. It must therefore absorb exactly
    what a PDF extractor mangles and nothing more.

    Extractors insert and drop spaces inside words -- `logit difference` comes out as
    `logitdifference` -- so whitespace is removed. They do not turn `=` into `<`, delete a
    minus sign, or drop a decimal point. An earlier version stripped every non-alphanumeric
    character, which made `p < 0.05` match a source reading `p = 0.05`, and `-0.42` match
    `0.42`: a reversed inequality and a flipped sign both reported as quoted verbatim, by the
    one check that exists to catch a misquotation.
    """
    return re.sub(r"\s+", "", fold(s))


@functools.lru_cache(maxsize=64)
def _read(pdf: pathlib.Path, page: int | None = None, reader: str | None = None):
    """The extraction itself, and what produced it. Cached: N quotes against one file is one read.

    Raises `SourceUnreadableError` when the toolchain is at fault -- no reader installed, a
    timeout, a permission error, a parser that could not open the file -- rather than
    returning empty text. An empty return means the document genuinely holds no extractable
    text on that page, which is a different fact and gets a different message.
    """
    if pdf.suffix.lower() in TEXT_SUFFIXES:
        try:
            return readers.Extraction(pdf.read_text(errors="replace"), PLAIN_TEXT, "")
        except OSError as e:
            raise SourceUnreadableError(pdf, f"could not be read: {e}") from e
    return readers.read(pdf, page, reader)


@functools.lru_cache(maxsize=64)
def extract(pdf: pathlib.Path, page: int | None = None) -> str:
    """Text of a source, and the one seam the default check reads through.

    Exported, and stood in for by callers outside this package: `repro`'s quote backend calls
    `check_one`, and its regression suite replaces this function with a two-argument stub so a
    test can fix what the document says on each page. The signature is that shape for that
    reason, and the reader-specific read lives in `reading_with` rather than in a third
    parameter no existing stub accepts.

    A reader chain that went around this function would leave those stubs measuring the
    stand-in bytes on disk, every reader would fail on them, and a wrong-page misquote would
    grade `unchecked` instead of `mismatch` -- which `publication` warns on rather than fails.
    """
    return _read(pdf, page).text


def reading(pdf: pathlib.Path, page: int | None = None):
    """Text and what produced it, with the text taken from `extract`.

    `extract` is called first, so a source nothing can read raises there and never reaches the
    provenance lookup. Reaching the fallback below therefore means one thing: `extract`
    returned text the reader chain did not produce, because a caller replaced it. That text is
    the caller's and the provenance is not this module's to invent, so the reader is named
    `substituted` rather than guessed at.
    """
    text = extract(pdf, page)
    try:
        got = _read(pdf, page)
    except SourceUnreadableError:
        return readers.Extraction(text, SUBSTITUTED, "")
    return dataclasses.replace(got, text=text)


def reading_with(pdf: pathlib.Path, page: int | None = None, *, reader: str):
    """One named reader's own reading of a source. Triangulation, and nothing else.

    This reads the file rather than going through `extract`, because the question it answers
    is what a particular reader makes of the bytes. A caller that replaced `extract` has said
    what the document contains, which is an answer to a different question, and routing it
    here would make three readers agree by construction.
    """
    return _read(pdf, page, reader)


@functools.lru_cache(maxsize=256)
def sha256(p: pathlib.Path) -> str:
    """Hash of a file on disk. The implementation is shared; this keeps the local name."""
    return sha256_of_file(p)


def clear_caches() -> None:
    """Forget every memoized read, fold and digest.

    One call rather than five, because a caller that clears four of them and forgets the
    fifth gets a stale answer that looks like a fresh one.
    """
    for cached in (_read, extract, fold, skeleton, sha256):
        cached.cache_clear()


def check_pin(artifact: pathlib.Path | None, expected: str | None) -> Pin:
    """Is the file on disk the file that was pinned?

    An unpinned source is reported as `unpinned`, never as `ok`: no hash was recorded, so
    nothing was checked, and saying otherwise would claim a guarantee the record does not make.
    """
    if artifact is None or not artifact.exists():
        return Pin("missing")
    if not (expected and expected.strip()):
        return Pin("unpinned")
    try:
        actual = sha256(artifact)
    except OSError:
        return Pin("missing")
    expected = expected.strip().lower()
    return Pin("ok" if actual == expected else "broken", expected, actual)


def check_one(
    quote: str,
    artifact: pathlib.Path | None,
    page: int | None = None,
    triangulate: bool = False,
) -> Result:
    """Does this passage appear in this source?

    One reader by default. `triangulate` asks every installed reader instead and reports
    `indeterminate` where they disagree, which costs one extraction per reader and is why it
    is not the default. Triangulation over a machine carrying one reader measures nothing and
    says so: `agreement` names the readers consulted, and one reader never establishes
    agreement.
    """
    warn: list[str] = []
    text = quote.strip()
    if len(text) < MIN_QUOTE_CHARS or text.endswith(
        (",", " and", " or", " but", " the", " a", " of", " for", " with")
    ):
        warn.append("short")

    if artifact is None or not artifact.exists():
        return Result("unchecked", "file not found", warn)

    if triangulate:
        return _triangulate(quote, artifact, page, warn)

    try:
        got = reading(artifact)
    except SourceUnreadableError as e:
        return Result("unchecked", e.detail, warn)
    result = _against(quote, got.text, artifact, page, warn, got.reader)
    result.reader = got.reader
    result.fallback = got.fallback
    result.fallback_reason = got.fallback_reason
    return result


def _against(
    quote: str,
    full: str,
    artifact: pathlib.Path,
    page: int | None,
    warn: list[str],
    reader: str,
) -> Result:
    """The verdict on one passage against one reader's text."""
    if not full.strip():
        return Result("unchecked", "no text extracted", list(warn))
    warn = list(warn)

    q, doc = fold(quote), fold(full)
    if not q:
        # `"" in doc` is True. A quotation that folds away entirely is not a quotation.
        return Result("not found", "the quotation is empty after normalization", warn)
    if q in doc:
        if _cuts_a_token(q, doc):
            warn.append("truncated")
        if page and not _on_page(artifact, q, page, reader):
            warn.append("page")
            found_at, capped = _find_page(artifact, q, reader=reader)
            detail = f"not on page {page}"
            if found_at is None and capped:
                detail += f"; searched the first {PAGE_SCAN_LIMIT} pages"
            return Result("found", detail, warn, found_at)
        return Result("found", "", warn)
    if skeleton(quote) and skeleton(quote) in skeleton(full):
        warn.append("normalized")
        return Result("found", "", warn)
    return Result(
        "not found",
        "read the source: a broken extraction reads the same as a passage that was never there",
        warn,
    )


def _triangulate(quote: str, artifact: pathlib.Path, page: int | None, warn: list[str]) -> Result:
    """Ask every installed reader, and report disagreement as disagreement.

    A reader that could not open the file contributes no verdict rather than a `not found`:
    "this reader failed" and "this reader read it and the passage is not there" are the two
    facts the outcome model exists to keep apart, and pooling them here would smuggle the
    first into the second one level down.
    """
    verdicts: dict[str, Result] = {}
    reasons: list[str] = []
    for name in readers.available():
        try:
            got = reading_with(artifact, reader=name)
        except SourceUnreadableError as e:
            reasons.append(f"{name}: {e.detail}")
            continue
        result = _against(quote, got.text, artifact, page, warn, name)
        if result.state == "unchecked":
            reasons.append(f"{name}: {result.detail}")
            continue
        verdicts[name] = result

    if not verdicts:
        return Result("unchecked", "; ".join(reasons) or readers.NO_READER, list(warn))

    agreement = {name: r.state for name, r in verdicts.items()}
    # The preferred reader that reached a verdict carries the warnings and the page finding:
    # they describe the text, and merging warnings from readings that disagree about the text
    # would attribute to one document what two extractions said.
    lead = next(name for name in readers.PREFERRED if name in verdicts)
    result = verdicts[lead]
    result.reader = lead
    result.fallback = lead != readers.PREFERRED[0]
    result.agreement = agreement

    if len(set(agreement.values())) > 1:
        said = ", ".join(f"{name} {state}" for name, state in agreement.items())
        return Result(
            "indeterminate",
            f"readers disagree ({said}); the document is not determinate under these readers",
            list(warn),
            reader=lead,
            fallback=result.fallback,
            agreement=agreement,
        )
    return result


def _on_page(
    artifact: pathlib.Path, folded_quote: str, page: int, reader: str | None = None
) -> bool:
    """Is the quote on the page the record claims? An unreadable page is not a match.

    Read with the same reader that found the passage. Asking a second reader which page it is
    on would report the disagreement between two extractions as a page number the record got
    wrong.
    """
    try:
        return folded_quote in fold(_page_text(artifact, page, reader))
    except SourceUnreadableError:
        return False


def _page_text(artifact: pathlib.Path, page: int, reader: str | None) -> str:
    """One page's text, from whatever produced the document's text.

    The default path goes back through `extract`, so a caller that replaced it fixes what each
    page says as well as what the document says -- which is what a per-page stub is for, and
    what the wrong-page check depends on. Triangulation names its reader instead: asking a
    second reader which page a passage is on would report a disagreement between two
    extractions as a page number the record got wrong.
    """
    if reader in (None, "", PLAIN_TEXT, SUBSTITUTED):
        return extract(artifact, page)
    return reading_with(artifact, page, reader=reader).text


def _cuts_a_token(q: str, doc: str) -> bool:
    """Does every occurrence of the quote stop in the middle of a word or a number?

    `"an accuracy of 0.9"` is genuinely present in a source reporting **0.95**, so it is `found`
    and the reader is told a true thing that misstates the result. The same cut turns
    `"We trained 50"` into `"We trained 5"`. This is not the `short` warning: length is not the
    problem, and a long quote ending one digit early is the more convincing version of it.

    Every occurrence must cut, because a quote that lands cleanly somewhere in the document is
    quoting that place.
    """
    if not q or not q[-1].isalnum():
        return False
    at, seen = doc.find(q), False
    while at >= 0:
        seen = True
        after = at + len(q)
        if after >= len(doc) or not doc[after].isalnum():
            return False
        at = doc.find(q, at + 1)
    return seen


def is_paginated(artifact: pathlib.Path) -> bool:
    """Whether asking which page a passage is on means anything for this source."""
    return artifact.suffix.lower() not in TEXT_SUFFIXES


def _find_page(
    artifact: pathlib.Path,
    folded_quote: str,
    limit: int = PAGE_SCAN_LIMIT,
    reader: str | None = None,
) -> tuple[int | None, bool]:
    """Which page holds the quote, and whether the scan hit its limit without deciding.

    The second element exists so a caller can tell "searched the whole document and it is not
    on any page" from "stopped searching at page N". Reporting both as `None` makes a cap look
    like a finding.

    A source with no pages answers `(None, False)` at once. Extraction ignores the page number
    there, so a scan would return the same text `limit` times and then claim it had searched
    that many pages of a document that has none.
    """
    if not is_paginated(artifact):
        return None, False
    for p in range(1, limit + 1):
        try:
            text = _page_text(artifact, p, reader)
        except SourceUnreadableError:
            return None, False
        if not text:
            return None, False  # ran off the end of the document
        if folded_quote in fold(text):
            return p, False
    return None, True  # still going when the limit ran out
