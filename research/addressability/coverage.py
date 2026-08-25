"""Which numbers in a manuscript are bound to a recorded run, and which are not.

Audit mode. The scan cannot say whether a stranger's paper is true -- a printed value against
a dense artifact carries too little information, which `DEV_LOG.md` measures. It can say
which of a paper's numbers their author bound to something, which is a question with a
defensible answer and a useful one to be asked before submitting.

A claim recorded by `results claim` carries the claim text as it appears in the manuscript.
Any number inside that text is bound: the ledger names a run, the run names sealed inputs,
and `results verify` checks the chain. A number appearing nowhere in any claim is unbound --
not wrong, and not checked by anything.

Reads a manuscript in LaTeX, since that is what the author has while writing. Extraction from
a PDF loses the table structure this depends on.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))

from scan_numbers import NUMBER, scan  # noqa: E402

TRACEABLE = {"measurement", "table_cell", "parameter", "equation_content"}

#: LaTeX whose numbers describe the page rather than the work: lengths, float placement,
#: graphics options, cross-reference keys. Their arguments are not claims about anything.
LAYOUT = re.compile(
    r"\\(?:vspace|hspace|vskip|hskip|setlength|addtolength|scalebox|resizebox|includegraphics"
    r"|arraystretch|tabcolsep|columnsep|baselinestretch|textwidth|linewidth|multirow"
    r"|multicolumn|cmidrule|cline|rule|label|ref|eqref|cite[a-z]*|bibitem|newcommand"
    r"|renewcommand|documentclass|usepackage|geometry|definecolor|color|rowcolor)"
    r"\s*(?:\[[^\]]*\])?\s*(?:\{[^{}]*\})*", re.I)

COMMENT = re.compile(r"(?<!\\)%.*$", re.M)


def body(source: str) -> str:
    """The manuscript's prose and tables, with comments, preamble and layout removed."""
    source = COMMENT.sub("", source)
    start = source.find(r"\begin{document}")
    if start != -1:
        source = source[start:]
    return LAYOUT.sub(" ", source)


def claim_numbers(ledger: pathlib.Path) -> tuple[set[str], int]:
    """Every number appearing in the text of a recorded claim, and how many claims there are.

    A claim's text is the sentence as the manuscript prints it, so its numbers are exactly
    the ones the author asserted were backed by the run they named.
    """
    bound: set[str] = set()
    claims = 0
    for line in ledger.read_text().splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        if record.get("event") != "claim":
            continue
        claims += 1
        bound.update(NUMBER.findall(record.get("claim", "")))
    return bound, claims


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manuscript", help="the .tex the author is writing")
    parser.add_argument("--ledger", default=".results/ledger.jsonl")
    parser.add_argument("--show", type=int, default=20)
    args = parser.parse_args()

    source = pathlib.Path(args.manuscript).read_text(errors="replace")
    records = [r for r in scan(body(source)) if r["kind"] in TRACEABLE]
    bound, claims = claim_numbers(pathlib.Path(args.ledger))

    for record in records:
        record["bound"] = record["printed"] in bound

    covered = [r for r in records if r["bound"]]
    print(f"\n  {args.manuscript}")
    print(f"  {claims} recorded claims, naming {len(bound)} distinct values")
    print(f"  {len(records)} numbers in the manuscript that an artifact could hold\n")
    print(f"    bound to a run   {len(covered):>5}  ({len(covered) / len(records):.0%})"
          if records else "    no numbers found")
    print(f"    unbound          {len(records) - len(covered):>5}  "
          f"({1 - len(covered) / len(records):.0%})\n" if records else "")

    unbound = [r for r in records if not r["bound"]]
    if unbound:
        print(f"    unbound, by where they sit:")
        seen: dict[str, int] = {}
        for r in unbound:
            seen[r["kind"]] = seen.get(r["kind"], 0) + 1
        for kind, n in sorted(seen.items(), key=lambda kv: -kv[1]):
            print(f"      {kind:18} {n}")
        print(f"\n    first {min(args.show, len(unbound))}:")
        for r in unbound[:args.show]:
            print(f"      {r['printed']:>10}  line {r['line']:<5} {r['context'][:76]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
