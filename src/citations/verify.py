"""Does each quotation appear in the source it cites?

Builds a corpus of quotations checked against a pinned source, so later work quotes from the
corpus rather than from memory.

Two orthogonal things, kept apart.

The result -- did the passage appear? Exhaustive, three outcomes:

    found        the passage is in the source
    not found    the source was read and the passage is not in it
    unchecked    the source could not be read, so no measurement was made

The warnings -- is the quote well formed? A quote can be `found` and still carry one:

    short        the source may qualify it in the next clause
    normalized   matched only after ignoring punctuation and spacing
    page         found, but not on the page the record claims

`missing` means read the source. A mirror-reversed scan or a broken extraction produces the
same signal as a passage that was never there.
"""
from __future__ import annotations

import hashlib
import pathlib
import re
import functools
import subprocess
import unicodedata
from dataclasses import dataclass, field

# Long enough to carry its own qualifiers. "We trained 50" resolves against a sentence that
# continues "...and 5 refits each for 12 layered".
MIN_QUOTE_CHARS = 40


@dataclass
class Result:
    """`state` is the measurement; `warnings` are notes about the quote itself."""
    state: str                       # found | not found | unchecked
    detail: str = ""                 # why, when unchecked or not found
    warnings: list[str] = field(default_factory=list)
    page_found: int | None = None


@dataclass
class Report:
    checked: int = 0
    counts: dict[str, int] = field(default_factory=dict)
    problems: list[tuple[str, str, Result]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """Only `not found` is a failure. Unchecked is neither a pass nor a fail.

        A run that measured nothing is not a pass, decided here so no caller can report
        success on an empty run.
        """
        if self.checked == 0:
            return False
        return not any(r.state == "not found" for _, _, r in self.problems)


@functools.lru_cache(maxsize=256)
def fold(s: str) -> str:
    """Normalize the way a PDF extractor mangles text, without changing which words appear."""
    s = unicodedata.normalize("NFKC", s)
    # A PDF's embedded fonts can reach the extractor as raw glyph codes, arriving as control
    # characters mid-page. They become separators rather than being deleted: deleting them would
    # join two words that were never one word, which manufactures a match that is not there.
    s = re.sub(r"[\x00-\x08\x0b\x0e-\x1f\x7f]", " ", s)
    s = s.replace("’", "'").replace("‘", "'")
    s = s.replace("“", '"').replace("”", '"')
    s = s.replace("—", "-").replace("–", "-").replace("−", "-")
    s = re.sub(r"-\s*\n\s*", "", s)      # de-hyphenate across a line break
    return " ".join(s.split()).lower()


@functools.lru_cache(maxsize=256)
def skeleton(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", fold(s))


@functools.lru_cache(maxsize=64)
def extract(pdf: pathlib.Path, page: int | None = None) -> str:
    """Text of a source. Cached, so N quotes against one file is one extraction.

    A source is not always a PDF. Plain text and markdown are read directly; running a PDF
    extractor over them returns nothing, which reads as an unreadable source.
    """
    if pdf.suffix.lower() in (".txt", ".md", ".tei", ".xml", ".html"):
        try:
            text = pdf.read_text(errors="replace")
        except Exception:
            return ""
        return text if page is None else text      # no pagination in a text file
    cmd = ["pdftotext", "-layout"]
    if page:
        cmd += ["-f", str(page), "-l", str(page)]
    cmd += [str(pdf), "-"]
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=120).stdout
    except Exception:
        return ""


def sha256(p: pathlib.Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def check_one(quote: str, artifact: pathlib.Path | None, page: int | None = None) -> Result:
    warn: list[str] = []
    text = quote.strip()
    if len(text) < MIN_QUOTE_CHARS or text.endswith(
            (",", " and", " or", " but", " the", " a", " of", " for", " with")):
        warn.append("short")

    if artifact is None or not artifact.exists():
        return Result("unchecked", "file not found", warn)

    full = extract(artifact)
    if not full.strip():
        return Result("unchecked", "no text extracted", warn)

    q, doc = fold(quote), fold(full)
    if q in doc:
        if _cuts_a_token(q, doc):
            warn.append("truncated")
        if page and fold(extract(artifact, page)).find(q) < 0:
            warn.append("page")
            return Result("found", f"not on page {page}", warn, _find_page(artifact, q))
        return Result("found", "", warn)
    if skeleton(quote) and skeleton(quote) in skeleton(full):
        warn.append("normalized")
        return Result("found", "", warn)
    return Result("not found", "read the source: a broken extraction reads the same as a "
                               "passage that was never there", warn)


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


def _find_page(artifact: pathlib.Path, folded_quote: str, limit: int = 60) -> int | None:
    for p in range(1, limit + 1):
        text = extract(artifact, p)
        if not text:
            break
        if folded_quote in fold(text):
            return p
    return None
