"""Find the numbers in a manuscript, and say which a recorded claim already names.

A claim recorded by `results claim` carries the sentence as the manuscript prints it, so the
numbers inside that sentence are bound: the ledger names a run, the run names sealed inputs,
and `results verify` checks the chain. A number appearing in no claim is unbound. Unbound is
not wrong; it is unchecked, and it is the state most numbers in most papers are in.

Reads the manuscript source rather than a rendered PDF. Extraction from a PDF loses the table
structure and the column alignment that say what a number is, and recovering a number's
meaning afterward is the problem this whole approach exists to avoid.
"""

from __future__ import annotations

import pathlib
import re
import unicodedata

#: A number in prose. Two lookbehinds earn their place. Every comma must be followed by a
#: digit, so a value ending a clause is not captured with its punctuation: `UMR 7222, Paris`
#: yields `7222`. And a sign may not follow a hyphen or dash, so the LaTeX range
#: `(1.01--1.05)` yields two positive numbers rather than a positive and a negative one --
#: a confidence interval read as containing a negative bound is a different claim. The
#: condition sits on the sign rather than on the whole match, so the upper bound is still
#: captured -- dropping it would lose half of every interval the paper reports.
#:
#: A decimal may open on its point, `.049`, as journals that drop the leading zero print it. A
#: sign may be the Unicode minus `\u2212`, which typeset text uses and which read as no sign at all
#: turned `\u22120.37` into `0.37`. Digits may be grouped in threes by a thin space, LaTeX's `\,` or
#: U+2009 and U+202F, so `12\,500` is one number and not `12` followed by `500`.
NUMBER = re.compile(
    r"(?<![\w.])"
    r"(?:(?<![-\u2010\u2011\u2012\u2013\u2014])[-+\u2212])?"
    r"(?:\d(?:,?\d)*(?:(?:\\,|[\u2009\u202f])\d{3}(?!\d))*(?:\.\d+)?|\.\d+)"
    r"(?:[eE][-+]?\d+)?(?![\w])"
)

#: A word, for reading the text on either side of a number. A LaTeX command is not one:
#: `\textbf` is markup, and the letters after a backslash are never matched.
WORD = re.compile(r"(?<![\\A-Za-z])[A-Za-z]+")

#: A number or a word, in the order the text gives them.
TOKEN = re.compile(f"(?P<number>{NUMBER.pattern})|(?P<word>{WORD.pattern})")


def readable(text: str) -> tuple[str, int]:
    """`text` without format characters and other characters that print nothing, and how many
    were taken out.

    A zero-width space, joiner or mark (Unicode category Cf) prints nothing, so `0.71\u200b57`
    reads as 0.7157 and was matched as the two numbers `0.71` and `57`. They are removed before
    any number is read, and the count is said, since a manuscript has no reason to hold one.
    """
    kept = [c for c in text if unicodedata.category(c) != "Cf" and not _blank(c)]
    return "".join(kept), len(text) - len(kept)


#: Characters that print nothing and are not format characters: the combining grapheme joiner,
#: the variation selectors, and the Hangul and Braille blanks.
BLANKS = frozenset("\u034f\u3164\u2800\u115f\u1160\uffa0")


def _blank(c: str) -> bool:
    point = ord(c)
    return c in BLANKS or 0xFE00 <= point <= 0xFE0F or 0xE0100 <= point <= 0xE01EF


#: What marks a number as a percentage when it follows it: `%`, LaTeX's `\%`, or the word.
PERCENT = re.compile(r"\s*(?:\\?%|percent\b|per\s+cent\b)", re.I)


def percent_after(text: str, end: int) -> bool:
    """Whether the number ending at `end` is printed as a percentage."""
    return bool(PERCENT.match(text, end))


def canonical(printed: str) -> str:
    """A printed number in one spelling, so two printings of one value compare equal.

    `\u22120.37` and `-0.37`, `.049` and `0.049`, `12\\,500`, `12,500` and `12500` each name one
    value. A leading `+` says nothing a bare number does not. Trailing zeros are kept: `0.50`
    is printed to two places and `0.5` to one, and that is a difference in what is claimed.
    """
    text = printed.replace("\u2212", "-").lstrip("+")
    for separator in ("\\,", "\u2009", "\u202f", ","):
        text = text.replace(separator, "")
    sign, digits = ("-", text[1:]) if text.startswith("-") else ("", text)
    if digits.startswith("."):
        digits = "0" + digits
    return sign + digits


#: Manuscript sources this can read.
SUFFIXES = {".tex", ".md", ".rmd", ".qmd", ".typ", ".org", ".rst", ".txt"}

#: Markup whose numbers describe the page rather than the work: lengths, float placement,
#: graphics options, cross-reference keys. Their arguments assert nothing.
LAYOUT = re.compile(
    r"\\(?:vspace|hspace|vskip|hskip|setlength|addtolength|scalebox|resizebox|includegraphics"
    r"|arraystretch|tabcolsep|columnsep|baselinestretch|multirow|multicolumn|cmidrule|cline"
    r"|rule|label|ref|eqref|cite[a-z]*|bibitem|newcommand|renewcommand|documentclass"
    r"|usepackage|geometry|definecolor|rowcolor)"
    r"\s*(?:\[[^\]]*\])?\s*(?:\{[^{}]*\})*",
    re.I,
)

COMMENT = re.compile(r"(?<!\\)%.*$", re.M)

#: Sources in which `%` opens a comment.
LATEX = {".tex", ".ltx", ".sty", ".cls"}

#: A macro taking no argument whose body is plain text: `\newcommand{\icc}{0.42}`,
#: `\newcommand\icc{0.42}`, `\def\icc{0.42}`. A paper that sets its numbers this way prints
#: each one where the macro is used, and reading only the definition counted none of them.
#: A macro with arguments is not expanded: its body is a template, not a value.
DEFINITION = re.compile(
    r"\\(?:(?:re|provide)?newcommand\*?\s*\{?\s*\\(?P<a>[A-Za-z]+)\s*\}?|def\s*\\(?P<b>[A-Za-z]+))"
    r"\s*\{(?P<body>[^{}#]*(?:\{[^{}#]*\}[^{}#]*)*)\}"
)

#: How many times a line is expanded, so a macro defined through another one is read through.
MAX_EXPANSIONS = 4

#: A section pulled in from another file. Most real submissions are a short shell of these
#: with the body elsewhere: of twenty arXiv papers read as single files, seven reported no
#: numbers at all and one reported a single number, because the shell was all that was read.
INCLUDE = re.compile(r"\\(?:input|include|subfile)\s*\{([^}]+)\}")

#: How deep to follow includes. Sections including subsections is ordinary; deeper than this
#: is a cycle the visited set already guards against, or a document nobody wrote by hand.
MAX_INCLUDE_DEPTH = 8

#: A citation on the line. A number beside one is usually attributable to the work cited
#: rather than produced here -- an odds ratio quoted from a meta-analysis, an effect size
#: taken from the study under review. Such a value cannot be bound to a run of yours, and
#: counting it as unbound reports someone else's number as your omission.
#:
#: Reported as its own group rather than discarded, because the signal is good and not
#: exact: a sentence can cite a source and still state a count of your own.
CITATION = re.compile(r"\\(?:cite[a-z]*|autocite|footcite|parencite)\s*[\[\{]", re.I)

#: A digit joined to a word by a hyphen names something rather than measuring it: `CIFAR-10`,
#: `ResNet-18`, `top-1`. The digits belong to the name.
NAME_FRAGMENT = re.compile(r"[A-Za-z][‐‑‒–-]$")

#: Identifiers, whose digits are an address rather than a quantity.
IDENTIFIER = re.compile(
    r"(?:https?://\S+|www\.\S+|\b10\.\d{4,}/\S+|\bdoi:\s*\S+|\barXiv:\s*\S+"
    r"|\b\d{4}\.\d{4,5}(?:v\d+)?\b|\bswh:1:[a-z]{3}:[0-9a-f]+)",
    re.I,
)

#: Constants belonging to a formula rather than to the work, where the text around them is a
#: formula's: `p < 0.05`, `95% CI`, `per 1000`. Exempt only there. Exempt anywhere, `0.95`
#: and `100` were never owed a claim, and `we enrolled 100 participants` or `an AUC of 0.95`
#: is a result like any other.
CONSTANTS = frozenset(
    {
        "0",
        "1",
        "2",
        "3",
        "4",
        "5",
        "10",
        "100",
        "1000",
        "1.96",
        "2.5",
        "97.5",
        "0.05",
        "0.01",
        "0.001",
        "95",
        "99",
        "0.5",
        "0.95",
    }
)

#: The normal quantile, which nothing but a formula prints. Exempt wherever it appears.
QUANTILES = frozenset({"1.96"})

#: Text before a constant that makes it a threshold or a scale: a comparison, a significance
#: level, a multiplier. `=` alone is not enough, since `n = 100` reports a count.
FORMULA_BEFORE = re.compile(
    r"(?:[<>≤≥]|\\(?:le|leq|ge|geq|lt|gt)(?![A-Za-z])|(?:\\alpha|α|\balpha)\s*="
    r"|\\times|×|\bper|\blevel(?:\s+of)?|\bthreshold(?:\s+of)?|\bsignificance(?:\s+of)?)"
    r"[\s$~{]*$",
    re.I,
)

#: Text after a constant that makes it the coverage of an interval or a quantile: `95% CI`,
#: `95\% confidence`, `the 0.95 quantile`.
FORMULA_AFTER = re.compile(
    r"^[\s$}]*(?:\\?%|percent|per\s*cent)?[\s~-]*"
    r"(?:CI|CrI|confidence|credible|prediction|interval|quantile|percentile|level)",
    re.I,
)

#: The number of a table, figure, section or equation names a place in the paper.
PLACE = re.compile(
    r"(?:\btables?|\bfigs?\.?|\bfigures?|\bsecs?\.?|\bsections?|\bappendix|\beqs?\.?"
    r"|\bequations?|\bchapters?|§)[\s~]*\(?$",
    re.I,
)

#: A digit joined to a following word by a hyphen names a design, `10-fold`, `3-layer`.
NAME_AFTER = re.compile(r"^[‐‑‒–-][A-Za-z]")

#: A single digit is almost always structure -- an item count, a footnote marker, an
#: exponent. Two is the floor because a sample size is often two digits, and a denominator
#: is the class of number whose errors survive review. The floor is on whole numbers only and
#: counts every digit: `100` is three digits and `0.5` is a value, not a footnote marker.
MIN_DIGITS = 2


class UnreadableManuscript(Exception):
    """The manuscript could not be read. Never a statement about its contents."""


def constraining_digits(printed: str) -> int:
    """Digits that distinguish this value from another. Leading and trailing zeros do not."""
    body = printed.lstrip("-+").replace(",", "")
    if "." in body:
        return max(1, len(body.replace(".", "").lstrip("0")))
    return max(1, len(body.strip("0") or "0"))


def resolve_include(
    name: str, root: pathlib.Path, here: pathlib.Path | None = None
) -> pathlib.Path | None:
    """The file an `\\input` names, or None where it is not on disk.

    LaTeX resolves an include against the directory of the *main* document, not against the
    file doing the including. A section at `text/appendix.tex` writing
    `\\input{text/appendix/dataset}` means `text/appendix/dataset.tex` from the root, and
    resolving it beside the including file looks for `text/text/appendix/dataset.tex` and
    finds nothing. That mistake cost one paper its entire appendix.

    The including file's own directory is tried second, since a submission assembled from a
    subdirectory sometimes relies on it. The extension may be omitted, so both forms are
    tried before giving up: a missing include is not an error, because a submission may name
    a generated file it never deposited.
    """
    for base in (root, here):
        if base is None:
            continue
        candidate = (base / name).resolve()
        for path in (
            candidate,
            candidate.with_suffix(".tex"),
            candidate.parent / (candidate.name + ".tex"),
        ):
            if path.is_file():
                return path
    return None


def definitions(
    source: str,
    base: pathlib.Path | None = None,
    root: pathlib.Path | None = None,
    visited: set[pathlib.Path] | None = None,
    depth: int = 0,
) -> dict[str, str]:
    """Each simple macro the manuscript defines, by name, with its body.

    Read from the whole source, preamble included, and from every file it pulls in there or
    later: a paper's numbers are usually defined in a `macros.tex` the preamble inputs.
    """
    visited = visited if visited is not None else set()
    if root is None and base is not None:
        root = base.parent
    source = COMMENT.sub("", source)
    found: dict[str, str] = {}
    for match in DEFINITION.finditer(source):
        found[match["a"] or match["b"]] = match["body"]
    if base is None or depth >= MAX_INCLUDE_DEPTH:
        return found
    for include in INCLUDE.finditer(source):
        target = resolve_include(include.group(1).strip(), root or base.parent, base.parent)
        if target is None or target in visited:
            continue
        visited.add(target)
        try:
            text = target.read_text(errors="replace")
        except OSError:
            continue
        found = definitions(text, target, root, visited, depth + 1) | found
    return found


def uses(macros: dict[str, str]) -> re.Pattern[str] | None:
    """What a use of any of these macros looks like: `\\icc`, or `\\icc{}`."""
    if not macros:
        return None
    names = sorted(macros, key=len, reverse=True)
    return re.compile(r"\\(" + "|".join(map(re.escape, names)) + r")(?![A-Za-z])(?:\{\})?")


def expand(line: str, macros: dict[str, str], pattern: re.Pattern[str] | None) -> str:
    """The line with each simple macro replaced by its body, and its definitions removed."""
    line = DEFINITION.sub(" ", line)
    if pattern is None or "\\" not in line:
        return line
    for _ in range(MAX_EXPANSIONS):
        line, count = pattern.subn(lambda m: macros[m.group(1)], line)
        if not count:
            break
    return line


def body(
    source: str,
    base: pathlib.Path | None = None,
    visited: set[pathlib.Path] | None = None,
    depth: int = 0,
    root: pathlib.Path | None = None,
    macros: dict[str, str] | None = None,
) -> list[tuple[str, bool, str, int]]:
    """Every line of the manuscript and the files it pulls in.

    Each entry is the line with layout stripped, whether it carries a citation, which file it
    came from, and its line number in that file. Layout is stripped per line so a line number
    always indexes the same line of its own source, and citations are noted before they are
    stripped, since a `\\cite` is what marks the numbers beside it as somebody else's.

    Includes are followed because most submissions are a shell: a preamble, a title, and a
    list of `\\input` calls. Reading only the shell reports a paper as having no numbers.
    """
    visited = visited if visited is not None else set()
    if root is None and base is not None:
        root = base.parent
    # `%` opens a comment in LaTeX alone: in Markdown it is a percent sign, and stripping from
    # it to the end of the line dropped every number after `50%`.
    if base is None or base.suffix.lower() in LATEX:
        source = COMMENT.sub("", source)
    if macros is None:
        # Read before the preamble is cut, since that is where a paper defines its macros.
        macros = definitions(source, base, root)
    pattern = uses(macros)
    if depth == 0:
        start = source.find(r"\begin{document}")
        if start != -1:
            source = source[start:]

    out: list[tuple[str, bool, str, int]] = []
    name = "" if base is None else base.name
    for lineno, line in enumerate(source.splitlines(), 1):
        include = INCLUDE.search(line)
        if include and base is not None and depth < MAX_INCLUDE_DEPTH:
            # `root` is set from `base` on the first call, so it is never None here;
            # naming the fallback keeps that true for a reader and for the checker.
            target = resolve_include(include.group(1).strip(), root or base.parent, base.parent)
            if target is not None and target not in visited:
                visited.add(target)
                try:
                    text = target.read_text(errors="replace")
                except OSError:
                    continue
                out.extend(body(text, target, visited, depth + 1, root, macros))
                continue
        line = expand(line, macros, pattern)
        out.append((LAYOUT.sub(" ", line), bool(CITATION.search(line)), name, lineno))
    return out


def formula(line: str, at: int, end: int) -> bool:
    """Whether the text around `line[at:end]` makes it a threshold, a level or a scale."""
    return bool(FORMULA_BEFORE.search(line[:at]) or FORMULA_AFTER.search(line[end:]))


def needs_no_claim(printed: str, line: str, at: int) -> str | None:
    """Why this value owes no run, or None if it owes one."""
    value = canonical(printed)
    end = at + len(printed)
    if value in QUANTILES or (value in CONSTANTS and formula(line, at, end)):
        return "a constant of the formula"
    whole = value.lstrip("-")
    if "." not in whole and "e" not in whole.lower() and len(whole.lstrip("0")) < MIN_DIGITS:
        return "a single digit, almost always structure"
    if NAME_FRAGMENT.search(line[:at]) or NAME_AFTER.search(line[end:]):
        return "part of a hyphenated identifier"
    if PLACE.search(line[:at]):
        return "the number of a table, figure or section"
    if any(m.start() <= at < m.end() for m in IDENTIFIER.finditer(line)):
        return "inside a DOI, URL or archive identifier"
    return None


def tokens(text: str) -> list[str]:
    """The words and numbers of a text, in order: each word lowercased, each number in its
    canonical spelling. What a number is read beside, to say which claim states it."""
    return [
        canonical(m["number"]) if m["number"] is not None else m["word"].lower()
        for m in TOKEN.finditer(readable(text)[0])
    ]


def numbers(path: pathlib.Path) -> list[dict]:
    """Every number in the manuscript that could name a result, with where it sits.

    Each record carries `value`, the number in its canonical spelling, and `at`, its position
    in the words and numbers of the whole manuscript, which `words` returns alongside: the
    text a claim has to share with the manuscript for its sentence to be the one printed here.
    """
    return read(path)[0]


def read(path: pathlib.Path) -> tuple[list[dict], list[str]]:
    """The numbers, and the words and numbers of the whole manuscript in order."""
    if path.suffix.lower() not in SUFFIXES:
        raise UnreadableManuscript(
            f"{path.name}: not a manuscript source. Reads {', '.join(sorted(SUFFIXES))}; "
            f"a rendered PDF loses the structure that says what a number is."
        )
    try:
        source = path.read_text(errors="replace")
    except OSError as error:
        raise UnreadableManuscript(f"{path}: {error}") from error
    source, _ = readable(source)

    found: list[dict] = []
    stream: list[str] = []
    for line, cited, source_name, lineno in body(source, path):
        for match in TOKEN.finditer(line):
            if match["number"] is None:
                stream.append(match["word"].lower())
                continue
            printed = match["number"]
            found.append(
                {
                    "printed": printed,
                    "value": canonical(printed),
                    "at": len(stream),
                    "line": lineno,
                    "source": source_name,
                    "context": line.strip()[:160],
                    "exempt": needs_no_claim(printed, line, match.start()),
                    "attributed": cited,
                    "percent": percent_after(line, match.end()),
                }
            )
            stream.append(canonical(printed))
    return found, stream


def claimed_values(events: list[dict]) -> set[str]:
    """Every number named by the text of a recorded claim, in its canonical spelling."""
    values: set[str] = set()
    for event in events:
        if event.get("event") == "claim":
            text = readable(event.get("claim", ""))[0]
            values.update(canonical(n) for n in NUMBER.findall(text))
    return values


#: Words and numbers on each side of a number that a claim has to share with the manuscript.
WINDOW = 2


def _side(stream: list[str], at: int, step: int) -> tuple[str | None, ...]:
    """The `WINDOW` tokens before `at` (step -1) or after it (step 1), None past either end."""
    picks = range(at - WINDOW, at) if step < 0 else range(at + 1, at + 1 + WINDOW)
    return tuple(stream[i] if 0 <= i < len(stream) else None for i in picks)


def stated_by(stream: list[str], at: int, claim: list[str]) -> bool:
    """Whether the claim prints the number at `stream[at]` with the words the manuscript
    prints beside it: the same tokens immediately before it, or immediately after it, and a
    word among them. A claim that is a list of numbers shares no words with any sentence, so
    it states none of them, whatever values it lists."""
    value = stream[at]
    before, after = _side(stream, at, -1), _side(stream, at, 1)
    for j, token in enumerate(claim):
        if token != value:
            continue
        for mine, theirs in ((before, _side(claim, j, -1)), (after, _side(claim, j, 1))):
            if mine == theirs and any(t is not None and t[0].isalpha() for t in mine):
                return True
    return False
