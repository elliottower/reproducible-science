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
"""

from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass

from provenance_core import try_run

from results import ledger, stamps


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
    """Each commit in the history of HEAD that changed `path`, newest first."""
    out = try_run("log", "--format=%H", "--", path, cwd=where.top)
    return out.split() if out else []


def _lines(text: str) -> list[str]:
    return [line.strip() for line in text.split("\n") if line.strip()]


def committed_ledgers(lp: pathlib.Path) -> list[tuple[str, list[str]]]:
    """Each version of the ledger a commit holds, as its lines, newest commit first."""
    where = locate(lp)
    if where is None:
        return []
    found = []
    for sha in _commits(where, where.ledger):
        text = try_run("show", f"{sha}:{where.ledger}", cwd=where.top)
        if text is not None:
            found.append((sha, _lines(text)))
    return found


def committed_counts(lp: pathlib.Path) -> list[tuple[str, int]]:
    """The length each committed version of the anchor records, newest commit first."""
    where = locate(lp)
    if where is None:
        return []
    found = []
    for sha in _commits(where, where.anchor):
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
    """Each timestamp proof a commit added that is not on disk now, with the commit."""
    where = locate(lp)
    if where is None:
        return []
    out = try_run(
        "log",
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


__all__ = ["committed_counts", "committed_ledgers", "locate", "missing_proofs", "rewritten"]
