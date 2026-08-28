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

#: How far below the root a data directory is looked for. Three levels reaches
#: `paper/prior_art/claims`, which is where this registry's own papers keep them, and stops
#: well before a search becomes a crawl of the whole tree.
MAX_DEPTH = 3

#: Directories a data marker is never looked for inside.
SKIP = frozenset({"node_modules", "venv", ".venv", "site-packages", "build", "dist"})


def _hidden(rel: pathlib.Path) -> bool:
    return any(p.startswith(".") or p in SKIP for p in rel.parts)


#: A tool, how to reach its command, how to ask it to check a project, and how to tell
#: whether the project uses it at all. `detect` is the part that keeps `repro check` honest:
#: a project with no preregistration should not be told its preregistrations are fine.
@dataclass(frozen=True)
class Tool:
    name: str
    module: str
    summary: str
    check_argv: tuple[str, ...]
    state_markers: tuple[str, ...]
    """Directories the tool creates. Existence is enough: the tool made them, so it is in use.

    State directories only, never a data directory that happens to share the name. `results/`
    is a committed data directory in this project's own convention while `.results/` is the
    tool's state, and matching the former reported the demo as using `results` and then failed
    it for having no `.results/` -- a spurious failure invented by the detector.
    """

    data_markers: tuple[str, ...] = ()
    """Directories holding the material a check reads, found at the root or below it.

    Two things separate these from state markers. They must have something in them: an empty
    `preregistrations/` was read as "this project preregisters", and `prereg check` then failed
    it for having no plan -- the detector inventing a failure again, one level along. And they
    are looked for below the root, because a paper keeps its claims where its paper lives:
    this library's own registry points at `paper/prior_art/claims`, which a root-only search
    does not see, so a project with 61 pinned quotations was told no tool applied to it.
    """

    points_at: str | None = None
    """The flag that tells this tool's check where the data is, where it must be told.

    `citations verify` checks the claims directory it is given and reports "nothing to check"
    otherwise, so running it without one turns every citations project into a failure. A tool
    that must be pointed somewhere is in use only when there is somewhere to point it: a
    library with no claims is not a project whose quotations failed, it is one with none.
    """

    @property
    def markers(self) -> tuple[str, ...]:
        return self.state_markers + self.data_markers

    def entry(self) -> Callable[[Sequence[str] | None], int]:
        import importlib

        return importlib.import_module(self.module).main

    def data_dir(self, root: pathlib.Path) -> pathlib.Path | None:
        """The shallowest non-empty data directory, root first. None where there is none."""
        for name in self.data_markers:
            here = root / name
            if here.is_dir() and any(here.iterdir()):
                return here
        for depth in range(1, MAX_DEPTH + 1):
            for name in self.data_markers:
                found = sorted(
                    d
                    for d in root.glob("/".join(["*"] * depth) + f"/{name}")
                    if d.is_dir() and not _hidden(d.relative_to(root)) and any(d.iterdir())
                )
                if found:
                    return found[0]
        return None

    def used_by(self, root: pathlib.Path) -> bool:
        if self.points_at:
            return self.data_dir(root) is not None
        return any((root / m).exists() for m in self.state_markers) or (
            self.data_dir(root) is not None
        )

    def argv_for(self, root: pathlib.Path) -> tuple[str, ...]:
        """`check_argv`, told where to look where the tool needs telling."""
        if not self.points_at:
            return self.check_argv
        found = self.data_dir(root)
        return (*self.check_argv, self.points_at, str(found)) if found else self.check_argv


TOOLS: tuple[Tool, ...] = (
    Tool(
        name="prereg",
        module="prereg.cli",
        summary="freeze a plan before running, and record what deviated from it",
        check_argv=("check",),
        state_markers=(".prereg",),
        data_markers=("preregistrations", "preregs"),
    ),
    Tool(
        name="citations",
        module="citations.cli",
        summary="check that every quotation resolves in the source it cites",
        check_argv=("verify",),
        state_markers=(".citations",),
        data_markers=("claims",),
        points_at="--claims",
    ),
    Tool(
        name="results",
        module="results.cli",
        summary="seal a run, record what it produced, and verify the chain",
        check_argv=("verify",),
        state_markers=(".results",),
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
            code = run(tool, tool.argv_for(root))
        out.append(Outcome(tool.name, True, code, buf.getvalue()))
    return out
