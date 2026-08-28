"""A prototype `verify` pipeline: extract once, address by content, reuse, parallelize misses.

Reproduces the verdicts `citations.verify.check_one` reaches, with four changes to how it gets
there. Each is measured separately in `bench_matrix.py`; the verdicts are hashed and compared
against the current implementation's, because a faster run that decides differently is not a
faster run of the same check.

    one extraction per artifact      `pdftotext` writes U+000C between pages, so the whole
                                     document already carries every page boundary. The current
                                     `_page_text` spawns one process per page instead, up to
                                     `PAGE_SCAN_LIMIT`.
    unique jobs, not quotations      the schedulable unit is (artifact digest, extractor), so
                                     183 quotations against one PDF are one extraction.
    two content-addressed caches     a rendition survives an edited quotation; a verdict does
                                     not survive an edited quotation, a changed matcher, or a
                                     different rendition.
    failures cached too              `functools.lru_cache` does not memoize a raised
                                     exception, so a source that cannot be read is re-read
                                     once per quotation. On this corpus that is the single
                                     largest cost and it buys nothing.

Every result carries `origin`: `executed` or `reused`. A reused deterministic result over
identical inputs is the same computation, so it is not reported as a weaker verdict -- but it
is never reported as a fresh execution either. Provenance and verdict are separate fields.
"""

from __future__ import annotations

import collections
import dataclasses
import pathlib
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import _bench
import rendition as R

sys.path.insert(0, str(_bench.REPO_ROOT / "packages/citations/src"))
sys.path.insert(0, str(_bench.REPO_ROOT / "packages/provenance-core/src"))

from citations import verify as V
from citations.models import load_claim_file

LAYOUT = "pdftotext -layout"
READING_ORDER = "pdftotext"


@dataclasses.dataclass
class Job:
    """One artifact to be read by one extractor. The unit of scheduling."""

    artifact: pathlib.Path
    artifact_sha256: str
    extractor: R.ExtractorIdentity
    label: str


@dataclasses.dataclass
class Timings:
    yaml: float = 0.0
    hashing: float = 0.0
    rendition_wall: float = 0.0
    check_wall: float = 0.0
    flush: float = 0.0
    total: float = 0.0


def _identity(label: str) -> R.ExtractorIdentity:
    return R.poppler_identity(layout=label == LAYOUT)


def _verdict_from_rendition(
    quote: str,
    rend: R.Rendition,
    page: int | None,
    prefix: str,
    suffix: str,
    extractor_label: str,
) -> dict:
    """`verify._verdict`, with the page map standing in for the per-page subprocess.

    The matching primitives are imported rather than reimplemented. A second normalizer is how
    `-0.42` and `0.42` end up folded together in one place and not the other.
    """
    warn: list[str] = []
    text = quote.strip()
    if len(text) < V.MIN_QUOTE_CHARS or text.endswith(
        (",", " and", " or", " but", " the", " a", " of", " for", " with")
    ):
        warn.append("short")

    q, doc = V.fold(quote), V.fold(rend.text)
    if not q:
        return _row("not found", "the quotation is empty after normalization", warn)

    m = V.resolve_in(quote, rend.text, prefix, suffix)
    if m.normalized:
        warn.append("normalized")
    if m.state == "ambiguous":
        return _row("ambiguous", V._ambiguous(m.count, bool(prefix or suffix)), warn)
    if m.state == "not found":
        return _row(
            "not found",
            "read the source: a broken extraction reads the same as a passage that was never there",
            warn,
        )
    if m.normalized:
        return _row("found", "", warn)
    if V._cuts_a_token(q, doc):
        warn.append("truncated")
    if page and q not in V.fold(rend.page(page)):
        warn.append("page")
        found_at, capped = _find_page(q, rend)
        detail = f"not on page {page}"
        if found_at is None and capped:
            detail += f"; searched the first {V.PAGE_SCAN_LIMIT} pages"
        return _row("found", detail, warn, found_at)
    return _row("found", "", warn)


def _find_page(folded_quote: str, rend: R.Rendition) -> tuple[int | None, bool]:
    """`verify._find_page` over the page map. Same stopping rule, no subprocesses.

    Stops on the first empty page, exactly as the current implementation does: an extraction
    past the last page prints nothing, which it reads as running off the end.
    """
    for p in range(1, V.PAGE_SCAN_LIMIT + 1):
        text = rend.page(p)
        if not text:
            return None, False
        if folded_quote in V.fold(text):
            return p, False
    return None, True


def _row(state: str, detail: str, warn: list[str], page_found: int | None = None) -> dict:
    return {
        "state": state,
        "detail": detail,
        "warnings": sorted(warn),
        "page_found": page_found,
    }


def run(
    claims_dir: pathlib.Path,
    cache: R.RenditionCache,
    checks: R.CheckCache,
    workers: int = 1,
    use_check_cache: bool = True,
    second_opinion: bool = True,
) -> dict:
    """One verify pass. Returns verdicts in manifest order, plus what it cost."""
    t = Timings()
    t0 = time.perf_counter()

    # --- claims, in a deterministic order -------------------------------------------------
    y0 = time.perf_counter()
    files = sorted(claims_dir.glob("*.yaml"))
    parsed = [(p, load_claim_file(p)) for p in files]
    t.yaml = time.perf_counter() - y0

    # --- unique jobs, hashed once ---------------------------------------------------------
    h0 = time.perf_counter()
    digests: dict[pathlib.Path, str] = {}
    for _, cf in parsed:
        art = cf.artifact()
        if art and art.exists() and art not in digests:
            digests[art] = R.sha256_of_file(art)
    t.hashing = time.perf_counter() - h0

    rends: dict[tuple[pathlib.Path, str], R.Rendition] = {}
    errors: dict[tuple[pathlib.Path, str], str] = {}

    def fetch(job: Job):
        return cache.get(job.artifact, job.extractor, job.artifact_sha256)

    def wave(jobs: list[Job]) -> None:
        """Fetch a set of renditions, bounded, and record which failed.

        Ordering of completion is not ordering of the report: results land in a dict keyed on
        the job, and the report is assembled from the manifest afterwards. A run whose output
        order depends on which thread finished first is not a deterministic substrate.
        """
        if workers <= 1:
            for job in jobs:
                try:
                    rends[(job.artifact, job.label)] = fetch(job)
                except R.CacheError as e:
                    errors[(job.artifact, job.label)] = str(e)
            return
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(fetch, job): job for job in jobs}
            for fut, job in futures.items():
                try:
                    rends[(job.artifact, job.label)] = fut.result()
                except R.CacheError as e:
                    errors[(job.artifact, job.label)] = str(e)

    # --- wave 1: the preferred reading of every artifact ----------------------------------
    r0 = time.perf_counter()
    pdfs = [(a, s) for a, s in digests.items() if a.suffix.lower() != ".txt"]
    first = [Job(a, s, _identity(LAYOUT), LAYOUT) for a, s in pdfs]
    wave(first)

    # --- checks, first pass ---------------------------------------------------------------
    c0 = time.perf_counter()
    slots: list[dict] = []
    pending: list[int] = []
    for path, cf in parsed:
        art = cf.artifact()
        for cid, claim in cf.claims.items():
            for q in claim.quotes:
                if not q.text:
                    continue
                row = _check(q, art, digests, rends, errors, checks, use_check_cache)
                slots.append({"file": path.name, "claim": cid, "q": q, "art": art, "row": row})
                if (
                    second_opinion
                    and row["state"] == "not found"
                    and row["origin"] == "executed"
                    and art is not None
                    and V.is_paginated(art)
                ):
                    pending.append(len(slots) - 1)
    t.check_wall = time.perf_counter() - c0

    # --- wave 2: a second reading, only for artifacts a passage read as absent from -------
    # A second opinion costs an extraction, and it is owed only where the first answer was
    # going to be an accusation. Extracting every document twice unconditionally would pay for
    # it on a corpus that never needs it, which is most corpora.
    if pending:
        need = sorted({slots[i]["art"] for i in pending}, key=str)
        wave([Job(a, digests[a], _identity(READING_ORDER), READING_ORDER) for a in need])
        c1 = time.perf_counter()
        for i in pending:
            slot = slots[i]
            _rescue(slot, rends, checks, use_check_cache)
        t.check_wall += time.perf_counter() - c1
    t.rendition_wall = time.perf_counter() - r0 - t.check_wall

    verdicts = [
        {
            "file": s["file"],
            "claim": s["claim"],
            "quote": s["q"].text[:80],
            "state": s["row"]["state"],
            "extractor": s["row"]["extractor"],
            "warnings": s["row"]["warnings"],
            "page_found": s["row"]["page_found"],
        }
        for s in slots
    ]
    origins: collections.Counter = collections.Counter(s["row"]["origin"] for s in slots)

    f0 = time.perf_counter()
    checks.flush()
    t.flush = time.perf_counter() - f0
    t.total = time.perf_counter() - t0

    return {
        "verdicts": verdicts,
        "results_digest": _bench.results_digest(verdicts),
        "counts": dict(collections.Counter(v["state"] for v in verdicts)),
        "origins": dict(origins),
        "timings_seconds": dataclasses.asdict(t),
        "renditions_requested": len(rends) + len(errors),
        "unique_artifacts": len(digests),
        "unique_artifact_bytes": sum(a.stat().st_size for a in digests),
        "rendition_hits": cache.hits,
        "rendition_misses": cache.misses,
        "extractions": cache.extractions,
        "extract_seconds": cache.extract_seconds,
        "cache_io_seconds": cache.io_seconds,
        "check_hits": checks.hits,
        "check_misses": checks.misses,
        "page_subprocesses": 0,
        "workers": workers,
    }


def _check(q, art, digests, rends, errors, checks, use_check_cache) -> dict:
    """One quotation against the preferred reading. May end `not found` pending a second one."""
    if art is None or not art.exists():
        return {**_row("unchecked", "file not found", []), "origin": "executed", "extractor": ""}

    # `check_one` passes `page if paginated else None`, so a page recorded against a `.txt`
    # is never checked. Reproduced here rather than reinvented: warning `page` on an
    # unpaginated source would be a verdict the current implementation does not reach.
    page = q.page if V.is_paginated(art) else None

    if art.suffix.lower() in V.TEXT_SUFFIXES:
        text = art.read_text(errors="replace")
        rend = R.Rendition(
            text,
            R.hashlib.sha256(text.encode()).hexdigest(),
            (text,),
            R.ExtractorIdentity("text", "", ()),
            digests[art],
            "",
            "executed",
        )
        label = V.PLAIN_TEXT
    else:
        rend = rends.get((art, LAYOUT))
        label = LAYOUT
        if rend is None:
            return {
                **_row("unchecked", errors.get((art, LAYOUT), "no reader"), []),
                "origin": "executed",
                "extractor": "",
            }

    key = R.check_key(rend.text_sha256, q.text, q.prefix, q.suffix, page)
    if use_check_cache:
        hit = checks.get(rend.text_sha256, key)
        if hit is not None:
            return {**hit, "origin": "reused"}

    row = _verdict_from_rendition(q.text, rend, page, q.prefix, q.suffix, label)
    row["extractor"] = label
    row["_key"] = key
    row["_rendition"] = rend.text_sha256
    row["_page"] = page

    # A `not found` is not written to the check cache here. The second opinion has not been
    # taken yet, and caching the interim answer would persist a verdict the run itself is about
    # to overturn -- the one way a cache turns a correct implementation into a wrong one.
    if use_check_cache and row["state"] != "not found":
        checks.put(rend.text_sha256, key, _clean(row))
    return {**row, "origin": "executed"}


def _clean(row: dict) -> dict:
    """The verdict without the bookkeeping the cache has no business storing."""
    return {k: v for k, v in row.items() if not k.startswith("_") and k != "origin"}


def _rescue(slot: dict, rends: dict, checks, use_check_cache: bool) -> None:
    """Ask the reading-order rendition about a passage `-layout` reported absent.

    `-layout` preserves a page's geometry, so on a two-column paper it interleaves the columns
    and shreds every sentence crossing the gutter. The other mode preserves the sentence. Only
    reached where the first answer was going to be an accusation against the manuscript.
    """
    q, art, row = slot["q"], slot["art"], slot["row"]
    other = rends.get((art, READING_ORDER))
    if other is not None and V.resolve_in(q.text, other.text, q.prefix, q.suffix).state == "found":
        new = _verdict_from_rendition(
            q.text, other, row["_page"], q.prefix, q.suffix, READING_ORDER
        )
        new["extractor"] = READING_ORDER
        new["origin"] = "executed"
        slot["row"] = {**new, "_key": row["_key"], "_rendition": row["_rendition"]}
    if use_check_cache:
        checks.put(row["_rendition"], row["_key"], _clean(slot["row"]))
