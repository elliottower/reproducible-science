"""What adding one candidate to `citations.readers` would change, per candidate.

The pairwise matrix says how two readers differ. It does not say what the package would do
differently, because `verify --triangulate` does not compare two readers: it asks every
installed reader and reports `indeterminate` on any disagreement. So a candidate changes two
things, and they pull in opposite directions.

    rescued        passage checks no installed reader resolves and the candidate does. This is
                   coverage the package does not have, and the only thing a new reader can add
                   that nothing else can.
    made_indeterminate   passage checks every installed reader currently agrees on, that the
                   candidate dissents from. Each becomes `indeterminate`, which `--strict`
                   refuses, so a reader that disagrees more makes a passing build fail on
                   passages that were settled.

Each installed reader is scored the same way against the other three, so the candidates are
read against what a reader already in the chain contributes rather than against zero.
"""

from __future__ import annotations

import argparse
import itertools
import json
import pathlib
from typing import Any

from compare_readers import distinct

#: The readers `citations` consults today: poppler's two modes and the two extras in
#: `optional-dependencies.pdf`. A candidate is scored against the set as it stands.
INSTALLED = ("poppler-layout", "poppler-flow", "pdfplumber", "pypdf")


def found(outcome: str) -> bool:
    return outcome.startswith("found")


def verdicts(check: dict[str, Any], names: tuple[str, ...]) -> dict[str, bool]:
    """Each named reader's found/not-found, dropping the ones that could not read the file.

    A reader that failed to open the document contributes nothing rather than a `not found`:
    `_triangulate` drops it the same way, and pooling the two would report a panic as a missing
    passage.
    """
    return {
        name: found(check["outcomes"][name])
        for name in names
        if check["outcomes"].get(name) not in ("unchecked", "empty", None)
    }


def score(checks: list[dict[str, Any]], candidate: str, against: tuple[str, ...]) -> dict[str, Any]:
    rescued = made_indeterminate = agreed = 0
    unreadable = 0
    settled_found = settled_not_found = 0
    for check in checks:
        base = verdicts(check, against)
        if not base:
            continue
        mine = verdicts(check, (candidate,))
        if not mine:
            unreadable += 1
            continue
        theirs = set(base.values())
        ours = mine[candidate]
        if len(theirs) > 1:
            continue  # already indeterminate; the candidate cannot make it worse or better
        settled = next(iter(theirs))
        if settled:
            settled_found += 1
        else:
            settled_not_found += 1
        if ours == settled:
            agreed += 1
        elif ours:
            rescued += 1
        else:
            made_indeterminate += 1
    return {
        "checks_the_others_settle": settled_found + settled_not_found,
        "settled_found": settled_found,
        "settled_not_found": settled_not_found,
        "agreed_with_the_settled_verdict": agreed,
        "rescued": rescued,
        "made_indeterminate": made_indeterminate,
        "could_not_read_the_document": unreadable,
        "rescued_per_indeterminate": (
            round(rescued / made_indeterminate, 3) if made_indeterminate else None
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shard", type=pathlib.Path, required=True)
    parser.add_argument(
        "--measured",
        type=pathlib.Path,
        help="the run_candidates.py agreement report, for the reader versions it recorded",
    )
    parser.add_argument("--corpus", default="quotations")
    parser.add_argument("--out", type=pathlib.Path, required=True)
    args = parser.parse_args()

    records = [json.loads(line) for line in args.shard.read_text().splitlines() if line.strip()]
    records = [r for r in records if r["corpus"] == args.corpus]
    checks = [c for _, c in distinct([(r, c) for r in records for c in r["checks"]])]
    names = list(records[0]["outcomes"] if "outcomes" in records[0] else records[0]["readings"])
    candidates = [n for n in names if n not in INSTALLED]

    added = {c: score(checks, c, INSTALLED) for c in candidates}
    # Each installed reader against the other three, so a candidate's row is read against what
    # a reader already in the chain contributes rather than against nothing.
    incumbent = {
        name: score(checks, name, tuple(n for n in INSTALLED if n != name)) for name in INSTALLED
    }

    # How often a document is unreadable, which is the other half of a reader's cost: a reader
    # that panics contributes no verdict on every passage in that document.
    docs = list({r.get("sha256") or r["pdf"]: r for r in records}.values())
    opened = {
        name: {
            "documents": len(docs),
            "opened": sum(1 for r in docs if r["readings"][name]["opened"]),
            "errors": sorted(
                {r["readings"][name]["error"] for r in docs if not r["readings"][name]["opened"]}
            ),
        }
        for name in names
    }

    # A candidate that only ever rescues what another candidate rescues is one reader's worth
    # of coverage, not two.
    overlap = {}
    for a, b in itertools.combinations(candidates, 2):
        both = either = 0
        for check in checks:
            base = verdicts(check, INSTALLED)
            if not base or len(set(base.values())) > 1 or next(iter(base.values())):
                continue
            ra = verdicts(check, (a,)).get(a, False)
            rb = verdicts(check, (b,)).get(b, False)
            both += ra and rb
            either += ra or rb
        overlap[f"{a} and {b}"] = {"rescued_by_either": either, "rescued_by_both": both}

    # How much room a new reader has to help at all. `rescued` can only be drawn from checks
    # every installed reader currently misses, and a corpus of quotations taken from claims
    # files is a corpus of passages somebody could already read. A near-empty pool here is a
    # fact about the corpus and bounds what any candidate could have scored.
    today = {"all_found": 0, "all_not_found": 0, "disagree": 0, "no_reader_opened_it": 0}
    for check in checks:
        base = verdicts(check, INSTALLED)
        if not base:
            today["no_reader_opened_it"] += 1
        elif len(set(base.values())) > 1:
            today["disagree"] += 1
        elif next(iter(base.values())):
            today["all_found"] += 1
        else:
            today["all_not_found"] += 1
    today["rescue_headroom"] = today["all_not_found"]

    report = {
        "question": (
            "What would adding this reader change in `citations verify --triangulate`, "
            "which reports `indeterminate` on any disagreement?"
        ),
        "installed_readers": list(INSTALLED),
        # Carried rather than referenced, so this file says which readers produced the counts
        # in it without a second file having to be open beside it.
        "reader_versions": json.loads(args.measured.read_text())["reader_versions"]
        if args.measured and args.measured.exists()
        else {},
        "what_the_installed_readers_do_today": today,
        "corpus": args.corpus,
        "passage_checks": len(checks),
        "documents": len(docs),
        "shard": str(args.shard),
        "candidates": added,
        "incumbents_scored_the_same_way": incumbent,
        "rescue_overlap_between_candidates": overlap,
        "documents_opened": opened,
    }
    args.out.write_text(json.dumps(report, indent=1) + "\n")
    print(json.dumps({"candidates": added, "incumbents": incumbent}, indent=1))


if __name__ == "__main__":
    main()
