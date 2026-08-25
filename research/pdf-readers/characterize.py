"""What the reader that missed a passage did with it instead.

`compare_readers.py` records that two readers disagreed. It does not say why, and a divergence
rate with no cause behind it cannot be acted on: "poppler is better" is a preference, "the
pure-Python readers splice subscripts into running prose" is a reason.

For each divergent check this re-reads the document with the dissenting reader, locates the
longest prefix of the passage that survives, and records what sits at the break. Four signals,
each countable rather than eyeballed:

    cid_placeholder    the dissenting text carries `(cid:N)` near the break -- a glyph with no
                       ToUnicode mapping, which pdfminer emits as a literal placeholder and
                       which no normalization can recover
    spliced_token      a run of letters appears inside the passage in the dissenting reader
                       that appears nowhere in it in the agreeing reader -- a subscript or
                       superscript hoisted onto the baseline mid-word
    math_nearby        the agreeing reader's text carries Greek or mathematical characters
                       within the passage or just outside it
    dropped_region     the passage's first 20 characters are absent from the dissenting text
                       entirely, so nothing was spliced and nothing was placed: it is gone

The output is one record per divergence with the passage, the two readings around the break,
and the signals, so every count in the report can be traced to a document and a sentence.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
from typing import Any

from citations import readers
from citations import verify as V
from citations.exceptions import SourceUnreadableError
from compare_readers import distinct, diverges

CID = re.compile(r"\(cid:\d+\)")
MATH = re.compile(r"[Ͱ-Ͽ←-⋿⨀-⫿±×÷]")
LETTERS = re.compile(r"[a-z]+")

#: How far either side of the break to look. Wide enough to catch a placeholder at the end of
#: the previous word, narrow enough that a signal is about this passage and not the page.
WINDOW = 200


def longest_prefix(skeleton_quote: str, skeleton_text: str) -> int:
    """How many characters of the passage survive in this reader's text.

    Binary search on the prefix length. A linear scan over a 200,000-character document per
    divergence is minutes; this is milliseconds and answers the same question.
    """
    lo, hi = 0, len(skeleton_quote)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if skeleton_quote[:mid] in skeleton_text:
            lo = mid
        else:
            hi = mid - 1
    return lo


def signals(quote: str, agreeing: str, dissenting: str) -> dict[str, Any]:
    q, doc = V.skeleton(quote), V.skeleton(dissenting)
    kept = longest_prefix(q, doc)
    at = doc.find(q[:kept]) if kept else -1
    window = doc[max(0, at) : at + kept + WINDOW] if at >= 0 else ""

    ours = V.skeleton(agreeing)
    ours_at = ours.find(q)
    ours_window = ours[max(0, ours_at - 40) : ours_at + len(q) + 40] if ours_at >= 0 else ""

    # A run of letters the dissenting reader put inside the passage that the agreeing reader
    # does not have there. Restricted to runs of three or more, since one or two letters is
    # as likely to be a spacing artifact as a hoisted subscript.
    spliced = ""
    if at >= 0 and kept:
        after = doc[at + kept : at + kept + 24]
        run = LETTERS.match(after)
        if run and len(run.group()) >= 3 and run.group() not in q[kept : kept + 24]:
            spliced = run.group()

    return {
        "characters_of_passage_kept": kept,
        "passage_characters": len(q),
        "cid_placeholder": bool(CID.search(window)),
        "spliced_token": spliced,
        "math_nearby": bool(MATH.search(ours_window)) if ours_window else None,
        "dropped_region": kept < 20,
        "dissenting_at_break": window[:180],
        "agreeing_at_break": ours_window[:180],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shard", type=pathlib.Path, action="append", required=True)
    parser.add_argument("--out", type=pathlib.Path, required=True)
    args = parser.parse_args()

    records = [
        json.loads(line)
        for shard in args.shard
        for line in shard.read_text().splitlines()
        if line.strip()
    ]
    divergent = [
        (record, check)
        for record, check in distinct([(r, c) for r in records for c in r["checks"]])
        if diverges(check["outcomes"])
    ]

    out: list[dict[str, Any]] = []
    cache: dict[tuple[str, str], str | None] = {}
    for record, check in divergent:
        path = pathlib.Path(record["pdf"])
        texts = {}
        for name in ("poppler", "pdfplumber", "pypdf"):
            key = (str(path), name)
            if key not in cache:
                try:
                    cache[key] = readers.read(path, reader=name).text
                except SourceUnreadableError:
                    cache[key] = None
            texts[name] = cache[key]

        agreeing = next(
            (texts[n] for n, o in check["outcomes"].items() if o.startswith("found")), None
        )
        dissenters = [n for n, o in check["outcomes"].items() if o == "not_found" and texts[n]]
        if agreeing is None or not dissenters:
            continue
        for name in dissenters:
            out.append(
                {
                    "corpus": record["corpus"],
                    "pdf": record["name"],
                    "claim_file": check.get("file"),
                    "claim": check.get("claim"),
                    "passage": check["text"],
                    "dissenting_reader": name,
                    "outcomes": check["outcomes"],
                    **signals(check["text"], agreeing, texts[name] or ""),
                }
            )
        print(f"{len(out):>4}  {record['name']}", flush=True)

    counts: dict[str, dict[str, int]] = {}
    for row in out:
        bucket = counts.setdefault(
            row["dissenting_reader"],
            {
                "divergences": 0,
                "cid_placeholder": 0,
                "spliced_token": 0,
                "math_nearby": 0,
                "dropped_region": 0,
            },
        )
        bucket["divergences"] += 1
        for signal in ("cid_placeholder", "spliced_token", "math_nearby", "dropped_region"):
            if row[signal]:
                bucket[signal] += 1

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({"counts": counts, "divergences": out}, indent=1))
    print(json.dumps(counts, indent=1))


if __name__ == "__main__":
    main()
