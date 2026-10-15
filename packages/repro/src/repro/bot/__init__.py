"""`repro bot`: comments on a pull request for each claim that fails or went stale, and records
the answers given to them. Workflows in the author's own repository; nothing is hosted, and no
model reads or writes anything.

    repro bot init    write the three workflows
    repro bot check   check the pull request's head commit and write what was found, read-only
    repro bot post    comment on what `check` found: one comment per assertion, edited in place
    repro bot reply   read a reply to one of those comments and record the answer

`check` runs where the pull request's files are, with a read-only token. `post` and `reply` run
with a token that writes, check out nothing, and read the pull request through the API.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib

from provenance_core import atomic_write
from provenance_core.gitref import try_run

from repro.bot import actions, workflows
from repro.bot.findings import Findings, check, manifest_path
from repro.bot.github import API, GRAPHQL, Client
from repro.exceptions import ReproError
from repro.manifest import DEFAULT_NAME, find, load

#: The largest findings file `post` reads. One holds at most fifty findings.
MAX_FINDINGS_BYTES = 5 * 1024 * 1024


class EnvironmentMissingError(ReproError):
    """A variable the workflow sets is not set."""

    def __init__(self, name: str) -> None:
        super().__init__(
            f"{name} is not set; `repro bot post` and `repro bot reply` run in the workflows "
            "`repro bot init` writes, which set it"
        )


def _env(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise EnvironmentMissingError(name)
    return value


def _client() -> Client:
    return Client(
        _env("GITHUB_REPOSITORY"),
        _env("GH_TOKEN"),
        os.environ.get("GITHUB_API_URL") or API,
        os.environ.get("GITHUB_GRAPHQL_URL") or GRAPHQL,
    )


def command_check(args: argparse.Namespace) -> int:
    path = pathlib.Path(args.manifest) if args.manifest else find()
    top = try_run("rev-parse", "--show-toplevel", cwd=pathlib.Path.cwd())
    root = pathlib.Path(top.strip()) if top else pathlib.Path.cwd()
    if path is None:
        found = Findings(
            pull_request=args.pull_request,
            head_sha=args.head_sha,
            problem=f"no {DEFAULT_NAME} here or above",
        )
    else:
        try:
            found = check(load(path), root, args.pull_request, args.head_sha)
        except ReproError as failed:
            found = Findings(
                pull_request=args.pull_request, head_sha=args.head_sha, problem=str(failed)[:2000]
            )
    out = pathlib.Path(args.out)
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
    path = pathlib.Path(args.findings)
    if path.stat().st_size > MAX_FINDINGS_BYTES:
        raise ReproError(f"{path} is over {MAX_FINDINGS_BYTES} bytes; nothing was posted.")
    found = Findings.model_validate_json(path.read_bytes())
    done = actions.post(
        found,
        _client(),
        args.head_sha,
        args.head_repository,
        args.head_branch,
        manifest=args.manifest,
    )
    print(json.dumps(done.model_dump(mode="json"), indent=2))
    return 0


def command_reply(args: argparse.Namespace) -> int:
    name = args.event_name or _env("GITHUB_EVENT_NAME")
    event = json.loads(pathlib.Path(args.event or _env("GITHUB_EVENT_PATH")).read_text("utf-8"))
    done = actions.reply(
        name, event, _client(), manifest=args.manifest, dispatch=tuple(args.dispatch or ())
    )
    print(json.dumps(done.model_dump(mode="json"), indent=2))
    return 0


def command_init(args: argparse.Namespace) -> int:
    return workflows.init(pathlib.Path.cwd(), force=args.force)


def add_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "bot",
        help="comment on a pull request for each claim that fails, and record the answers",
        description=(
            "A pull-request bot made of three workflows in your own repository. `init` writes "
            "them. On a pull request, `check` checks the head commit with a read-only token, "
            "as `repro ci claims` and `repro ci reruns` do, and writes what fails or went "
            "stale; `post` comments on each, once, on the manuscript's line where it is in "
            "the diff; `reply` records a reply of 1 to 4 from someone with write access. "
            "Nothing is hosted and no model is involved."
        ),
    )
    p.set_defaults(func=lambda args: p.print_help() or 1)
    actions_ = p.add_subparsers(dest="action")

    p_init = actions_.add_parser(
        "init",
        help="write the three workflows",
        description=(
            f"Write {', '.join(workflows.FILES)} under .github/workflows/. A workflow this "
            "command wrote is replaced only with --force, and any other file of that name is "
            "never replaced."
        ),
    )
    p_init.add_argument("--force", action="store_true", help="replace workflows this wrote")
    p_init.set_defaults(func=command_init)

    p_check = actions_.add_parser(
        "check",
        help="check the pull request's head commit and write the findings",
        description=(
            "Check every assertion, as `repro export` does, and write each that fails or went "
            "stale to --out as JSON, with the pull request's number and head commit. Executes "
            "nothing, comments on nothing and exits 0 once the file is written."
        ),
    )
    p_check.add_argument("manifest", nargs="?", help=f"path to {DEFAULT_NAME}")
    p_check.add_argument("--out", required=True, metavar="PATH")
    p_check.add_argument("--pull-request", required=True, type=int, metavar="NUMBER")
    p_check.add_argument("--head-sha", required=True, metavar="SHA")
    p_check.set_defaults(func=command_check)

    p_post = actions_.add_parser(
        "post",
        help="comment on the findings `check` wrote",
        description=(
            "Read the findings, refuse them unless the pull request they name is at --head-sha, "
            "and comment once per assertion: on the manuscript's line where it is in the diff "
            "and the pull request is not from a fork, in the conversation otherwise. A comment "
            "already there is edited, never posted again, and marked fixed when the assertion "
            "passes. Reads GITHUB_REPOSITORY and GH_TOKEN."
        ),
    )
    p_post.add_argument("findings", help="the file `repro bot check` wrote")
    p_post.add_argument("--head-sha", required=True, metavar="SHA")
    p_post.add_argument(
        "--head-repository",
        required=True,
        metavar="OWNER/REPO",
        help="the repository the checked run was of; the pull request must be from it",
    )
    p_post.add_argument(
        "--head-branch",
        required=True,
        metavar="BRANCH",
        help="the branch the checked run was of; the pull request must be from it",
    )
    p_post.add_argument(
        "--manifest",
        default=DEFAULT_NAME,
        type=manifest_path,
        help="the manifest's path from the top of the repository; findings about any other "
        f"file are refused (default: {DEFAULT_NAME})",
    )
    p_post.set_defaults(func=command_post)

    p_reply = actions_.add_parser(
        "reply",
        help="record a reply to one of the bot's comments",
        description=(
            "Read the event GITHUB_EVENT_PATH names. A reply in one of the bot's threads that "
            "starts with 1 to 4, from someone with write access, is recorded; 3 and 4 commit a "
            "`set_aside` entry to the pull request's branch, never to a fork's. Reads "
            "GITHUB_REPOSITORY and GH_TOKEN."
        ),
    )
    p_reply.add_argument("--event", metavar="PATH", help="default: $GITHUB_EVENT_PATH")
    p_reply.add_argument("--event-name", metavar="NAME", help="default: $GITHUB_EVENT_NAME")
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
        metavar="WORKFLOW",
        help="a workflow file to start again on the branch after a commit, so its required "
        "check runs on the new head; repeatable",
    )
    p_reply.set_defaults(func=command_reply)


__all__ = ["add_parser"]
