"""`repro bot init`: the three workflows, written as `repro ci init` writes its own.

    repro-bot-check.yml   on `pull_request`, read-only: check the pull request's head commit
                          and upload what was found as an artifact
    repro-bot-post.yml    on `workflow_run` after the check: download that artifact and comment;
                          checks out nothing
    repro-bot-reply.yml   on `issue_comment` and `pull_request_review_comment`: record an
                          answer, and commit a `set_aside` entry to a branch of this repository;
                          checks out nothing

The split is GitHub's advice for a pull request from a fork: the job that runs on the pull
request's files holds a read-only token, and the jobs holding a token that writes never check
those files out. Every action is pinned by commit, every job states its permissions, and a file
this command did not write is never replaced.
"""

from __future__ import annotations

import pathlib
import shlex

from provenance_core import atomic_write
from pydantic import BaseModel, ConfigDict

from repro import __version__, ci
from repro.bot import actions
from repro.bot.findings import manifest_path
from repro.exceptions import ReproError
from repro.manifest import DEFAULT_NAME

#: The first line of every workflow `init` writes, and how it knows one of its own.
MARKER = "# Written by `repro bot init`."
DOCS = "https://reproducible.science/tools/repro/#a-bot-on-pull-requests"

#: Pinned by commit, as `.github/workflows/ci.yml` in this repository pins them.
UPLOAD = "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a  # v7.0.1"
DOWNLOAD = "actions/download-artifact@3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c  # v8.0.1"

#: The name the post workflow waits for. `workflow_run` names a workflow by its `name`.
CHECK_NAME = "repro bot check"
ARTIFACT = "repro-bot-findings"
FINDINGS = "${{ runner.temp }}/repro-bot"

CHECK = """\
{marker} On a pull request, it checks the pull request's head
# commit with a read-only token and uploads what it found. It comments on nothing: the workflow
# in repro-bot-post.yml does that, and never checks out this commit. `repro bot reply` starts
# it again with workflow_dispatch after it commits to the branch. {docs}
name: {check_name}

on:
  pull_request:
  workflow_dispatch:
    inputs:
      pull_request:
        description: the number of the pull request whose branch this is
        required: true

permissions: {{}}

concurrency:
  group: repro-bot-check-${{{{ github.event.pull_request.number || inputs.pull_request }}}}
  cancel-in-progress: true

jobs:
  check:
    name: check the pull request's head commit
    runs-on: ubuntu-latest
    permissions:
      contents: read  # to check out the pull request's head commit
    steps:
      - uses: {checkout}
        with:
          ref: ${{{{ github.event.pull_request.head.sha || github.sha }}}}
          persist-credentials: false
      - uses: {setup_uv}
      # --no-config: a uv.toml or pyproject.toml in the pull request does not choose where
      # the package is installed from.
      - run: >-
          uvx --no-config --from {distribution}=={version} repro bot check{manifest_arg}
          --out "$RUNNER_TEMP/repro-bot/findings.json"
          --pull-request "$PULL_REQUEST" --head-sha "$HEAD_SHA"
        env:
          PULL_REQUEST: ${{{{ github.event.pull_request.number || inputs.pull_request }}}}
          HEAD_SHA: ${{{{ github.event.pull_request.head.sha || github.sha }}}}
      - uses: {upload}
        with:
          name: {artifact}
          path: {findings}/findings.json
          retention-days: 1
"""

POST = """\
{marker} After `{check_name}` finishes on a pull request, it reads the
# findings that run uploaded and comments on the pull request. It checks out nothing and runs
# nothing from the pull request; the findings are data, and the pull request they name must be
# at the commit that was checked, from the repository and branch that were checked. {docs}
name: repro bot post

# workflow_run runs with a token that writes, so it is safe only where it never runs what the
# pull request brought. This workflow checks out nothing and reads the findings as data.
on:  # zizmor: ignore[dangerous-triggers]
  workflow_run:
    workflows: [{check_name}]
    types: [completed]

permissions: {{}}

# One run per branch at a time, and a later run waits rather than cancelling one under way.
concurrency:
  group: repro-bot-post-${{{{ github.event.workflow_run.head_repository.full_name }}}}-${{{{ github.event.workflow_run.head_branch }}}}
  cancel-in-progress: false

jobs:
  post:
    name: comment on the findings
    if: >-
      (github.event.workflow_run.event == 'pull_request' || github.event.workflow_run.event == 'workflow_dispatch')
      && github.event.workflow_run.conclusion == 'success'
    runs-on: ubuntu-latest
    permissions:
      actions: read  # to download the findings the check uploaded
      issues: write  # to comment in the pull request's conversation
      pull-requests: write  # to read the pull request, comment on its diff and resolve threads
    steps:
      - uses: {setup_uv}
        with:
          enable-cache: false
      - uses: {download}
        with:
          name: {artifact}
          path: {findings}
          run-id: ${{{{ github.event.workflow_run.id }}}}
          github-token: ${{{{ github.token }}}}
      - run: >-
          uvx --no-config --from {distribution}=={version} repro bot post
          "$RUNNER_TEMP/repro-bot/findings.json" --manifest {manifest}
          --head-sha "$HEAD_SHA" --head-repository "$HEAD_REPOSITORY" --head-branch "$HEAD_BRANCH"
        env:
          HEAD_SHA: ${{{{ github.event.workflow_run.head_sha }}}}
          HEAD_REPOSITORY: ${{{{ github.event.workflow_run.head_repository.full_name }}}}
          HEAD_BRANCH: ${{{{ github.event.workflow_run.head_branch }}}}
          GH_TOKEN: ${{{{ github.token }}}}
"""

REPLY = """\
{marker} On a reply to one of the bot's comments, it records the
# answer, and for 3 or 4 commits a set_aside entry to {manifest} on the pull request's branch,
# never to a fork's and never to any other file. It checks out nothing: the manifest is read and
# written through the API, as text. Replies from anyone without write access to this repository
# are not recorded. {docs}
name: repro bot reply

on:
  issue_comment:
    types: [created]
  pull_request_review_comment:
    types: [created]

permissions: {{}}

# One run per pull request at a time. GitHub cancels a run waiting behind another when a third
# queues, so each run records every answer on the pull request not yet recorded, not only its
# own, and never replaces an answer with an older one.
concurrency:
  group: repro-bot-reply-${{{{ github.event.issue.number || github.event.pull_request.number }}}}
  cancel-in-progress: false

jobs:
  reply:
    name: record an answer
    if: (github.event.issue.pull_request || github.event.pull_request) && github.event.comment.user.type != 'Bot'
    runs-on: ubuntu-latest
    permissions:
      actions: write  # to start the checks again on the branch after a commit
      contents: write  # to commit a set_aside entry to the manifest on the pull request's branch
      issues: write  # to answer in the pull request's conversation
      pull-requests: write  # to read the pull request and answer in a thread on its diff
    steps:
      - uses: {setup_uv}
        with:
          enable-cache: false
      - run: >-
          uvx --no-config --from {distribution}=={version} repro bot reply
          --manifest {manifest}{dispatch}
        env:
          GH_TOKEN: ${{{{ github.token }}}}
"""

FILES = {
    "repro-bot-check.yml": CHECK,
    "repro-bot-post.yml": POST,
    "repro-bot-reply.yml": REPLY,
}


class WorkflowExistsError(ReproError):
    """A file is already where `init` would write. Nothing is overwritten."""

    def __init__(self, ours: tuple[pathlib.Path, ...], foreign: tuple[pathlib.Path, ...]) -> None:
        self.ours = ours
        self.foreign = foreign
        said = []
        if foreign:
            said.append(
                f"{', '.join(str(path) for path in foreign)} exists and `repro bot init` did not "
                "write it, so it is never replaced."
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


class Workflow(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    file: str
    text: str


def workflows(manifest: str = DEFAULT_NAME, dispatch: tuple[str, ...] = ()) -> list[Workflow]:
    """The three workflows, pinned to the installed version of this package. `manifest` is the
    manifest's path from the top of the repository, and `dispatch` the workflows besides the
    check that `reply` starts again after it commits."""
    if __version__ == "0+unknown":
        raise ci.VersionUnknownError
    manifest = manifest_path(manifest)
    started = (actions.CHECK_WORKFLOW, *dispatch)
    fields = {
        "marker": MARKER,
        "docs": DOCS,
        "check_name": CHECK_NAME,
        "checkout": ci.CHECKOUT,
        "setup_uv": ci.SETUP_UV,
        "upload": UPLOAD,
        "download": DOWNLOAD,
        "artifact": ARTIFACT,
        "findings": FINDINGS,
        "distribution": ci.DISTRIBUTION,
        "version": __version__,
        "manifest": shlex.quote(manifest),
        "manifest_arg": "" if manifest == DEFAULT_NAME else f" {shlex.quote(manifest)}",
        "dispatch": "".join(f" --dispatch {shlex.quote(name)}" for name in started),
    }
    return [Workflow(file=file, text=text.format(**fields)) for file, text in FILES.items()]


def init(cwd: pathlib.Path, *, force: bool = False) -> int:
    """Write the three workflows into the repository holding `cwd`."""
    root, path = ci.located(cwd)
    if path is None:
        raise NoManifestError(root)
    started = dispatchable(root)
    wanted = workflows(path.relative_to(root).as_posix(), tuple(started))
    there = [root / ci.WORKFLOWS / flow.file for flow in wanted]
    ours = tuple(
        target
        for target in there
        if target.exists() and target.read_text(encoding="utf-8").startswith(MARKER)
    )
    foreign = tuple(target for target in there if target.exists() and target not in ours)
    if foreign or (ours and not force):
        raise WorkflowExistsError(() if force else ours, foreign)

    (root / ci.WORKFLOWS).mkdir(parents=True, exist_ok=True)
    for flow, target in zip(wanted, there, strict=True):
        atomic_write(target, flow.text)
        print(f"wrote {target}")
    print(f"  {wanted[0].file}: on a pull request, checks its head commit read-only")
    print(f"  {wanted[1].file}: after the check, comments; checks out nothing")
    print(f"  {wanted[2].file}: records a reply 1-4; checks out nothing")
    print("\nnext:")
    print(f"  1. commit {ci.WORKFLOWS.as_posix()}/repro-bot-*.yml and merge them into the")
    print("     default branch. GitHub runs `workflow_run` and `issue_comment` workflows only")
    print("     from the default branch, so the bot comments on no pull request before that.")
    print("  2. a reply is recorded only from someone with write access to this repository.")
    print("  3. on a pull request from a fork the bot comments and commits nothing.")
    print("  4. a commit the bot makes starts no workflow by itself, so after one it starts")
    print(f"     again: {', '.join((actions.CHECK_WORKFLOW, *started))}.")
    lacking = [
        name
        for name in sorted(p.name for p in (root / ci.WORKFLOWS).glob("*.yml"))
        if name not in started and _ci_written(root / ci.WORKFLOWS / name)
    ]
    if lacking:
        print(f"     {', '.join(lacking)} cannot be started that way; `repro ci init --force`")
        print("     rewrites them with a workflow_dispatch trigger, and then `repro bot init")
        print("     --force` names them here.")
    return 0


def _ci_written(path: pathlib.Path) -> bool:
    return path.read_text(encoding="utf-8").startswith(ci.MARKER)


def dispatchable(root: pathlib.Path) -> list[str]:
    """The workflows `repro ci init` wrote here that can be started with workflow_dispatch:
    the checks a branch protection rule may require, which a commit by the bot starts none of."""
    folder = root / ci.WORKFLOWS
    return [
        path.name
        for path in sorted(folder.glob("*.yml"))
        if _ci_written(path) and "\n  workflow_dispatch:" in path.read_text(encoding="utf-8")
    ]


__all__ = [
    "MARKER",
    "NoManifestError",
    "Workflow",
    "WorkflowExistsError",
    "dispatchable",
    "init",
    "workflows",
]
