"""Pure-Python PDF readers, for a machine with no poppler on it.

`pip install citations` cannot install a system package, and `pdftotext` is the one thing
`verify` needed that pip cannot supply. These two stand in where it is absent. Both are
optional: a missing one is reported, never imported at call time and never raised as an
`ImportError` out of a check.

    pdfplumber   pdfminer.six character extraction plus its own layout layer. MIT.
    pypdf        its own content-stream parser. BSD.

`pdfminer.six` is not a third reader. pdfplumber is built on it and shares its character
extraction, so the two cannot disagree about which characters are on a page, and counting both
would inflate agreement between readers that are one pipeline. PyMuPDF is not one either: it is
AGPL, and linking it would relicense this package.

Poppler is not here. It is a subprocess, and running one is `verify`'s own job -- the same
`_run` that executes a declared `extract_cmd` under an allowlist. Splitting it across two
modules would mean two ways to run a program and two places for a failure to be classified.

What this module does not do is decide anything. It reports what is installed and returns what
a named reader produced; which reader to prefer, when to fall back, and whether two of them
agree are all `verify`'s to settle.
"""

from __future__ import annotations

import dataclasses
import pathlib
from collections.abc import Callable

from citations.exceptions import SourceUnreadableError

try:  # optional: `pip install "citations[pdfplumber]"`
    import pdfplumber
except ImportError:  # pragma: no cover - exercised by the extras matrix, not the suite
    pdfplumber = None

try:  # optional: `pip install "citations[pypdf]"`
    import pypdf
except ImportError:  # pragma: no cover
    pypdf = None


@dataclasses.dataclass(frozen=True)
class Extraction:
    """Text, and what produced it.

    `fallback` is true when the preferred extractor did not produce this text -- it was not
    installed, or it failed on this document -- and `fallback_reason` says which. A result
    taken without poppler is then distinguishable from one taken with it, and a substitution
    nobody recorded is a substitution nobody can account for later.
    """

    text: str
    extractor: str
    fallback: bool = False
    fallback_reason: str = ""


@dataclasses.dataclass(frozen=True)
class Reader:
    """One pure-Python extractor, and how to tell whether it is installed."""

    name: str
    read: Callable[[pathlib.Path, int | None], str]
    present: Callable[[], bool]


def _read_pdfplumber(pdf: pathlib.Path, page: int | None) -> str:
    if pdfplumber is None:
        raise SourceUnreadableError(
            pdf, 'pdfplumber is not installed -- pip install "citations[pdf]"'
        )
    try:
        with pdfplumber.open(pdf) as doc:
            if page:
                # Past the last page is not an error: `_find_page` walks until a page comes
                # back empty, and raising here would report the end of a document as a source
                # that could not be read.
                if page > len(doc.pages):
                    return ""
                return doc.pages[page - 1].extract_text() or ""
            return "\n".join(p.extract_text() or "" for p in doc.pages)
    except SourceUnreadableError:
        raise
    except Exception as e:  # any failure to parse is the document's, not ours
        raise SourceUnreadableError(pdf, f"pdfplumber could not read it: {e}") from e


def _read_pypdf(pdf: pathlib.Path, page: int | None) -> str:
    if pypdf is None:
        raise SourceUnreadableError(pdf, 'pypdf is not installed -- pip install "citations[pdf]"')
    try:
        reader = pypdf.PdfReader(str(pdf))
        if page:
            if page > len(reader.pages):
                return ""
            return reader.pages[page - 1].extract_text() or ""
        return "\n".join(p.extract_text() or "" for p in reader.pages)
    except SourceUnreadableError:
        raise
    except Exception as e:
        raise SourceUnreadableError(pdf, f"pypdf could not read it: {e}") from e


READERS: dict[str, Reader] = {
    "pdfplumber": Reader("pdfplumber", _read_pdfplumber, lambda: pdfplumber is not None),
    "pypdf": Reader("pypdf", _read_pypdf, lambda: pypdf is not None),
}

#: Preference order among the pure-Python readers. Measured rather than assumed: over 1,593
#: passage checks in `research/pdf-readers/`, pypdf reproduced poppler's outcome on 92.7% of
#: them against pdfplumber's 90.2%, and read documents in a third of the time.
PREFERRED = ("pypdf", "pdfplumber")


def available() -> list[str]:
    """The pure-Python readers installed here, in preference order."""
    return [name for name in PREFERRED if READERS[name].present()]


__all__ = ["PREFERRED", "READERS", "Extraction", "Reader", "available"]
