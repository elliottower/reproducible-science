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
EQUATION_NUM = re.compile(r"^\s*\(\d+\)\s*$|\(\d+\)\s*$")
AFFILIATION = re.compile(r"^\s*\d\s+[A-Z][a-z]+\s+(?:University|Institute|College|Lab)", re.I)

#: Bibliographic furniture. Nothing in an artifact corresponds to these.
CITATION = re.compile(r"\[\d+(?:\s*,\s*\d+)*\]")
YEAR = re.compile(r"^(1[89]|20)\d\d$")
IDENTIFIER_LINE = re.compile(
    r"doi|https?://|arxiv|isbn|issn|swh:1:|zenodo|github\.com|openreview", re.I)
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

#: Math-layout damage: a flattened formula loses its structure, so no verbatim reading is
#: recoverable. Deliberately narrow -- an earlier version flagged adjacent digits, which
#: matched every table row, because whitespace between numbers is what a table IS.
MANGLED = re.compile(r"[√∫∑∏⟨⟩∂∇⊕⊗◦̸⃗∈∀∃⊂⊆≠≡µξαβγδθλσΣΩ]")

#: A pointer to an equation, figure or table rather than a quantity: "according to (3)",
#: "see (2)", "in equation (2)". The parenthesised number names a location in the paper.
CROSS_REF = re.compile(
    r"(?:see|according\s+to|in|from|using|by|eq\.?|equation|figure|fig\.?|table)\s*\(?$",
    re.I)

#: A number immediately following a word with no space, numbering an item in an inline list:
#: "Influence maximization(1), Node classification(2)".
ENUM_MARKER = re.compile(r"[a-z]\($")

#: A superscript or subscript flattened onto the baseline: "(Wv ))2", "(x)◦2".
EXPONENT = re.compile(r"[)\]}◦^]$")

#: Lines carrying this many numbers are almost always a flattened figure: pdftotext dumps
#: axis ticks with no structure. Kept as a separate category rather than dropped, because a
#: dense table row looks the same and the distinction needs a reader.
DENSE_LINE = 4


def classify(printed: str, context: str, line_count: int) -> tuple[str, str]:
    """Category and reason for one numeric token.

    `line_count` is how many numbers share this line, which is the only signal available
    for distinguishing a flattened figure from prose without layout information.
    """
    at = context.find(printed)
    window = context[max(0, at - 40) : at + len(printed) + 12]

    if IDENTIFIER_LINE.search(context):
        return "bibliographic", "line carries a DOI, URL, repository or archive identifier"
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
    if EQUATION_NUM.search(context.strip()) and context.strip().endswith(f"({printed})"):
        return "structural", "equation number"

    before = context[:at]
    if MANGLED.search(window):
        return "extraction_failed", "flattened formula; no reliable verbatim reading"
    if EXPONENT.search(before.rstrip()) and len(printed) <= 2:
        return "extraction_failed", "superscript or subscript flattened onto the baseline"
    if context.strip() == printed:
        return "structural", "line contains nothing but this number"
    if CROSS_REF.search(before.rstrip()) or (
            before.rstrip().endswith("(") and context[at + len(printed):].startswith(")")
            and len(printed) <= 2):
        return "structural", "cross-reference to an equation, figure or table"
    if ENUM_MARKER.search(before):
        return "structural", "inline enumeration marker"
    if BOUNDED.search(window):
        return "bounded", "qualified by a bound or approximation; states no single quantity"
    if line_count >= DENSE_LINE:
        return "dense_line", f"{line_count} numbers on one line; likely a flattened figure or table"
    if PARAMETER.search(context[:at]):
        return "parameter", "bound to a named symbol; traceable to a config or call site"
    return "measurement", "a quantity the paper states about the work"


def scan(text: str) -> list[dict]:
    records = []
    for lineno, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if not stripped:
            continue
        line_count = len(NUMBER.findall(line))
        for match in NUMBER.finditer(line):
            printed = match.group(0)
            kind, reason = classify(printed, line, line_count)
            records.append(
                {
                    "printed": printed,
                    "line": lineno,
                    "context": stripped[:160],
                    "kind": kind,
                    "reason": reason,
                }
            )
    return records


def main(path: str) -> int:
    text = pathlib.Path(path).read_text(errors="replace")
    records = scan(text)

    counts: dict[str, int] = {}
    for r in records:
        counts[r["kind"]] = counts.get(r["kind"], 0) + 1
    total = len(records)

    print(f"  {path}")
    print(f"  numeric tokens: {total}\n")
    for kind in ("measurement", "parameter", "dense_line", "bounded",
                 "structural", "bibliographic", "extraction_failed"):
        n = counts.get(kind, 0)
        print(f"    {kind:18} {n:5}  ({n/total:5.1%})" if total else f"    {kind:18} {n:5}")

    out = pathlib.Path(path).with_suffix(".numbers.json")
    out.write_text(json.dumps({"source": path, "counts": counts, "records": records},
                              indent=2) + "\n")
    print(f"\n  wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
