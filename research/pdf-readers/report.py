"""Assemble one answer to "does poppler earn its system dependency?" from the measured shards.

`compare_readers.py` writes one line per document as it goes. This reads those lines, records
where every document came from and how many were obtainable, and writes the single file the
answer is quoted from. Nothing here measures anything: a number that appears in the report and
not in a shard would have no run behind it.
"""

from __future__ import annotations

import argparse
import json
import pathlib
from typing import Any

from compare_readers import DECISION_CRITERION, reader_versions, summarize


def load(shard: pathlib.Path) -> list[dict[str, Any]]:
    if not shard.exists():
        return []
    return [json.loads(line) for line in shard.read_text().splitlines() if line.strip()]


def fetch_summary(log: pathlib.Path) -> dict[str, Any]:
    """How many ReScience articles were obtainable, from the fetch log.

    One key can appear twice -- an interrupted run and its resumption both log -- so the
    best status per key is taken rather than the row count, which would report more articles
    than the frame holds.
    """
    if not log.exists():
        return {}
    best: dict[str, dict[str, Any]] = {}
    for line in log.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if best.get(row["key"], {}).get("status") != "ok":
            best[row["key"]] = row
    return {
        "development_articles_in_frame": len(best),
        "pdf_obtained": sum(1 for r in best.values() if r["status"] == "ok"),
        "unavailable": sorted(k for k, r in best.items() if r["status"] != "ok"),
    }


def quotation_provenance(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Which repositories the quotations came from, counted from the shard rather than listed.

    A document's claim files name the repository that pinned it, so the corpus describes
    itself: no separate list can fall out of date with what was measured.

    The counts are before deduplication, and are labelled so. Two repositories here hold the
    same claims file against their own copy of one PDF, so a per-repository total that had
    been deduplicated would attribute a shared check to whichever repository was read first.
    """
    by_repo: dict[str, dict[str, Any]] = {}
    for record in records:
        if record["corpus"] != "quotations":
            continue
        for claim_file in record.get("claim_files", []):
            parts = pathlib.Path(claim_file).parts
            repo = parts[parts.index("GitHub") + 1] if "GitHub" in parts else parts[0]
            entry = by_repo.setdefault(
                repo, {"claim_files": set(), "documents": set(), "checks": 0}
            )
            entry["claim_files"].add(claim_file)
            entry["documents"].add(record["pdf"])
        for claim_file in record.get("claim_files", []):
            parts = pathlib.Path(claim_file).parts
            repo = parts[parts.index("GitHub") + 1] if "GitHub" in parts else parts[0]
            by_repo[repo]["checks"] += sum(
                1 for c in record["checks"] if c.get("file") == claim_file
            )
    return {
        repo: {
            "claim_files": len(v["claim_files"]),
            "documents": len(v["documents"]),
            "passage_checks_before_deduplication": v["checks"],
        }
        for repo, v in sorted(by_repo.items())
    }


def sampled_balance(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Whether the sampled corpus drew evenly from the three readers, which it must.

    The design rests on symmetry: a passage drawn from reader A favours reader A, so every
    reader supplies an equal share and the bias cancels. Two thresholds break that. Passages
    are drawn from lines of at least 120 characters, and each reader breaks lines its own way
    -- pdfplumber emits one visual line per line and rarely reaches that length, while poppler
    reconstructs the page and often exceeds it. And the gutter filter that keeps a two-column
    splice out of the sample removes nearly every poppler line in a two-column paper.

    So the draw is reported rather than assumed. An uneven one means the corpus measures which
    reader writes long lines, and its numbers do not bear on the decision.
    """
    drawn: dict[str, int] = {}
    silent = 0
    for record in records:
        if record["corpus"] != "sampled":
            continue
        if not record["checks"]:
            silent += 1
        for check in record["checks"]:
            reader = check.get("drawn_from", "?")
            drawn[reader] = drawn.get(reader, 0) + 1
    total = sum(drawn.values())
    even = total and min(drawn.values()) / max(drawn.values()) > 0.5
    return {
        "passages_drawn_from": drawn,
        "documents_contributing_nothing": silent,
        "draw_is_even": bool(even),
        "bears_on_the_decision": bool(even),
    }


def verdict(quotations: dict[str, Any]) -> dict[str, Any]:
    """Which branch of the pre-stated criterion the quotation corpus lands in."""
    checks = quotations["passage_checks"]
    diverging = quotations["divergent_checks"]
    rate = quotations["divergence_rate"]
    if checks == 0:
        branch = "undecided: no passage checks were made"
    elif diverging == 0:
        branch = (
            "poppler is droppable: the pure-Python readers reproduced its outcome on every check"
        )
    elif rate < 0.01:
        branch = "small divergence: each case is listed and characterized"
    else:
        branch = "substantial divergence: poppler stays and triangulation is worth building"
    return {
        "passage_checks": checks,
        "divergent_checks": diverging,
        "divergence_rate": rate,
        "branch": branch,
    }


def per_document(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One row per document: how it was read, how long it took, and how the checks came out.

    No passage text. The shards hold every quotation this corpus checked, and those
    quotations belong to publishers who did not license their redistribution — the same
    reason `paper/prior_art/reference/` is not in this repository. A row carries the counts,
    which is what any later run needs to compare itself against.
    """
    rows = []
    for record in records:
        outcomes = {
            name: {
                "found": sum(
                    1 for c in record["checks"] if c["outcomes"][name].startswith("found")
                ),
                "found_only_after_normalization": sum(
                    1 for c in record["checks"] if c["outcomes"][name] == "found_normalized"
                ),
                "not_found": sum(1 for c in record["checks"] if c["outcomes"][name] == "not_found"),
            }
            for name in ("poppler", "pdfplumber", "pypdf")
        }
        rows.append(
            {
                "corpus": record["corpus"],
                "name": record["name"],
                "sha256": record["sha256"],
                "bytes": record["bytes"],
                "checks": len(record["checks"]),
                "readings": record["readings"],
                "outcomes": outcomes,
            }
        )
    return rows


def reader_cost(records: list[dict[str, Any]]) -> dict[str, Any]:
    """What each reader cost in wall-clock seconds per document.

    The median is what a person waits for on an ordinary paper; the worst case is what decides
    whether a reader can be left unbounded. Only poppler runs in a subprocess and can be given
    a timeout — a call already inside a Python parser cannot be interrupted without abandoning
    the thread still executing it — so its worst case is the one the package can cap.
    """
    out = {}
    for name in ("poppler", "pdfplumber", "pypdf"):
        times = sorted(r["readings"][name]["seconds"] for r in records)
        if not times:
            continue
        out[name] = {
            "documents": len(times),
            "median_seconds": round(times[len(times) // 2], 2),
            "total_seconds": round(sum(times), 1),
            "worst_seconds": round(times[-1], 1),
            "worst_document": max(records, key=lambda r: r["readings"][name]["seconds"])["name"],
        }
    return out


def worked_examples(causes: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    """A bounded set of divergences, one per document, quoted in full.

    A rate with no example behind it cannot be checked and cannot be acted on, so the cause
    of each class is shown rather than named. Bounded and one per document, because the point
    is to make the mechanism legible and not to republish the corpus.
    """
    seen: set[str] = set()
    out = []
    for row in sorted(causes.get("divergences", []), key=lambda r: -r["passage_characters"]):
        if row["pdf"] in seen or len(out) >= limit:
            continue
        seen.add(row["pdf"])
        out.append(row)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quotations-shard", type=pathlib.Path, required=True)
    parser.add_argument("--sampled-shard", type=pathlib.Path, required=True)
    parser.add_argument("--fetch-log", type=pathlib.Path)
    parser.add_argument("--corebench-probe", type=pathlib.Path)
    parser.add_argument("--causes", type=pathlib.Path, help="output of characterize.py")
    parser.add_argument("--examples", type=int, default=12)
    parser.add_argument("--out", type=pathlib.Path, required=True)
    args = parser.parse_args()

    records = load(args.quotations_shard) + load(args.sampled_shard)
    results = summarize(records)
    causes = json.loads(args.causes.read_text()) if args.causes else {}
    # The summary keeps its counts; the passages behind them do not travel into a public
    # repository beyond the worked examples.
    for corpus in results:
        results[corpus].pop("divergences", None)

    report = {
        "question": DECISION_CRITERION["question"],
        "decision_criterion": DECISION_CRITERION,
        "reader_versions": reader_versions(),
        "quotation_corpus_by_repository": quotation_provenance(records),
        "corebench_probe": (
            json.loads(args.corebench_probe.read_text()) if args.corebench_probe else {}
        ),
        "rescience_fetch": fetch_summary(args.fetch_log) if args.fetch_log else {},
        "verdict": verdict(results["quotations"]),
        "sampled_corpus_balance": sampled_balance(records),
        "results": results,
        "reader_cost": reader_cost(records),
        "divergence_causes": causes.get("counts", {}),
        "worked_examples": worked_examples(causes, args.examples),
        "documents": per_document(records),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=1) + "\n")
    print(json.dumps({k: report[k] for k in ("verdict", "divergence_causes")}, indent=1))


if __name__ == "__main__":
    main()
