"""How much of an extractor invocation is the process, and how much is the PDF?

`_find_page` spawns one `pdftotext` per page. Whether that is expensive because of poppler or
because of the spawn changes which fix is the right one, so the two are separated here:

    /usr/bin/true          fork + exec + exit, and nothing else
    pdftotext -v           the same, plus loading poppler and its dependencies
    pdftotext -f 1 -l 1    the above, plus opening the document and parsing its xref
    pdftotext (whole doc)  the above, plus rendering every page

The gap between the second and third rows is what a page extraction pays before it produces a
character of the page it was asked for -- paid once per page, `PAGE_SCAN_LIMIT` times in the
worst case.

    python bench_spawn.py
"""

from __future__ import annotations

import pathlib
import statistics
import subprocess
import sys
import time

import _bench

sys.path.insert(0, str(_bench.REPO_ROOT / "packages/citations/src"))
sys.path.insert(0, str(_bench.REPO_ROOT / "packages/provenance-core/src"))

from citations.models import load_claim_file

NAME = "04_spawn"
REPS = 40


def timed(argv: list[str], reps: int = REPS) -> dict:
    samples = []
    for _ in range(reps):
        t0 = time.perf_counter()
        subprocess.run(argv, capture_output=True, timeout=300)
        samples.append(time.perf_counter() - t0)
    return {
        "argv": " ".join(argv),
        "reps": reps,
        "median_seconds": statistics.median(samples),
        "min_seconds": min(samples),
        "max_seconds": max(samples),
        "mean_seconds": statistics.fmean(samples),
    }


def main() -> int:
    env = _bench.envelope(NAME, ["python", "bench_spawn.py"])

    artifacts: list[pathlib.Path] = []
    for p in sorted(_bench.CLAIMS_DIR.glob("*.yaml")):
        art = load_claim_file(p).artifact()
        if art and art.exists() and art.suffix.lower() == ".pdf" and art not in artifacts:
            artifacts.append(art)
    artifacts.sort(key=lambda p: p.stat().st_size)
    small, large = artifacts[0], artifacts[-1]

    rows = [
        timed(["/usr/bin/true"]),
        timed(["pdftotext", "-v"]),
        timed(["pdftotext", "-layout", "-f", "1", "-l", "1", str(small), "-"], reps=20),
        timed(["pdftotext", "-layout", str(small), "-"], reps=10),
        timed(["pdftotext", "-layout", "-f", "1", "-l", "1", str(large), "-"], reps=20),
        timed(["pdftotext", "-layout", str(large), "-"], reps=10),
    ]
    for r, note in zip(  # noqa: B905
        rows,
        [
            "fork+exec floor",
            "spawn + load poppler",
            f"one page of {small.name} ({small.stat().st_size:,} B)",
            f"whole {small.name}",
            f"one page of {large.name} ({large.stat().st_size:,} B)",
            f"whole {large.name}",
        ],
    ):
        r["note"] = note

    env["rows"] = rows
    env["smallest_artifact"] = {"name": small.name, "bytes": small.stat().st_size}
    env["largest_artifact"] = {"name": large.name, "bytes": large.stat().st_size}
    env["spawn_floor_seconds"] = rows[0]["median_seconds"]
    env["poppler_load_seconds"] = rows[1]["median_seconds"] - rows[0]["median_seconds"]
    env["page_open_cost_seconds"] = {
        small.name: rows[2]["median_seconds"] - rows[1]["median_seconds"],
        large.name: rows[4]["median_seconds"] - rows[1]["median_seconds"],
    }
    env["pages_per_whole_document"] = {
        small.name: rows[3]["median_seconds"] / rows[2]["median_seconds"],
        large.name: rows[5]["median_seconds"] / rows[4]["median_seconds"],
    }
    out = _bench.write(NAME, env)
    print(f"wrote {out}")
    for r in rows:
        print(f"  {r['note']:<48} {r['median_seconds'] * 1000:9.1f} ms median")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
