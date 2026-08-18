"""Seal a run, record what it produced, and verify the chain.

    results init              start tracking results here
    results seal <file>...    hash inputs before a run (prereg, script, data)
    results access <note>     record a data-access event (what you looked at, when)
    results run <file>...     record outputs after a run completes
    results claim <text>      bind a manuscript claim to a run's output
    results verify            check the ledger chain and every hash it names
"""
from __future__ import annotations

import argparse
import os
import pathlib
import sys

from results import ledger


RESULTS_DIR = ".results"


def find_root(start: pathlib.Path | None = None) -> pathlib.Path | None:
    here = (start or pathlib.Path.cwd()).resolve()
    for d in [here, *here.parents]:
        if (d / RESULTS_DIR).is_dir():
            return d / RESULTS_DIR
    return None


def require_root() -> pathlib.Path:
    root = find_root()
    if root is None:
        print(f"no {RESULTS_DIR}/ here or above. `results init` makes one.")
        sys.exit(2)
    return root


def ledger_path(root: pathlib.Path) -> pathlib.Path:
    return root / ledger.LEDGER


def cmd_init(a) -> int:
    d = pathlib.Path.cwd() / RESULTS_DIR
    if d.exists():
        print(f"{d} already exists.")
        return 1
    d.mkdir()
    lp = d / ledger.LEDGER
    lp.touch()
    ledger.append_event(lp, {"event": "init"})
    print(f"created {RESULTS_DIR}/")
    print(f"  {ledger.LEDGER}   append-only event log")
    print("\nseal your inputs before running: `results seal prereg.md script.py data.csv`")
    return 0


def cmd_seal(a) -> int:
    root = require_root()
    lp = ledger_path(root)
    sealed = []
    for name in a.files:
        p = pathlib.Path(name).resolve()
        if not p.is_file():
            print(f"not a file: {name}")
            return 1
        digest = ledger.sha256_of_file(p)
        sealed.append({"path": os.path.relpath(p), "sha256": digest})
    ev = ledger.append_event(lp, {
        "event": "seal",
        "role": a.role,
        "files": sealed,
    })
    print(f"sealed {len(sealed)} file(s) as {a.role}")
    for s in sealed:
        print(f"  {s['sha256'][:16]}…  {s['path']}")
    return 0


def cmd_access(a) -> int:
    root = require_root()
    lp = ledger_path(root)
    if a.level not in ACCESS_LEVELS:
        print(f"level must be one of: {', '.join(ACCESS_LEVELS)}")
        return 1
    ev = ledger.append_event(lp, {
        "event": "access",
        "level": a.level,
        "note": a.note,
    })
    print(f"recorded: {a.level} — {a.note}")
    if a.level == "outcomes seen":
        print("\nany analysis registered after this is retrospective, not confirmatory.")
    return 0


def cmd_run(a) -> int:
    root = require_root()
    lp = ledger_path(root)
    existing = ledger.read_ledger(lp)
    existing_ids = {e["run_id"] for e in existing if e.get("event") == "run"}
    if a.run_id in existing_ids:
        print(f"warning: run id '{a.run_id}' already exists in the ledger.")
        print("the new run will be recorded alongside the old one.")
    outputs = []
    for name in a.files:
        p = pathlib.Path(name).resolve()
        if not p.is_file():
            print(f"not a file: {name}")
            return 1
        digest = ledger.sha256_of_file(p)
        outputs.append({"path": os.path.relpath(p), "sha256": digest})
    ev = ledger.append_event(lp, {
        "event": "run",
        "run_id": a.run_id,
        "outputs": outputs,
        "note": a.note or "",
    })
    print(f"run {a.run_id}: {len(outputs)} output(s)")
    for o in outputs:
        print(f"  {o['sha256'][:16]}…  {o['path']}")
    return 0


def cmd_claim(a) -> int:
    root = require_root()
    lp = ledger_path(root)

    events = ledger.read_ledger(lp)
    run_ids = {e["run_id"] for e in events if e.get("event") == "run"}
    if a.run_id not in run_ids:
        print(f"no run with id '{a.run_id}' in the ledger.")
        print(f"known runs: {', '.join(sorted(run_ids)) or '(none)'}")
        return 1

    ev = ledger.append_event(lp, {
        "event": "claim",
        "claim": a.text,
        "run_id": a.run_id,
        "confirmatory": a.confirmatory,
        "location": a.location or "",
    })
    status = "confirmatory" if a.confirmatory else "exploratory"
    print(f"claim ({status}): {a.text[:72]}")
    print(f"  backed by run: {a.run_id}")
    if a.location:
        print(f"  appears in: {a.location}")
    return 0


def cmd_verify(a) -> int:
    root = require_root()
    lp = ledger_path(root)

    ok, problems = ledger.verify_chain(lp)
    if not ok:
        print("CHAIN BROKEN")
        for p in problems:
            print(f"  {p}")
        return 1

    events = ledger.read_ledger(lp)
    print(f"chain intact: {len(events)} events\n")

    counts = {}
    for e in events:
        t = e.get("event", "?")
        counts[t] = counts.get(t, 0) + 1
    for t, n in sorted(counts.items()):
        print(f"  {t:<12}{n:>5}")

    drift = 0
    if a.files:
        print("\nfile hashes:")
        file_hashes = {}
        for e in events:
            for f in e.get("files", []) + e.get("outputs", []):
                file_hashes[f["path"]] = f["sha256"]
        for path, expected in sorted(file_hashes.items()):
            p = pathlib.Path(path)
            if not p.exists():
                print(f"  MISSING    {path}")
                drift += 1
            else:
                actual = ledger.sha256_of_file(p)
                if actual == expected:
                    print(f"  ok         {path}")
                else:
                    print(f"  CHANGED    {path}")
                    print(f"    sealed   {expected[:16]}…")
                    print(f"    now      {actual[:16]}…")
                    drift += 1
        if drift:
            print(f"\n{drift} file(s) changed or missing since they were recorded.")
            return 1

    access_events = [e for e in events if e.get("event") == "access"]
    if access_events:
        print("\ndata access timeline:")
        for e in access_events:
            print(f"  {e['timestamp'][:19]}  {e['level']:<20}  {e.get('note', '')}")

    claims = [e for e in events if e.get("event") == "claim"]
    if claims:
        unlinked = []
        for c in claims:
            run_events = [e for e in events
                          if e.get("event") == "run" and e.get("run_id") == c.get("run_id")]
            if not run_events:
                unlinked.append(c)
        if unlinked:
            print(f"\n{len(unlinked)} claim(s) reference missing runs:")
            for c in unlinked:
                print(f"  {c['claim'][:60]}  (run: {c.get('run_id')})")

    print()
    if ok and not (a.files and drift):
        print("all checks passed.")
    return 0


ACCESS_LEVELS = [
    "nothing seen",
    "metadata only",
    "structure seen",
    "outcomes seen",
]


def main() -> int:
    ap = argparse.ArgumentParser(prog="results", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd")

    sub.add_parser("init", help="start tracking results here")

    s = sub.add_parser("seal", help="hash inputs before a run")
    s.add_argument("files", nargs="+")
    s.add_argument("--role", default="input",
                   help="what these files are: input, prereg, script, data")
    s.set_defaults(fn=cmd_seal)

    ac = sub.add_parser("access", help="record a data-access event")
    ac.add_argument("note", help="what was accessed and why")
    ac.add_argument("--level", default="metadata only",
                    help=f"one of: {', '.join(ACCESS_LEVELS)}")
    ac.set_defaults(fn=cmd_access)

    r = sub.add_parser("run", help="record outputs after a run")
    r.add_argument("files", nargs="+")
    r.add_argument("--run-id", required=True, help="a name for this run")
    r.add_argument("--note", help="what this run computed")
    r.set_defaults(fn=cmd_run)

    cl = sub.add_parser("claim", help="bind a manuscript claim to a run")
    cl.add_argument("text", help="the claim, as it appears in the manuscript")
    cl.add_argument("--run-id", required=True, help="which run backs this claim")
    cl.add_argument("--confirmatory", action="store_true",
                    help="mark as confirmatory (default: exploratory)")
    cl.add_argument("--location", help="where in the manuscript: Table 2, Section 4.1, etc.")
    cl.set_defaults(fn=cmd_claim)

    v = sub.add_parser("verify", help="check the ledger and every hash it names")
    v.add_argument("--files", action="store_true",
                   help="also check that sealed/output files still match their hashes")
    v.set_defaults(fn=cmd_verify)

    a = ap.parse_args()
    if not a.cmd:
        ap.print_help()
        return 0
    if a.cmd == "init":
        return cmd_init(a)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
