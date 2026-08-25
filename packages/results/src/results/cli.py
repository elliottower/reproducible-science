"""Seal a run, record what it produced, and verify the chain.

results init              start tracking results here
results seal <file>...    hash inputs before a run (prereg, script, data)
results access <note>     record a data-access event (what you looked at, when)
results run <file>...     record outputs after a run completes
results claim <text>      bind a manuscript claim to a run's output
results coverage <paper>  how many of a manuscript's numbers are bound to a run
results verify            check the ledger chain and every hash it names
"""

from __future__ import annotations

import argparse
import datetime
import os
import pathlib
import sys

from results import ledger, manuscript

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
    """Timestamp of the *latest* run recorded under this id.

    It once returned the earliest, so a second run recorded under an id that already existed
    inherited the first one's timestamp: a run performed after the outcomes were seen was
    ordered by when the id was first used, and the confirmatory guard passed. Duplicate ids
    are refused now, and this takes the latest regardless -- what a claim rests on is the most
    recent run under the id.
    """
    stamps = [
        e["timestamp"] for e in events if e.get("event") == "run" and e.get("run_id") == run_id
    ]
    return max(stamps) if stamps else None


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
    if a.run_id in existing_ids and not getattr(a, "anyway", False):
        # A warning was not enough: both the claim-time refusal and `verify`'s contested list
        # resolve an id to one timestamp, so two runs sharing an id let a claim rest on the
        # earlier of them. Typing the same id twice defeated the confirmatory guard.
        print(f"run id '{a.run_id}' already exists in the ledger.")
        print("one run id names one run: choose another, or pass --anyway to record both")
        print("and accept that a claim naming this id is ordered by the later run.")
        return 1
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
    frozen_at = getattr(a, "frozen_at", None)
    frozen_time = freeze_timestamp(root, frozen_at) if frozen_at else None
    if frozen_at and frozen_time is None:
        print(f"cannot resolve --frozen-at '{frozen_at}': not a commit in this repository.")
        print("a freeze reference must name a commit that contains the frozen plan.")
        return 1

    if a.confirmatory:
        seen = first_outcomes_seen(events)
        if seen is not None:
            recorded = first_run_timestamp(events, a.run_id)
            if recorded is None or recorded > seen:
                retrospective = seen

    # Exposure is evidence of possible contamination, not contamination. What
    # threatens a confirmatory reading is propagation: outcome information
    # reaching a consequential choice. A plan committed before the exposure
    # cannot be reached by it, so the disposition is confirmatory with the
    # exposure logged, and the demotion is scoped to decisions not so protected.
    protected = bool(retrospective and frozen_time and precedes(frozen_time, retrospective))
    if protected:
        retrospective = None

    if retrospective and not a.anyway:
        print(
            f"refusing: outcomes were seen at {retrospective[:19]}, and run "
            f"'{a.run_id}' was recorded after that."
        )
        print("a claim from a run that postdates seeing the outcomes is retrospective,")
        print("unless the choices it rests on were fixed before the exposure.")
        print("if a commit contains the frozen plan, pass --frozen-at <commit>;")
        print("otherwise drop --confirmatory, or pass --anyway to record it as")
        print("confirmatory with the ordering noted permanently in the ledger.")
        return 1

    ledger.append_event(
        lp,
        {
            "event": "claim",
            "claim": a.text,
            "run_id": a.run_id,
            "confirmatory": a.confirmatory,
            "after_outcomes_seen": bool(retrospective),
            "frozen_at": frozen_at or "",
            "frozen_at_time": frozen_time or "",
            "location": a.location or "",
        },
    )
    status = "confirmatory" if a.confirmatory else "exploratory"
    print(f"claim ({status}): {a.text[:72]}")
    print(f"  backed by run: {a.run_id}")
    if a.location:
        print(f"  appears in: {a.location}")
    if protected and frozen_time:
        print(f"  plan frozen at {frozen_at} on {frozen_time[:19]}, before outcomes")
        print("  were seen: confirmatory, exposure logged")
    elif retrospective:
        print(f"  recorded after outcomes were seen at {retrospective[:19]}; verify will report it")
    return 0


def precedes(earlier: str, later: str) -> bool:
    """Whether one ISO timestamp names an instant before another.

    Both sides must be parsed. The freeze time comes from git as `%cI`, which carries the
    committer's local offset, and the ledger writes UTC; comparing them as strings compares
    the offsets rather than the instants. That comparison passed on a machine four hours
    behind UTC, where the local hour is numerically smaller, and failed on a UTC runner where
    the two agree to the second and the ordering fell to whether `+` or `Z` sorts before `.`.

    An unparseable timestamp is not treated as earlier. A freeze that cannot be placed in time
    cannot protect a claim, and guessing here would grant the protection on a malformed value.
    """
    try:
        first = datetime.datetime.fromisoformat(earlier)
        second = datetime.datetime.fromisoformat(later)
    except (TypeError, ValueError):
        return False
    if (first.tzinfo is None) != (second.tzinfo is None):
        # One naive and one aware cannot be ordered without inventing a zone for the naive one.
        return False
    return first < second


def freeze_timestamp(root: pathlib.Path, ref: str) -> str | None:
    """When the plan named by `ref` was fixed, as an ISO timestamp.

    A freeze reference is a git commit containing the frozen plan. Its commit
    date is the moment the plan stopped being editable, which is the fact that
    matters: a plan already committed cannot be reached by anything a context
    reads afterwards.
    """
    import subprocess

    try:
        out = subprocess.run(
            ["git", "-C", str(root), "show", "-s", "--format=%cI", ref],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() or None if out.returncode == 0 else None


def cmd_coverage(a) -> int:
    root = require_root()
    events = ledger.read_ledger(ledger_path(root))
    claimed = manuscript.claimed_values(events)
    claims = sum(1 for e in events if e.get("event") == "claim")

    try:
        found = manuscript.numbers(pathlib.Path(a.manuscript))
    except manuscript.UnreadableManuscript as error:
        print(error)
        return 1

    checkable = [n for n in found if n["exempt"] is None]
    for number in checkable:
        number["bound"] = number["printed"] in claimed
    bound = [n for n in checkable if n["bound"]]
    # A number beside a citation belongs to the work cited. Counting it as unbound would
    # report someone else's figure as an omission of yours.
    attributed = [n for n in checkable if not n["bound"] and n["attributed"]]
    unbound = [n for n in checkable if not n["bound"] and not n["attributed"]]
    owed = bound + unbound

    print(f"{a.manuscript}")
    print(
        f"  {claims} claim{'' if claims == 1 else 's'} in the ledger, "
        f"naming {len(claimed)} distinct value{'' if len(claimed) == 1 else 's'}"
    )
    if not owed:
        print("  no numbers in this manuscript owe a run.")
        return 0

    share = len(bound) / len(owed) if owed else 0.0
    print(f"  yours, bound to a run       {len(bound):>5}   ({share:.0%} of {len(owed)})")
    print(f"  yours, bound to nothing     {len(unbound):>5}")
    print(f"  beside a citation           {len(attributed):>5}   attributable to the work cited")
    print(
        f"  owing no claim              {len(found) - len(checkable):>5}   "
        f"constants, identifiers, hyphenated names"
    )

    if unbound:
        # Grouped by line, since a dense abstract or a table row holds a dozen values and
        # listing each separately buries every other place a number went unbound.
        by_line: dict[tuple[str, int], list[dict]] = {}
        for number in unbound:
            by_line.setdefault((number.get("source", ""), number["line"]), []).append(number)
        print("\nbound to nothing, by line:")
        for key in sorted(by_line)[: a.limit]:
            lineno = key[1]
            entries = by_line[key]
            values = ", ".join(n["printed"] for n in entries)
            where = entries[0].get("source") or pathlib.Path(a.manuscript).name
            print(f"  {where}:{lineno}  {values[:58]}")
            print(f"      {entries[0]['context'][:74]}")
        if len(by_line) > a.limit:
            print(f"  ... and {len(by_line) - a.limit} more lines; pass --limit to see them")
        print("\nEach states a result or it does not. Bind the ones that do:")
        print('  results claim --run-id <run> --location "<where>" "<the sentence>"')
    return 1 if unbound and a.strict else 0


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
        # `TRUNCATED` was missing, so deleting trailing events -- a failed run, a claim --
        # and then re-anchoring was a two-command path to a clean bill of health. It is the
        # status this guard most needs to cover, since truncation is the cheapest tampering.
        ledger.ChainStatus.TRUNCATED,
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
        # Keyed by path, the last seal of a path silently replaced every earlier one, so
        # "seal your inputs before a run" was not what this checked. Keep them all, and report
        # a path recorded under more than one hash.
        file_hashes: dict[str, list[str]] = {}
        for e in events:
            for f in e.get("files", []) + e.get("outputs", []):
                recorded = file_hashes.setdefault(f["path"], [])
                if f["sha256"] not in recorded:
                    recorded.append(f["sha256"])
        base = root.parent
        for path, recorded in sorted(file_hashes.items()):
            p = base / path
            if not p.exists():
                print(f"  MISSING    {path}")
                drift += 1
                continue
            actual = ledger.sha256_of_file(p)
            if actual in recorded:
                if len(recorded) > 1:
                    # The file on disk matches one recorded hash and the ledger holds others,
                    # so the path was sealed, changed, and sealed again.
                    print(f"  RESEALED   {path}")
                    print(f"    recorded {len(recorded)} different hashes for this path")
                    drift += 1
                else:
                    print(f"  ok         {path}")
            else:
                print(f"  CHANGED    {path}")
                print(f"    sealed   {recorded[-1][:16]}…")
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
    protected = []
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
            late = [
                c
                for c in claims
                if c.get("confirmatory")
                and (first_run_timestamp(events, str(c.get("run_id") or "")) or "") > seen
            ]
            # The same instant comparison the claim path uses. This line held the string
            # form of the defect after the claim path was fixed, so the claim was accepted
            # and then reported as unprotected by the command that checks it.
            protected = [
                c for c in late
                if c.get("frozen_at_time") and precedes(c["frozen_at_time"], seen)
            ]
            contested = [c for c in late if c not in protected]
        if protected:
            print(
                f"\n{len(protected)} confirmatory claim(s) rest on plans frozen "
                f"before outcomes were seen:"
            )
            for c in protected:
                print(f"  {c['claim'][:56]}  (frozen at {c.get('frozen_at')})")
            print("  confirmatory, exposure logged: a committed plan cannot be")
            print("  reached by an exposure that follows it.")
        if contested:
            print(
                f"\n{len(contested)} confirmatory claim(s) rest on runs recorded "
                f"after outcomes were seen, with no freeze reference:"
            )
            for c in contested:
                print(f"  {c['claim'][:60]}  (run: {c.get('run_id')})")
            print("  these are retrospective unless a commit fixed the choices they")
            print("  rest on; if one did, re-record with --frozen-at.")

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
    r.add_argument(
        "--anyway",
        action="store_true",
        help="record a second run under an id that already exists; a claim naming that id "
        "is then ordered by the later run",
    )
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
    cl.add_argument(
        "--frozen-at",
        help="a commit containing the frozen plan this claim rests on; if it "
        "predates the exposure, the claim is confirmatory with the "
        "exposure logged rather than retrospective",
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

    cv = sub.add_parser("coverage", help="how many of a manuscript's numbers are bound to a run")
    cv.add_argument("manuscript", help="the manuscript source: .tex, .md, .qmd, .rst")
    cv.add_argument(
        "--limit", type=int, default=25, help="how many unbound numbers to list (default: 25)"
    )
    cv.add_argument(
        "--strict",
        action="store_true",
        help="exit non-zero when anything is unbound, for a pre-submission check",
    )
    cv.set_defaults(fn=cmd_coverage)

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
