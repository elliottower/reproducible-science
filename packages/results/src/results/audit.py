"""The commands that read the record back.

`verify` walks the chain, then the file hashes it names, then the ordering of the claims it
holds, and prints a different headline for each way the chain can fail, because truncated,
edited and unattested have different remedies. `coverage` reads a manuscript instead and
reports which of its numbers a recorded claim already names.

`reanchor` writes rather than reads, and sits here because it is only intelligible beside
`verify`: it records the ledger's current length and head as authoritative, which repairs a
chain written before anchoring existed and records the damage on one that was truncated. That
is why it is a separate command and not something verification does on its own.
"""

from __future__ import annotations

import pathlib

from provenance_core import sha256_of_tree, try_run

from results import ledger, manuscript
from results.paths import ledger_path, require_root
from results.timeline import first_outcomes_seen, first_run_timestamp, precedes


def in_history(ledger: pathlib.Path) -> str | None:
    """What stands between this ledger and anyone else, or None where nothing does.

    A ledger is the record a claim appeals to, and one that exists only on this disk cannot
    be appealed to at all: nobody else can read it, and nothing outside it says it once had
    a different length. `citations` already reports a record that is not committed for the
    same reason, and this said nothing -- three of the four ledgers on the machine that
    prompted this are untracked, including one behind a submitted paper.

    Reported, never blocking. A ledger written between commits is the ordinary state of
    working, and refusing to verify it would be wrong far more often than right.
    """
    root = ledger.parent.parent
    if not (root / ".git").exists():
        return None
    if try_run("ls-files", "--error-unmatch", "--", str(ledger), cwd=root) is None:
        return "is not tracked by git"
    if (try_run("status", "--porcelain", "--", str(ledger), cwd=root) or "").strip():
        return "has changes that are not committed"
    return None


def coverage(manuscript_path: str, limit: int, strict: bool) -> int:
    root = require_root()
    events = ledger.read_ledger(ledger_path(root))
    claimed = manuscript.claimed_values(events)
    claims = sum(1 for e in events if e.get("event") == "claim")

    try:
        found = manuscript.numbers(pathlib.Path(manuscript_path))
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

    print(f"{manuscript_path}")
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
        for key in sorted(by_line)[:limit]:
            lineno = key[1]
            entries = by_line[key]
            values = ", ".join(n["printed"] for n in entries)
            where = entries[0].get("source") or pathlib.Path(manuscript_path).name
            print(f"  {where}:{lineno}  {values[:58]}")
            print(f"      {entries[0]['context'][:74]}")
        if len(by_line) > limit:
            print(f"  ... and {len(by_line) - limit} more lines; pass --limit to see them")
        print("\nEach states a result or it does not. Bind the ones that do:")
        print('  results claim --run-id <run> --location "<where>" "<the sentence>"')
    return 1 if unbound and strict else 0


def reanchor() -> int:
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


def verify(check_files: bool) -> int:
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

    if state := in_history(lp):
        print(f"  the ledger {state}. A record is evidence once it is in history.\n")

    counts = {}
    for e in events:
        t = e.get("event", "?")
        counts[t] = counts.get(t, 0) + 1
    for t, n in sorted(counts.items()):
        print(f"  {t:<12}{n:>5}")

    drift = 0
    if check_files:
        print("\nfile hashes:")
        # Keyed by path, the last seal of a path silently replaced every earlier one, so
        # "seal your inputs before a run" was not what this checked. Keep them all, and report
        # a path recorded under more than one hash.
        file_hashes: dict[str, list[str]] = {}
        # Whether each path was sealed as a file or as a directory, so it is re-derived the way
        # it was recorded. A tree re-hashed with `sha256_of_file` is not a mismatch to report;
        # it is a path that cannot be read at all, and would have been an error rather than a
        # verdict.
        kinds: dict[str, str] = {}
        for e in events:
            for f in e.get("files", []) + e.get("outputs", []):
                recorded = file_hashes.setdefault(f["path"], [])
                kinds[f["path"]] = f.get("kind", "file")
                if f["sha256"] not in recorded:
                    recorded.append(f["sha256"])
        base = root.parent
        for path, recorded in sorted(file_hashes.items()):
            p = base / path
            if not p.exists():
                print(f"  MISSING    {path}")
                drift += 1
                continue
            if kinds.get(path) == "tree":
                if not p.is_dir():
                    # Sealed as a directory and now something else. The digest cannot be
                    # re-derived, and reporting a hash mismatch would describe a comparison
                    # that never happened.
                    print(f"  NOT A TREE {path}")
                    print("    sealed as a directory; what is there now is not one")
                    drift += 1
                    continue
                actual = sha256_of_tree(p)[0]
            elif p.is_dir():
                print(f"  NOT A FILE {path}")
                print("    sealed as a file; what is there now is a directory")
                drift += 1
                continue
            else:
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
                c for c in late if c.get("frozen_at_time") and precedes(c["frozen_at_time"], seen)
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
    if not check_files:
        print("chain intact. file hashes were not checked — pass --files to check them.")
        return 0
    if contested:
        print("chain intact and every file hash matches, with the notes above.")
        return 0
    print("all checks passed.")
    return 0
