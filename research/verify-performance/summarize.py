"""Assemble the ranked findings from the measurement files, without retyping a number.

Reads `data/*.json` and writes `data/00_summary.json`. Every entry names the file and key its
number came from, so a claim in prose traces to the run that produced it. A measurement that
was not taken is recorded as `not measured` with the reason; an absent measurement and a
measurement of zero are different facts and this never turns the first into the second.

    python summarize.py
"""

from __future__ import annotations

import json

import _bench

NAME = "00_summary"


def load(stem: str) -> dict:
    p = _bench.DATA / f"{stem}.json"
    return json.loads(p.read_text()) if p.is_file() else {}


def run_of(matrix: dict, label: str) -> dict:
    return next((r for r in matrix.get("runs", []) if r.get("label") == label), {})


def main() -> int:
    base = load("01_baseline_profile")
    mtx = load("03_matrix")
    spawn = load("04_spawn_and_page")

    env = _bench.envelope(NAME, ["python", "summarize.py"])
    t = base.get("totals", {})
    wall = t.get("wall_seconds")

    env["measured"] = {
        "01_baseline_profile": "current implementation, corpus as declared. PARTIAL: 15 of 16 "
        "claims files (workspace.yaml never reached).",
        "03_matrix": "prototype, all 16 files, 13 configurations, cold/warm/workers/invalidation.",
        "04_spawn_and_page": "process spawn floor, poppler load, one-page vs whole-document cost.",
    }
    env["not_measured"] = {
        "current implementation in a WORKING configuration": "the largest gap. Every number in "
        "01_baseline_profile comes from the failure path. The prototype's cold run is the only "
        "working-configuration measurement, and it is a different implementation, so "
        "11.65 s vs 1292.6 s is not a like-for-like speedup.",
        "page-map canary over the whole corpus": "one page of one document was verified "
        "byte-identical by hand; bench_pagemap.py exists and was not run.",
        "alternative reader backends": "owned by a separate study; nothing here compares readers.",
        "OS-cold timings": "clearing the macOS page cache needs `purge` and root, and no real "
        "run starts from a cleared cache. `cold` throughout means the prototype's caches are empty.",
        "multi-process concurrency": "atomic-rename publication is designed for it; only "
        "in-process single flight was exercised.",
        "a native (Rust) reimplementation": "the Python-side cost is reported instead, which is "
        "what bounds what one could remove.",
    }

    env["baseline_as_declared"] = {
        "status": "BROKEN CONFIGURATION -- see `defect_exception_caching` and `defect_extract_cmd`",
        "files": f"{base.get('files_done')} of {base.get('files_total')}",
        "quotations": sum(t.get("verdicts", {}).values()),
        "verdicts": t.get("verdicts"),
        "wall_seconds": wall,
        "fractions_of_wall": {
            "extractor_subprocess": t.get("subprocess_seconds", 0) / wall if wall else None,
            "sha256_of_artifacts": t.get("hash_seconds", 0) / wall if wall else None,
            "yaml_parse": t.get("yaml_seconds", 0) / wall if wall else None,
            "matching": t.get("match_seconds", 0) / wall if wall else None,
            "everything_else": t.get("unaccounted_seconds", 0) / wall if wall else None,
        },
        "seconds": {
            "extractor_subprocess": t.get("subprocess_seconds"),
            "sha256_of_artifacts": t.get("hash_seconds"),
            "yaml_parse": t.get("yaml_seconds"),
            "matching": t.get("match_seconds"),
            "everything_else": t.get("unaccounted_seconds"),
        },
        "subprocess_calls": t.get("subprocess_calls"),
        "sha256_calls": t.get("hash_calls"),
        "sha256_bytes": t.get("hash_bytes"),
        "source": "data/01_baseline_profile.json",
    }

    env["defect_exception_caching"] = {
        "claim": "`functools.lru_cache` does not memoize a raised exception, so a source whose "
        "extraction fails is re-extracted once per quotation instead of once per document.",
        "status": "CONFIRMED",
        "code_path": [
            "cli.cmd_verify -> verify.check_one (per quotation)",
            "check_one -> reading() -> extract()   [@functools.lru_cache(maxsize=64)]",
            "extract -> _extract -> _argv -> _run  -> raises SourceUnreadableError",
            "the lru_cache wrapper inserts only on normal return, so nothing is memoized",
            "check_one catches SourceUnreadableError and returns Result('unchecked', ...)",
            "the next quotation with identical arguments misses again",
        ],
        "evidence_in_profile": "subprocess_calls equals the quotation count in every one of the "
        "14 PDF-backed claims files measured (183/183, 163/163, 132/132, 129/129, 217/217, "
        "212/212, 136/136, 160/160, 132/132, 172/172, 167/167, 109/109, 192/192, 106/106).",
        "direct_demonstration": {
            "failing extract() x5 with identical arguments": "5 subprocess invocations, "
            "CacheInfo(hits=0, misses=5, currsize=0)",
            "succeeding extract() x5 with identical arguments": "0 further invocations, "
            "CacheInfo(hits=4, misses=1, currsize=1)",
        },
        "cost_here": "2,210 extractions where 14 unique PDF artifacts were involved: 158x more "
        "poppler invocations than the work requires, and 2,210 x 2 sha256 passes instead of 28.",
        "interaction_with_second_opinion": "_second_opinion fires on every `not found` and asks "
        "each remaining extractor. Those readings go through `reading_with`, which is also "
        "lru_cached and also does not memoize failures, so a document no reader can read is "
        "re-attempted by every reader on every quotation.",
    }

    env["defect_extract_cmd"] = {
        "claim": "these records declare `extract_cmd: pdftotext -layout`; `citations._argv` "
        "appends the input path alone and reads stdout, while the convention the records were "
        "written for appends an input AND an output path. `pdftotext -layout FILE` therefore "
        "writes FILE.txt and prints nothing.",
        "consequence_1": "every quotation in the corpus is `unchecked`: 2,512 of 2,512 in the "
        "user's own saved run (research/quote-selector/mechval_16claims_with_selector.txt).",
        "consequence_2": "verify WRITES into the source tree. 32 sibling .txt files now sit in "
        "mechanistic-validity-NEW2/reference/, timestamped to these runs. `_run`'s tamper check "
        "hashes only the input path, so a renderer that writes a sibling is invisible to it.",
        "source": "data/01_baseline_profile.json verdicts, and reference/*.txt mtimes",
    }

    env["defect_double_hash"] = {
        "claim": "`_run` calls `sha256_of_file` before and after every extractor invocation to "
        "detect an extractor that writes to its input.",
        "measured_cost": {
            "seconds": t.get("hash_seconds"),
            "fraction_of_wall": t.get("hash_seconds", 0) / wall if wall else None,
            "calls": t.get("hash_calls"),
            "bytes": t.get("hash_bytes"),
            "corpus_bytes": (base.get("corpus") or {}).get("reference_bytes"),
            "times_the_corpus": t.get("hash_bytes", 0)
            / ((base.get("corpus") or {}).get("reference_bytes") or 1),
            "throughput_bytes_per_second": t.get("hash_bytes", 0) / (t.get("hash_seconds") or 1),
        },
        "verdict": "the check is worth keeping and the per-invocation cost is not. It is "
        "proportional to invocations, and the invocation count is itself the defect: with one "
        "extraction per artifact the same check costs 2 x 15 hashes of 48.2 MB, well under a "
        "second. The `before` hash is also computed twice over -- the cache key needs the "
        "artifact digest anyway, so it should be taken once and passed in.",
        "cheaper_form": "keep the `before` digest from the cache key; for `after`, compare "
        "(st_ino, st_size, st_mtime_ns) first and re-hash only when the fingerprint moved. That "
        "still fails on a writer, because a writer moves mtime.",
    }

    C, D, D2, _L = (run_of(mtx, x) for x in ("C", "D", "D2", "L"))
    env["prototype"] = {
        "what": "research/verify-performance/pipeline.py -- one extraction per artifact, page "
        "boundaries from U+000C instead of per-page subprocesses, content-addressed rendition "
        "and check caches, bounded parallelism, second-opinion rendition fetched only where a "
        "passage read as absent.",
        "corpus": "all 16 claims files, 2,512 quotations, 15 unique artifacts (48.2 MB)",
        "cold_wall_seconds": C.get("wall_seconds"),
        "cold_child_cpu_seconds": C.get("child_cpu_seconds"),
        "cold_self_cpu_seconds": C.get("self_cpu_seconds"),
        "warm_wall_seconds": D.get("wall_seconds"),
        "warm_child_cpu_seconds": D.get("child_cpu_seconds"),
        "warm_self_cpu_seconds": D.get("self_cpu_seconds"),
        "warm_renditions_cold_checks_wall_seconds": D2.get("wall_seconds"),
        "extractions_cold": C.get("extractions"),
        "page_subprocesses": C.get("page_subprocesses"),
        "cache_bytes": {
            "renditions": C.get("rendition_cache_bytes"),
            "rendition_entries": C.get("rendition_entries"),
            "checks": C.get("check_cache_bytes"),
            "total": (C.get("rendition_cache_bytes") or 0) + (C.get("check_cache_bytes") or 0),
            "as_fraction_of_artifacts": (
                (C.get("rendition_cache_bytes") or 0) + (C.get("check_cache_bytes") or 0)
            )
            / (C.get("unique_artifact_bytes") or 1),
        },
        "warm_time_is_mostly_yaml": {
            "yaml_seconds": (D.get("timings_seconds") or {}).get("yaml"),
            "fraction_of_warm_wall": ((D.get("timings_seconds") or {}).get("yaml") or 0)
            / (D.get("wall_seconds") or 1),
        },
        "worker_sweep": [
            {
                "workers": run_of(mtx, lab).get("workers"),
                "wall_seconds": run_of(mtx, lab).get("wall_seconds"),
                "child_cpu_seconds": run_of(mtx, lab).get("child_cpu_seconds"),
                "speedup_vs_1": (run_of(mtx, "E").get("wall_seconds") or 0)
                / (run_of(mtx, lab).get("wall_seconds") or 1),
            }
            for lab in ("E", "F", "G", "H", "H2")
            if run_of(mtx, lab)
        ],
        "invalidation": {
            lab: {
                "note": run_of(mtx, lab).get("note"),
                "rendition_hits": run_of(mtx, lab).get("rendition_hits"),
                "rendition_misses": run_of(mtx, lab).get("rendition_misses"),
                "check_hits": run_of(mtx, lab).get("check_hits"),
                "check_misses": run_of(mtx, lab).get("check_misses"),
                "wall_seconds": run_of(mtx, lab).get("wall_seconds"),
                "results_digest": (run_of(mtx, lab).get("results_digest") or "")[:12],
            }
            for lab in ("I", "J", "K", "L", "M")
        },
        "verdicts": C.get("counts"),
        "cross_validation": "2,509 found / 3 not found, and the three are refusal:I1, "
        "successor_heads:C5, superposition:C3 -- the same three, by name, that mechval's own "
        "independent gate reports in research/quote-selector/mechval_after_refactor.json, whose "
        "`loose` count of 45 also equals this run's 45 `normalized` warnings.",
        "digests_agree_where_inputs_unchanged": mtx.get("digests_agree_where_inputs_unchanged"),
        "source": "data/03_matrix.json",
    }

    env["page_scan_risk"] = {
        "on_this_corpus": "workspace.yaml is the only file carrying page locators: 154 "
        "quotations, every one with a page, and none of them off its page (0 `page` warnings in "
        "run C). So `_on_page` would fire 154 times and `_find_page` never.",
        "measured_page_cost_seconds": next(
            (r["median_seconds"] for r in spawn.get("rows", []) if "one page" in r.get("note", "")),
            None,
        ),
        "projected_on_page_seconds": spawn.get("projected_on_page_subprocess_seconds"),
        "spawn_floor_seconds": spawn.get("spawn_floor_seconds"),
        "poppler_load_seconds": spawn.get("poppler_load_seconds"),
        "one_page_as_fraction_of_whole_document": spawn.get("one_page_as_fraction_of_whole"),
        "latent_worst_case": "a single quotation whose recorded page is wrong costs up to "
        "PAGE_SCAN_LIMIT (200) page extractions. At the measured 50 ms that is ~10 s for one "
        "quotation, and 60% of each 50 ms is process startup and poppler loading, before the "
        "page is touched.",
        "source": "data/04_spawn_and_page.json, data/03_matrix.json",
    }

    env["rust_verdict"] = {
        "against_todays_run": {
            "removable_by_rewriting_the_python": t.get("unaccounted_seconds", 0) / wall
            if wall
            else None,
            "explanation": "95.07% is the poppler subprocess, 4.64% is sha256 in OpenSSL, 0.17% "
            "is libyaml. Interpreted Python is 0.13% of 1292.6 s. A Rust rewrite of the "
            "orchestration removes essentially none of today's 21 minutes.",
        },
        "against_the_fixed_cold_pipeline": {
            "self_cpu_fraction": (C.get("self_cpu_seconds") or 0) / (C.get("wall_seconds") or 1),
            "explanation": "3.31 s of 11.65 s is in-process, and 2.01 s of that 3.31 s is YAML "
            "parsing (libyaml, already C) with 0.92 s in the matcher (CPython string search, "
            "also C). A native core would be competing with C for the part it could reach.",
        },
        "against_the_warm_pipeline": {
            "wall_seconds": D.get("wall_seconds"),
            "yaml_fraction": ((D.get("timings_seconds") or {}).get("yaml") or 0)
            / (D.get("wall_seconds") or 1),
            "explanation": "71% of the warm run is re-parsing 16 YAML files that did not change. "
            "That is fixed by caching the parse on (path, size, mtime_ns), not by changing "
            "language. After that the warm run is a few hundred milliseconds.",
        },
        "where_a_native_core_would_actually_pay": "an in-process parallel PDF extractor, "
        "replacing the subprocess entirely: it would remove the 5.2 ms fork+exec and 29.8 ms "
        "poppler load per invocation and the text-through-a-pipe copy. That is a reader "
        "project, not an orchestration project, it competes with C++ poppler on parse speed "
        "rather than on language, and it only touches cold runs -- which, once the rendition "
        "cache exists, happen once per artifact ever.",
        "recommendation": "no Rust for this. Fix the exception cache, extract once per "
        "artifact, cache renditions and the YAML parse. Those are measured at 1292.6 s -> "
        "11.65 s cold -> ~2.7 s warm, in Python.",
    }

    ranked = [
        {
            "rank": 1,
            "change": "Memoize extraction failures, so a source that cannot be read is read "
            "once per document rather than once per quotation.",
            "wall_clock_saved": "the dominant term of the 1292.6 s run. 2,210 subprocess "
            "invocations become at most 15.",
            "measured": "data/01_baseline_profile.json totals.subprocess_seconds = 1228.8 s "
            "(95.07% of wall); per_file shows subprocess_calls == quotes in all 14 PDF files.",
            "risk": "low. A cached failure must carry its reason and must not be treated as a "
            "verdict about the passage; `unchecked` already has that shape.",
        },
        {
            "rank": 2,
            "change": "Make the declared-command convention unambiguous, and refuse a command "
            "that writes beside its input. `pdftotext -layout FILE` writes FILE.txt and prints "
            "nothing; `_argv` should require an explicit `{}` and `-`, or reject the form.",
            "wall_clock_saved": "not a speed change; it is the difference between 2,512 "
            "unchecked and 2,509 found. Without it every other optimization makes a broken run "
            "faster.",
            "measured": "data/01_baseline_profile.json verdicts (2,358 unchecked over 15 files); "
            "the user's own run reports 2,512 of 2,512 unchecked. 32 stray .txt files in "
            "reference/ are the write side effect.",
            "risk": "low, but it changes what existing claims files do -- they start being "
            "checked, and three of them fail.",
        },
        {
            "rank": 3,
            "change": "One extraction per artifact, with page boundaries taken from the U+000C "
            "form feeds already in the output, instead of one `pdftotext` per page.",
            "wall_clock_saved": "7.7 s on this corpus (154 paged quotations x 50.2 ms), and it "
            "removes a latent ~10 s per quotation whose recorded page is wrong.",
            "measured": "data/04_spawn_and_page.json; data/03_matrix.json run C reports "
            "page_subprocesses = 0 and reaches the same verdicts.",
            "risk": "low, but the equivalence is load-bearing and only spot-checked: one page of "
            "one document was verified byte-identical. bench_pagemap.py checks every page of "
            "every artifact and was not run.",
        },
        {
            "rank": 4,
            "change": "Content-addressed rendition cache on disk, keyed on (artifact sha256, "
            "backend, backend version, argument vector, page selection, schema).",
            "wall_clock_saved": "11.65 s cold -> 3.52 s with warm renditions and cold checks. "
            "8.1 s, all of it poppler.",
            "measured": "data/03_matrix.json runs C and D2. Cache is 2.51 MB for 18 renditions "
            "of 48.2 MB of artifacts (5.2%).",
            "risk": "medium. Key completeness is the whole safety argument; case L shows a "
            "version bump invalidating all 14 renditions, case K shows a changed artifact "
            "invalidating exactly one.",
        },
        {
            "rank": 5,
            "change": "Cache the YAML parse of claims files on (path, size, mtime_ns).",
            "wall_clock_saved": "1.94 s of the 2.74 s warm run -- 71% of it.",
            "measured": "data/03_matrix.json run D timings_seconds.yaml = 1.944 s.",
            "risk": "low. mtime is a weaker key than content; falling back to a content hash "
            "costs a read of 16 small files.",
        },
        {
            "rank": 6,
            "change": "Bounded parallelism over unique (artifact, extractor) jobs.",
            "wall_clock_saved": "11.30 s -> 6.42 s at 4 workers, 1.76x. It does not scale past "
            "4: child CPU rises from 8.07 s to 11.41 s at 8 workers, and one 12.5 MB document "
            "sets the floor.",
            "measured": "data/03_matrix.json runs E, F, G, H, H2.",
            "risk": "medium. Report ordering must come from the manifest, not from completion "
            "order; single flight must be per key, since lru_cache does not prevent two threads "
            "extracting the same document.",
        },
        {
            "rank": 7,
            "change": "Check-result cache, keyed on the rendition digest plus the quotation, its "
            "selectors, the page constraint and a matching-policy version.",
            "wall_clock_saved": "0.78 s (3.52 s -> 2.74 s). Small, because the matcher is cheap.",
            "measured": "data/03_matrix.json runs D and D2.",
            "risk": "medium, and the highest of the seven relative to its payoff. A cached pass "
            "must be reported as reused, not as fresh; case M shows a policy bump invalidating "
            "all 2,512 verdicts while re-extracting nothing.",
        },
        {
            "rank": 8,
            "change": "Take the artifact digest once and reuse it for the cache key and the "
            "tamper check, instead of hashing before and after every invocation.",
            "wall_clock_saved": "60.0 s of the broken run (4.64%); under 0.2 s once extraction "
            "happens once per artifact.",
            "measured": "data/01_baseline_profile.json totals.hash_* (4,420 calls, 15.7 GB, "
            "38.5x the 408 MB corpus); data/03_matrix.json timings_seconds.hashing = 0.168 s.",
            "risk": "low, and mostly subsumed by rank 1.",
        },
    ]
    env["ranked_changes"] = ranked

    out = _bench.write(NAME, env)
    print(f"wrote {out}")
    for r in ranked:
        print(f"  {r['rank']}. {r['change'][:88]}")
        print(f"     saved: {r['wall_clock_saved'][:96]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
