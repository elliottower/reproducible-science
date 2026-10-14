"""Build graph.json, the data behind the lineage view, for one project.

Reads the project's repro.yaml, runs `repro verify --format json` and `repro stale --format json`
(both read-only apart from the check history `repro verify` already keeps), and reads the
results ledger and the local record of checks. Writes one JSON file the web app loads.

    uv run --no-project --with pyyaml==6.0.2 python builder/build_graph.py <project> web/public/graph.json
"""

import argparse
import collections
import hashlib
import json
import pathlib
import re
import subprocess

import yaml

# Files are grouped by topic, first match wins; anything unmatched is grouped by directory.
# This list is specific to the reproducible-science paper and moves to a config file next.
TOPICS = [
    ("Manuscript", r"^(manuscript|appendix|failure-cases|certified-reproductions|reexecution-precedents|literature-census|figures)"),
    ("CODECHECK register", r"^codecheck"),
    ("CORE-Bench", r"^corebench"),
    ("Timing", r"(timings|performance)"),
    ("Literature census", r"^(census|corpus|unions|extractor-spread|audit-record-census|conformance)"),
    ("Audits of our papers", r"(knockout|cross-design|catch-log|command-counts|audit-counts)"),
    ("Bibliography audit", r"^bibliography"),
    ("RNA worked example", r"^rna-"),
    ("Coverage of this paper", r"^(layout|split|body-claims|number-coverage)"),
]
PAPER_GROUPS = {"Section": "Paper: body", "Table": "Paper: tables", "Appendix": "Paper: appendices"}
MANUSCRIPT_IDS = {"manuscript", "manuscript-text", "appendix", "appendix-text"}
# Worst first, for collapsing several assertions into one outcome per check.
OUTCOME_RANK = ["mismatch", "not_found", "error", "unchecked", "verified"]


def sha256(path: pathlib.Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def repro_json(project: pathlib.Path, command: str) -> dict:
    out = subprocess.run(
        ["repro", command, "--format", "json", str(project / "repro.yaml")],
        cwd=project, capture_output=True, text=True, check=False,
    )
    if not out.stdout.strip():
        raise RuntimeError(f"repro {command} wrote nothing: {out.stderr.strip()[:500]}")
    return json.loads(out.stdout)


def section_of(where: str) -> str:
    first = where.split(",")[0].strip()
    m = re.match(r"Section (\d+)", first)
    return f"Section {m.group(1)}" if m else first


def topic_of(aid: str, path: str) -> str:
    for name, pat in TOPICS:
        if re.search(pat, aid):
            return name
    return str(pathlib.PurePosixPath(path).parent)


def worst(outcomes: list[str]) -> str:
    return min(outcomes, key=lambda o: OUTCOME_RANK.index(o) if o in OUTCOME_RANK else 0)


def read_checks(project: pathlib.Path) -> list[dict]:
    git_dir = subprocess.run(["git", "rev-parse", "--git-dir"], cwd=project, capture_output=True, text=True)
    candidates = []
    if git_dir.returncode == 0:
        candidates.append((project / git_dir.stdout.strip()) / "repro" / "checks.jsonl")
    candidates.append(project / ".repro" / "checks.jsonl")
    for c in candidates:
        if c.is_file():
            return [json.loads(line) for line in c.read_text().splitlines() if line.strip()]
    return []


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("project", type=pathlib.Path)
    ap.add_argument("out", type=pathlib.Path)
    a = ap.parse_args()
    project = a.project.resolve()

    manifest = yaml.safe_load((project / "repro.yaml").read_text())
    report = repro_json(project, "verify")["report"]
    staleness = repro_json(project, "stale")["staleness"]
    ledger_path = project / ".results" / "ledger.jsonl"
    ledger = [json.loads(x) for x in ledger_path.read_text().splitlines()] if ledger_path.exists() else []
    checks = read_checks(project)

    artifacts = {x["id"]: x for x in manifest["artifacts"]}
    is_code = {aid for aid, x in artifacts.items() if x.get("media_type") == "text/x-python"}
    claim_decl = {c["id"]: c for c in manifest["claims"]}

    last_run: dict[str, dict] = {}
    for e in ledger:
        if e.get("event") == "run":
            for o in e.get("outputs", []):
                last_run[o["path"]] = {"run_id": e["run_id"], "timestamp": e["timestamp"], "sha256": o["sha256"], "note": e.get("note", "")}

    regen_of = {r["output"]["artifact"]: r for r in manifest.get("regenerations", [])}
    stale_art = {x["id"]: x for x in staleness["artifacts"]}
    stale_regen = {r["artifact"]: r for r in staleness["regenerations"]}
    stale_claim = {c["id"]: c for c in staleness["claims"]}
    causes_by_regen = collections.defaultdict(list)
    for f in staleness["findings"]:
        causes_by_regen[f["regeneration"]].append({"cause": f["cause"], "artifact": f["artifact"]})

    # History: per claim, one point per check that recorded it, with the worst outcome among its
    # assertions in that check. Per file, when a check last read it.
    history = collections.defaultdict(list)
    last_checked: dict[str, str] = {}
    for e in checks:
        by_claim = collections.defaultdict(list)
        for x in e.get("assertions", []):
            if x["claim_id"] in claim_decl:
                by_claim[x["claim_id"]].append(x["outcome"])
                for aid in x.get("digests", {}):
                    last_checked[aid] = e["timestamp"]
        for cid, outs in by_claim.items():
            history[cid].append({"t": e["timestamp"], "outcome": worst(outs)})

    per_art = collections.defaultdict(lambda: {"ok": 0, "fail": 0, "stale": 0, "claims": []})
    per_sec = collections.defaultdict(lambda: {"ok": 0, "fail": 0, "stale": 0, "claims": []})
    edge_counts = collections.Counter()
    for c in report["claims"]:
        decl = claim_decl.get(c["claim_id"], {})
        where = decl.get("where", "unplaced")
        sec = section_of(where)
        st = stale_claim.get(c["claim_id"], {})
        st_assert = st.get("assertions", [])
        rows = []
        for i, dcs in enumerate(c["decisions"]):
            rows.append({
                "kind": dcs["kind"], "artifact": dcs["artifact_id"],
                "ok": dcs["execution"] == "completed" and dcs["comparison"] == "match",
                "comparison": dcs["comparison"], "reason": dcs["reason"], "detail": dcs["detail"],
                "extracted": dcs["extracted"], "warnings": dcs["warnings"],
                "stale": st_assert[i]["state"] if i < len(st_assert) else None,
            })
        row = {
            "id": c["claim_id"], "where": where, "section": sec, "text": decl.get("text", ""),
            "ok": all(r["ok"] for r in rows), "stale": st.get("state"),
            "history": history.get(c["claim_id"], []),
        }
        row["assertions"] = rows
        per_sec[sec]["claims"].append(row)
        per_sec[sec]["ok" if row["ok"] else "fail"] += 1
        per_sec[sec]["stale"] += row["stale"] == "stale"
        for art in {r["artifact"] for r in rows}:
            mine = [r for r in rows if r["artifact"] == art]
            per_art[art]["claims"].append(row)
            per_art[art]["ok" if all(r["ok"] for r in mine) else "fail"] += 1
            per_art[art]["stale"] += any(r["stale"] == "stale" for r in mine)
            if art not in MANUSCRIPT_IDS:
                edge_counts[(art, sec)] += 1

    nodes, groups = [], {}
    for aid, art in artifacts.items():
        if aid in is_code:
            continue
        path = art["path"]
        run = last_run.get(path)
        current = sha256(project / path)
        pinned = art.get("digest", {}).get("value")
        group = topic_of(aid, path)
        groups.setdefault(group, {"id": group, "kind": "files"})
        regen = regen_of.get(aid)
        sr = stale_regen.get(aid)
        nodes.append({
            "id": aid, "type": "artifact", "group": group, "path": path,
            "media_type": art.get("media_type"),
            "pinned": pinned, "current": current,
            "state": "missing" if current is None else ("changed" if pinned and current != pinned else "pinned"),
            "run": run and {**run, "fresh": run["sha256"] == current},
            "regenerated_by": regen and " ".join(regen["command"]),
            "code": [artifacts[i["artifact"]]["path"] for i in (regen or {}).get("inputs", []) if i["artifact"] in is_code],
            "freshness": stale_art.get(aid, {}).get("state"),
            "rerun_at": sr and sr.get("rerun_at"),
            "causes": causes_by_regen.get(aid, []),
            "last_checked": last_checked.get(aid),
            "ok": per_art[aid]["ok"], "fail": per_art[aid]["fail"], "stale": per_art[aid]["stale"],
            "claims": per_art[aid]["claims"],
        })

    def sec_key(s: str) -> tuple:
        order = {"Section": 0, "Table": 1, "Appendix": 2}
        return (order.get(s.split()[0], 3), s)

    for g in PAPER_GROUPS.values():
        groups[g] = {"id": g, "kind": "sections"}
    for sec in sorted(per_sec, key=sec_key):
        v = per_sec[sec]
        nodes.append({"id": f"sec:{sec}", "type": "section", "group": PAPER_GROUPS.get(sec.split()[0], "Paper: body"),
                      "label": sec, "ok": v["ok"], "fail": v["fail"], "stale": v["stale"], "claims": v["claims"]})

    edges = []
    for r in manifest.get("regenerations", []):
        for i in r["inputs"]:
            if i["artifact"] in is_code:
                continue
            if i["artifact"] in artifacts and r["output"]["artifact"] in artifacts:
                edges.append({"source": i["artifact"], "target": r["output"]["artifact"], "kind": "regenerates"})
    for (art, sec), n in edge_counts.items():
        edges.append({"source": art, "target": f"sec:{sec}", "kind": "supports", "count": n})

    out = {
        "project": report["project"],
        "manifest_digest": report["manifest_digest"],
        "totals": {
            "claims": len(report["claims"]),
            "assertions": sum(len(c["decisions"]) for c in report["claims"]),
            "artifacts": len(artifacts),
            "failing": sum(1 for c in per_sec.values() for r in c["claims"] if not r["ok"]),
            "reruns": int(staleness.get("reruns") or 0),
            "stale_steps": sum(1 for r in staleness["regenerations"] if r["state"] == "stale"),
            "checks": len(checks),
            "last_check": checks[-1]["timestamp"] if checks else None,
        },
        "groups": list(groups.values()),
        "nodes": nodes,
        "edges": edges,
    }
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(out, indent=1))
    print(f"{len(nodes)} nodes, {len(edges)} edges, {len(groups)} groups -> {a.out}")


if __name__ == "__main__":
    main()
