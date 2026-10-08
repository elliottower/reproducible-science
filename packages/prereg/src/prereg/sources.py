"""Does git track a source this project's quotations are pinned to, as a plan is frozen?

A freeze names a commit, and the freeze is evidence because that commit's identifier never
changes. A source text git tracks is in that commit or in one close to it, and the only way to
take it out later is to rewrite the history, which gives the commit another identifier. So the
time to hear about a tracked source is before the freeze is committed.

`citations` knows where a project keeps its claims files and which of the sources they pin git
tracks. This asks it, by running `citations lint --claims --json` in the plan's directory, and
knows neither: no name of a directory is written here, and nothing of that package is imported.

Printed text and nothing else. Where `citations` is not installed, where it is a version that
cannot be asked this way, where the project keeps no claims directory, or where git cannot
answer, there is nothing to say and nothing is said.
"""

from __future__ import annotations

import json
import pathlib
import shutil
import subprocess

from provenance_core.gitref import try_run

#: How many sources the warning names before it counts the rest.
SHOWN = 10

#: `citations lint --claims` runs one `git ls-files` for each directory of sources.
TIMEOUT = 30


def _asked(program: str, folder: pathlib.Path) -> list[str]:
    """The tracked sources `citations` reports from `folder`, or none where it reports nothing."""
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
        return [str(row["source"]) for row in json.loads(done.stdout)["tracked"]]
    except (ValueError, KeyError, TypeError):
        return []


def tracked(plan_dir: pathlib.Path) -> list[str]:
    """Every pinned source git tracks, as a path from the top of the repository, in order."""
    program = shutil.which("citations")
    top = try_run("rev-parse", "--show-toplevel", cwd=plan_dir)
    if program is None or not top:
        return []
    root = pathlib.Path(top).resolve()
    found = (pathlib.Path(source) for source in _asked(program, plan_dir))
    return sorted(
        path.relative_to(root).as_posix() if path.is_relative_to(root) else str(path)
        for path in found
    )


def warning(plan_dir: pathlib.Path) -> str:
    """What a freeze prints about tracked sources, or nothing where there are none."""
    found = tracked(plan_dir)
    if not found:
        return ""
    n = len(found)
    lines = [
        f"git tracks {n:,} source{'' if n == 1 else 's'} this project's quotations are pinned to"
    ]
    lines += [f"  tracked  {source}" for source in found[:SHOWN]]
    if n > SHOWN:
        lines.append(f"  ... and {n - SHOWN:,} more; `citations lint --claims` lists every one")
    lines += [
        "  A source in the commit a freeze names can only be removed later by rewriting history,",
        "  which changes that commit's identifier. Untrack and ignore the files before freezing.",
    ]
    return "\n".join(lines)
