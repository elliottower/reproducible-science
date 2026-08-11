"""Does each quotation appear in the source it cites?

The point is not to replace grep. It is to build a corpus of quotations that have been checked
against a pinned artifact, so later work quotes from the corpus instead of from memory. A model
writing from a verified library makes a different class of error than one writing from
recollection, and every fabricated quotation this project has produced came from the latter.

Five states, and the distinction between them is the whole design:

    ok           found verbatim in the pinned artifact
    loose        found on the alphanumeric skeleton -- reported, never failed, because a
                 skeleton match cannot tell `a - b` from `a + b`
    page-off     found, but not on the page the record claims
    no-source    the artifact is not on disk. Nothing was checked
    missing      the artifact was read and the text is not in it

`missing` means look at this. It never means fabricated: a mirror-reversed scan or a broken
extraction produces the same signal, and a tool that accuses an author of invention on that
evidence is worse than no tool.
"""
from __future__ import annotations

import hashlib
import pathlib
import re
import functools
import subprocess
import unicodedata
from dataclasses import dataclass, field

# A quotation must be long enough to carry its own qualifiers. "We trained 50" resolves
# cleanly against a source that continues "...each for 2, 4 and 8 layered variants and 5 for
# 12 layered", which is how a record came to claim fifty refits when the true number was five.
MIN_QUOTE_CHARS = 40


@dataclass
class Result:
    state: str
    detail: str = ""
    page_found: int | None = None


@dataclass
class Report:
    checked: int = 0
    counts: dict[str, int] = field(default_factory=dict)
    problems: list[tuple[str, str, Result]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """Only `missing` and `page-off` are failures. Unreachable is not the same as absent."""
        return not any(r.state in ("missing", "page-off") for _, _, r in self.problems)


@functools.lru_cache(maxsize=256)
def fold(s: str) -> str:
    """Normalize the way a PDF extractor mangles text, without changing which words appear."""
    s = unicodedata.normalize("NFKC", s)
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
    """Cached: 2,940 quotations across 16 artifacts is 16 extractions, not 2,940."""
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
    if len(quote.strip()) < MIN_QUOTE_CHARS:
        return Result("too-short",
                      f"{len(quote.strip())} chars, under the {MIN_QUOTE_CHARS} needed to "
                      f"carry its own qualifiers")
    if quote.strip().endswith((",", "and", "or", "but", "the", "a", "of", "for", "with")):
        return Result("too-short", "ends mid-clause; a truncated quote can verify a claim "
                                   "its source contradicts")
    if artifact is None or not artifact.exists():
        return Result("no-source", f"artifact not on disk: {artifact}")

    full = extract(artifact)
    if not full.strip():
        return Result("no-source", "extraction produced no text; is this a scanned image?")

    q, doc = fold(quote), fold(full)
    if q in doc:
        if page:
            if fold(extract(artifact, page)).find(q) < 0:
                found = _find_page(artifact, q)
                return Result("page-off", f"found, but not on page {page}", found)
        return Result("ok")
    if skeleton(quote) and skeleton(quote) in skeleton(full):
        return Result("loose", "matched on the alphanumeric skeleton only")
    return Result("missing", "not found in the artifact — look at this; a broken extraction "
                             "produces the same signal as an invented quotation")


def _find_page(artifact: pathlib.Path, folded_quote: str, limit: int = 60) -> int | None:
    for p in range(1, limit + 1):
        text = extract(artifact, p)
        if not text:
            break
        if folded_quote in fold(text):
            return p
    return None
