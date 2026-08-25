"""Enumerate every number in a paper, with location, and classify what kind of thing it is.

Stage one of a provenance scan. The question is not "is this a finding" -- that judgment is
what made human and model raters disagree, and it is not needed. The question is only
whether a number is a claim about the work (so an artifact could in principle hold it) or
bibliographic furniture (so nothing could).

That line is close to mechanical, which is the point: raters agree on it, and what survives
goes to the verifier rather than to a coder.

Output is one record per number:

    printed   verbatim string as it appears
    line      1-indexed line in the extracted text
    context   the surrounding line, for a human or model to read
    kind      claim | bibliographic | bounded | extraction_failed
    reason    why it was classified that way

`bounded` and `extraction_failed` are separated from both other categories rather than
folded into either. A bound ("at most 10 minutes") states no single quantity, so no
comparison against a stored value can succeed or fail. A mangled extraction means the paper
was not read at that position. Coding either as "not traceable" would record a limit of the
instrument as a property of the paper.
"""

from __future__ import annotations

import json
import pathlib
import re
import sys

#: A numeric token: optional sign, digits with optional thousands separators, optional
#: decimal, optional exponent. Percent and unit suffixes are captured separately so the
#: printed string stays verbatim.
NUMBER = re.compile(r"(?<![\w.])[-+]?\d[\d,]*(?:\.\d+)?(?:[eE][-+]?\d+)?(?![\w])")

#: Document furniture: numbering that organises the paper rather than describing the work.
SECTION_HEAD = re.compile(r"^\s*\d+(?:\.\d+)*\s+[A-Z]")
AFFILIATION = re.compile(r"^\s*\d\s+[A-Z][a-z]+\s+(?:University|Institute|College|Lab)", re.I)

#: The label printed to the right of a display equation, so it can be referred to later.
#: The label is furniture; what the equation asserts is not.
EQUATION_LABEL = re.compile(r"\((\d+)\)\s*$")

#: Bibliographic furniture. Nothing in an artifact corresponds to these.
CITATION = re.compile(r"\[\d+(?:\s*,\s*\d+)*\]")
YEAR = re.compile(r"^(1[89]|20)\d\d$")
#: An identifier and its payload, matched as a span rather than as a property of the line.
#: A sentence may cite a dataset URL and then state a measurement; scoping the rule to the
#: line would bury the measurement inside the citation.
IDENTIFIER = re.compile(
    r"(?:https?://\S+|www\.\S+|\b10\.\d{4,}/\S+|\bdoi:\S+|\barXiv:\S+"
    r"|\bswh:1:[a-z]{3}:[0-9a-f]+(?:;\S*)?|\bISBN[\s-]*[\d-]+|\bISSN[\s-]*[\d-]+)", re.I)
DATE_LINE = re.compile(
    r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\b")
PAGE_RANGE = re.compile(r"\bpp?\.\s*\d+")

#: A value bound to a named symbol is a parameter of the work -- a hyperparameter, a
#: dimension, a threshold. Traceable to a config or a call site, so it is kept and labelled
#: rather than discarded: a paper stating `d = 128` where the code sets 256 is exactly the
#: mismatch an audit should surface.
PARAMETER = re.compile(r"\b[A-Za-z][A-Za-z_]{0,12}\s*(?:=|∈|:)\s*$")

#: Qualifiers that turn a stated number into a bound or approximation, so it cannot be
#: compared against a stored value at printed precision.
BOUNDED = re.compile(
    r"(?:\bat\s+most\b|\bat\s+least\b|\bup\s+to\b|\bno\s+more\s+than\b"
    r"|\bapproximately\b|\bapprox\.?\b|\babout\b|\broughly\b|\bnearly\b|\baround\b"
    r"|\bover\b|\bunder\b|\bless\s+than\b|\bmore\s+than\b|[<>≤≥~≈±])",
    re.I,
)

#: Symbols that survive extraction but whose layout does not: an operator that took an
#: argument above, below or under a radical loses that argument when the page is flattened
#: to a single baseline.
MATH_SYMBOL = re.compile(r"[√∫∑∏⟨⟩∂∇⊕⊗◦̸⃗∈∀∃⊂⊆≠≡µξαβγδθλσΣΩ]")

#: A superscript or subscript pushed onto the baseline. Requires the digit to be flush
#: against a closing bracket with no space -- an earlier version tested only for a preceding
#: `)`, which matched the axis label `Accuracy (%)     40` and the sub-figure marker
#: `(a) 3-grouped graph`.
FLUSH_EXPONENT = re.compile(r"[)\]}◦^]$")

#: A pointer to an equation, figure or table rather than a quantity: "according to (3)",
#: "in equation (2)", "(See (2))".
#: Cue words are restricted to those that name a document object. An earlier version
#: included the bare prepositions, and "resulting in 360 reproduced values" was read as a
#: cross-reference to equation 360.
CROSS_REF = re.compile(
    r"(?:see|according\s+to|eq\.?|equation|figure|fig\.?|table|section|appendix)\s*\(?$",
    re.I)

#: A digit joined to a word by a hyphen or dash names something rather than measuring it:
#: `CIFAR-10`, `ResNet-18`, `DenseNet-121`, `VGG-16`, `top-1`. The identifier is the whole
#: token, and its digits are as much a part of the name as its letters. Left in, they are
#: the single largest false-positive class in this corpus -- 126 of 1054 tokens in one
#: article -- and they confirm against artifacts at near-certainty, because a repository
#: training on CIFAR-10 with a ResNet-18 writes those digits everywhere.
NAME_FRAGMENT = re.compile(r"[A-Za-z][\u2010\u2011\u2012\u2013-]$")

#: A number closed up against the word it numbers, marking an item in a running list:
#: "Influence maximization(1), Node classification(2)".
ENUM_MARKER = re.compile(r"[a-z]\($")

#: A line carrying at least this many numbers is not prose. What it is instead -- a table
#: row, a figure's axis ticks, a running footer -- is decided by the document pre-pass
#: below, because the answer is not visible in the line alone.
DENSE_LINE = 4

#: A line that recurs once its digits are blanked, this many times or more, is printed by
#: the page template rather than written: a running header or footer.
HEADER_REPEATS = 3

#: Alphabetic characters a repeating line must carry before it counts as a header. Without
#: it, blanking the digits collapses every numeric row of a table onto one form, the form
#: repeats once per row, and the table is deleted as page furniture.
HEADER_MIN_LETTERS = 12

#: `pdftotext -layout` preserves column alignment, so numbers in a table land at stable
#: character offsets down the block while a figure's flattened tick labels do not. Offsets
#: within this many characters are treated as the same column.
COLUMN_TOLERANCE = 3

#: A run of lines is read as a table when at least this many of them share at least two
#: aligned numeric columns.
TABLE_MIN_ROWS = 3

#: The share of a block's rows a column must appear in before it counts as a column.
COLUMN_SUPPORT = 0.6

#: A caption line. The appendix numbering `Table A9` is why the number is optional after a
#: letter: requiring digits immediately after the word made every appendix table invisible.
CAPTION = re.compile(r"^\s*(Table|Figure|Fig\.)\s*[A-Z]?\d+", re.I)

#: How far from a block to look for the caption that names it. Captions sit above or below
#: the body depending on the class file, so the search runs in both directions.
CAPTION_WINDOW = 20

#: Words of three or more letters per number, above which a block is prose. Consecutive
#: sentences naming `VGG-16`, `PreAct-18` and `DenseNet-121` align as readily as columns do;
#: they run 2.0 to 3.0 by this measure and a table row runs 0.0.
WORD_NUMBER_RATIO = 1.5

WORD = re.compile(r"[A-Za-z]{3,}")


def captions(lines: list[str]) -> list[tuple[int, str]]:
    """0-indexed caption lines, each tagged `table` or `figure`."""
    found = []
    for i, line in enumerate(lines):
        match = CAPTION.match(line)
        if match:
            found.append((i, "figure" if match.group(1).lower().startswith("fig") else "table"))
    return found


def block_caption(marks: list[tuple[int, str]], lo: int, hi: int) -> str | None:
    """What the document calls the block at lines `lo`-`hi`.

    Vertical alignment alone cannot separate a table from a multi-panel figure, because tick
    labels on stacked panels align as readily as columns do. The caption is the label the
    document itself supplies.

    A table caption in the window wins over a figure caption, rather than the nearer of the
    two winning. Extraction order does not preserve which caption a block sits under -- one
    table in this corpus has its own caption eighteen lines above and an unrelated figure
    caption five lines below -- and the two errors do not cost the same. Reading a table as
    a figure discards the most directly checkable numbers the paper prints; reading tick
    labels as cells sends a few values to a verifier, which reports them unmatched.
    """
    kinds = {kind for i, kind in marks if lo - CAPTION_WINDOW <= i <= hi + CAPTION_WINDOW}
    if "table" in kinds:
        return "table"
    if "figure" in kinds:
        return "figure"
    return None


def running_headers(lines: list[str]) -> set[str]:
    """Normalised forms of lines the page template prints on every page.

    Blanking the digits collapses `... Kim et al. 2021    2` and `... Kim et al. 2021    6`
    onto one form, so the page number does not hide the repetition.
    """
    counts: dict[str, int] = {}
    for line in lines:
        form = header_form(line)
        if form and sum(c.isalpha() for c in form) >= HEADER_MIN_LETTERS:
            counts[form] = counts.get(form, 0) + 1
    return {form for form, n in counts.items() if n >= HEADER_REPEATS}


def header_form(line: str) -> str:
    """A line reduced to what the page template contributes.

    Runs of whitespace collapse as well as digits, because a footer sets its page number in
    a fixed column: the number changes width from page 9 to page 10, the padding before it
    changes to compensate, and the raw forms then differ on every page.
    """
    return re.sub(r"\s+", " ", re.sub(r"\d+", "#", line.strip()))


def aligned_blocks(
        lines: list[str]) -> tuple[set[int], set[int], dict[int, list[tuple[int, bool]]]]:
    """Lines belonging to a table, and lines belonging to a figure, by alignment and caption.

    A run is consecutive non-empty lines each carrying two or more numbers. Within a run,
    every numeric token contributes its start offset; offsets recurring down most of the run
    are columns, and two columns over three rows makes the run a candidate. The caption then
    decides which kind it is: a table's cells are the most directly checkable numbers a
    paper prints, and a multi-panel figure's tick labels are among the least.
    """
    marks = captions(lines)
    tables: set[int] = set()
    figures: set[int] = set()
    quoted: dict[int, list[tuple[int, bool]]] = {}
    run: list[int] = []

    def close(run: list[int]) -> None:
        if len(run) < TABLE_MIN_ROWS:
            return
        columns: dict[int, set[int]] = {}
        for row in run:
            for match in NUMBER.finditer(lines[row]):
                position = match.start()
                key = next((k for k in columns if abs(k - position) <= COLUMN_TOLERANCE),
                           position)
                columns.setdefault(key, set()).add(row)
        aligned = [rows for rows in columns.values()
                   if len(rows) >= max(2, COLUMN_SUPPORT * len(run))]
        if len(aligned) < 2:
            return
        words = sum(len(WORD.findall(lines[row])) for row in run)
        numbers = sum(len(NUMBER.findall(lines[row])) for row in run)
        if words > WORD_NUMBER_RATIO * numbers:
            return
        if block_caption(marks, run[0], run[-1]) == "figure":
            figures.update(run)
        else:
            tables.update(run)
            headers = column_headers(lines, run)
            if headers:
                for row in run:
                    quoted[row] = headers

    for i, line in enumerate(lines):
        if line.strip() and len(NUMBER.findall(line)) >= 2:
            run.append(i)
        else:
            close(run)
            run = []
    close(run)
    return tables, figures, quoted


#: Column headers naming the work being reproduced rather than this one. A value under one
#: of these is quoted from another paper: it is checkable against that paper and not against
#: these authors' artifact, and counting it in the denominator understates what the artifact
#: settles. In one development article this is 134 of 268 accuracy cells.
QUOTED_HEADER = re.compile(r"\b(Org|Orig|Original|Paper|Reported|Prev|Ref|Theirs)\b\.?", re.I)

#: Column headers naming this work.
OWN_HEADER = re.compile(r"\b(Rep|Repro|Reproduced|Ours?|Obtained|This)\b\.?", re.I)

#: How far above a table body its column headers may sit.
HEADER_LOOKBACK = 6


def column_headers(lines: list[str], block: list[int]) -> list[tuple[int, bool]]:
    """Header offsets for a comparison table, each marked as quoted or as this paper's.

    A comparison table sets the reproduced value beside the one it reproduces, and the
    header says which is which. Reading the header is what separates a paper's own result
    from a number it is quoting -- the judgment a codebook would otherwise ask a human
    coder to make on every cell.

    Both kinds are returned, sorted, so a cell can be assigned to the header immediately to
    its left. Returning only the quoted offsets would make each quoted column run to the
    start of the next quoted column, swallowing the reproduced column between them.

    Empty unless the header carries both kinds of label: a table headed only `Original` is
    not a comparison, and its body is not this paper's either.
    """
    for index in range(block[0] - 1, max(-1, block[0] - 1 - HEADER_LOOKBACK), -1):
        line = lines[index]
        quoted = [(m.start(), True) for m in QUOTED_HEADER.finditer(line)]
        own = [(m.start(), False) for m in OWN_HEADER.finditer(line)]
        if quoted and own:
            return sorted(quoted + own)
    return []


def axis_dump(line: str) -> bool:
    """A line of tick labels: four or more numbers and almost no words to label them.

    A table row carries a row label; a flattened axis carries at most a unit.
    """
    numbers = NUMBER.findall(line)
    if len(numbers) < DENSE_LINE:
        return False
    words = re.findall(r"[A-Za-z]{3,}", line)
    return len(words) <= 1

#: An equation body reaches at most this far above its label before the block is assumed to
#: have ended. Display equations in this corpus run one to four lines.
EQUATION_LOOKBACK = 4


def equation_lines(lines: list[str]) -> dict[int, str]:
    """Map 0-indexed line number to its role in a display equation.

    A display equation is recognised by its label -- a bare `(N)` at the end of a line --
    and the body is the run of lines above it that carry a relation or a math symbol. The
    numbers inside the body state what the equation asserts, so an implementation either
    sets them or does not; the label names a location in the paper and asserts nothing.
    """
    roles: dict[int, str] = {}
    for i, line in enumerate(lines):
        if not EQUATION_LABEL.search(line.rstrip()):
            continue
        stripped = line.strip()
        # A sentence that happens to end in a citation-like "(3)" is not an equation.
        if len(stripped) > 90 and not MATH_SYMBOL.search(stripped) and "=" not in stripped:
            continue
        roles[i] = "label"
        for j in range(i - 1, max(-1, i - 1 - EQUATION_LOOKBACK), -1):
            body = lines[j].strip()
            if not body or EQUATION_LABEL.search(body):
                break
            if "=" in body or MATH_SYMBOL.search(body) or len(body) < 40:
                roles.setdefault(j, "body")
            else:
                break
    return roles


def classify(printed: str, context: str, line_count: int, role: str | None,
             line_kind: str | None,
             columns: list[tuple[int, bool]] | None = None) -> tuple[str, str]:
    """Category and reason for one numeric token.

    `role` is the line's position in a display equation, or None. `line_kind` is what the
    document pre-pass made of the whole line -- `header`, `table`, `axis`, or None -- which
    is not recoverable from the line on its own.
    """
    at = context.find(printed)
    before = context[:at]
    after = context[at + len(printed):]
    window = context[max(0, at - 40):at + len(printed) + 12]

    if line_kind == "header":
        return "structural", "running header or footer printed by the page template"

    if any(span.start() <= at < span.end() for span in IDENTIFIER.finditer(context)):
        return "bibliographic", "inside a DOI, URL, repository or archive identifier"
    if DATE_LINE.search(context) and len(printed) <= 4:
        return "bibliographic", "day or year within a date"
    if YEAR.match(printed) and not re.search(r"[%=]", window):
        return "bibliographic", "four-digit year with no numeric operator nearby"
    if CITATION.search(window) and f"[{printed}]" in window:
        return "bibliographic", "bracketed reference index"
    if PAGE_RANGE.search(window):
        return "bibliographic", "page number"

    if AFFILIATION.match(context):
        return "structural", "affiliation marker"
    if SECTION_HEAD.match(context) and context.strip().startswith(printed):
        return "structural", "section number"
    if role == "label" and before.rstrip().endswith("(") and after.startswith(")") \
            and context.rstrip().endswith(f"({printed})"):
        return "structural", "equation label"
    if ENUM_MARKER.search(before):
        return "structural", "inline enumeration marker"
    if NAME_FRAGMENT.search(before) and not after[:1].isdigit():
        return "name_fragment", "part of a hyphenated identifier, not a quantity"
    if CROSS_REF.search(before.rstrip()):
        return "structural", "cross-reference to an equation, figure or table"

    if role in ("label", "body"):
        if MATH_SYMBOL.search(context):
            return "equation_content", "stated inside a display equation carrying flattened math"
        return "equation_content", "stated inside a display equation"

    if line_kind == "table":
        if columns:
            preceding = [(offset, is_quoted) for offset, is_quoted in columns if offset <= at]
            if preceding and preceding[-1][1]:
                return "quoted_value", "under a column headed as another study's result"
        return "table_cell", "cell in an aligned table row"

    if MATH_SYMBOL.search(window):
        return "extraction_failed", "flattened formula; no reliable verbatim reading"
    if FLUSH_EXPONENT.search(before) and len(printed) <= 2:
        return "extraction_failed", "superscript or subscript flattened onto the baseline"

    if context.strip() == printed:
        return "orphan", "the line holds this number and nothing else; no label to match on"
    if line_kind == "axis":
        return "figure_axis", "inside a block the nearest caption names as a figure"

    if BOUNDED.search(window):
        return "bounded", "qualified by a bound or approximation; states no single quantity"
    if PARAMETER.search(before):
        return "parameter", "bound to a named symbol; traceable to a config or call site"
    if line_count >= DENSE_LINE:
        return "dense_line", f"{line_count} numbers on one line, in none of the known layouts"
    return "measurement", "a quantity the paper states about the work"


def scan(text: str) -> list[dict]:
    lines = text.splitlines()
    roles = equation_lines(lines)
    headers = running_headers(lines)
    tables, figures, quoted = aligned_blocks(lines)
    records = []
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        if header_form(line) in headers:
            line_kind = "header"
        elif index in tables:
            line_kind = "table"
        elif index in figures or axis_dump(line):
            line_kind = "axis"
        else:
            line_kind = None
        line_count = len(NUMBER.findall(line))
        for match in NUMBER.finditer(line):
            printed = match.group(0)
            kind, reason = classify(printed, line, line_count, roles.get(index), line_kind,
                                    quoted.get(index))
            records.append({"printed": printed, "line": index + 1,
                            "context": stripped[:160], "kind": kind, "reason": reason})
    return records


#: Reported in three groups, and never collapsed into two. The first group goes to the
#: verifier. The second cannot be checked because nothing in an artifact corresponds to it.
#: The third is not a statement about the paper at all -- it records where the instrument
#: could not read, and folding it into either of the other two would publish a limit of the
#: scanner as a property of the article.
TRACEABLE = ("measurement", "table_cell", "parameter", "equation_content")

#: Checkable, but against the paper being reproduced rather than this one's artifact.
QUOTED = ("quoted_value",)
UNTRACEABLE = ("bibliographic", "structural", "name_fragment")
SEPARATE = ("figure_axis", "dense_line", "orphan", "bounded", "extraction_failed")


def main(path: str) -> int:
    text = pathlib.Path(path).read_text(errors="replace")
    records = scan(text)

    counts: dict[str, int] = {}
    for r in records:
        counts[r["kind"]] = counts.get(r["kind"], 0) + 1
    total = len(records)

    print(f"  {path}")
    print(f"  numeric tokens: {total}\n")
    for title, group in (("traceable", TRACEABLE), ("quoted from another study", QUOTED),
                         ("untraceable", UNTRACEABLE), ("reported separately", SEPARATE)):
        subtotal = sum(counts.get(k, 0) for k in group)
        print(f"    {title:22} {subtotal:5}  ({subtotal / total:5.1%})" if total else title)
        for kind in group:
            n = counts.get(kind, 0)
            print(f"      {kind:20} {n:5}  ({n / total:5.1%})" if total else f"      {kind}")
        print()

    out = pathlib.Path(path).with_suffix(".numbers.json")
    out.write_text(json.dumps({"source": path, "counts": counts, "records": records},
                              indent=2) + "\n")
    print(f"  wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
