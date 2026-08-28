"""Where the time in `citations verify` actually goes.

Runs the loop `cli.cmd_verify` runs, over the same corpus, with three seams instrumented:

    subprocess.run      every extractor invocation, its argv, and whether it asked for a page
    sha256_of_file      every whole-file hash, including the two `_run` takes per invocation
    the matcher         `resolve_in`, so Python-side matching is separated from extraction

Nothing in `citations` is modified. The module attributes are rebound in this process only.

Checkpoints after every claims file, so a run that is killed leaves the files it has measured
rather than nothing.

    uv run --with pyyaml --with pydantic --with platformdirs python profile_baseline.py [--limit N]
"""

from __future__ import annotations

import argparse
import collections
import pathlib
import subprocess
import sys
import time
import types

import _bench

sys.path.insert(0, str(_bench.REPO_ROOT / "packages/citations/src"))
sys.path.insert(0, str(_bench.REPO_ROOT / "packages/provenance-core/src"))

from citations import verify as V
from citations.models import load_claim_file

NAME = "01_baseline_profile"


class Ledger:
    """What each seam cost, kept as totals plus a per-call list for the extractor."""

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.hash_seconds = 0.0
        self.hash_calls = 0
        self.hash_bytes = 0
        self.match_seconds = 0.0
        self.match_calls = 0

    def subprocess_seconds(self) -> float:
        return sum(c["seconds"] for c in self.calls)

    def by_kind(self) -> dict:
        out: dict[str, dict] = {}
        for c in self.calls:
            row = out.setdefault(c["kind"], {"calls": 0, "seconds": 0.0, "stdout_bytes": 0})
            row["calls"] += 1
            row["seconds"] += c["seconds"]
            row["stdout_bytes"] += c["stdout_bytes"]
        return out

    def by_artifact(self) -> dict:
        out: dict[str, dict] = {}
        for c in self.calls:
            row = out.setdefault(c["artifact"], {"calls": 0, "seconds": 0.0, "page_calls": 0})
            row["calls"] += 1
            row["seconds"] += c["seconds"]
            row["page_calls"] += int(c["kind"] == "page")
        return dict(sorted(out.items(), key=lambda kv: -kv[1]["seconds"]))


def install(ledger: Ledger) -> None:
    """Rebind the three seams inside `citations.verify` for this process."""
    real_run = subprocess.run
    real_hash = V.sha256_of_file
    real_resolve = V.resolve_in

    def timed_run(argv, **kw):
        t0 = time.perf_counter()
        proc = real_run(argv, **kw)
        dt = time.perf_counter() - t0
        page = None
        if "-f" in argv:
            page = argv[argv.index("-f") + 1]
        ledger.calls.append(
            {
                "argv": " ".join(str(a) for a in argv),
                "artifact": pathlib.Path(
                    next((a for a in argv if str(a).endswith((".pdf", ".txt"))), "?")
                ).name,
                "kind": "page" if page else "document",
                "page": int(page) if page else None,
                "seconds": dt,
                "stdout_bytes": len(getattr(proc, "stdout", "") or ""),
            }
        )
        return proc

    def timed_hash(p):
        t0 = time.perf_counter()
        out = real_hash(p)
        ledger.hash_seconds += time.perf_counter() - t0
        ledger.hash_calls += 1
        try:
            ledger.hash_bytes += pathlib.Path(p).stat().st_size
        except OSError:
            pass
        return out

    def timed_resolve(quote, text, prefix="", suffix=""):
        t0 = time.perf_counter()
        out = real_resolve(quote, text, prefix, suffix)
        ledger.match_seconds += time.perf_counter() - t0
        ledger.match_calls += 1
        return out

    V.subprocess = types.SimpleNamespace(
        run=timed_run,
        TimeoutExpired=subprocess.TimeoutExpired,
        CalledProcessError=subprocess.CalledProcessError,
    )
    V.sha256_of_file = timed_hash
    V.resolve_in = timed_resolve


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="only the first N claims files")
    ap.add_argument(
        "--healthy",
        action="store_true",
        help="drop each file's declared extract_cmd, so extraction succeeds and the page and "
        "second-opinion paths are reached. mechval's claims files declare `pdftotext -layout`, "
        "which citations runs as `pdftotext -layout FILE` -- poppler then writes FILE.txt and "
        "prints nothing, so every quotation in the corpus is `unchecked` as it stands.",
    )
    ap.add_argument("--name", default="", help="output basename under data/")
    ap.add_argument(
        "--budget",
        type=float,
        default=0.0,
        help="stop after this many seconds and record what was measured. The healthy path "
        "can spend `PAGE_SCAN_LIMIT` extractions on a single quotation, so an unbounded run "
        "is not guaranteed to terminate inside a working session.",
    )
    a = ap.parse_args()

    name = a.name or (f"{NAME}_healthy" if a.healthy else NAME)
    globals()["NAME"] = name

    env = _bench.envelope(name, ["python", "profile_baseline.py", *sys.argv[1:]])
    env["configuration"] = "healthy (declared extract_cmd dropped)" if a.healthy else "as-declared"
    env["cache_state"] = "cold (no disk cache exists in this build)"
    env["available_extractors"] = V.available_extractors()
    env["page_scan_limit"] = V.PAGE_SCAN_LIMIT
    env["lru_maxsize_extract"] = V.extract.cache_parameters()["maxsize"]

    ledger = Ledger()
    install(ledger)

    files = sorted(_bench.CLAIMS_DIR.glob("*.yaml"))
    if a.limit:
        files = files[: a.limit]

    t_yaml = 0.0
    per_file: list[dict] = []
    verdicts: list[dict] = []
    counts: collections.Counter = collections.Counter()
    t_start = time.perf_counter()

    for path in files:
        t0 = time.perf_counter()
        cf = load_claim_file(path)
        t_yaml += time.perf_counter() - t0

        artifact = cf.artifact()
        t_file = time.perf_counter()
        calls_before = len(ledger.calls)
        sub_before = ledger.subprocess_seconds()
        hash_before = ledger.hash_seconds
        match_before = ledger.match_seconds

        n_quotes = 0
        n_paged = 0
        for cid, claim in cf.claims.items():
            for q in claim.quotes:
                if not q.text:
                    continue
                n_quotes += 1
                n_paged += int(q.page is not None)
                r = V.check_one(
                    q.text,
                    artifact,
                    q.page,
                    None if a.healthy else cf.source.extract_cmd,
                    V.DEFAULT_EXTRACTORS,
                    False,
                    q.prefix,
                    q.suffix,
                )
                counts[r.state] += 1
                verdicts.append(
                    {
                        "file": path.name,
                        "claim": cid,
                        "quote": q.text[:80],
                        "state": r.state,
                        "extractor": r.extractor,
                        "warnings": sorted(r.warnings),
                        "page_found": r.page_found,
                    }
                )

        per_file.append(
            {
                "file": path.name,
                "artifact": artifact.name if artifact else None,
                "artifact_bytes": artifact.stat().st_size if artifact and artifact.exists() else 0,
                "quotes": n_quotes,
                "quotes_with_page": n_paged,
                "wall_seconds": time.perf_counter() - t_file,
                "subprocess_calls": len(ledger.calls) - calls_before,
                "subprocess_seconds": ledger.subprocess_seconds() - sub_before,
                "hash_seconds": ledger.hash_seconds - hash_before,
                "match_seconds": ledger.match_seconds - match_before,
            }
        )

        # Checkpoint inside the unit of work, not after it.
        env["budget_seconds"] = a.budget or None
        env["partial"] = True
        env["files_done"] = len(per_file)
        env["files_total"] = len(files)
        env["elapsed_seconds"] = time.perf_counter() - t_start
        env["per_file"] = per_file
        env["totals"] = _totals(ledger, t_yaml, env["elapsed_seconds"], counts)
        _bench.write(name, env)
        print(
            f"  {path.name:<32} {per_file[-1]['wall_seconds']:8.1f}s  "
            f"{per_file[-1]['subprocess_calls']:6,} subprocesses "
            f"({per_file[-1]['subprocess_calls'] - _page_calls(ledger, calls_before)} document, "
            f"{_page_calls(ledger, calls_before)} page)",
            flush=True,
        )
        if a.budget and (time.perf_counter() - t_start) > a.budget:
            env["stopped_on_budget"] = True
            break

    total = time.perf_counter() - t_start
    env["partial"] = False
    env["elapsed_seconds"] = total
    env["totals"] = _totals(ledger, t_yaml, total, counts)
    env["subprocess_by_kind"] = ledger.by_kind()
    env["subprocess_by_artifact"] = ledger.by_artifact()
    env["page_scan_histogram"] = _page_histogram(ledger)
    env["verdict_counts"] = dict(counts)
    env["results_digest"] = _bench.results_digest(verdicts)
    env["verdicts"] = verdicts
    out = _bench.write(name, env)

    t = env["totals"]
    print(f"\nwrote {out}")
    print(f"  total wall           {total:10.1f}s")
    print(
        f"  extractor subprocess {t['subprocess_seconds']:10.1f}s  {t['subprocess_calls']:,} calls"
    )
    print(f"  sha256 of artifacts  {t['hash_seconds']:10.1f}s  {t['hash_calls']:,} calls")
    print(f"  matching             {t['match_seconds']:10.1f}s  {t['match_calls']:,} calls")
    print(f"  yaml load            {t['yaml_seconds']:10.1f}s")
    print(f"  unaccounted          {t['unaccounted_seconds']:10.1f}s")
    return 0


def _page_calls(ledger: Ledger, since: int) -> int:
    return sum(1 for c in ledger.calls[since:] if c["kind"] == "page")


def _totals(ledger: Ledger, t_yaml: float, total: float, counts) -> dict:
    sub = ledger.subprocess_seconds()
    return {
        "wall_seconds": total,
        "subprocess_seconds": sub,
        "subprocess_calls": len(ledger.calls),
        "hash_seconds": ledger.hash_seconds,
        "hash_calls": ledger.hash_calls,
        "hash_bytes": ledger.hash_bytes,
        "match_seconds": ledger.match_seconds,
        "match_calls": ledger.match_calls,
        "yaml_seconds": t_yaml,
        "unaccounted_seconds": total - sub - ledger.hash_seconds - ledger.match_seconds - t_yaml,
        "verdicts": dict(counts),
    }


def _page_histogram(ledger: Ledger) -> dict:
    """How many page extractions each artifact paid for, and the highest page reached."""
    out: dict[str, dict] = {}
    for c in ledger.calls:
        if c["kind"] != "page":
            continue
        row = out.setdefault(c["artifact"], {"page_calls": 0, "max_page": 0, "seconds": 0.0})
        row["page_calls"] += 1
        row["max_page"] = max(row["max_page"], c["page"] or 0)
        row["seconds"] += c["seconds"]
    return dict(sorted(out.items(), key=lambda kv: -kv[1]["page_calls"]))


if __name__ == "__main__":
    raise SystemExit(main())
