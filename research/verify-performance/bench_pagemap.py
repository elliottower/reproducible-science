"""Canary: is a whole-document extraction's page split the same text as a per-page extraction?

The entire per-page optimization rests on this. `pdftotext` writes U+000C between pages, so
`full.split("\\f")[p-1]` should equal what `pdftotext -f p -l p` prints, with its trailing form
feed removed. If that is false on any page of any artifact, the page map is not a substitute
for the subprocess and the optimization is unsound.

Every page of every artifact in the corpus is checked, not a sample. A canary that only looks
at page 1 cannot fail on the case that matters, which is a document whose page boundaries do
not line up.

    python bench_pagemap.py
"""

from __future__ import annotations

import pathlib
import subprocess
import sys
import time

import _bench

sys.path.insert(0, str(_bench.REPO_ROOT / "packages/citations/src"))
sys.path.insert(0, str(_bench.REPO_ROOT / "packages/provenance-core/src"))

from citations.models import load_claim_file

NAME = "02_pagemap_canary"


def whole(pdf: pathlib.Path) -> str:
    r = subprocess.run(
        ["pdftotext", "-layout", str(pdf), "-"], capture_output=True, text=True, timeout=300
    )
    return r.stdout if r.returncode == 0 else ""


def one_page(pdf: pathlib.Path, p: int) -> str:
    r = subprocess.run(
        ["pdftotext", "-layout", "-f", str(p), "-l", str(p), str(pdf), "-"],
        capture_output=True,
        text=True,
        timeout=300,
    )
    return r.stdout if r.returncode == 0 else ""


def main() -> int:
    env = _bench.envelope(NAME, ["python", "bench_pagemap.py"])

    artifacts: list[pathlib.Path] = []
    for path in sorted(_bench.CLAIMS_DIR.glob("*.yaml")):
        art = load_claim_file(path).artifact()
        if art and art.exists() and art.suffix.lower() == ".pdf" and art not in artifacts:
            artifacts.append(art)

    rows: list[dict] = []
    mismatches: list[dict] = []
    t_page = 0.0
    t_whole = 0.0
    pages_checked = 0

    for pdf in artifacts:
        t0 = time.perf_counter()
        full = whole(pdf)
        t_whole += time.perf_counter() - t0
        pages = full.split("\f")
        n = len(pages) - 1 if pages and pages[-1] == "" else len(pages)
        bad = 0
        t1 = time.perf_counter()
        for p in range(1, n + 1):
            got = one_page(pdf, p).rstrip("\f")
            pages_checked += 1
            if got != pages[p - 1]:
                bad += 1
                if len(mismatches) < 20:
                    mismatches.append(
                        {
                            "artifact": pdf.name,
                            "page": p,
                            "subprocess_len": len(got),
                            "pagemap_len": len(pages[p - 1]),
                        }
                    )
        dt = time.perf_counter() - t1
        t_page += dt
        rows.append(
            {
                "artifact": pdf.name,
                "bytes": pdf.stat().st_size,
                "pages": n,
                "mismatched_pages": bad,
                "whole_document_seconds": None,
                "per_page_seconds": dt,
            }
        )
        env["partial"] = True
        env["per_artifact"] = rows
        env["mismatches"] = mismatches
        _bench.write(NAME, env)
        print(f"  {pdf.name:<48} {n:>4} pages  {bad} mismatched  {dt:6.1f}s", flush=True)

    env["partial"] = False
    env["artifacts"] = len(artifacts)
    env["pages_checked"] = pages_checked
    env["mismatched_pages"] = sum(r["mismatched_pages"] for r in rows)
    env["page_map_is_equivalent"] = env["mismatched_pages"] == 0
    env["totals_seconds"] = {
        "whole_document_extractions": t_whole,
        "per_page_extractions": t_page,
        "ratio_per_page_over_whole": (t_page / t_whole) if t_whole else None,
    }
    out = _bench.write(NAME, env)
    print(f"\nwrote {out}")
    print(f"  {pages_checked:,} pages over {len(artifacts)} artifacts")
    print(f"  mismatched: {env['mismatched_pages']}")
    print(f"  whole-document extractions {t_whole:8.1f}s")
    print(f"  per-page extractions       {t_page:8.1f}s  ({t_page / t_whole:.0f}x)")
    return 0 if env["page_map_is_equivalent"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
