"""`repro ci init --pr-bot`: the caller workflows of the pull-request bot.

    repro-pr-bot.yml           on `pull_request` (and `workflow_dispatch`): the check, with a
                               read-only token
    repro-pr-bot-respond.yml   on `workflow_run` after the check, `issue_comment` and
                               `pull_request_review_comment`: comment and record answers

Each calls the reusable workflow this repository holds at `.github/workflows/pr-bot.yml`,
which holds the jobs; these files only choose when it runs and what its token may do. They are two and not one: the comments must be
posted by a run that holds a token which writes, which `pull_request` never gives a fork, and
that run is started by `workflow_run` after the check. A workflow started by its own completion
is not something GitHub documents, so the run that writes is started by a second file.

The reusable workflow narrows the token again per job: the check job asks for `contents: read`
only, whatever the caller grants, because a called workflow can lower the permissions it is
passed and never raise them. Neither caller checks anything out. A file this command did not
write is never replaced.
"""

from __future__ import annotations

import argparse
import pathlib

from claims.manifest import DEFAULT_NAME
from provenance_core import atomic_write
from pydantic import BaseModel, ConfigDict

from repro import ci
from repro.exceptions import ReproError

#: The first line of each file this writes, and how it knows one of its own.
MARKER = "# Written by `repro ci init --pr-bot`."
DOCS = "https://reproducible.science/tools/repro/#a-bot-on-pull-requests"

#: The reusable workflow that holds the jobs, in this toolkit's own repository.
REUSABLE = "elliottower/reproducible-science/.github/workflows/pr-bot.yml"
#: The release of this repository the callers use: the tag of the release that publishes
#: reproducible-science-pr-bot at the version the reusable workflow runs.
REF = "v0.7.0"

CHECK_FILE = "repro-pr-bot.yml"
RESPOND_FILE = "repro-pr-bot-respond.yml"
#: The check caller's name, which `workflow_run` in the respond caller names it by.
CHECK_NAME = "repro pr bot check"

CHECK = """\
{marker} The pull-request bot's check: on a pull request it checks the
# head commit with a read-only token and uploads what it found, and comments on nothing.
# {respond} comments. {docs}
name: {check_name}

on:
  pull_request:
  # `reproducible-science-pr-bot reply` starts this again after it commits to the branch.
  workflow_dispatch:
    inputs:
      pull_request:
        description: the number of the pull request whose branch this is
        required: true

permissions: {{}}

jobs:
  check:
    permissions:
      contents: read  # to check out the pull request's head commit
    # Pinned to a release tag of the toolkit. Replace it with the commit that tag names.
    uses: {reusable}@{ref}  # zizmor: ignore[unpinned-uses]
    with:
      manifest: {manifest}
"""

RESPOND = """\
{marker} The pull-request bot's comments and answers: after the check
# it comments on the pull request, and on a reply 1-4 from someone with write access it records
# the answer. Neither job checks out the pull request. {docs}
name: repro pr bot respond

# workflow_run and issue_comment run with a token that writes, so each is safe only where it
# never runs what the pull request brought. The jobs they call check out nothing and read the
# findings and the comments as data. An edited reply is read as what it now says.
on:
  workflow_run:  # zizmor: ignore[dangerous-triggers]
    workflows: [{check_name}]
    types: [completed]
  issue_comment:  # zizmor: ignore[dangerous-triggers]
    types: [created, edited]
  pull_request_review_comment:
    types: [created, edited]

permissions: {{}}

jobs:
  respond:
    # The most either job needs; each job of the called workflow asks for less.
    permissions:
      actions: write  # to download the findings, and start the checks again after a commit
      contents: write  # to commit a set_aside entry to {manifest} on a pull request's branch
      issues: write  # to comment in a pull request's conversation
      pull-requests: write  # to comment on a diff, answer in its threads and resolve them
    # Pinned to a release tag of the toolkit. Replace it with the commit that tag names.
    uses: {reusable}@{ref}  # zizmor: ignore[unpinned-uses]
    with:
      manifest: {manifest}
      dispatch: {dispatch}
"""


class CallerExistsError(ReproError):
    """A file is already where `--pr-bot` would write. Nothing is overwritten."""

    def __init__(self, ours: tuple[pathlib.Path, ...], foreign: tuple[pathlib.Path, ...]) -> None:
        self.ours = ours
        self.foreign = foreign
        said = []
        if foreign:
            said.append(
                f"{', '.join(str(path) for path in foreign)} exists and `repro ci init "
                "--pr-bot` did not write it, so it is never replaced."
            )
        if ours:
            said.append(
                f"{', '.join(str(path) for path in ours)} exists. `--force` replaces a workflow "
                "this command wrote."
            )
        super().__init__(" ".join(said) + " Nothing was written.")


class NoManifestError(ReproError):
    """There is no manifest for the bot to check."""

    def __init__(self, root: pathlib.Path) -> None:
        super().__init__(
            f"no {DEFAULT_NAME} in {root} or above it inside the repository; nothing was "
            "written. Write one first:\n\n    repro manifest init"
        )


class Caller(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    file: str
    text: str


def _yaml(text: str) -> str:
    """A string as a YAML scalar: plain where it can be, double-quoted otherwise."""
    return ci._scalar(text)


def callers(manifest: str = DEFAULT_NAME, dispatch: tuple[str, ...] = ()) -> list[Caller]:
    """The two caller workflows. `manifest` is the manifest's path from the top of the
    repository, and `dispatch` the workflows besides the check that `reply` starts again after
    it commits."""
    started = " ".join((CHECK_FILE, *dispatch))
    fields = {
        "marker": MARKER,
        "docs": DOCS,
        "check_name": CHECK_NAME,
        "respond": RESPOND_FILE,
        "reusable": REUSABLE,
        "ref": REF,
        "manifest": _yaml(manifest),
        "dispatch": _yaml(started),
    }
    return [
        Caller(file=CHECK_FILE, text=CHECK.format(**fields)),
        Caller(file=RESPOND_FILE, text=RESPOND.format(**fields)),
    ]


def _ci_written(path: pathlib.Path) -> bool:
    return path.read_text(encoding="utf-8").startswith(ci.MARKER)


def dispatchable(root: pathlib.Path) -> list[str]:
    """The workflows `repro ci init` wrote here that can be started with workflow_dispatch:
    the checks a branch protection rule may require, which a commit by the bot starts none of."""
    return [
        path.name
        for path in sorted((root / ci.WORKFLOWS).glob("*.yml"))
        if _ci_written(path) and "\n  workflow_dispatch:" in path.read_text(encoding="utf-8")
    ]


def init(cwd: pathlib.Path, *, force: bool = False) -> int:
    """Write the two caller workflows into the repository holding `cwd`."""
    root, path = ci.located(cwd)
    if path is None:
        raise NoManifestError(root)
    started = dispatchable(root)
    wanted = callers(path.relative_to(root).as_posix(), tuple(started))
    there = [root / ci.WORKFLOWS / caller.file for caller in wanted]
    ours = tuple(
        target
        for target in there
        if target.exists() and target.read_text(encoding="utf-8").startswith(MARKER)
    )
    foreign = tuple(target for target in there if target.exists() and target not in ours)
    if foreign or (ours and not force):
        raise CallerExistsError(() if force else ours, foreign)

    (root / ci.WORKFLOWS).mkdir(parents=True, exist_ok=True)
    for caller, target in zip(wanted, there, strict=True):
        atomic_write(target, caller.text)
        print(f"wrote {target}")
    print(f"  {CHECK_FILE}: on a pull request, checks its head commit read-only")
    print(f"  {RESPOND_FILE}: after the check, comments; on a reply 1-4, records the answer")
    print(f"  both call {REUSABLE}@{REF}")
    print("\nnext:")
    print(f"  1. commit {ci.WORKFLOWS.as_posix()}/{CHECK_FILE} and {RESPOND_FILE}, and merge")
    print("     them into the default branch. GitHub runs `workflow_run` and `issue_comment`")
    print("     workflows only from the default branch, so the bot comments on no pull request")
    print("     before that.")
    print("  2. a reply is recorded only from someone with write access to this repository.")
    print("  3. on a pull request from a fork the bot comments and commits nothing.")
    print("  4. a commit the bot makes starts no workflow by itself, so after one it starts")
    print(f"     again: {' '.join((CHECK_FILE, *started))}.")
    lacking = [
        name
        for name in sorted(p.name for p in (root / ci.WORKFLOWS).glob("*.yml"))
        if name not in started and _ci_written(root / ci.WORKFLOWS / name)
    ]
    if lacking:
        print(f"     {', '.join(lacking)} cannot be started that way; `repro ci init --force`")
        print("     rewrites them with a workflow_dispatch trigger, and then `repro ci init")
        print("     --pr-bot --force` names them here.")
    return 0


def command(args: argparse.Namespace) -> int:
    """`repro ci init --pr-bot`."""
    return init(pathlib.Path.cwd(), force=args.force)


__all__ = [
    "CHECK_FILE",
    "MARKER",
    "REF",
    "RESPOND_FILE",
    "REUSABLE",
    "CallerExistsError",
    "NoManifestError",
    "callers",
    "command",
    "dispatchable",
    "init",
]
