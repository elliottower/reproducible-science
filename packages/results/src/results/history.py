"""What git history holds of the ledger, read back against the ledger on disk.

The anchor records how long the chain is, and whoever can write the ledger can write the
anchor. A ledger with an event deleted and every later `prev_hash` recomputed, its anchor
rewritten to match, verifies: the chain is consistent and the anchor agrees with it. What it
cannot also rewrite is a commit that was made before. A ledger only grows, so every version
of it that history holds is a prefix of the one on disk, and a committed version that is not
is a ledger that was rewritten.

Read with git and nothing else. Outside a repository, or where the ledger was never
committed, there is no history and nothing is reported: the check is as strong as what was
committed, and no stronger.

A commit in which the ledger is absent ends one chain. A ledger deleted and started again at the
same path is a new chain, and every version of the old one failed as a rewrite of it. Only the
versions committed after the latest such commit are compared, and the restart is reported with
the exposures the earlier chain recorded and this one does not, since a restart is also the
cheapest way to drop one.

A restart is a note, naming the date and the events the earlier chain held, and fails nothing:
honest work restarts a ledger, and the records make a restart visible to a reader with a clone
rather than resist an author who means to rewrite them. Every exposure the earlier chain held is
carried forward with the commit that first added it, so an exposure re-added after a claim,
which the comparison by content then finds kept, still orders before every run of the new chain
committed after it, and a confirmatory claim on such a run is reported as made after the
outcomes were seen.
"""

from __future__ import annotations

import datetime
import json
import pathlib
from dataclasses import dataclass, field

from provenance_core import try_run

from results import ledger, stamps
from results.timeline import precedes


@dataclass(frozen=True)
class Located:
    """Where the ledger sits in its repository."""

    top: pathlib.Path
    ledger: str
    anchor: str
    stamps: str


def locate(lp: pathlib.Path) -> Located | None:
    """The repository holding the ledger and the ledger's paths in it, or None where git does
    not track this directory."""
    here = lp.resolve().parent
    top = try_run("rev-parse", "--show-toplevel", cwd=here)
    if not top:
        return None
    root = pathlib.Path(top).resolve()
    try:
        rel = here.relative_to(root)
    except ValueError:
        return None
    return Located(
        root,
        (rel / lp.name).as_posix(),
        (rel / ledger.ANCHOR).as_posix(),
        (rel / stamps.STAMPS).as_posix(),
    )


def _commits(where: Located, path: str) -> list[str]:
    """Each commit in the history of HEAD that changed `path`, newest first, merges included.
    `--full-history`, because git's default simplification follows one parent where a merge
    leaves the path as that parent had it, and a merge taking one side's ledger then hid every
    commit on the other side, a committed exposure among them."""
    out = try_run("log", "--full-history", "--topo-order", "--format=%H", "--", path, cwd=where.top)
    return out.split() if out else []


@dataclass(frozen=True)
class Exposure:
    """An `access` event a chain before the restart held, and the commit that first added it."""

    event: dict
    commit: str
    #: That commit's committer time, which orders it only where commit order cannot.
    committed_at: str


@dataclass(frozen=True)
class Restart:
    """The latest commit in which the ledger is absent, and what the chain before it held."""

    deleted: str
    #: The first commit after `deleted` holding a ledger, or "" where none is committed yet.
    restarted: str
    #: Events the latest version before `deleted` held.
    events: int
    #: Each exposure, an `access` event, an earlier version held and the ledger does not.
    dropped: list[dict] = field(default_factory=list)
    #: Each event any version before `deleted` held, on every line of history, once.
    earlier: list[dict] = field(default_factory=list)
    #: Each `access` event any version before `deleted` held, kept here or not.
    exposures: list[Exposure] = field(default_factory=list)
    #: When the ledger was deleted: the committer time of `deleted`, in UTC, or "".
    on: str = ""

    @property
    def kinds(self) -> dict[str, int]:
        """How many events of each kind the earlier chain held, in the order first seen."""
        counted: dict[str, int] = {}
        for e in self.earlier:
            kind = str(e.get("event") or "?")
            counted[kind] = counted.get(kind, 0) + 1
        return counted


def _after(where: Located, lp: pathlib.Path) -> tuple[set[str] | None, Restart | None]:
    """The commits after the latest one in which the ledger is absent, and that restart; None
    and None where every commit that changed the ledger holds one. Newest first in topological
    order, so the first commit without a ledger has no later one among its descendants."""
    shas = _commits(where, where.ledger)
    deleted = next(
        (
            sha
            for sha in shas
            if try_run("cat-file", "-e", f"{sha}:{where.ledger}", cwd=where.top) is None
        ),
        None,
    )
    if deleted is None:
        return None, None
    out = try_run("rev-list", "--ancestry-path", f"{deleted}..HEAD", cwd=where.top)
    after = set(out.split()) if out else set()
    restarted = next((sha for sha in reversed(shas) if sha in after), "")
    now = ledger.read_ledger(lp) if lp.exists() else []
    kept = {(e.get("level"), e.get("note")) for e in now if e.get("event") == "access"}
    dropped: list[dict] = []
    earlier: list[dict] = []
    added: dict[str, tuple[dict, str]] = {}
    events = 0
    for sha in shas:
        if sha in after or sha == deleted:
            continue
        text = try_run("show", f"{sha}:{where.ledger}", cwd=where.top)
        if text is None:
            continue
        held = [json.loads(line) for line in _lines(text) if _is_event(line)]
        events = events or len(held)
        for e in held:
            if e not in earlier:
                earlier.append(e)
            if e.get("event") == "access":
                # Newest first, so the last commit seen holding it is the one that added it.
                added[json.dumps(e, sort_keys=True)] = (e, sha)
            key = (e.get("level"), e.get("note"))
            if e.get("event") == "access" and key not in kept and e not in dropped:
                dropped.append(e)
    exposures = [Exposure(e, sha, _committed_at(where, sha)) for e, sha in added.values()]
    on = _committed_at(where, deleted)
    return after, Restart(deleted, restarted, events, dropped, earlier, exposures, on)


def _committed_at(where: Located, sha: str) -> str:
    """The commit's committer time in UTC, as the ledger writes its own, or ""."""
    said = try_run("show", "-s", "--format=%ct", sha, cwd=where.top)
    if not said or not said.isdigit():
        return ""
    return datetime.datetime.fromtimestamp(int(said), datetime.UTC).isoformat()


def exposed_before(lp: pathlib.Path, exposure: Exposure, run: dict) -> bool:
    """Whether `exposure`, which a chain before the restart held, came before `run`, an event of
    the ledger on disk. By commit order: the run is not committed, or the first commit holding
    it descends from the one that added the exposure. Where neither descends from the other,
    by that commit's time against the run's timestamp."""
    where = locate(lp)
    if where is None:
        return True
    after = _after(where, lp)[0] or set()
    holding = [
        sha
        for sha in _commits(where, where.ledger)
        if sha in after
        and run in [json.loads(line) for line in _lines(_show(where, sha)) if _is_event(line)]
    ]
    if not holding:
        return True
    first = holding[-1]
    if try_run("merge-base", "--is-ancestor", exposure.commit, first, cwd=where.top) is not None:
        return True
    return precedes(exposure.committed_at, str(run.get("timestamp") or ""))


def _show(where: Located, sha: str) -> str:
    return try_run("show", f"{sha}:{where.ledger}", cwd=where.top) or ""


def _is_event(line: str) -> bool:
    try:
        return isinstance(json.loads(line), dict)
    except json.JSONDecodeError:
        return False


def restart(lp: pathlib.Path) -> Restart | None:
    """The restart before which committed versions of the ledger are not compared, or None."""
    where = locate(lp)
    return None if where is None else _after(where, lp)[1]


def _lines(text: str) -> list[str]:
    return [line.strip() for line in text.split("\n") if line.strip()]


def committed_ledgers(lp: pathlib.Path) -> list[tuple[str, list[str]]]:
    """Each version of the ledger a commit after the latest restart holds, as its lines, newest
    commit first."""
    where = locate(lp)
    if where is None:
        return []
    after = _after(where, lp)[0]
    found = []
    for sha in _commits(where, where.ledger):
        if after is not None and sha not in after:
            continue
        text = try_run("show", f"{sha}:{where.ledger}", cwd=where.top)
        if text is not None:
            found.append((sha, _lines(text)))
    return found


def committed_counts(lp: pathlib.Path) -> list[tuple[str, int]]:
    """The length each committed version of the anchor after the ledger's latest restart
    records, newest commit first."""
    where = locate(lp)
    if where is None:
        return []
    after = _after(where, lp)[0]
    found = []
    for sha in _commits(where, where.anchor):
        if after is not None and sha not in after:
            continue
        text = try_run("show", f"{sha}:{where.anchor}", cwd=where.top)
        try:
            count = json.loads(text).get("count") if text else None
        except (json.JSONDecodeError, AttributeError):
            continue
        if isinstance(count, int):
            found.append((sha, count))
    return found


def rewritten(lp: pathlib.Path) -> list[str]:
    """One problem for each committed version of the ledger or its anchor the ledger on disk
    does not extend. Empty where every committed version is a prefix of it."""
    now = ledger._lines(lp) if lp.exists() else []
    problems = []
    for sha, lines in committed_ledgers(lp):
        if len(lines) > len(now):
            problems.append(
                f"commit {sha[:12]} holds {len(lines)} events and the ledger holds {len(now)}"
            )
            continue
        differs = next(
            (i for i, (a, b) in enumerate(zip(lines, now[: len(lines)], strict=True)) if a != b),
            None,
        )
        if differs is not None:
            problems.append(
                f"commit {sha[:12]} holds a different event {differs + 1} than the ledger does"
            )
    for sha, count in committed_counts(lp):
        if count > len(now):
            problems.append(
                f"commit {sha[:12]} anchors {count} events and the ledger holds {len(now)}"
            )
    return problems


def missing_proofs(lp: pathlib.Path) -> list[tuple[str, str]]:
    """Each timestamp proof a commit added that is not on disk now, with the commit. On every
    line of history, and with a merge diffed against each parent, so a proof added on a side a
    merge dropped, or inside the merge itself, is still found."""
    where = locate(lp)
    if where is None:
        return []
    out = try_run(
        "log",
        "--full-history",
        "-m",
        "--diff-filter=A",
        "--name-only",
        "--format=commit %H",
        "--",
        where.stamps,
        cwd=where.top,
    )
    found: dict[str, str] = {}
    sha = ""
    for line in (out or "").splitlines():
        if line.startswith("commit "):
            sha = line.removeprefix("commit ").strip()
        elif line.strip().endswith(".ots"):
            found.setdefault(line.strip(), sha)
    return [(path, sha) for path, sha in sorted(found.items()) if not (where.top / path).exists()]


__all__ = [
    "Exposure",
    "Restart",
    "committed_counts",
    "committed_ledgers",
    "exposed_before",
    "locate",
    "missing_proofs",
    "restart",
    "rewritten",
]
