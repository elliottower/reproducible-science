"""Does git hold a source this project's quotations are pinned to, as a plan is frozen?

A freeze names a commit, and the freeze is evidence because that commit's identifier never
changes. A source text in that commit can only be taken out later by rewriting the history,
which gives the commit another identifier. So a freeze asks first, and where git holds a pinned
source it is refused before anything is written, unless `--allow-tracked-sources` says the
sources are meant to be there.

The commit a freeze names is `HEAD`, so `HEAD` is one of the two places asked about: a source
`git rm --cached` has untracked is in it until the removal is committed. The index is the
other, because what is staged is what the next commit will hold.

`citations` knows where a project keeps its claims files, what a pinned source is, and which
of them git holds. This asks it, by running `citations lint --claims --json` in the plan's
directory, and knows none of that: no name of a directory is written here, and nothing of that
package is imported.

Only an answer refuses. Where `citations` is not installed, where it is a version that cannot
be asked this way, where the project keeps no claims directory, or where git cannot answer,
nothing was found, nothing is said, and the freeze goes ahead: a check that could not run is
never a reason a plan could not be frozen.
"""

from __future__ import annotations

import json
import pathlib
import shutil
import subprocess
from dataclasses import dataclass

from provenance_core.gitref import try_run

#: How many sources a report names before it counts the rest.
SHOWN = 10

#: `citations lint --claims` runs one `git ls-files` for each directory of sources, and one
#: `git ls-tree` for the repository.
TIMEOUT = 30

TRACKED = "tracked"
STAGED = "staged"
IN_HEAD = "in HEAD"


@dataclass(frozen=True, order=True)
class Held:
    """One pinned source git holds: its path from the top of the repository, and where."""

    path: str
    index: bool
    head: bool

    @property
    def label(self) -> str:
        """`tracked` in the index and the last commit, `staged` in the index alone, and
        `in HEAD` out of the index with its removal not yet committed."""
        if not self.index:
            return IN_HEAD
        return TRACKED if self.head else STAGED


def _asked(program: str, folder: pathlib.Path) -> list[Held]:
    """The sources `citations` reports git holding, asked from `folder`, or none.

    A row that says nothing of the index or of `HEAD` is one git tracks: that is what a row
    meant before `citations` said which.
    """
    try:
        done = subprocess.run(
            [program, "lint", "--claims", "--json"],
            cwd=folder,
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
            check=False,  # no claims directory exits 2, and an older `citations` refuses the flag
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if done.returncode != 0:
        return []
    try:
        return [
            Held(str(row["source"]), bool(row.get("index", True)), bool(row.get("head", True)))
            for row in json.loads(done.stdout)["tracked"]
        ]
    except (ValueError, KeyError, TypeError, AttributeError):
        return []


def tracked(plan_dir: pathlib.Path) -> list[Held]:
    """Every pinned source git holds, by path from the top of the repository, in order."""
    program = shutil.which("citations")
    top = try_run("rev-parse", "--show-toplevel", cwd=plan_dir)
    if program is None or not top:
        return []
    root = pathlib.Path(top).resolve()
    found = []
    for held in _asked(program, plan_dir):
        path = pathlib.Path(held.path)
        within = path.relative_to(root).as_posix() if path.is_relative_to(root) else held.path
        found.append(Held(within, held.index, held.head))
    return sorted(found)


def _listed(found: list[Held]) -> list[str]:
    """The heading and the sources under it, ten at most and then a count of the rest."""
    n = len(found)
    lines = [
        f"git holds {n:,} source{'' if n == 1 else 's'} this project's quotations are pinned to"
    ]
    lines += [f"  {held.label:<7}  {held.path}" for held in found[:SHOWN]]
    if n > SHOWN:
        lines.append(f"  ... and {n - SHOWN:,} more; `citations lint --claims` lists every one")
    return lines


def refusal(path: pathlib.Path, found: list[Held]) -> str:
    """What a freeze of `path` prints in place of freezing, with the way out of each case."""
    labels = {held.label for held in found}
    lines = [
        f"{path} was not frozen, and nothing was written.",
        *_listed(found),
        "A freeze names a commit, and a source in that commit can only be removed later by",
        "rewriting history, which changes the commit's identifier.",
    ]
    in_index = [f"`{label}`" for label in (TRACKED, STAGED) if label in labels]
    if in_index:
        lines += [
            f"{' and '.join(in_index)}: untrack each with `git rm --cached <file>`, add an ignore",
            "rule, commit, and freeze again. The record's sha256 still pins the file.",
        ]
    if IN_HEAD in labels:
        lines += [
            f"`{IN_HEAD}`: no longer tracked, and still in the last commit. Commit the removal,",
            "then freeze.",
        ]
    lines.append("Or keep them and freeze with --allow-tracked-sources.")
    return "\n".join(lines)


def warning(found: list[Held]) -> str:
    """What a freeze made with `--allow-tracked-sources` prints after its own report."""
    return "\n".join(
        [
            *_listed(found),
            "  Frozen with --allow-tracked-sources. A source in the commit a freeze names can only",
            "  be removed later by rewriting history, which changes that commit's identifier.",
        ]
    )
