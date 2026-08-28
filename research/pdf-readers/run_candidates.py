"""Are the Rust text layers worth adding to `citations.readers`?

Two questions, one per subcommand, both answered on corpora the repository already uses.

    speed       wall-clock and CPU cost of each reader over one directory of PDFs, serially.
                The number to beat is `pdftotext -layout`, which is measured in the same loop
                rather than quoted, so the comparison is between two rows of one run.

    agreement   the pairwise matrix `compare_readers.py` already computes, with the candidates
                registered into its reader table. For each pair of readers: how many passage
                checks one resolved and the other did not, in both directions. A reader that
                is uniformly worse adds nothing to triangulation; a reader that resolves
                passages the others miss while missing passages they resolve is exactly what
                triangulation consults a second reader for.

Both write one line per unit to a `.jsonl` shard before the next unit starts, so an
interrupted run resumes rather than restarts, and no number in the output lacks a line behind
it.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import random
import time
from typing import Any

import candidate_readers
import compare_readers as C

#: A cold read of a 389 MB corpus measures the disk, and the first reader in the loop would pay
#: for every reader after it. Every file is read once before timing starts, and the fact that
#: it was is recorded: a timing that does not say whether the page cache was warm is not
#: comparable with one taken on another machine.
WARM_THE_CACHE = True


def warm(pdfs: list[pathlib.Path]) -> int:
    total = 0
    for pdf in pdfs:
        total += len(pdf.read_bytes())
    return total


def cpu_seconds() -> tuple[float, float]:
    """(this process, its children) CPU seconds so far -- user plus system.

    Children as well as self, because four of the readers are subprocesses and one is not: a
    CPU number that counted only this process would report the Rust readers as free.
    """
    t = os.times()
    return t.user + t.system, t.children_user + t.children_system


def speed(args: argparse.Namespace) -> None:
    pdfs = sorted(p for d in args.pdf_dir for p in d.glob("*.pdf"))
    if args.limit:
        pdfs = pdfs[: args.limit]
    names = args.reader or list(C.READERS)

    shard = args.out.with_suffix(".jsonl")
    done = set()
    if shard.exists():
        for line in shard.read_text().splitlines():
            if line.strip():
                row = json.loads(line)
                done.add((row["reader"], row["pdf"]))

    warmed = warm(pdfs) if WARM_THE_CACHE else 0
    for name in names:
        read = C.READERS[name]
        started, (self0, kids0) = time.monotonic(), cpu_seconds()
        for pdf in pdfs:
            if (name, str(pdf)) in done:
                continue
            reading = read(pdf)
            with shard.open("a") as fh:
                fh.write(
                    json.dumps(
                        {
                            "reader": name,
                            "pdf": str(pdf),
                            "bytes": pdf.stat().st_size,
                            "seconds": round(reading.seconds, 4),
                            "chars": len(reading.text or ""),
                            "opened": reading.opened,
                            "error": reading.error,
                        }
                    )
                    + "\n"
                )
        self1, kids1 = cpu_seconds()
        print(
            f"{name}: wall {time.monotonic() - started:.1f}s "
            f"cpu_self {self1 - self0:.1f}s cpu_children {kids1 - kids0:.1f}s",
            flush=True,
        )

    rows = [json.loads(line) for line in shard.read_text().splitlines() if line.strip()]
    per_reader: dict[str, Any] = {}
    for name in names:
        mine = [r for r in rows if r["reader"] == name]
        if not mine:
            continue
        times = sorted(r["seconds"] for r in mine)
        worst = max(mine, key=lambda r: r["seconds"])
        per_reader[name] = {
            "documents": len(mine),
            "opened": sum(1 for r in mine if r["opened"]),
            "failed": [
                {"pdf": pathlib.Path(r["pdf"]).name, "error": r["error"]}
                for r in mine
                if not r["opened"]
            ],
            "total_seconds": round(sum(times), 2),
            "median_seconds": round(times[len(times) // 2], 3),
            "p90_seconds": round(times[int(0.9 * (len(times) - 1))], 3),
            "worst_seconds": round(times[-1], 2),
            "worst_document": pathlib.Path(worst["pdf"]).name,
            "characters_produced": sum(r["chars"] for r in mine),
        }
    baseline = per_reader.get("poppler-layout", {}).get("total_seconds")
    for row in per_reader.values():
        row["times_poppler_layout"] = (
            round(row["total_seconds"] / baseline, 2) if baseline else None
        )

    report = {
        "question": "Is a Rust PDF text layer meaningfully faster than pdftotext -layout?",
        "unit": "one document read end to end, serially, one reader at a time",
        "corpus": {
            "directories": [str(d) for d in args.pdf_dir],
            "documents": len(pdfs),
            "bytes": sum(p.stat().st_size for p in pdfs),
            "page_cache_warmed_before_timing": WARM_THE_CACHE,
            "bytes_read_to_warm": warmed,
        },
        "machine": {
            "platform": os.uname().sysname,
            "release": os.uname().release,
            "machine": os.uname().machine,
        },
        "reader_versions": {**C.reader_versions(), **candidate_readers.versions(args.pdfrs)},
        "per_reader": per_reader,
        "shard": str(shard),
    }
    args.out.write_text(json.dumps(report, indent=1) + "\n")
    print(json.dumps(per_reader, indent=1))


def agreement(args: argparse.Namespace) -> None:
    documents, skipped = C.quotation_corpus(args.claims_root)
    for directory in args.pdf_dir:
        for pdf in sorted(directory.glob("*.pdf")):
            documents.append({"pdf": str(pdf), "quotes": [], "sources": [], "sha256": ""})
    if args.limit:
        documents = documents[: args.limit]

    # Beside the report only if nowhere else is named. The shard holds every quotation the
    # corpus checked, and those belong to publishers who did not license their redistribution
    # -- the same reason `results.json` carries counts and twelve worked examples rather than
    # the corpus. `--shard` points it outside the repository.
    shard = args.shard or args.out.with_suffix(".jsonl")
    done = set()
    if shard.exists():
        for line in shard.read_text().splitlines():
            if line.strip():
                done.add(json.loads(line)["pdf"])

    rng = random.Random(args.seed)
    for i, entry in enumerate(documents, 1):
        seed = rng.randrange(2**32)  # drawn for every document, so resuming draws the same one
        if entry["pdf"] in done:
            continue
        corpus = "quotations" if entry["quotes"] else "sampled"
        result = C.measure_document(
            pathlib.Path(entry["pdf"]), entry["quotes"], corpus, random.Random(seed)
        )
        result["sha256"] = entry["sha256"]
        result["claim_files"] = entry["sources"]
        with shard.open("a") as fh:
            fh.write(json.dumps(result) + "\n")
        print(
            f"[{i}/{len(documents)}] {result['name']} {corpus} checks={len(result['checks'])} "
            + " ".join(
                f"{n}={'ok' if r['opened'] else 'FAIL'}" for n, r in result["readings"].items()
            ),
            flush=True,
        )

    records = [json.loads(line) for line in shard.read_text().splitlines() if line.strip()]
    results = C.summarize(records)
    for corpus in results:
        results[corpus].pop("divergences", None)
    report = {
        "question": (
            "Does a candidate reader fail in a different direction from the readers already "
            "installed, which is what makes it worth adding to triangulation?"
        ),
        "decision_criterion": {
            "unit": C.DECISION_CRITERION["unit"],
            "outcome_compared": C.DECISION_CRITERION["outcome_compared"],
            "add_to_triangulation_if": (
                "against every installed reader the candidate resolves passage checks that "
                "reader missed, in numbers of the same order as the 59/29 split that put "
                "poppler's two modes both in the chain"
            ),
            "do_not_add_if": (
                "the candidate's only-found column is near zero against every installed "
                "reader, which makes it a strictly worse reader and adds nothing to a "
                "triangulation that already disagrees"
            ),
            "same_pipeline_pairs_are_not_two_readers": (
                "poppler-layout/poppler-flow are one binary, and pdf-extract/lopdf are one "
                "object model. Each pair is a mode comparison and is never counted as two "
                "readers agreeing."
            ),
            "pooling_forbidden": C.DECISION_CRITERION["pooling_forbidden"],
        },
        "readers_measured": list(C.READERS),
        "reader_versions": {**C.reader_versions(), **candidate_readers.versions(args.pdfrs)},
        "inputs": {
            "claims_roots": [str(p) for p in args.claims_root],
            "pdf_dirs": [str(p) for p in args.pdf_dir],
            "seed": args.seed,
            "documents": len(records),
            "claim_files_skipped": skipped,
        },
        "results": results,
        "reader_cost_seconds_per_document": _cost(records),
        "shard": str(shard),
    }
    args.out.write_text(json.dumps(report, indent=1) + "\n")
    print(json.dumps({c: results[c]["pairwise"] for c in results}, indent=1))


def _cost(records: list[dict[str, Any]]) -> dict[str, Any]:
    out = {}
    for name in C.READERS:
        times = sorted(r["readings"][name]["seconds"] for r in records if name in r["readings"])
        if not times:
            continue
        out[name] = {
            "documents": len(times),
            "median_seconds": round(times[len(times) // 2], 2),
            "total_seconds": round(sum(times), 1),
            "worst_seconds": round(times[-1], 1),
        }
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdfrs", type=pathlib.Path, default=candidate_readers.PDFRS)
    parser.add_argument("--candidate", action="append", default=None)
    sub = parser.add_subparsers(dest="command", required=True)

    s = sub.add_parser("speed")
    s.add_argument("--pdf-dir", type=pathlib.Path, action="append", required=True)
    s.add_argument("--reader", action="append", default=None)
    s.add_argument("--limit", type=int, default=0)
    s.add_argument("--out", type=pathlib.Path, required=True)
    s.set_defaults(func=speed)

    a = sub.add_parser("agreement")
    a.add_argument("--claims-root", type=pathlib.Path, action="append", default=[])
    a.add_argument("--pdf-dir", type=pathlib.Path, action="append", default=[])
    a.add_argument(
        "--shard",
        type=pathlib.Path,
        default=None,
        help="where the per-document lines go; keep it out of the repository",
    )
    a.add_argument("--seed", type=int, default=20260825)
    a.add_argument("--limit", type=int, default=0)
    a.add_argument("--out", type=pathlib.Path, required=True)
    a.set_defaults(func=agreement)

    args = parser.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    added = candidate_readers.register(args.pdfrs, args.candidate)
    print(f"registered candidates: {', '.join(added)}", flush=True)
    args.func(args)


if __name__ == "__main__":
    main()
