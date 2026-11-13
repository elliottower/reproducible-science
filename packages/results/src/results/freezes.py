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
the checks made of it here. A record is placed only where its plan exists with the digest it
records; a record with no plan behind it, or one whose commit holds the plan with other bytes,
places nothing. A commit this clone does not hold, as in the shallow clone CI checks out, and a
freeze made with `--force` from bytes no commit held, leave nothing to compare at the commit:
each is a note, as `prereg check` reads it, and fails nothing. Where `prereg freeze` wrote a
`freeze` event into the ledger, that event is the position, since it sits inside the hash chain and the
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
    #: Placed before every ledger at this path by commit order, a chain deleted since included.
    prior: bool = False


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


def no_plan(record: pathlib.Path) -> str:
    """Why the record has no plan beside it, or "" where it has one. A record standing alone
    places no freeze, and says nothing of an edit: there are no bytes to compare."""
    plan = plan_of(record)
    return "" if plan.is_file() else f"no plan {plan.name} stands beside the record"


def plan_changed(record: pathlib.Path, held: dict) -> tuple[str, str]:
    """Why the plan on disk is not the file the record froze, and a note on what could not be
    compared, each "" where there is none. A plan frozen whole keeps its log in a file beside
    it, so a log entry never changes it. A companion frozen with it, such as an analysis
    configuration, is part of the plan and is compared too.

    Only bytes that are present and differ are a change. A plan or a companion that is not on
    disk is a note: nothing was compared, and nothing on disk says it was edited."""
    plan = plan_of(record)
    if absent := no_plan(record):
        return "", absent
    if sha256_of_file(plan) != held.get("sha256"):
        return f"{plan.name} has changed since it was frozen: `prereg check` reports it", ""
    companions = held.get("companions")
    for name, digest in sorted(companions.items() if isinstance(companions, dict) else []):
        companion = plan.parent / name
        if not companion.is_file():
            return "", f"companion {name} frozen with {plan.name} is not on disk"
        if sha256_of_file(companion) != digest:
            return f"companion {name} has changed since it was frozen with {plan.name}", ""
    return "", ""


def _commit_held(top: pathlib.Path, commit: str) -> bool:
    """Whether this clone holds `commit`. A shallow clone, as CI checks out, holds the last."""
    return try_run("cat-file", "-e", f"{commit}^{{commit}}", cwd=top) is not None


def _plan_problem(record: pathlib.Path, held: dict, top: pathlib.Path | None) -> tuple[str, str]:
    """Why the record's plan does not stand behind it, and a note on what could not be read,
    each "" where there is none, as `prereg check` reads a plan frozen whole.

    A problem only where bytes are present and differ: the plan or a companion on disk is not
    what the record froze, or the commit the record names is in this clone and holds the plan
    with other bytes. A plan edited after the outcomes were seen, beside a record left as it was,
    made a confirmatory claim pass. Everything that leaves nothing to compare is a note and
    fails nothing: a freeze made with `--force` from bytes no commit held, a commit a shallow
    clone does not hold, a commit that does not hold the plan at this path, a plan outside git.
    """
    problem, note = plan_changed(record, held)
    if problem or note:
        return problem, note
    plan = plan_of(record)
    commit = held["commit"]
    if held.get("uncommitted"):
        return "", f"frozen with --force from bytes that are not those of commit {commit[:12]}"
    name = _name(top, plan) if top is not None else None
    if top is None or name is None:
        return "", f"{plan.name} is not in a git repository, so its commit was not read"
    if not _commit_held(top, commit):
        return "", f"commit {commit[:12]} is not in this clone, so {name} was not read there"
    stored = _blob(top, f"{commit}:{name}")
    if stored is None:
        return "", f"{name} is not in commit {commit[:12]}, so it was not read there"
    if hashlib.sha256(stored).hexdigest() != held.get("sha256"):
        return f"{name} at commit {commit[:12]} is not the file the record froze", ""
    return "", ""


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


def checked_plans(project: pathlib.Path) -> list[tuple[pathlib.Path, str, str, str]]:
    """Each plan frozen whole, the commit its record names, why the plan does not stand behind
    the record, and a note on what could not be compared, each "" where there is none. In a
    repository by `_plan_problem`, which also asks whether the commit holds the plan with the
    record's digest, so a record whose digest was rewritten to fit an edited plan is caught;
    outside one by the digests alone."""
    found = []
    for record, held, repo in _records(project):
        problem, note = (
            _plan_problem(record, held, repo) if repo is not None else plan_changed(record, held)
        )
        found.append((plan_of(record), held["commit"], problem, note))
    return found


def event_plan_problem(
    ledger: pathlib.Path, lines: list[str], commit: str
) -> tuple[str, str] | None:
    """Why the plan a `freeze` event in the ledger names at `commit` does not stand behind it,
    and a note on what could not be compared, each "" where there is none; None where no such
    event is in the ledger. For a claim whose freeze record is gone: deleting the record left
    the claim on no plan at all, while the chain still holds what was frozen.

    A problem only where bytes are present and differ: the plan on disk, or the plan at a commit
    this clone holds. A plan no longer on disk, or a commit a shallow clone does not hold, is a
    note."""
    events = []
    for line in lines:
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict) and event.get("event") == "freeze" and event.get("commit"):
            events.append(event)
    named = [e for e in events if e["commit"] == commit]
    if not named:
        return None
    found = try_run("rev-parse", "--show-toplevel", cwd=ledger.parent)
    top = pathlib.Path(found) if found else None
    notes = []
    for event in named:
        plan = ledger.parent.parent / str(event.get("file", ""))
        if not plan.is_file():
            notes.append(f"the ledger's freeze of {event.get('file')} names no plan on disk")
            continue
        if sha256_of_file(plan) != event.get("sha256"):
            return f"{plan.name} has changed since the ledger recorded its freeze", ""
        name = _name(top, plan) if top is not None else None
        if top is None or name is None:
            notes.append(f"{plan.name} is not in a git repository, so its commit was not read")
        elif not _commit_held(top, commit):
            notes.append(f"commit {commit[:12]} is not in this clone, so {name} was not read there")
        elif (stored := _blob(top, f"{commit}:{name}")) is None:
            notes.append(f"{name} is not in commit {commit[:12]}, so it was not read there")
        elif hashlib.sha256(stored).hexdigest() != event.get("sha256"):
            return f"commit {commit[:12]} does not hold {plan.name} as the ledger froze it", ""
    return "", "; ".join(notes)


def read_all(project: pathlib.Path, ledger: pathlib.Path) -> list[Freeze]:
    """Every freeze record in the repository holding `project`, or below `project` outside one."""
    lines = lines_of(ledger) if ledger.is_file() else []
    found = []
    for record, held, repo in _records(project):
        frozen_at = str(held.get("frozen_at", ""))
        # A plan edited since the freeze places nothing, nor does a record with no plan beside
        # it. What could not be read, such as a commit a shallow clone does not hold or a freeze
        # made with `--force`, leaves the record placed by the ledger as it would be otherwise.
        problem, _ = _plan_problem(record, held, repo)
        if problem := problem or no_plan(record):
            found.append(Freeze(record, held["commit"], frozen_at, None, problem, True))
            continue
        prior = False
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
            prior = position == 0
        found.append(
            Freeze(record, held["commit"], frozen_at, position, misplaced, ledger.is_file(), prior)
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
