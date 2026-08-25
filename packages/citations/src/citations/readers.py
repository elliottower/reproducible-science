"""Which program turned a PDF's bytes into text, and whether more than one of them agrees.

A pin proves the file has not changed. It says nothing about whether the reader turned those
bytes into the right text, and a mangled extraction produces a confident `not found` that
accuses a manuscript of misquoting a source it quotes correctly. So the reader is recorded on
every result: a decision that does not name what read the document cannot be compared with a
later one taken with something else.

Three readers, three separate pipelines:

    poppler      `pdftotext -layout`, run as a subprocess. A GPL binary, shelled out and
                 never linked, so nothing about this package's license follows from it.
    pdfplumber   pdfminer.six character extraction with its own layout layer. MIT.
    pypdf        its own content-stream parser. BSD.

`pdfminer.six` is not a fourth reader. pdfplumber is built on it and shares its character
extraction, so the two cannot disagree about which characters are on a page and counting both
would inflate agreement. PyMuPDF is not one either: it is AGPL, and linking it would relicense
this package.

Two uses, deliberately not the same thing:

    fallback        can anything read this document? Prefer poppler, fall back to a
                    pure-Python reader so `pip install citations` works with no system
                    binary. A fallback is recorded as a fallback.
    triangulation   do independent readers agree that the passage is there? Opt in, because
                    reading one document three times is three times the work, and a single
                    reader stays the default.

Availability is not validity. A fallback answers the first question and says nothing about
the second, and this module never lets one stand in for the other: `read` returns what one
reader produced and names it, and nothing here compares two readings. Agreement is decided a
level up, by a caller that asked each reader in turn and holds more than one answer.
"""

from __future__ import annotations

import dataclasses
import importlib.metadata
import pathlib
import shutil
import subprocess
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

#: How long the subprocess reader may take before it is reported as an infrastructure failure
#: rather than waited on. A document this slow is not one a person is watching.
#:
#: It bounds poppler only. The pure-Python readers run in this process, and a call already
#: inside a parser cannot be interrupted without abandoning the thread still executing it, so
#: no timeout is claimed for them rather than one being faked. That is a real cost of dropping
#: poppler: measured over 193 documents in `research/pdf-readers/`, pdfplumber's median read
#: is 18x poppler's and its worst is 71 seconds against poppler's 2.4.
SUBPROCESS_TIMEOUT_SECONDS = 120

#: Preference order. Poppler first: `-layout` reproduces column geometry, which is what keeps
#: a two-column paper's sentences from being interleaved, and the measurement in
#: `research/pdf-readers/` is what put it there rather than a preference.
PREFERRED = ("poppler", "pdfplumber", "pypdf")


@dataclasses.dataclass(frozen=True)
class Extraction:
    """Text, and what produced it.

    `fallback` is true when the preferred reader did not produce this text -- it was not
    installed, or it failed on this document -- and `fallback_reason` says which. A result
    taken without poppler is then distinguishable from one taken with it, and a substitution
    nobody recorded is a substitution nobody can account for later.
    """

    text: str
    reader: str
    version: str
    fallback: bool = False
    fallback_reason: str = ""


def _poppler_version() -> str:
    try:
        proc = subprocess.run(["pdftotext", "-v"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    banner = (proc.stderr or proc.stdout or "").strip().splitlines()
    return banner[0].replace("pdftotext version ", "") if banner else "unknown"


def _installed(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:  # pragma: no cover
        return "unknown"


def _read_poppler(pdf: pathlib.Path, page: int | None) -> str:
    cmd = ["pdftotext", "-layout"]
    if page:
        cmd += ["-f", str(page), "-l", str(page)]
    cmd += [str(pdf), "-"]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=SUBPROCESS_TIMEOUT_SECONDS
        )
    except FileNotFoundError as e:
        raise SourceUnreadableError(pdf, "pdftotext is not on PATH -- install poppler-utils") from e
    except subprocess.TimeoutExpired as e:
        raise SourceUnreadableError(
            pdf, f"pdftotext timed out after {SUBPROCESS_TIMEOUT_SECONDS}s"
        ) from e
    except OSError as e:
        raise SourceUnreadableError(pdf, f"pdftotext could not be run: {e}") from e
    if proc.returncode != 0:
        detail = (proc.stderr or "").strip().splitlines()
        raise SourceUnreadableError(
            pdf, f"pdftotext exited {proc.returncode}" + (f": {detail[-1]}" if detail else "")
        )
    return proc.stdout


def _read_pdfplumber(pdf: pathlib.Path, page: int | None) -> str:
    if pdfplumber is None:  # pragma: no cover - guarded by `available`
        raise SourceUnreadableError(pdf, "pdfplumber is not installed")
    try:
        with pdfplumber.open(pdf) as doc:
            if page:
                # Past the last page is not an error: `_find_page` walks until a page comes
                # back empty, and raising here would report the end of a document as a
                # source that could not be read.
                if page > len(doc.pages):
                    return ""
                return doc.pages[page - 1].extract_text() or ""
            return "\n".join(p.extract_text() or "" for p in doc.pages)
    except SourceUnreadableError:
        raise
    except Exception as e:
        raise SourceUnreadableError(pdf, f"pdfplumber could not read it: {e}") from e


def _read_pypdf(pdf: pathlib.Path, page: int | None) -> str:
    if pypdf is None:  # pragma: no cover - guarded by `available`
        raise SourceUnreadableError(pdf, "pypdf is not installed")
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


@dataclasses.dataclass(frozen=True)
class Reader:
    """One way of turning a PDF into text, and how to tell whether it is installed."""

    name: str
    read: Callable[[pathlib.Path, int | None], str]
    present: Callable[[], bool]
    describe: Callable[[], str]

    def available(self) -> bool:
        return bool(self.present())

    def version(self) -> str:
        return str(self.describe())


READERS: dict[str, Reader] = {
    "poppler": Reader(
        "poppler", _read_poppler, lambda: shutil.which("pdftotext") is not None, _poppler_version
    ),
    "pdfplumber": Reader(
        "pdfplumber",
        _read_pdfplumber,
        lambda: pdfplumber is not None,
        lambda: _installed("pdfplumber"),
    ),
    "pypdf": Reader("pypdf", _read_pypdf, lambda: pypdf is not None, lambda: _installed("pypdf")),
}

#: What to tell someone whose machine can read no PDF at all. Both routes are given: the
#: system package for layout fidelity, and the pure-Python one for a machine where installing
#: a system package is not on offer.
NO_READER = (
    "no PDF reader available -- install poppler-utils for layout fidelity, "
    'or `pip install "citations[pdf]"` for a pure-Python reader'
)


def available() -> list[str]:
    """The readers installed on this machine, in preference order."""
    return [name for name in PREFERRED if READERS[name].available()]


def read(pdf: pathlib.Path, page: int | None = None, reader: str | None = None) -> Extraction:
    """Text of one document, from the first reader in `PREFERRED` that produces any.

    Raises `SourceUnreadableError` when no reader is installed, and when every installed
    reader failed on this document -- never an empty string, which would be
    indistinguishable from a page that genuinely holds no text.

    The chain moves on both when a reader is not installed and when an installed one fails on
    this document. Both are recorded on the result as a fallback and its reason, because a
    reader that choked on a malformed file and a reader that was never there are different
    facts about a machine, and a passage checked against a substitute is not a passage checked
    against poppler either way.

    A named `reader` is used or the call fails; it never falls through, because a caller
    naming one reader is comparing it with another and a silent substitution would make two
    readers look like one.
    """
    if reader is not None:
        if reader not in READERS:
            raise SourceUnreadableError(pdf, f"no such reader: {reader}")
        if not READERS[reader].available():
            raise SourceUnreadableError(pdf, f"{reader} is not installed")
        return Extraction(READERS[reader].read(pdf, page), reader, READERS[reader].version())

    if not available():
        raise SourceUnreadableError(pdf, NO_READER)
    reasons: list[str] = []
    for name in PREFERRED:
        if not READERS[name].available():
            reasons.append(f"{name} is not installed")
            continue
        try:
            text = READERS[name].read(pdf, page)
        except SourceUnreadableError as e:
            reasons.append(e.detail)
            continue
        return Extraction(
            text,
            name,
            READERS[name].version(),
            fallback=name != PREFERRED[0],
            fallback_reason="; ".join(reasons),
        )
    raise SourceUnreadableError(pdf, "; ".join(reasons))


__all__ = [
    "NO_READER",
    "PREFERRED",
    "READERS",
    "Extraction",
    "Reader",
    "available",
    "read",
]
