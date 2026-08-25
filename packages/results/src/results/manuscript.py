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

#: A number in prose. Two lookbehinds earn their place. Every comma must be followed by a
#: digit, so a value ending a clause is not captured with its punctuation: `UMR 7222, Paris`
#: yields `7222`. And a sign may not follow a hyphen or dash, so the LaTeX range
#: `(1.01--1.05)` yields two positive numbers rather than a positive and a negative one --
#: a confidence interval read as containing a negative bound is a different claim. The
#: condition sits on the sign rather than on the whole match, so the upper bound is still
#: captured -- dropping it would lose half of every interval the paper reports.
NUMBER = re.compile(
    r"(?<![\w.])"
    r"(?:(?<![-\u2010\u2011\u2012\u2013\u2014])[-+])?"
    r"\d(?:,?\d)*(?:\.\d+)?(?:[eE][-+]?\d+)?(?![\w])"
)

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

#: Constants belonging to a formula rather than to the work. A paper stating the normal
#: quantile owes no run for it.
CONSTANTS = frozenset(
    {"0", "1", "2", "3", "4", "5", "10", "100", "1000", "1.96", "2.5", "97.5",
     "0.05", "0.01", "0.001", "95", "99", "0.5", "0.95"}
)

#: A single digit is almost always structure -- an item count, a footnote marker, an
#: exponent. Two is the floor because a sample size is often two digits, and a denominator
#: is the class of number whose errors survive review.
MIN_DIGITS = 2


class UnreadableManuscript(Exception):
    """The manuscript could not be read. Never a statement about its contents."""


def constraining_digits(printed: str) -> int:
    """Digits that distinguish this value from another. Leading and trailing zeros do not."""
    body = printed.lstrip("-+").replace(",", "")
    if "." in body:
        return max(1, len(body.replace(".", "").lstrip("0")))
    return max(1, len(body.strip("0") or "0"))


def resolve_include(name: str, root: pathlib.Path,
                    here: pathlib.Path | None = None) -> pathlib.Path | None:
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
        for path in (candidate, candidate.with_suffix(".tex"),
                     candidate.parent / (candidate.name + ".tex")):
            if path.is_file():
                return path
    return None


def body(source: str, base: pathlib.Path | None = None,
         visited: set[pathlib.Path] | None = None,
         depth: int = 0,
         root: pathlib.Path | None = None) -> list[tuple[str, bool, str, int]]:
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
    source = COMMENT.sub("", source)
    if depth == 0:
        start = source.find(r"\begin{document}")
        if start != -1:
            source = source[start:]

    out: list[tuple[str, bool, str, int]] = []
    name = "" if base is None else base.name
    for lineno, line in enumerate(source.splitlines(), 1):
        include = INCLUDE.search(line)
        if include and base is not None and depth < MAX_INCLUDE_DEPTH:
            target = resolve_include(include.group(1).strip(), root, base.parent)
            if target is not None and target not in visited:
                visited.add(target)
                try:
                    out.extend(body(target.read_text(errors="replace"), target,
                                    visited, depth + 1, root))
                except OSError:
                    pass
                continue
        out.append((LAYOUT.sub(" ", line), bool(CITATION.search(line)), name, lineno))
    return out


def needs_no_claim(printed: str, line: str, at: int) -> str | None:
    """Why this value owes no run, or None if it owes one."""
    if printed in CONSTANTS:
        return "a constant of the formula"
    if constraining_digits(printed) < MIN_DIGITS:
        return "a single digit, almost always structure"
    if NAME_FRAGMENT.search(line[:at]):
        return "part of a hyphenated identifier"
    if any(m.start() <= at < m.end() for m in IDENTIFIER.finditer(line)):
        return "inside a DOI, URL or archive identifier"
    return None


def numbers(path: pathlib.Path) -> list[dict]:
    """Every number in the manuscript that could name a result, with where it sits."""
    if path.suffix.lower() not in SUFFIXES:
        raise UnreadableManuscript(
            f"{path.name}: not a manuscript source. Reads {', '.join(sorted(SUFFIXES))}; "
            f"a rendered PDF loses the structure that says what a number is."
        )
    try:
        source = path.read_text(errors="replace")
    except OSError as error:
        raise UnreadableManuscript(f"{path}: {error}") from error

    found = []
    for line, cited, source_name, lineno in body(source, path):
        for match in NUMBER.finditer(line):
            printed = match.group(0)
            found.append(
                {
                    "printed": printed,
                    "line": lineno,
                    "source": source_name,
                    "context": line.strip()[:160],
                    "exempt": needs_no_claim(printed, line, match.start()),
                    "attributed": cited,
                }
            )
    return found


def claimed_values(events: list[dict]) -> set[str]:
    """Every number named by the text of a recorded claim."""
    values: set[str] = set()
    for event in events:
        if event.get("event") == "claim":
            values.update(NUMBER.findall(event.get("claim", "")))
    return values
