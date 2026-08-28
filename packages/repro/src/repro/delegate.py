"""`repro <tool>` runs the tool, and `repro check` runs the ones the project uses.

Each tool ships its own command and keeps it. `citations verify` is not deprecated, is not
going to be, and `repro citations verify` does exactly what it does -- the delegation is a
spelling, not a feature, and saying otherwise would oversell it.

What only exists here is `repro check`: one pass over a project, one report, one exit code,
across every tool the project actually uses. Four commands run by hand, each with its own
exit code and its own idea of what a clean run looks like, is the thing this replaces.

The tools are called in process rather than as subprocesses. They are declared dependencies
of this package, so they are importable wherever it is installed, and a subprocess would cost
an interpreter start per tool for no isolation this needs.
"""

from __future__ import annotations

import contextlib
import io
import pathlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass


#: A tool, how to reach its command, how to ask it to check a project, and how to tell
#: whether the project uses it at all. `detect` is the part that keeps `repro check` honest:
#: a project with no preregistration should not be told its preregistrations are fine.
@dataclass(frozen=True)
class Tool:
    name: str
    module: str
    summary: str
    check_argv: tuple[str, ...]
    markers: tuple[str, ...]
    """Paths whose presence means this project uses the tool. Any one is enough.

    State directories only, never a data directory that happens to share the name. `results/`
    is a committed data directory in this project's own convention while `.results/` is the
    tool's state, and matching the former reported the demo as using `results` and then failed
    it for having no `.results/` -- a spurious failure invented by the detector.
    """

    def entry(self) -> Callable[[Sequence[str] | None], int]:
        import importlib

        return importlib.import_module(self.module).main

    def used_by(self, root: pathlib.Path) -> bool:
        return any((root / m).exists() for m in self.markers)


TOOLS: tuple[Tool, ...] = (
    Tool(
        name="prereg",
        module="prereg.cli",
        summary="freeze a plan before running, and record what deviated from it",
        check_argv=("check",),
        markers=(".prereg", "preregistrations", "preregs"),
    ),
    Tool(
        name="citations",
        module="citations.cli",
        summary="check that every quotation resolves in the source it cites",
        check_argv=("verify",),
        markers=(".citations", "claims"),
    ),
    Tool(
        name="results",
        module="results.cli",
        summary="seal a run, record what it produced, and verify the chain",
        check_argv=("verify",),
        markers=(".results",),
    ),
)

BY_NAME = {t.name: t for t in TOOLS}


def run(tool: Tool, argv: Sequence[str]) -> int:
    """Call one tool's command with `argv`, returning its exit code.

    A tool that raises `SystemExit` -- argparse does, on `--help` and on a usage error -- has
    its code taken rather than being allowed to end this process, so `repro citations --help`
    prints help and returns instead of exiting from underneath the caller.
    """
    try:
        return int(tool.entry()(list(argv)) or 0)
    except SystemExit as e:
        return int(e.code or 0)


@dataclass(frozen=True)
class Outcome:
    tool: str
    used: bool
    code: int | None
    output: str

    @property
    def line(self) -> str:
        if not self.used:
            return f"  {self.tool:<12} not used here"
        return f"  {self.tool:<12} {'ok' if self.code == 0 else f'FAILED (exit {self.code})'}"


def check(root: pathlib.Path, only: Sequence[str] = ()) -> list[Outcome]:
    """Run every applicable tool's check over `root`, capturing what each said.

    A tool the project does not use is reported as such and not run. Reporting it as passing
    would be the same defect these tools exist to catch: a clean line standing for a check
    that never happened.
    """
    out: list[Outcome] = []
    for tool in TOOLS:
        if only and tool.name not in only:
            continue
        if not tool.used_by(root):
            out.append(Outcome(tool.name, False, None, ""))
            continue
        buf = io.StringIO()
        # Each tool resolves its configuration from the working directory, so running one for
        # a project elsewhere means being in that project. Without this, `repro check <dir>`
        # reported on whatever directory the shell happened to be in.
        with (
            contextlib.chdir(root),
            contextlib.redirect_stdout(buf),
            contextlib.redirect_stderr(buf),
        ):
            code = run(tool, tool.check_argv)
        out.append(Outcome(tool.name, True, code, buf.getvalue()))
    return out
