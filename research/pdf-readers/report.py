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
            "passage_checks": v["checks"],
        }
        for repo, v in sorted(by_repo.items())
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quotations-shard", type=pathlib.Path, required=True)
    parser.add_argument("--sampled-shard", type=pathlib.Path, required=True)
    parser.add_argument("--fetch-log", type=pathlib.Path)
    parser.add_argument("--corebench-probe", type=pathlib.Path)
    parser.add_argument("--out", type=pathlib.Path, required=True)
    args = parser.parse_args()

    records = load(args.quotations_shard) + load(args.sampled_shard)
    results = summarize(records)
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
        "results": results,
        "documents": records,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=1))
    print(json.dumps({k: report[k] for k in ("verdict", "rescience_fetch")}, indent=1))


if __name__ == "__main__":
    main()
