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

import json
import os
import pathlib

from provenance_core import anchor, atomic_write, sha256_of_tree, try_run

from results import freezes, history, ledger, manuscript, outputs, plans, stamps
from results.paths import RESULTS_DIR, ledger_own, ledger_path, require_root
from results.record import LINKED, rerecorded_paths, retired, skipped_lines
from results.timeline import first_outcomes_seen, first_run_timestamp

#: Said of a recorded path that is one of the ledger's own files, in the text and the JSON.
OWN_FILE = "the ledger's own file, which changes with every event; not compared"


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


def reviews(events: list[dict], base: pathlib.Path, check_files: bool) -> list[str]:
    """One block per review, and with `check_files` whether each subject is still those bytes.

    A review is of a digest. Where the file has changed since, the review says nothing about
    what is there now, and printing the verdict without that would carry it forward. Reported
    and never counted as drift: a reviewed file that then changes is the ordinary result of
    acting on a review.
    """
    lines: list[str] = []
    for e in events:
        if e.get("event") != "review":
            continue
        ran_in = e.get("session") or {}
        harness = " ".join(v for k in ("harness", "harness_version") if (v := ran_in.get(k)))
        named = ", ".join(v for v in (ran_in.get("model"), harness) if v)
        lines.append(
            f"  {e['timestamp'][:19]}  {e.get('verdict', '?'):<10}  {e.get('reviewer', '?')}"
            + (f"  [{named}]" if named else "")
        )
        lines.append(f"    scope: {e.get('scope', '')}")
        lines += subjects(e, base, check_files, "reviewed")
    return lines


def annotation_lines(events: list[dict], base: pathlib.Path, check_files: bool) -> list[str]:
    """One block per annotation: what it links to, and with `check_files` whether each subject
    is still the bytes the link was stated of.

    An annotation is a statement that these bytes correspond to something outside the ledger.
    Nothing here reads the target, so the most this can say is whether the local side of the
    link still exists as recorded. Reported and never counted as drift, as a review is.
    """
    lines: list[str] = []
    for e in events:
        if e.get("event") != "annotation":
            continue
        target = e.get("target") or {}
        lines.append(
            f"  {e['timestamp'][:19]}  {target.get('kind', '?')}  {target.get('ref', '?')}"
            + (f"  [{by}]" if (by := e.get("by")) else "")
        )
        if stated := target.get("digest"):
            lines.append(f"    digest as stated: {stated}")
        if location := e.get("location"):
            lines.append(f"    appears in: {location}")
        lines += subjects(e, base, check_files, "annotated")
    return lines


def subjects(event: dict, base: pathlib.Path, check_files: bool, was: str) -> list[str]:
    """Each subject of a review or an annotation, and whether it is still the recorded bytes."""
    lines: list[str] = []
    for subject in event.get("subjects", []):
        path, recorded = subject["path"], subject["sha256"]
        p = base / path
        if not check_files:
            lines.append(f"    not checked  {path}")
        elif not p.exists():
            lines.append(f"    MISSING      {path}")
        else:
            now = sha256_of_tree(p)[0] if p.is_dir() else ledger.sha256_of_file(p)
            if now == recorded:
                lines.append(f"    current      {path}")
            else:
                lines.append(f"    STALE        {path}")
                lines.append(f"      {was} {recorded[:16]}…, now {now[:16]}…")
    return lines


def coverage(manuscript_path: str, limit: int, strict: bool) -> int:
    root = require_root()
    events = ledger.read_ledger(ledger_path(root))
    claimed = manuscript.claimed_values(events)
    claims = sum(1 for e in events if e.get("event") == "claim")

    try:
        found, stream = manuscript.read(pathlib.Path(manuscript_path))
    except manuscript.UnreadableManuscript as error:
        print(error)
        return 1
    hidden = manuscript.readable(pathlib.Path(manuscript_path).read_text(errors="replace"))[1]

    checkable = [n for n in found if n["exempt"] is None]
    binding = Binding(events, root.parent, stream)
    for number in checkable:
        number["bound"] = number["value"] in claimed and binding.binds(number)
    bound = [n for n in checkable if n["bound"]]
    # A number beside a citation belongs to the work cited. Counting it as unbound would
    # report someone else's figure as an omission of yours.
    attributed = [n for n in checkable if not n["bound"] and n["attributed"]]
    unbound = [n for n in checkable if not n["bound"] and not n["attributed"]]
    owed = bound + unbound

    print(f"{manuscript_path}")
    if hidden:
        print(
            f"  warning: {hidden} format character(s), zero-width or invisible, were removed "
            "before the numbers were read"
        )
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


class Binding:
    """Which claim, if any, binds a number the manuscript prints.

    A number was bound wherever any claim's text held the same digits, so one claim listing
    fifteen numbers covered a manuscript printing them. A claim binds a printed number where
    it states it: the claim prints the number with the words the manuscript prints beside it,
    or the run the claim names wrote it, at the precision printed.
    """

    def __init__(self, events: list[dict], base: pathlib.Path, stream: list[str]) -> None:
        self.stream = stream
        self.base = base
        self.events = events
        self.claims = [
            (c, manuscript.tokens(c.get("claim", ""))) for c in events if c.get("event") == "claim"
        ]
        self._held: dict[str, outputs.Held] = {}

    def held(self, run_id: str) -> outputs.Held:
        if run_id not in self._held:
            self._held[run_id] = outputs.held_by(self.events, run_id, self.base)
        return self._held[run_id]

    def binds(self, number: dict) -> bool:
        value = number["value"]
        naming = [(c, said) for c, said in self.claims if value in said]
        if any(manuscript.stated_by(self.stream, number["at"], said) for _, said in naming):
            return True
        percent = bool(number.get("percent"))
        return any(self.held(str(c.get("run_id") or "")).holds(value, percent) for c, _ in naming)


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
    # With the anchor moved aside, a chain cut short reads as one that predates anchoring, and
    # this was a two-command path to anchoring the shorter chain. A commit holding a longer
    # ledger, or an anchor counting more events, is the witness the moved anchor was.
    if rewrites := history.rewritten(lp):
        print("refusing to anchor: git history holds a ledger this one does not extend.")
        for problem in rewrites:
            print(f"  {problem}")
        print("re-anchoring would record the shorter or changed chain as authoritative.")
        return 1
    anchor = ledger.reanchor(lp)
    print(f"anchored {anchor['count']} events at {anchor['head'][:16]}…")
    return 0


def timestamp() -> int:
    """Stamp the current head, complete every pending proof, and check the complete ones."""
    root = require_root()
    lp = ledger_path(root)
    try:
        made = stamps.stamp_head(lp)
    except anchor.AnchorError as e:
        print(f"not timestamped: {e}")
        return 1
    if made is not None:
        print(f"stamped      {made.relative_to(root.parent)}")
    try:
        found = stamps.complete(lp)
    except anchor.AnchorError as e:
        print(f"TIMESTAMP    {e}")
        return 1
    dated = [(s, block) for s, block in found if block is not None]
    if dated:
        stamp, block = max(dated, key=lambda pair: pair[0].count)
        print(
            f"events 1–{stamp.count} existed by Bitcoin block {block.height}, "
            f"{block.time:%Y-%m-%d %H:%M} UTC"
        )
    waiting = [s for s, block in found if block is None]
    if waiting:
        latest = max(waiting, key=lambda s: s.count)
        print(f"events 1–{latest.count} pending; Bitcoin usually confirms within hours.")
    print("Commit .results/timestamps/ with the ledger.")
    return 0


def _retired(
    path: str, p: pathlib.Path, kind: str, recorded: list[str], said: dict, found: list[dict]
) -> int:
    """Report a retired path, and return 1 where it fails.

    Retired and absent, or present with bytes one of its records names, it passes: the path
    left the project, and anything still there is what was recorded. Present with bytes no
    record names, or as a file where a tree was sealed or the reverse, it is `REAPPEARED` and
    fails, because something new sits at a path the ledger says is gone.
    """
    if p.exists():
        if kind == "tree" and p.is_dir():
            actual: str | None = sha256_of_tree(p)[0]
        elif kind != "tree" and p.is_file():
            actual = ledger.sha256_of_file(p)
        else:
            actual = None
        if actual not in recorded:
            print(f"  REAPPEARED {path}")
            print(f"    retired: {said['note']}")
            print(f"    on disk again, holding bytes none of the {len(recorded)} records names")
            found.append({"path": path, "state": "reappeared", **said})
            return 1
    print(f"  RETIRED    {path}")
    print(f"    {said['note']}")
    if replacement := said.get("superseded_by"):
        print(f"    superseded by {replacement}")
    entry = {"path": path, "state": "retired", **said}
    if p.exists():
        print("    still on disk, holding bytes recorded for this path")
        entry["present"] = True
    found.append(entry)
    return 0


#: Directories never searched for a ledger below the project's.
NOT_SEARCHED = frozenset({"node_modules", "venv", "site-packages", "__pycache__"})

#: How deep below the project a ledger is looked for.
MAX_NESTED_DEPTH = 6


def nested(root: pathlib.Path) -> list[pathlib.Path]:
    """Every `.results/` holding a ledger below the project `root` governs, root excluded.

    A second ledger in a subdirectory governs its own files, and `verify` at the top read only
    the top one: a changed file recorded in the nested ledger passed. Hidden directories other
    than `.results/` are not searched, nor are installed environments.
    """
    top = root.parent
    found = []
    for directory, subdirectories, _ in os.walk(top):
        here = pathlib.Path(directory)
        depth = len(here.relative_to(top).parts)
        if here.name == RESULTS_DIR:
            if here != root and (here / ledger.LEDGER).is_file():
                found.append(here)
            subdirectories[:] = []
            continue
        subdirectories[:] = sorted(
            d
            for d in subdirectories
            if depth < MAX_NESTED_DEPTH
            and d not in NOT_SEARCHED
            and (d == RESULTS_DIR or not d.startswith("."))
        )
    return sorted(found)


def verify(
    check_files: bool, json_path: str | None = None, strict: bool = False, explain: bool = False
) -> int:
    """Check the chain and, with `check_files`, every recorded file. With `json_path`, the
    same findings are also written there as one JSON object: the chain's status and problems,
    the number of events, and each recorded path with what was found at it. Every ledger below
    this one is checked after it, and its findings are under `nested`.

    With `strict`, what is otherwise reported and passed fails: a claim printing a number its
    run's outputs, present and the bytes the run recorded, do not hold. A confirmatory claim
    whose plan is on disk, or at its freeze commit, with other bytes than were frozen fails
    whatever `strict` says.

    Everything the records cannot establish is a note, and fails nothing under `strict` either:
    a commit a shallow clone does not hold, a freeze made with `--force`, a restarted ledger, a
    claim whose outputs a later run rewrote or a later claim superseded, an output recorded
    again with no input sealed between, a timestamp proof history holds and the disk does not.
    A check that could not run is reported apart from a check that failed."""
    root = require_root()
    report: dict = {"files_checked": check_files, "files": []}
    code = _verify(check_files, report, root, strict, explain)
    below = nested(root)
    if below:
        report["nested"] = []
    for other in below:
        print(f"\n--- nested ledger {other.relative_to(root.parent).as_posix()} ---\n")
        found: dict = {"root": other.relative_to(root.parent).as_posix(), "files": []}
        found["exit"] = _verify(check_files, found, other, strict, explain)
        report["nested"].append(found)
        code = max(code, found["exit"])
    if below:
        print(f"\n{len(below)} nested ledger(s) checked; the exit code covers them.")
    if json_path:
        atomic_write(json_path, json.dumps({**report, "exit": code}, indent=2) + "\n")
    return code


def _verify(
    check_files: bool,
    report: dict,
    root: pathlib.Path,
    strict: bool = False,
    explain: bool = False,
) -> int:
    lp = ledger_path(root)

    status, problems = ledger.verify(lp)
    report |= {"chain": status.value, "problems": problems}
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
    report["events"] = len(events)
    if rewrites := history.rewritten(lp):
        # The chain and its anchor agree with each other, and a commit says the ledger was
        # once something this one does not extend: an event removed or changed and the chain
        # recomputed. Nothing on disk can show that; only what was committed before can.
        report["chain"] = "rewritten"
        report["problems"] = rewrites
        print("LEDGER HISTORY REWRITTEN — a committed version is not a prefix of this ledger")
        for problem in rewrites:
            print(f"  {problem}")
        print("\n  A ledger only grows. Restore it from the commit, then record what follows.")
        return 1
    print(f"chain intact: {len(events)} events, anchored\n")

    if state := in_history(lp):
        print(f"  the ledger {state}. A record is evidence once it is in history.\n")

    restarted = history.restart(lp)
    if restarted is not None:
        report["restart"] = {
            "deleted_in": restarted.deleted,
            "restarted_in": restarted.restarted,
            "on": restarted.on,
            "earlier_events": restarted.events,
            "earlier_by_kind": restarted.kinds,
            "dropped_exposures": restarted.dropped,
        }
        # A note, whatever the earlier chain held: restarting a ledger is something honest work
        # does, and the earlier chain's exposures still order the claims below.
        since = (
            f"restarted in {restarted.restarted[:12]}"
            if restarted.restarted
            else "the ledger on disk started after it and is not committed"
        )
        when = f" on {restarted.on[:10]}" if restarted.on else ""
        print(f"  the ledger was deleted in commit {restarted.deleted[:12]}{when}; {since}.")
        held = ", ".join(f"{n} {kind}" for kind, n in restarted.kinds.items())
        print(
            f"  the {restarted.events}-event chain committed before it"
            + (f" ({held})" if held else "")
            + " is a different chain and is not compared."
        )
        for e in restarted.dropped:
            print(f"  RESTART DROPPED AN EXPOSURE  {e.get('level')}: {str(e.get('note'))[:60]}")
            print(f"    recorded {str(e.get('timestamp'))[:19]} in the earlier chain; not here")
        print("  a restart is a note and fails nothing.\n")

    reading = stamps.read(lp)
    if reading.contradictions:
        # The chain verifies against its own anchor and not against a proof held outside it, so
        # the chain and the anchor were rewritten together after that proof was made.
        print("TIMESTAMP CONTRADICTS THE CHAIN — the ledger was rewritten after it was stamped")
        for problem in reading.contradictions:
            print(f"  {problem}")
        return 1
    if reading.dated:
        print(
            f"  events 1–{reading.dated.count} dated by Bitcoin block "
            f"{reading.dated.status.blocks[0]}. `results timestamp` checks the block."
        )
    if reading.pending and (not reading.dated or reading.pending.count > reading.dated.count):
        print(
            f"  events 1–{reading.pending.count} stamped, pending at "
            f"{len(reading.pending.status.pending)} calendars."
        )
    if not reading.dated and not reading.pending:
        print("  no outside timestamp. `results timestamp` makes one.")
    gone_proofs = history.missing_proofs(lp)
    report["missing_proofs"] = [{"path": path, "added_in": sha} for path, sha in gone_proofs]
    for path, sha in gone_proofs:
        # A deleted proof was reported as an absent one, which is the ordinary state of a
        # ledger nobody stamped. History says it existed.
        print(f"  TIMESTAMP PROOF MISSING  {path}")
        print(f"    committed in {sha[:12]} and not on disk: `git checkout {sha[:12]} -- {path}`")
    print()

    counts = {}
    for e in events:
        t = e.get("event", "?")
        counts[t] = counts.get(t, 0) + 1
    for t, n in sorted(counts.items()):
        print(f"  {t:<12}{n:>5}")

    drift = resealed = 0
    rerecords: list[str] = []
    if check_files:
        print("\nfile hashes:")
        # Keyed by path, the last seal of a path silently replaced every earlier one, so
        # "seal your inputs before a run" was not what this checked. Keep them all, and report
        # a path recorded under more than one hash.
        file_hashes: dict[str, list[str]] = {}
        # The hash of each path's last record, which is not the last distinct hash where a
        # path was recorded under one hash, then another, then the first again.
        latest: dict[str, str] = {}
        # Whether each path was sealed as a file or as a directory, so it is re-derived the way
        # it was recorded. A tree re-hashed with `sha256_of_file` is not a mismatch to report;
        # it is a path that cannot be read at all, and would have been an error rather than a
        # verdict.
        kinds: dict[str, str] = {}
        for e in events:
            for f in e.get("files", []) + e.get("outputs", []):
                recorded = file_hashes.setdefault(f["path"], [])
                kinds[f["path"]] = f.get("kind", "file")
                latest[f["path"]] = f["sha256"]
                if f["sha256"] not in recorded:
                    recorded.append(f["sha256"])
        base = root.parent
        found = report["files"]
        gone = retired(events)
        again = rerecorded_paths(events)
        for path, recorded in sorted(file_hashes.items()):
            p = base / path
            if path in again and path not in gone:
                # Recorded as an output under other bytes with no input of the earlier run
                # sealed between: changed and recorded again, or re-run without a record of
                # its inputs. A warning, failed under `--strict`; the path is still compared
                # below, so a file that also changed since is said to have.
                run_ids = again[path]
                print(f"  RERECORDED {path}")
                print(
                    f"    recorded again by run '{run_ids[1]}' under other bytes than run "
                    f"'{run_ids[0]}' wrote, with no input of that run sealed between"
                )
                found.append({"path": path, "state": "rerecorded", "runs": list(run_ids)})
                rerecords.append(path)
            if ledger_own(path):
                # Recorded before `seal` refused these. The file changes with every event, so
                # comparing it says nothing about the work, and failing on it would fail every
                # later verify with nothing the author can do.
                print(f"  IGNORED    {path}")
                print(f"    {OWN_FILE}")
                found.append({"path": path, "state": "ignored", "note": OWN_FILE})
                continue
            if path in gone:
                drift += _retired(path, p, kinds.get(path, "file"), recorded, gone[path], found)
                continue
            if not p.exists():
                print(f"  MISSING    {path}")
                found.append({"path": path, "state": "missing"})
                drift += 1
                continue
            if kinds.get(path) == "tree":
                if not p.is_dir():
                    # Sealed as a directory and now something else. The digest cannot be
                    # re-derived, and reporting a hash mismatch would describe a comparison
                    # that never happened.
                    print(f"  NOT A TREE {path}")
                    print("    sealed as a directory; what is there now is not one")
                    found.append({"path": path, "state": "not a tree"})
                    drift += 1
                    continue
                actual, _, skipped_now = sha256_of_tree(p)
                # Said before the tree's state, which says what the digest covered.
                if notes := skipped_lines(skipped_now, p):
                    print(f"  TREE       {path}")
                    print("\n".join(notes))
            elif p.is_dir():
                print(f"  NOT A FILE {path}")
                print("    sealed as a file; what is there now is a directory")
                found.append({"path": path, "state": "not a file"})
                drift += 1
                continue
            else:
                actual = ledger.sha256_of_file(p)
            if actual == latest[path] and len(recorded) > 1:
                # Sealed, changed, and sealed again, and the disk holds what the last record
                # names. Reported by its own word, because a path is meant to be sealed once
                # and a new version to be a new file; not failed, because nothing on disk
                # differs from the record.
                print(f"  RESEALED   {path}")
                print(f"    matches the latest of {len(recorded)} hashes recorded for this path")
                found.append({"path": path, "state": "resealed", "hashes": len(recorded)})
                resealed += 1
            elif actual == latest[path]:
                print(f"  ok         {path}")
                found.append({"path": path, "state": "ok"})
            elif actual in recorded:
                # The disk holds bytes an earlier record names and the latest does not: the
                # file went back, or the last record was of something that is no longer there.
                which = recorded.index(actual) + 1
                print(f"  REVERTED   {path}")
                print(
                    f"    matches hash {which} of {len(recorded)} recorded for this path, "
                    f"not the latest"
                )
                print(f"    latest   {latest[path][:16]}…")
                found.append(
                    {"path": path, "state": "reverted", "hashes": len(recorded), "matches": which}
                )
                drift += 1
            elif added := plans.entries_appended(base, path, latest[path]):
                print(f"  APPENDED   {path}")
                print(
                    f"    a plan frozen in place, unchanged; {added} log "
                    f"entr{'y' if added == 1 else 'ies'} appended since the latest seal"
                )
                found.append({"path": path, "state": "appended", "entries": added})
            else:
                print(f"  CHANGED    {path}")
                print(f"    sealed   {latest[path][:16]}…")
                print(f"    now      {actual[:16]}…")
                if len(recorded) > 1:
                    print(f"    matches none of the {len(recorded)} hashes recorded for this path")
                found.append({"path": path, "state": "changed"})
                drift += 1
        if resealed:
            print(
                f"\n{resealed} path(s) recorded under more than one hash hold the latest. "
                "A new version is a new file."
            )
        if drift:
            print(f"\n{drift} file(s) changed or missing since they were recorded.")
            return 1

    access_events = [e for e in events if e.get("event") == "access"]
    if access_events:
        print("\ndata access timeline:")
        for e in access_events:
            print(f"  {e['timestamp'][:19]}  {e['level']:<20}  {e.get('note', '')}")

    if review_lines := reviews(events, root.parent, check_files):
        print("\nreviews (self-reported, unsigned):")
        for line in review_lines:
            print(line)
        stale = sum(1 for line in review_lines if line.lstrip().startswith(("STALE", "MISSING")))
        if stale:
            print(f"  {stale} reviewed file(s) are no longer the bytes that were reviewed.")

    if linked := annotation_lines(events, root.parent, check_files):
        print(f"\nannotations ({LINKED}):")
        for line in linked:
            print(line)
        stale = sum(1 for line in linked if line.lstrip().startswith(("STALE", "MISSING")))
        if stale:
            print(f"  {stale} annotated file(s) are no longer the bytes the link was stated of.")

    claims = [e for e in events if e.get("event") == "claim"]
    unlinked = []
    contested = []
    protected = []
    unrecorded = []
    unplanned = []
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
        # The freeze is placed by its record, in the ledger's order where the record gives a
        # position, and never by the claim's `frozen_at_time`, which an older version took from
        # the commit date the committer sets.
        recorded = freezes.read_all(root.parent, lp)
        lines = freezes.lines_of(lp)
        seen = first_outcomes_seen(events)
        seen_at = freezes.index_of(lines, "access", lambda e: e.get("level") == "outcomes seen")
        # An exposure the chain before a restart held is read as though it were still in the
        # ledger, placed by the commit that first added it: re-adding it after the claim, or
        # dropping it, left the claim reading as one made before the outcomes were seen.
        carried = [
            x
            for x in (restarted.exposures if restarted else [])
            if x.event.get("level") == "outcomes seen"
        ]
        late = []
        for c in claims:
            if not c.get("confirmatory"):
                continue
            run_id = str(c.get("run_id") or "")
            in_ledger = seen is not None and (first_run_timestamp(events, run_id) or "") > seen
            run = next(
                (
                    e
                    for e in reversed(events)
                    if e.get("event") == "run" and e.get("run_id") == run_id
                ),
                None,
            )
            earlier = run is not None and any(history.exposed_before(lp, x, run) for x in carried)
            if not in_ledger and not earlier:
                continue
            late.append(c)
            freeze = freezes.named(recorded, str(c.get("frozen_at") or ""))
            if (
                freeze is not None
                and (not in_ledger or freezes.before(freeze, seen_at, seen))
                and (not earlier or freeze.prior)
            ):
                protected.append(c)
            elif c.get("frozen_at") and freeze is None:
                unrecorded.append(c)
        contested = [c for c in late if c not in protected and c not in unrecorded]
        for c in claims:
            if not c.get("confirmatory"):
                continue
            named = freezes.named(recorded, str(c.get("frozen_at") or ""))
            compared = [named] if named else recorded
            run_id = str(c.get("run_id") or "")
            run_at = freezes.run_index(lines, run_id)
            stamp = first_run_timestamp(events, run_id)
            if compared and all(freezes.before(f, run_at, stamp) is False for f in compared):
                unplanned.append(c)
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
                f"after outcomes were seen, with no freeze before them:"
            )
            for c in contested:
                print(f"  {c['claim'][:60]}  (run: {c.get('run_id')})")
            print("  these are retrospective unless a plan frozen before the exposure fixed")
            print("  the choices they rest on; if one did, re-record with --frozen-at.")
        if unrecorded:
            print(
                f"\n{len(unrecorded)} confirmatory claim(s) rest on runs recorded after "
                f"outcomes were seen, and cite a commit no freeze record names:"
            )
            for c in unrecorded:
                print(f"  {c['claim'][:56]}  (frozen at {c.get('frozen_at')})")
            print("  a commit's date is whatever its committer set, so it dates no freeze.")
        if unplanned:
            print(
                f"\n{len(unplanned)} confirmatory claim(s) rest on runs recorded before the "
                f"plan was frozen:"
            )
            for c in unplanned:
                print(f"  {c['claim'][:60]}  (run: {c.get('run_id')})")
            print("  no frozen plan governed these runs. Reported, not failed: a pilot can")
            print("  come before the plan it informs.")

    edited, uncompared = edited_plans(claims, root.parent, lp)
    report["confirmatory_claims_on_changed_plans"] = [
        {"claim": c["claim"], "plan": plan, "problem": problem} for c, plan, problem in edited
    ]
    report["plans_not_compared"] = [
        {"claim": c["claim"], "plan": plan, "note": note} for c, plan, note in uncompared
    ]
    if edited:
        print(
            f"\n{len(edited)} confirmatory claim(s) rest on a plan that has changed since it "
            "was frozen:"
        )
        for c, plan, problem in edited:
            print(f"  {c['claim'][:60]}  (run: {c.get('run_id')})")
            print(f"    plan {plan}: {problem}")
        print("  a confirmatory claim holds only of the plan as frozen: restore the plan, or")
        print("  record the change with `prereg amend` and claim under the amendment's freeze.")
    if uncompared:
        print("\nplans a confirmatory claim rests on, not compared at their freeze (a note):")
        for plan, note in dict.fromkeys((plan, note) for _, plan, note in uncompared):
            print(f"  {plan}: {note}")

    orphaned, unheld, unchecked, superseded = claim_backing(claims, events, root.parent)
    report["claims_on_retired_outputs"] = [c["claim"] for c in orphaned]
    report["claims_unchecked"] = [
        {"claim": c["claim"], "run_id": c.get("run_id"), "outputs": why} for c, why in unchecked
    ]
    report["claims_superseded"] = [
        {"claim": c["claim"], "run_id": c.get("run_id"), "by": by} for c, by in superseded
    ]
    report["claims_numbers_not_in_outputs"] = [
        {"claim": c["claim"], "run_id": c.get("run_id"), "numbers": absent} for c, absent in unheld
    ]
    if orphaned:
        print(f"\n{len(orphaned)} claim(s) rest on runs whose every output was retired:")
        for c in orphaned:
            print(f"  {c['claim'][:60]}  (run: {c.get('run_id')})")
        print("  the run no longer names a file in the project; a note, failing nothing.")
    if unheld and (explain or strict):
        print(f"\n{len(unheld)} claim(s) print numbers their run's outputs do not hold:")
        for c, absent in unheld:
            print(f"  {c['claim'][:60]}  (run: {c.get('run_id')})")
            print(f"    no output rounds to {', '.join(absent)} at the printed precision")
        print("  a number derived from the outputs is declared with `results claim --derived`.")
    elif unheld:
        # One line, since a paper reporting derived statistics prints dozens of these; the
        # JSON lists each, and `--strict` fails them.
        print(
            f"\n{len(unheld)} claim(s) print numbers their run's outputs do not hold; "
            "list with --explain"
        )
    if superseded:
        # Said once, as a count: the ledger only grows, so every re-run leaves the claims it
        # replaced behind, and listing each would bury what does need reading.
        print(
            f"\n{len(superseded)} claim(s) superseded: a later run rewrote their outputs and a "
            "later claim is bound to it. Not checked, failing nothing."
        )
    if unchecked:
        print(
            f"\n{len(unchecked)} claim(s) unchecked: their run's outputs are not the bytes it "
            "recorded, so their numbers were not compared:"
        )
        for c, why in unchecked:
            print(f"  {c['claim'][:60]}  (run: {c.get('run_id')})")
            for path, said in why.items():
                print(f"    {path}: {said}")
        print("  a note: bind the sentence to the run that wrote what is there now.")
    derived = [c for c in claims if c.get("derived")]
    report["claims_derived"] = [{"claim": c["claim"], "how": c["derived"]} for c in derived]
    if derived:
        print(f"\n{len(derived)} claim(s) print numbers derived from their run's outputs:")
        for c in derived:
            print(f"  {c['claim'][:60]}")
            print(f"    derived: {str(c['derived'])[:70]}")
        print("  not compared with the outputs: the claim says how the number was derived.")
    report["rerecorded"] = rerecords
    if rerecords:
        print(
            f"\n{len(rerecords)} output(s) recorded again with no input of the earlier run sealed:"
        )
        print("  a re-run seals what it reads first; a note, failing nothing.")
    # What `--strict` fails: a number a claim prints that outputs present on disk, as the run
    # recorded them, do not hold. Every other finding above is a note.
    warned = bool(unheld)
    noted = bool(
        orphaned or unchecked or superseded or gone_proofs or rerecords or restarted or uncompared
    )

    print()
    if unlinked:
        print("the ledger names runs it does not contain.")
        return 1
    if edited:
        print("a confirmatory claim rests on a plan edited after its freeze.")
        return 1
    if strict and warned:
        print("strict: a claim prints a number its run's outputs do not hold.")
        return 1
    if not check_files:
        print("chain intact. file hashes were not checked — pass --files to check them.")
        return 0
    if contested or unrecorded or unplanned or warned or noted:
        print("chain intact and every file hash matches, with the notes above.")
        return 0
    print("all checks passed.")
    return 0


def edited_plans(
    claims: list[dict], project: pathlib.Path, lp: pathlib.Path
) -> tuple[list[tuple[dict, str, str]], list[tuple[dict, str, str]]]:
    """Each confirmatory claim with each plan it rests on that is not the plan as frozen, and
    why; then each with each plan that could not be compared at its freeze, and why: the plan
    its `frozen_at` commit names, or every frozen plan in this project's directory where it
    names none.

    Asked at `results claim` and not since, so a plan edited after the claim was recorded
    left the claim confirmatory. A plan frozen whole is compared with its record's digest and
    its companions' and read at the commit the record names, and one frozen in place by
    `prereg check`'s own rule, which leaves its log out. A claim whose `frozen_at` names no
    record here is held to the ledger's `freeze` event at that commit, so deleting the record
    does not leave the claim on nothing.

    Only bytes present and different are an edit. A commit a shallow clone does not hold, a
    freeze made with `--force`, and a plan no longer on disk leave nothing to compare, and are
    the notes, which fail nothing.
    """
    confirmatory = [c for c in claims if c.get("confirmatory")]
    if not confirmatory:
        return [], []
    top = try_run("rev-parse", "--show-toplevel", cwd=project)
    checked = freezes.checked_plans(project)
    changed = [(plan, commit, problem) for plan, commit, problem, _ in checked if problem]
    unread = [(plan, commit, note) for plan, commit, problem, note in checked if note]
    if top:
        changed += plans.changed_in_place(pathlib.Path(top))
    base = pathlib.Path(top) if top else project
    lines = freezes.lines_of(lp) if lp.is_file() else []
    found: list[tuple[dict, str, str]] = []
    notes: list[tuple[dict, str, str]] = []
    for c in confirmatory:
        at = str(c.get("frozen_at") or "")
        for listed, into in ((changed, found), (unread, notes)):
            into += [
                (c, _shown(plan, base), why)
                for plan, commit, why in listed
                if (at and commit and at.startswith(commit)) or (not at and _within(plan, project))
            ]
        if at and not any(at == commit for _, commit, _, _ in checked):
            read = freezes.event_plan_problem(lp, lines, at)
            if read is not None and read[0]:
                found.append((c, f"frozen at {at[:12]}, no freeze record", read[0]))
            elif read is not None and read[1]:
                notes.append((c, f"frozen at {at[:12]}, no freeze record", read[1]))
    return found, notes


def _within(path: pathlib.Path, project: pathlib.Path) -> bool:
    return path.resolve().is_relative_to(project.resolve())


def _shown(path: pathlib.Path, base: pathlib.Path) -> str:
    try:
        return path.resolve().relative_to(base.resolve()).as_posix()
    except ValueError:
        return str(path)


def claim_backing(
    claims: list[dict], events: list[dict], base: pathlib.Path
) -> tuple[
    list[dict],
    list[tuple[dict, list[str]]],
    list[tuple[dict, dict[str, str]]],
    list[tuple[dict, str]],
]:
    """The claims whose run's outputs were all retired; the claims printing numbers their run's
    outputs do not hold, each with those numbers; the claims whose numbers could not be checked
    because an output of their run is not the bytes it recorded, each with what became of each
    such output; and the claims a later claim superseded, each with the run that did.

    Only the second is a finding: a number absent from outputs that are on disk as the run
    recorded them. A claim on a run whose outputs are not text is in none of these: there is
    nothing to compare, and `results claim` said so when it was recorded. A claim some of whose
    outputs were rewritten is checked against the others only where they hold every number it
    prints; otherwise it is unchecked, since the rewritten output may have held the rest.

    A claim is superseded where a later claim is bound to a run recorded after its own that
    rewrote one of its run's outputs, or states the same sentence: re-binding after a re-run is
    the remedy, and the claim it replaces stays in the ledger, which only grows.
    """
    gone = retired(events)
    orphaned: list[dict] = []
    unheld: list[tuple[dict, list[str]]] = []
    unchecked: list[tuple[dict, dict[str, str]]] = []
    superseded: list[tuple[dict, str]] = []
    cache: dict[str, outputs.Held] = {}
    ran = {e.get("run_id"): i for i, e in enumerate(events) if e.get("event") == "run"}
    for n, c in enumerate(claims):
        run_id = str(c.get("run_id") or "")
        paths = outputs.run_outputs(events, run_id)
        if paths and all(path in gone for path in paths):
            orphaned.append(c)
            continue
        if c.get("derived"):
            # Declared derived: the number is computed from the outputs and is not in them.
            continue
        if run_id not in cache:
            cache[run_id] = outputs.held_by(events, run_id, base)
        held = cache[run_id]
        # A later run supersedes a claim only where it changed the bytes the claim was read
        # against: a deterministic re-run leaves them as recorded, so the claim is still checked.
        if (held.changed or held.absent) and (
            by := _superseded_by(c, claims[n + 1 :], events, ran)
        ):
            superseded.append((c, by))
            continue
        absent = outputs.missing(c.get("claim", ""), held) if held.read else []
        if held.changed or held.absent:
            if outputs.owed(c.get("claim", "")) and (absent or not held.read):
                unchecked.append((c, _what_became(events, run_id, held, base)))
        elif absent:
            unheld.append((c, absent))
    return orphaned, unheld, unchecked, superseded


def _superseded_by(claim: dict, later: list[dict], events: list[dict], ran: dict) -> str:
    """The run of the first later claim that supersedes `claim`, or "": one bound to a run
    recorded after this claim's run, which states the same sentence or rewrote an output of
    this claim's run."""
    at = ran.get(claim.get("run_id"), -1)
    mine = set(outputs.run_outputs(events, str(claim.get("run_id") or "")))
    for c in later:
        other = str(c.get("run_id") or "")
        if ran.get(other, -1) <= at:
            continue
        if c.get("claim") == claim.get("claim") or mine & set(outputs.run_outputs(events, other)):
            return other
    return ""


def _what_became(
    events: list[dict], run_id: str, held: outputs.Held, base: pathlib.Path
) -> dict[str, str]:
    """For each unread output of `run_id`, the later run recording what is there now, a seal of
    those bytes, or that no record names them, or that it is gone."""
    said: dict[str, str] = {}
    for p in held.changed:
        path = p.relative_to(base).as_posix()
        now = ledger.sha256_of_file(p)
        later = [
            str(e.get("run_id"))
            for e in events
            if e.get("event") == "run"
            and e.get("run_id") != run_id
            and _names(e, "outputs", path, now)
        ]
        if later:
            said[path] = f"rewritten by run '{later[-1]}'"
        elif any(e.get("event") == "seal" and _names(e, "files", path, now) for e in events):
            said[path] = f"sealed since with other bytes than run '{run_id}' recorded"
        else:
            said[path] = f"changed since run '{run_id}' recorded it; no record names what is there"
    for p in held.absent:
        said[p.relative_to(base).as_posix()] = "not on disk"
    return said


def _names(event: dict, key: str, path: str, digest: str) -> bool:
    """Whether `event` records `path` with `digest` under `key`."""
    return any(f["path"] == path and f.get("sha256") == digest for f in event.get(key, []))
