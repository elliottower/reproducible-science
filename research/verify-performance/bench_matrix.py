"""The experiment matrix: cold, warm, worker sweep, and the four invalidation cases.

Every configuration writes its verdicts' canonical digest beside its timings, so "faster" and
"same answer" are separate columns. A configuration whose digest differs from the cold serial
run is a divergence to explain, not a speedup to report.

    C   prototype, cold caches, workers=1
    D   prototype, warm renditions + warm checks
    D2  warm renditions, cold checks -- what the rendition layer alone is worth
    E-H cold renditions, workers = 1, 2, 4, 8, logical
    I   fully unchanged incremental run
    J   one quotation changed       -> that check misses, no rendition does
    K   one artifact changed        -> its rendition misses, its checks miss
    L   extractor identity changed  -> every rendition misses, then every check
    M   matching policy changed     -> every check misses, no rendition does

J-M prove invalidation. A warm run that is fast proves nothing on its own: a cache that never
misses is a cache that cannot be wrong about a change, which is the failure this matrix exists
to rule out.

Cold means *the prototype's caches are empty*. The operating system's file cache is not
cleared: `purge` needs root, and no real run starts from a cleared page cache. The two senses
are labelled rather than conflated.

    python bench_matrix.py [--only C,D,E]
"""

from __future__ import annotations

import argparse
import os
import pathlib
import shutil
import sys
import tempfile
import time

import _bench
import pipeline
import rendition as R

NAME = "03_matrix"


def fresh(tmp: pathlib.Path, tag: str) -> tuple[R.RenditionCache, R.CheckCache]:
    root = tmp / tag
    if root.exists():
        shutil.rmtree(root)
    return R.RenditionCache(root / "renditions"), R.CheckCache(root / "checks")


def cloned(tmp: pathlib.Path, tag: str) -> tuple[R.RenditionCache, R.CheckCache]:
    """A copy of the warm cache, so one invalidation case cannot warm the next."""
    root = tmp / tag
    if root.exists():
        shutil.rmtree(root)
    shutil.copytree(tmp / "main", root)
    return R.RenditionCache(root / "renditions"), R.CheckCache(root / "checks")


def existing(tmp: pathlib.Path, tag: str) -> tuple[R.RenditionCache, R.CheckCache]:
    root = tmp / tag
    return R.RenditionCache(root / "renditions"), R.CheckCache(root / "checks")


def variant_corpus(tmp: pathlib.Path, tag: str, edit_first_quote=False, edit_artifact=False):
    """A corpus that differs from the real one in exactly one way.

    Built as a directory of copies beside a `reference/` of symlinks, so nothing under
    the reference corpus is touched. `ClaimFile.artifact()` resolves against the parent
    of the claims directory, which is why the shape is reproduced rather than faked.
    """
    root = tmp / "corpora" / tag
    if root.exists():
        shutil.rmtree(root)
    (root / "claims").mkdir(parents=True)
    (root / "reference").mkdir(parents=True)

    files = sorted(_bench.CLAIMS_DIR.glob("*.yaml"))
    for p in files:
        shutil.copy2(p, root / "claims" / p.name)

    victim_pdf = None
    for src in _bench.REFERENCE_DIR.iterdir():
        if src.is_file():
            (root / "reference" / src.name).symlink_to(src)

    if edit_first_quote:
        # One character added to one quotation. A new check key, the same rendition key.
        target = root / "claims" / files[0].name
        text = target.read_text()
        marker = "    - exact: "
        at = text.index(marker) + len(marker)
        target.write_text(text[:at] + "the " + text[at:])

    if edit_artifact:
        # One artifact's bytes changed. Its rendition key changes and nothing else does.
        cf = pipeline.load_claim_file(root / "claims" / files[0].name)
        art = cf.artifact()
        victim_pdf = art.name
        link = root / "reference" / art.name
        real = link.resolve()
        link.unlink()
        link.write_bytes(real.read_bytes() + b"\n%% one appended comment\n")

    return root / "claims", victim_pdf


def measure(label: str, note: str, fn) -> dict:
    # Child CPU as well as wall clock. This machine had other agents' `citations verify`
    # runs on it while these numbers were taken, and wall clock under contention says as
    # much about the neighbours as about the change; child CPU does not move with load.
    c0 = os.times()
    t0 = time.perf_counter()
    got = fn()
    c1 = os.times()
    got["label"] = label
    got["note"] = note
    got["wall_seconds"] = time.perf_counter() - t0
    got["child_cpu_seconds"] = (c1.children_user - c0.children_user) + (
        c1.children_system - c0.children_system
    )
    got["self_cpu_seconds"] = (c1.user - c0.user) + (c1.system - c0.system)
    rt = got["rendition_hits"] + got["rendition_misses"]
    ct = got["check_hits"] + got["check_misses"]
    print(
        f"  {label:<4} {note:<42} {got['wall_seconds']:8.2f}s wall "
        f"{got['child_cpu_seconds']:7.2f}s child-cpu  "
        f"rend {got['rendition_hits']:>3}/{rt:<3} hit  "
        f"check {got['check_hits']:>5}/{ct:<5} hit  {got['results_digest'][:10]}",
        flush=True,
    )
    return got


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="", help="comma-separated labels")
    a = ap.parse_args()
    want = set(a.only.split(",")) if a.only else None

    env = _bench.envelope(NAME, ["python", "bench_matrix.py", *sys.argv[1:]])
    env["cold_means"] = (
        "the prototype's own caches are empty. The OS file cache is not cleared: `purge` "
        "needs root and no real run starts from a cleared page cache."
    )
    env["concurrent_load"] = _concurrent()
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="verifyperf-"))
    env["cache_root"] = str(tmp)
    runs: list[dict] = []

    def keep(label: str) -> bool:
        return want is None or label in want

    def record():
        env["runs"] = runs
        env["partial"] = True
        _bench.write(NAME, env)

    claims = _bench.CLAIMS_DIR

    if keep("C"):
        c, k = fresh(tmp, "main")
        runs.append(measure("C", "cold caches, workers=1", lambda: pipeline.run(claims, c, k, 1)))
        runs[-1]["rendition_cache_bytes"] = c.size_bytes()
        runs[-1]["rendition_entries"] = c.entries()
        runs[-1]["check_cache_bytes"] = k.size_bytes()
        record()

    if keep("D"):
        c, k = existing(tmp, "main")
        runs.append(
            measure("D", "warm renditions + warm checks", lambda: pipeline.run(claims, c, k, 1))
        )
        record()

    if keep("D2"):
        c, _ = existing(tmp, "main")
        k2 = R.CheckCache(tmp / "checks-empty")
        runs.append(
            measure("D2", "warm renditions, cold checks", lambda: pipeline.run(claims, c, k2, 1))
        )
        record()

    logical = os.cpu_count() or 8
    for label, w in zip(["E", "F", "G", "H", "H2"], [1, 2, 4, 8, logical], strict=True):
        if not keep(label) or (label == "H2" and logical == 8):
            continue
        c, k = fresh(tmp, f"w{w}")
        runs.append(
            measure(
                label,
                f"cold renditions, workers={w}",
                lambda c=c, k=k, w=w: pipeline.run(claims, c, k, w, use_check_cache=False),
            )
        )
        record()

    if keep("I"):
        c, k = cloned(tmp, "case-I")
        runs.append(
            measure("I", "unchanged incremental run", lambda: pipeline.run(claims, c, k, 1))
        )
        record()

    if keep("J"):
        c, k = cloned(tmp, "case-J")
        cdir, _ = variant_corpus(tmp, "J", edit_first_quote=True)
        runs.append(measure("J", "one quotation changed", lambda: pipeline.run(cdir, c, k, 1)))
        record()

    if keep("K"):
        c, k = cloned(tmp, "case-K")
        cdir, victim = variant_corpus(tmp, "K", edit_artifact=True)
        runs.append(measure("K", "one artifact changed", lambda: pipeline.run(cdir, c, k, 1)))
        runs[-1]["changed_artifact"] = victim
        record()

    if keep("L"):
        c, k = cloned(tmp, "case-L")
        real = R.poppler_identity

        def bumped(layout: bool = True):
            got = real(layout)
            return R.ExtractorIdentity(got.backend, got.version + " (pretend 27.0)", got.arguments)

        pipeline.R.poppler_identity = bumped
        try:
            runs.append(
                measure("L", "extractor identity changed", lambda: pipeline.run(claims, c, k, 1))
            )
        finally:
            pipeline.R.poppler_identity = real
        record()

    if keep("M"):
        c, k = cloned(tmp, "case-M")
        real_v = R.MATCHING_POLICY_VERSION
        R.MATCHING_POLICY_VERSION = real_v + "+bumped"
        try:
            runs.append(
                measure("M", "matching policy changed", lambda: pipeline.run(claims, c, k, 1))
            )
        finally:
            R.MATCHING_POLICY_VERSION = real_v
        record()

    env["partial"] = False
    env["runs"] = runs
    unchanged = [r for r in runs if r["label"] not in ("J", "K")]
    env["digests_agree_where_inputs_unchanged"] = len({r["results_digest"] for r in unchanged}) == 1
    env["distinct_digests"] = sorted({r["results_digest"] for r in runs})
    out = _bench.write(NAME, env)
    print(f"\nwrote {out}")
    print(
        "  every configuration with unchanged inputs reached the same verdicts: "
        f"{env['digests_agree_where_inputs_unchanged']}"
    )
    return 0


def _concurrent() -> list[str]:
    """Other work on this machine while the numbers were taken. Contention is not noise to be
    averaged away; it is a fact about the measurement and belongs in the file with it."""
    import subprocess

    try:
        ps = subprocess.run(["ps", "-Ao", "comm"], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return []
    names = [line.strip() for line in ps.stdout.splitlines()]
    return sorted({n for n in names if "pdftotext" in n or "citations" in n})


if __name__ == "__main__":
    raise SystemExit(main())
