"""The freezes `prereg` recorded, read as data, and where each sits in this ledger's order.

`results claim --frozen-at` once took any reference git could resolve and dated the freeze by
its commit date. A commit date is whatever the committer's clock or `GIT_COMMITTER_DATE` said,
so a plan frozen after the outcomes were seen, in a commit dated a year earlier, made a
confirmatory claim pass. What dates a freeze is the record `prereg freeze` wrote beside the
plan, `.prereg/<file>.json`: the full commit, the instant of the freeze, and, where a ledger
existed, how many of its events it held then and the digest of the last. The position is the
part no clock can move. An event the ledger held at the freeze came before it, and one it did
not came after, and the chain fixes which is which.

The record is a file in the working tree, so its position and its time are only as good as
the checks made of it here. A record is placed only where its plan exists and the commit it
names holds the plan with the digest it records; a record with no plan behind it, or one whose
plan the commit does not hold, places nothing. Where `prereg freeze` wrote a `freeze` event
into the ledger, that event is the position, since it sits inside the hash chain and the
record does not: a record stating a position is placed only where the chain holds that event
at that position. A record written before any ledger existed holds no position; it precedes
every ledger event where every commit that touched it is a strict ancestor, in the commit
graph, of every commit that added the ledger. The position a record states is also checked
against the ledger as committed at the record's commit: the freeze came after that commit, so a record saying the
ledger held fewer events than the commit already did is false. Where a ledger exists and the
record cannot be placed in it, the record's `frozen_at`, a time anyone can write, places
nothing either.

This module reads those records and never imports `prereg`, as `prereg` reads the ledger and
never imports this package.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import re
import subprocess
from dataclasses import dataclass

from provenance_core import sha256_of_file, sha256_of_text
from provenance_core.gitref import clean_env, try_run

from results.timeline import precedes

RECORDS = ".prereg"
SKIPPED = {".git", "node_modules", ".venv", "venv", "site-packages"}

#: A full commit id, SHA-1 or SHA-256.
FULL_COMMIT = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")


@dataclass(frozen=True)
class Freeze:
    """One freeze record."""

    record: pathlib.Path
    commit: str
    frozen_at: str
    #: How many events this ledger held at the freeze, where the record names this ledger and
    #: its digest of the last of them still matches. None where it cannot be placed that way.
    position: int | None
    #: Why the record's position in the ledger could not be used, where it names one.
    misplaced: str = ""
    #: Whether a ledger exists to place it in, in which case `frozen_at` places nothing.
    ledgered: bool = False


def lines_of(ledger: pathlib.Path) -> list[str]:
    """The ledger's events as written, one per line."""
    return [line for line in ledger.read_text().splitlines() if line.strip()]


def _blob(top: pathlib.Path, spec: str) -> bytes | None:
    """The bytes git holds as `<commit>:<path>`, or None."""
    done = subprocess.run(
        ["git", "cat-file", "blob", spec],
        cwd=top,
        env=clean_env(),
        capture_output=True,
        check=False,
    )
    return done.stdout if done.returncode == 0 else None


def _name(top: pathlib.Path, path: pathlib.Path) -> str | None:
    try:
        return path.resolve().relative_to(top.resolve()).as_posix()
    except ValueError:
        return None


def plan_of(record: pathlib.Path) -> pathlib.Path:
    """The plan a freeze record describes: `PREREG.md` for `.prereg/PREREG.md.json`."""
    return record.parent.parent / record.name.removesuffix(".json")


def plan_changed(record: pathlib.Path, held: dict) -> str:
    """Why the plan on disk is not the file the record froze, or "" where it is. A plan frozen
    whole keeps its log in a file beside it, so a log entry never changes it."""
    plan = plan_of(record)
    if not plan.is_file():
        return f"no plan {plan.name} stands beside the record"
    if sha256_of_file(plan) != held.get("sha256"):
        return f"{plan.name} has changed since it was frozen: `prereg check` reports it"
    return ""


def _plan_problem(record: pathlib.Path, held: dict, top: pathlib.Path | None) -> str:
    """Why the record's plan does not stand behind it, or "" where it does: the plan exists,
    is the file the record froze, as `prereg check` reads a plan frozen whole, and the commit
    the record names holds it with the digest the record gives. A plan edited after the
    outcomes were seen, beside a record left as it was, made a confirmatory claim pass."""
    if changed := plan_changed(record, held):
        return changed
    plan = plan_of(record)
    if held.get("uncommitted"):
        return f"{plan.name} was frozen from bytes no commit holds"
    name = _name(top, plan) if top is not None else None
    if top is None or name is None:
        return f"{plan.name} is not in a git repository, so its commit cannot be read"
    stored = _blob(top, f"{held['commit']}:{name}")
    if stored is None:
        return f"commit {held['commit'][:12]} does not hold {name}"
    if hashlib.sha256(stored).hexdigest() != held.get("sha256"):
        return f"{name} at commit {held['commit'][:12]} is not the file the record froze"
    return ""


def _event_position(record: pathlib.Path, held: dict, ledger: pathlib.Path, lines: list[str]):
    """The index of the `freeze` event `prereg freeze` wrote into the ledger for this record,
    or None."""
    plan = (record.parent.parent / record.name.removesuffix(".json")).resolve()
    for i, line in enumerate(lines):
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if (
            event.get("event") == "freeze"
            and event.get("commit") == held.get("commit")
            and event.get("sha256") == held.get("sha256")
            and (ledger.parent.parent / str(event.get("file", ""))).resolve() == plan
        ):
            return i
    return None


def _place(
    record: pathlib.Path,
    held: dict,
    ledger: pathlib.Path,
    lines: list[str],
    top: pathlib.Path | None,
):
    """The record's position in `ledger`, or None and why where it names one but cannot be
    placed there."""
    where = held.get("ledger")
    if not isinstance(where, dict):
        return None, ""
    named = (record.parent.parent / str(where.get("path", ""))).resolve()
    if named != ledger.resolve():
        return None, ""
    events = where.get("events")
    if not isinstance(events, int) or events < 0 or events > len(lines):
        return None, f"it records {events} ledger events, and the ledger holds {len(lines)}"
    head = where.get("head") or ""
    if events and sha256_of_text(lines[events - 1]) != head:
        return None, f"event {events} of the ledger is not the event it recorded as the last"
    # The freeze came after the commit it names, so the ledger then held at least what that
    # commit holds. A record saying it held fewer was written to move the freeze earlier.
    name = _name(top, ledger) if top is not None else None
    stored = _blob(top, f"{held['commit']}:{name}") if top is not None and name else None
    if stored is not None:
        committed = len([x for x in stored.decode(errors="replace").splitlines() if x.strip()])
        if committed > events:
            return None, (
                f"the ledger as committed at {held['commit'][:12]} already held {committed} "
                f"events, and the record says {events}"
            )
    return events, ""


def _commits(top: pathlib.Path, name: str, *only: str) -> list[str]:
    """Every commit, on every line of history, that touched `name` (or, with `only`, did so as
    `--diff-filter` says). `--full-history`, because git's default simplification follows one
    parent where a merge leaves the path as both had it, and that hid the first commit adding
    the ledger behind a re-add on a side branch."""
    said = try_run(
        "log", "--full-history", "--no-merges", *only, "--format=%H", "--", name, cwd=top
    )
    return (said or "").split()


def _ancestor(top: pathlib.Path, older: str, newer: str) -> bool:
    done = subprocess.run(
        ["git", "merge-base", "--is-ancestor", older, newer],
        cwd=top,
        env=clean_env(),
        capture_output=True,
        check=False,
    )
    return done.returncode == 0


def _before_the_ledger(record: pathlib.Path, ledger: pathlib.Path, top: pathlib.Path) -> int | None:
    """0, before every ledger event, where the record was frozen before any ledger existed and
    git shows it: every commit that touched the record is a strict ancestor of every commit
    that added the ledger, on every line of history. By the order of commits in the graph,
    which no date moves. The record on disk must be the one HEAD holds and one a non-merge
    commit wrote, and the plan commit it names must precede that commit. None otherwise,
    including where either was never committed or both arrived in one commit.
    """
    record_name, ledger_name = _name(top, record), _name(top, ledger)
    if record_name is None or ledger_name is None:
        return None
    touched = _commits(top, record_name)
    added = _commits(top, ledger_name, "--diff-filter=A")
    if not touched or not added:
        return None
    try:
        current = record.read_bytes()
    except OSError:
        return None
    if _blob(top, f"HEAD:{record_name}") != current:
        return None
    # The bytes must be ones an ordinary commit wrote. Written inside a merge, which
    # `--no-merges` leaves out, a record reached HEAD without any commit in `touched` holding it.
    wrote = [sha for sha in touched if _blob(top, f"{sha}:{record_name}") == current]
    if not wrote:
        return None
    # The plan the record names was committed before the record that names it: a record
    # standing before a plan commit it cites is history rewritten around it.
    try:
        named = json.loads(current).get("commit")
    except (ValueError, AttributeError):
        return None
    if not isinstance(named, str) or not all(
        sha == named or _ancestor(top, named, sha) for sha in wrote
    ):
        return None
    for older in touched:
        for newer in added:
            if older == newer or not _ancestor(top, older, newer):
                return None
    return 0


def _records(project: pathlib.Path):
    """Each freeze record in the repository holding `project`, or below `project` outside one,
    with what it holds and the repository's top, or None outside one."""
    top = try_run("rev-parse", "--show-toplevel", cwd=project)
    base = pathlib.Path(top) if top else project
    repo = pathlib.Path(top) if top else None
    for record in sorted(base.rglob(f"{RECORDS}/*.json")):
        if any(part in SKIPPED for part in record.relative_to(base).parts):
            continue
        try:
            held = json.loads(record.read_text(errors="replace"))
        except (OSError, ValueError):
            continue
        if not isinstance(held, dict) or not isinstance(held.get("commit"), str):
            continue
        yield record, held, repo


def changed_plans(project: pathlib.Path) -> list[tuple[pathlib.Path, str, str]]:
    """Each plan frozen whole whose file is not the one its record froze, with the commit the
    record names and why."""
    return [
        (plan_of(record), held["commit"], problem)
        for record, held, _ in _records(project)
        if (problem := plan_changed(record, held))
    ]


def read_all(project: pathlib.Path, ledger: pathlib.Path) -> list[Freeze]:
    """Every freeze record in the repository holding `project`, or below `project` outside one."""
    lines = lines_of(ledger) if ledger.is_file() else []
    found = []
    for record, held, repo in _records(project):
        frozen_at = str(held.get("frozen_at", ""))
        if problem := _plan_problem(record, held, repo):
            found.append(Freeze(record, held["commit"], frozen_at, None, problem, True))
            continue
        if isinstance(held.get("ledger"), dict):
            # A record stating a position is placed only where the chain holds the freeze
            # event `prereg freeze` wrote with it, at that position: a position written by
            # hand, with no event behind it, made a freeze after the outcomes read as before.
            stated, misplaced = _place(record, held, ledger, lines, repo)
            event_at = _event_position(record, held, ledger, lines)
            position = None
            if stated is not None and not misplaced:
                if event_at is None:
                    misplaced = "no freeze event in the ledger stands where the record says"
                elif event_at != stated:
                    misplaced = (
                        f"the ledger's freeze event is at {event_at}, and the record says {stated}"
                    )
                else:
                    position = stated
        else:
            # No position: written before any ledger existed, and placed by commit order alone.
            misplaced = ""
            position = _before_the_ledger(record, ledger, repo) if repo is not None else None
        found.append(
            Freeze(record, held["commit"], frozen_at, position, misplaced, ledger.is_file())
        )
    return found


def named(freezes: list[Freeze], commit: str) -> Freeze | None:
    """The freeze recorded at exactly `commit`, or None."""
    return next((f for f in freezes if f.commit == commit), None)


def index_of(lines: list[str], kind: str, test) -> int | None:
    """The position of the first event of `kind` passing `test`, or None."""
    for i, line in enumerate(lines):
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get("event") == kind and test(event):
            return i
    return None


def run_index(lines: list[str], run_id: str) -> int | None:
    """The position of the latest run recorded under `run_id`, which a claim rests on."""
    found = None
    for i, line in enumerate(lines):
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get("event") == "run" and event.get("run_id") == run_id:
            found = i
    return found


def before(freeze: Freeze, index: int | None, stamp: str | None) -> bool | None:
    """Whether the freeze came before the event at `index` of the ledger, stamped `stamp`.

    By position where the record places the freeze in this ledger: the event came after it
    exactly when the ledger did not yet hold it. Where there is no ledger, by the instant the
    record gives, which `prereg freeze` wrote from the clock. Never by a commit date, and never
    by the record's time where a ledger exists to place it in. None where neither can say.
    """
    if freeze.position is not None and index is not None:
        return index >= freeze.position
    if freeze.misplaced or freeze.ledgered:
        return None
    if freeze.frozen_at and stamp:
        return precedes(freeze.frozen_at, stamp)
    return None
