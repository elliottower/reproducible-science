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
    """The governing `.results/`, or raise.

    Raises rather than exits: this is reached through library calls, and a function that kills
    the interpreter cannot be used from anything that is not a terminal.
    """
    root = find_root()
    if root is None:
        raise ledger.NoLedgerRootError(str(pathlib.Path.cwd()))
    return root


def ledger_path(root: pathlib.Path) -> pathlib.Path:
    return root / ledger.LEDGER


def record_path(p: pathlib.Path, root: pathlib.Path) -> str:
    """A path relative to the project root, so it resolves from anywhere in the tree.

    Recording relative to the current directory would make a file sealed from a
    subdirectory unfindable when verify runs at the root.
    """
    return os.path.relpath(p, root.parent)


def first_outcomes_seen(events: list[dict]) -> str | None:
    """Timestamp of the earliest 'outcomes seen' access event, if there is one."""
    stamps = [
        e["timestamp"]
        for e in events
        if e.get("event") == "access" and e.get("level") == "outcomes seen"
    ]
    return min(stamps) if stamps else None


def first_run_timestamp(events: list[dict], run_id: str) -> str | None:
    """Timestamp of the earliest run recorded under this id."""
    stamps = [
        e["timestamp"] for e in events if e.get("event") == "run" and e.get("run_id") == run_id
    ]
    return min(stamps) if stamps else None


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
        sealed.append({"path": record_path(p, root), "sha256": digest})
    ledger.append_event(
        lp,
        {
            "event": "seal",
            "role": a.role,
            "files": sealed,
        },
    )
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
    ledger.append_event(
        lp,
        {
            "event": "access",
            "level": a.level,
            "note": a.note,
        },
    )
    print(f"recorded: {a.level} — {a.note}")
    if a.level == "outcomes seen":
        print("\nany analysis registered after this is retrospective, not confirmatory.")
        print("`results claim --confirmatory` will now refuse runs recorded after this point.")
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
        outputs.append({"path": record_path(p, root), "sha256": digest})
    ledger.append_event(
        lp,
        {
            "event": "run",
            "run_id": a.run_id,
            "outputs": outputs,
            "note": a.note or "",
        },
    )
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

    retrospective = None
    if a.confirmatory:
        seen = first_outcomes_seen(events)
        if seen is not None:
            recorded = first_run_timestamp(events, a.run_id)
            if recorded is None or recorded > seen:
                retrospective = seen

    if retrospective and not a.anyway:
        print(
            f"refusing: outcomes were seen at {retrospective[:19]}, and run "
            f"'{a.run_id}' was recorded after that."
        )
        print("a claim from a run that postdates seeing the outcomes is retrospective.")
        print("drop --confirmatory, or pass --anyway to record it as confirmatory")
        print("with the ordering noted permanently in the ledger.")
        return 1

    ledger.append_event(
        lp,
        {
            "event": "claim",
            "claim": a.text,
            "run_id": a.run_id,
            "confirmatory": a.confirmatory,
            "after_outcomes_seen": bool(retrospective),
            "location": a.location or "",
        },
    )
    status = "confirmatory" if a.confirmatory else "exploratory"
    print(f"claim ({status}): {a.text[:72]}")
    print(f"  backed by run: {a.run_id}")
    if a.location:
        print(f"  appears in: {a.location}")
    if retrospective:
        print(f"  recorded after outcomes were seen at {retrospective[:19]}; verify will report it")
    return 0


def cmd_reanchor(a) -> int:
    """Record the ledger's current length and head as authoritative.

    Deliberate and separate from `verify`, because re-anchoring a truncated ledger records the
    truncation. It repairs a ledger written before anchoring existed, or one appended to by a
    run that crashed before the anchor was written; it recovers nothing.
    """
    root = require_root()
    lp = ledger_path(root)
    status, _ = ledger.verify(lp)
    if status in (
        ledger.ChainStatus.EDITED,
        ledger.ChainStatus.CORRUPT,
        ledger.ChainStatus.REORDERED,
    ):
        print(f"refusing to anchor a chain reported as {status.value}.")
        print("re-anchoring would record the damage as authoritative.")
        return 1
    anchor = ledger.reanchor(lp)
    print(f"anchored {anchor['count']} events at {anchor['head'][:16]}…")
    return 0


def cmd_verify(a) -> int:
    root = require_root()
    lp = ledger_path(root)

    status, problems = ledger.verify(lp)
    if status is not ledger.ChainStatus.INTACT:
        # Name which failure it is. Truncated, edited and unattested have different causes and
        # different remedies, and one banner for all three tells a reader nothing to act on.
        headline = {
            ledger.ChainStatus.TRUNCATED: "CHAIN TRUNCATED — events are missing from the end",
            ledger.ChainStatus.EXTENDED: "CHAIN EXTENDED — appended without updating the anchor",
            ledger.ChainStatus.EDITED: "CHAIN EDITED — a recorded event has been changed",
            ledger.ChainStatus.REORDERED: "CHAIN REORDERED — events are not in the order written",
            ledger.ChainStatus.CORRUPT: "CHAIN CORRUPT — a line is not a readable event",
            ledger.ChainStatus.NO_ANCHOR: "CHAIN UNATTESTED — no anchor, so length is unverified",
            ledger.ChainStatus.ABSENT: "NO LEDGER — nothing to verify",
        }.get(status, "CHAIN BROKEN")
        print(headline)
        for problem in problems:
            print(f"  {problem}")
        if status is ledger.ChainStatus.NO_ANCHOR:
            print("\n  This ledger predates anchoring. If it is intact, record its length:")
            print("      results reanchor")
        elif status is ledger.ChainStatus.EXTENDED:
            print("\n  If the extra events are yours, record the new length:")
            print("      results reanchor")
        return 1

    events = ledger.read_ledger(lp)
    print(f"chain intact: {len(events)} events, anchored\n")

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
        base = root.parent
        for path, expected in sorted(file_hashes.items()):
            p = base / path
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
    unlinked = []
    contested = []
    if claims:
        for c in claims:
            run_events = [
                e for e in events if e.get("event") == "run" and e.get("run_id") == c.get("run_id")
            ]
            if not run_events:
                unlinked.append(c)
        if unlinked:
            print(f"\n{len(unlinked)} claim(s) reference missing runs:")
            for c in unlinked:
                print(f"  {c['claim'][:60]}  (run: {c.get('run_id')})")

        # Recomputed from timestamps rather than read off the claim event, so a
        # ledger written by an older version, or edited by hand, is still caught.
        seen = first_outcomes_seen(events)
        if seen is not None:
            contested = [
                c
                for c in claims
                if c.get("confirmatory")
                and (first_run_timestamp(events, c.get("run_id")) or "") > seen
            ]
        if contested:
            print(
                f"\n{len(contested)} confirmatory claim(s) rest on runs recorded "
                f"after outcomes were seen:"
            )
            for c in contested:
                print(f"  {c['claim'][:60]}  (run: {c.get('run_id')})")
            print("  these are retrospective; describe them as such in the manuscript.")

    print()
    if unlinked:
        print("the ledger names runs it does not contain.")
        return 1
    if not a.files:
        print("chain intact. file hashes were not checked — pass --files to check them.")
        return 0
    if contested:
        print("chain intact and every file hash matches, with the notes above.")
        return 0
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
    s.add_argument(
        "--role", default="input", help="what these files are: input, prereg, script, data"
    )
    s.set_defaults(fn=cmd_seal)

    ac = sub.add_parser("access", help="record a data-access event")
    ac.add_argument("note", help="what was accessed and why")
    ac.add_argument("--level", default="metadata only", help=f"one of: {', '.join(ACCESS_LEVELS)}")
    ac.set_defaults(fn=cmd_access)

    r = sub.add_parser("run", help="record outputs after a run")
    r.add_argument("files", nargs="+")
    r.add_argument("--run-id", required=True, help="a name for this run")
    r.add_argument("--note", help="what this run computed")
    r.set_defaults(fn=cmd_run)

    cl = sub.add_parser("claim", help="bind a manuscript claim to a run")
    cl.add_argument("text", help="the claim, as it appears in the manuscript")
    cl.add_argument("--run-id", required=True, help="which run backs this claim")
    cl.add_argument(
        "--confirmatory", action="store_true", help="mark as confirmatory (default: exploratory)"
    )
    cl.add_argument(
        "--anyway",
        action="store_true",
        help="record a confirmatory claim whose run postdates seeing the "
        "outcomes; the ledger and verify both report the ordering",
    )
    cl.add_argument("--location", help="where in the manuscript: Table 2, Section 4.1, etc.")
    cl.set_defaults(fn=cmd_claim)

    v = sub.add_parser("verify", help="check the ledger and every hash it names")
    v.add_argument(
        "--files",
        action="store_true",
        help="also check that sealed/output files still match their hashes",
    )
    v.set_defaults(fn=cmd_verify)

    ra = sub.add_parser("reanchor", help="record the ledger's current length as authoritative")
    ra.set_defaults(fn=cmd_reanchor)

    a = ap.parse_args()
    if not a.cmd:
        ap.print_help()
        return 0
    try:
        if a.cmd == "init":
            return cmd_init(a)
        return a.fn(a)
    except ledger.ResultsError as e:
        # The process boundary. Library code raises; only here does a failure become a code.
        print(str(e))
        return 2


if __name__ == "__main__":
    sys.exit(main())
