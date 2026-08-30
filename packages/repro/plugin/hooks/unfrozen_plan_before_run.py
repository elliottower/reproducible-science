#!/usr/bin/env python3
"""Say, before an analysis runs, that the plan governing it was never frozen.

Runs as a Claude Code PreToolUse hook on `Bash`. `frozen_plan_changed.py` notices a plan
edited after it was frozen; nothing noticed a plan that was never frozen at all. The
mechanism therefore engaged only for authors who had already opted in, and nothing ever asked
them to: across this project's own repositories, eleven of twelve plans in one of them carry
no freeze, which is what a check that only fires after the fact produces.

Freezing is cheap and only means something beforehand. A digest taken after the outcome is
visible establishes nothing about what was planned, so the moment to say this is the moment
before the run, which is the moment this hook has.

Design constraints, in order, matching the rest of the set:

1. Never break the session. Every failure exits 0 in silence.
2. Never block. `PreToolUse` can deny a command; this must not. A check that can halt the
   work it observes is a check that gets switched off, and a plan is a thing an author
   freezes because they mean it rather than because a tool refused to proceed.
3. Say nothing when there is nothing to say -- no plan, a frozen plan, or a command that
   does not run an analysis. A hook that speaks on every shell command is noise, and noise
   is uninstalled.
"""

from __future__ import annotations

import json
import pathlib
import re
import shlex
import sys

#: What `prereg freeze` writes. Its absence is the whole signal.
FROZEN = re.compile(r"^\*\*Plan sha256:\*\*[ \t]*`[0-9a-f]{64}`", re.M)

#: The filename `prereg` governs a directory with.
PLAN = "PREREG.md"

#: Programs that run an analysis. Deliberately short: a plan is about a computation, and
#: `ls`, `git status` and `cat` are not one. Matched on the first word and on the word after
#: a runner, so `uv run python x.py` and `python x.py` both count.
RUNNERS = {
    "python",
    "python3",
    "uv",
    "uvx",
    "poetry",
    "pipenv",
    "conda",
    "Rscript",
    "julia",
    "matlab",
    "stata",
    "sas",
    "make",
    "snakemake",
    "nextflow",
    "dvc",
    "papermill",
    "jupyter",
    "quarto",
    "pytest",
    "sbatch",
    "srun",
}

#: A plan still holding this many template markers has not been written yet, and telling
#: someone to freeze a blank form is worse than saying nothing.
STUB_MARKERS = ("N/A — ", "<what", "TODO", "FILL-IN")
STUB_THRESHOLD = 12

#: A hook runs before every shell command and must stay cheap.
MAX_BYTES = 2 * 1024 * 1024


def runs_an_analysis(command: str) -> bool:
    try:
        words = shlex.split(command)
    except ValueError:
        words = command.split()
    return any(pathlib.Path(w).name in RUNNERS for w in words[:3])


def governing_plan(start: pathlib.Path) -> pathlib.Path | None:
    """The plan governing `start`: here, or the nearest one above. Mirrors `prereg.plan.find`."""
    for directory in [start, *start.parents]:
        candidate = directory / PLAN
        if candidate.is_file():
            return candidate
    return None


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (ValueError, OSError):
        return 0

    command = (payload.get("tool_input") or {}).get("command", "")
    if not command or not runs_an_analysis(command):
        return 0

    cwd = payload.get("cwd") or ""
    try:
        start = pathlib.Path(cwd).resolve() if cwd else pathlib.Path.cwd()
    except OSError:
        return 0

    plan = governing_plan(start)
    if plan is None:
        return 0

    try:
        if plan.stat().st_size > MAX_BYTES:
            return 0
        text = plan.read_text(errors="replace")
    except OSError:
        return 0

    if FROZEN.search(text):
        return 0
    if sum(text.count(marker) for marker in STUB_MARKERS) >= STUB_THRESHOLD:
        return 0

    message = (
        f"{plan} governs this directory and carries no freeze.\n"
        f"A plan frozen after the run establishes nothing about what was planned, so the "
        f"only moment this is worth saying is before it.\n"
        f"  prereg freeze {plan}\n"
        f"Freeze it if this run is confirmatory. If the work is exploratory, it needs no "
        f"freeze and this will not ask again once the plan says so."
    )
    json.dump(
        {"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": message}},
        sys.stdout,
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        # Constraint 1.
        sys.exit(0)
