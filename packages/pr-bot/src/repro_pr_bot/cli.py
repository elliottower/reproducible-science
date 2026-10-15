"""`reproducible-science-pr-bot`: comments on a pull request for each claim that fails or went
stale, and records the answers given to them. It runs in the author's own repository, from the
caller workflows `repro ci init --pr-bot` writes; nothing is hosted, and no model reads or
writes anything.

    reproducible-science-pr-bot check   check the pull request's head commit, read-only, and
                                        write what was found
    reproducible-science-pr-bot post    comment on what `check` found: one comment per
                                        assertion, edited in place
    reproducible-science-pr-bot reply   read a reply to one of those comments and record the
                                        answer

`check` runs where the pull request's files are, with a read-only token. `post` and `reply` run
with a token that writes, check out nothing, and read the pull request through the API. Each
reads what it needs of the run from the event GitHub gives the workflow, so a workflow names
no more than the manifest and the workflows to start again.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re

from claims.exceptions import ReproError
from claims.manifest import DEFAULT_NAME, find, load
from provenance_core import atomic_write
from provenance_core.gitref import try_run

from repro_pr_bot import __version__, actions
from repro_pr_bot.findings import Findings, check, manifest_path
from repro_pr_bot.github import API, GRAPHQL, Client

PROGRAM = "reproducible-science-pr-bot"
#: The largest findings file `post` reads. One holds at most fifty findings.
MAX_FINDINGS_BYTES = 5 * 1024 * 1024
#: Where `check` writes and `post` reads, under the runner's temporary directory.
FINDINGS = pathlib.Path("repro-pr-bot") / "findings.json"


class EnvironmentMissingError(ReproError):
    """A value the workflow gives is not there."""

    def __init__(self, name: str) -> None:
        super().__init__(
            f"{name} is not set and was not given; {PROGRAM} runs in the workflows "
            "`repro ci init --pr-bot` writes, which set it"
        )


def _env(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise EnvironmentMissingError(name)
    return value


def _event() -> dict:
    """The event GitHub gives the workflow: data GitHub wrote, read for the run's own facts."""
    path = os.environ.get("GITHUB_EVENT_PATH")
    return json.loads(pathlib.Path(path).read_text("utf-8")) if path else {}


def _default_findings() -> pathlib.Path:
    return pathlib.Path(_env("RUNNER_TEMP")) / FINDINGS


def _client() -> Client:
    return Client(
        _env("GITHUB_REPOSITORY"),
        _env("GH_TOKEN"),
        os.environ.get("GITHUB_API_URL") or API,
        os.environ.get("GITHUB_GRAPHQL_URL") or GRAPHQL,
    )


def _workflows(given: list[str] | None) -> tuple[str, ...]:
    """Workflow files named once each, from options that may each hold several, separated by
    spaces or commas."""
    names = [
        name for value in given or () for name in re.split(r"[\s,]+", value) if name
    ]
    return tuple(dict.fromkeys(names))


def command_check(args: argparse.Namespace) -> int:
    event = _event()
    pull = event.get("pull_request") or {}
    number = (
        args.pull_request
        or pull.get("number")
        or (event.get("inputs") or {}).get("pull_request")
    )
    head = (
        args.head_sha
        or (pull.get("head") or {}).get("sha")
        or os.environ.get("GITHUB_SHA")
    )
    if not number:
        raise EnvironmentMissingError("--pull-request")
    if not head:
        raise EnvironmentMissingError("--head-sha")
    path = pathlib.Path(args.manifest) if args.manifest else find()
    top = try_run("rev-parse", "--show-toplevel", cwd=pathlib.Path.cwd())
    root = pathlib.Path(top.strip()) if top else pathlib.Path.cwd()
    if path is None:
        found = Findings(
            pull_request=int(number),
            head_sha=head,
            problem=f"no {DEFAULT_NAME} here or above",
        )
    else:
        try:
            found = check(load(path), root, int(number), head)
        except ReproError as failed:
            found = Findings(
                pull_request=int(number), head_sha=head, problem=str(failed)[:2000]
            )
    out = pathlib.Path(args.out) if args.out else _default_findings()
    out.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(out, found.model_dump_json(indent=2) + "\n")
    print(f"wrote {out}")
    if found.problem:
        print(f"  nothing was checked: {found.problem}")
    else:
        print(
            f"  {len(found.checked)} assertions checked, {len(found.findings) + found.more} "
            f"failing or stale, {len(found.set_aside)} set aside"
        )
    return 0


def command_post(args: argparse.Namespace) -> int:
    run = _event().get("workflow_run") or {}
    path = pathlib.Path(args.findings) if args.findings else _default_findings()
    if path.stat().st_size > MAX_FINDINGS_BYTES:
        raise ReproError(
            f"{path} is over {MAX_FINDINGS_BYTES} bytes; nothing was posted."
        )
    found = Findings.model_validate_json(path.read_bytes())
    head_sha = args.head_sha or run.get("head_sha") or ""
    repository = args.head_repository or (run.get("head_repository") or {}).get(
        "full_name", ""
    )
    branch = args.head_branch or run.get("head_branch") or ""
    for name, value in (
        ("--head-sha", head_sha),
        ("--head-repository", repository),
        ("--head-branch", branch),
    ):
        if not value:
            raise EnvironmentMissingError(name)
    done = actions.post(
        found, _client(), head_sha, repository, branch, manifest=args.manifest
    )
    print(json.dumps(done.model_dump(mode="json"), indent=2))
    return 0


def command_reply(args: argparse.Namespace) -> int:
    name = args.event_name or _env("GITHUB_EVENT_NAME")
    path = args.event or _env("GITHUB_EVENT_PATH")
    event = json.loads(pathlib.Path(path).read_text("utf-8"))
    done = actions.reply(
        name,
        event,
        _client(),
        manifest=args.manifest,
        dispatch=_workflows(args.dispatch) or (actions.CHECK_WORKFLOW,),
    )
    print(json.dumps(done.model_dump(mode="json"), indent=2))
    return 0


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog=PROGRAM,
        description=(
            "Comment on a pull request for each claim in repro.yaml that fails or went stale, "
            "and record a reply of 1 to 4 from someone with write access. Runs in the "
            "workflows `repro ci init --pr-bot` writes. Nothing is hosted and no model is "
            "involved."
        ),
    )
    p.add_argument("--version", action="version", version=f"{PROGRAM} {__version__}")
    sub = p.add_subparsers(dest="action", required=True)

    p_check = sub.add_parser(
        "check",
        help="check the pull request's head commit and write the findings",
        description=(
            "Check every assertion, as `repro export` does, and write each that fails or went "
            "stale as JSON, with the pull request's number and head commit, which are read "
            "from the event where not given. Executes nothing, comments on nothing and exits 0 "
            "once the file is written."
        ),
    )
    p_check.add_argument("manifest", nargs="?", help=f"path to {DEFAULT_NAME}")
    p_check.add_argument(
        "--out", metavar="PATH", help=f"default: $RUNNER_TEMP/{FINDINGS.as_posix()}"
    )
    p_check.add_argument("--pull-request", type=int, metavar="NUMBER")
    p_check.add_argument("--head-sha", metavar="SHA")
    p_check.set_defaults(func=command_check)

    p_post = sub.add_parser(
        "post",
        help="comment on the findings `check` wrote",
        description=(
            "Read the findings, refuse them unless the pull request they name is at the run's "
            "head commit, from the run's repository and branch, and about --manifest, and "
            "comment once per assertion: on the manuscript's line where it is in the diff and "
            "the pull request is not from a fork, in the conversation otherwise. A comment "
            "already there is edited, never posted again, and marked fixed when the assertion "
            "passes. The run's commit, repository and branch are read from the workflow_run "
            "event where not given. Reads GITHUB_REPOSITORY and GH_TOKEN."
        ),
    )
    p_post.add_argument(
        "findings", nargs="?", help=f"default: $RUNNER_TEMP/{FINDINGS.as_posix()}"
    )
    p_post.add_argument("--head-sha", metavar="SHA")
    p_post.add_argument("--head-repository", metavar="OWNER/REPO")
    p_post.add_argument("--head-branch", metavar="BRANCH")
    p_post.add_argument(
        "--manifest",
        default=DEFAULT_NAME,
        type=manifest_path,
        help="the manifest's path from the top of the repository; findings about any other "
        f"file are refused (default: {DEFAULT_NAME})",
    )
    p_post.set_defaults(func=command_post)

    p_reply = sub.add_parser(
        "reply",
        help="record a reply to one of the bot's comments",
        description=(
            "Read the event GITHUB_EVENT_PATH names. A reply in one of the bot's threads that "
            "starts with 1 to 4, from someone with write access, is recorded; 3 and 4 commit a "
            "`set_aside` entry to --manifest on the pull request's branch, never to a fork's. "
            "Reads GITHUB_REPOSITORY and GH_TOKEN."
        ),
    )
    p_reply.add_argument("--event", metavar="PATH", help="default: $GITHUB_EVENT_PATH")
    p_reply.add_argument(
        "--event-name", metavar="NAME", help="default: $GITHUB_EVENT_NAME"
    )
    p_reply.add_argument(
        "--manifest",
        default=DEFAULT_NAME,
        type=manifest_path,
        help="the only file a `set_aside` entry is ever committed to, from the top of the "
        f"repository (default: {DEFAULT_NAME})",
    )
    p_reply.add_argument(
        "--dispatch",
        action="append",
        metavar="WORKFLOWS",
        help="workflow files to start again on the branch after a commit, separated by spaces "
        "or commas; the first is the bot's check, which is told the pull request's number "
        f"(default: {actions.CHECK_WORKFLOW})",
    )
    p_reply.set_defaults(func=command_reply)
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        return args.func(args)
    except ReproError as failed:
        print(f"{PROGRAM}: {failed}")
        return 2


__all__ = ["main", "parser"]
