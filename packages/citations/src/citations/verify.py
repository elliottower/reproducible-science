"""Does each quotation appear in the source it cites?

Builds a corpus of quotations checked against a pinned source, so later work quotes from the
corpus rather than from memory.

Three orthogonal things, kept apart.

The pin -- is this the document that was pinned? Checked once per artifact:

    ok           the file's sha256 matches the one recorded
    broken       the file has changed since the quotations were taken
    unpinned     no sha256 was recorded, so nothing can be checked
    missing      the file named by the record is not on disk

The result -- did the passage appear? Exhaustive, three outcomes:

    found        the passage is in the source
    not found    the source was read and the passage is not in it
    unchecked    the source could not be read, so no measurement was made

The warnings -- is the quote well formed? A quote can be `found` and still carry one:

    short        the source may qualify it in the next clause
    truncated    every occurrence stops mid-word or mid-number
    normalized   matched only after ignoring punctuation and spacing
    page         found, but not on the page the record claims

`unchecked` means read the source. A mirror-reversed scan or a broken extraction produces the
same signal as a passage that was never there -- so an extraction that failed for an
infrastructure reason says which one, rather than reporting the document as unreadable.
"""

from __future__ import annotations

import functools
import hashlib
import pathlib
import re
import subprocess
import unicodedata
from dataclasses import dataclass, field
from typing import Literal

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

State = Literal["found", "not found", "unchecked"]
PinState = Literal["ok", "broken", "unpinned", "missing"]


@dataclass
class Result:
    """`state` is the measurement; `warnings` are notes about the quote itself."""

    state: State
    detail: str = ""  # why, when unchecked or not found
    warnings: list[str] = field(default_factory=list)
    page_found: int | None = None


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

    @property
    def ok(self) -> bool:
        """Only `not found` and a broken pin are failures. Unchecked is neither.

        A run that measured nothing is not a pass, decided here so no caller can report
        success on an empty run.
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
    return re.sub(r"[^a-z0-9]", "", fold(s))


@functools.lru_cache(maxsize=64)
def extract(pdf: pathlib.Path, page: int | None = None) -> str:
    """Text of a source. Cached, so N quotes against one file is one extraction.

    Raises `SourceUnreadableError` when the extraction toolchain is at fault -- a missing
    `pdftotext`, a timeout, a permission error -- rather than returning empty text. An empty
    return means the document genuinely holds no extractable text on that page, which is a
    different fact and gets a different message.
    """
    if pdf.suffix.lower() in TEXT_SUFFIXES:
        try:
            return pdf.read_text(errors="replace")
        except OSError as e:
            raise SourceUnreadableError(pdf, f"could not be read: {e}") from e

    cmd = ["pdftotext", "-layout"]
    if page:
        cmd += ["-f", str(page), "-l", str(page)]
    cmd += [str(pdf), "-"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except FileNotFoundError as e:
        raise SourceUnreadableError(pdf, "pdftotext is not on PATH -- install poppler-utils") from e
    except subprocess.TimeoutExpired as e:
        raise SourceUnreadableError(pdf, "pdftotext timed out after 120s") from e
    except OSError as e:
        raise SourceUnreadableError(pdf, f"pdftotext could not be run: {e}") from e
    if proc.returncode != 0:
        detail = (proc.stderr or "").strip().splitlines()
        raise SourceUnreadableError(
            pdf, f"pdftotext exited {proc.returncode}" + (f": {detail[-1]}" if detail else "")
        )
    return proc.stdout


@functools.lru_cache(maxsize=256)
def sha256(p: pathlib.Path) -> str:
    """Hash of a file on disk, streamed so a large PDF is not held in memory."""
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


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


def check_one(quote: str, artifact: pathlib.Path | None, page: int | None = None) -> Result:
    warn: list[str] = []
    text = quote.strip()
    if len(text) < MIN_QUOTE_CHARS or text.endswith(
        (",", " and", " or", " but", " the", " a", " of", " for", " with")
    ):
        warn.append("short")

    if artifact is None or not artifact.exists():
        return Result("unchecked", "file not found", warn)

    try:
        full = extract(artifact)
    except SourceUnreadableError as e:
        return Result("unchecked", e.detail, warn)
    if not full.strip():
        return Result("unchecked", "no text extracted", warn)

    q, doc = fold(quote), fold(full)
    if q in doc:
        if _cuts_a_token(q, doc):
            warn.append("truncated")
        if page and not _on_page(artifact, q, page):
            warn.append("page")
            found_at, capped = _find_page(artifact, q)
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


def _on_page(artifact: pathlib.Path, folded_quote: str, page: int) -> bool:
    """Is the quote on the page the record claims? An unreadable page is not a match."""
    try:
        return folded_quote in fold(extract(artifact, page))
    except SourceUnreadableError:
        return False


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
    artifact: pathlib.Path, folded_quote: str, limit: int = PAGE_SCAN_LIMIT
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
            text = extract(artifact, p)
        except SourceUnreadableError:
            return None, False
        if not text:
            return None, False  # ran off the end of the document
        if folded_quote in fold(text):
            return p, False
    return None, True  # still going when the limit ran out
