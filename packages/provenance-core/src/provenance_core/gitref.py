"""Asking git a question, with one policy for what a failure means.

Three copies of this existed and disagreed about failure. One returned `None`, one raised,
and one returned the empty string -- which made a missing `git` binary, a locked index and a
directory outside a repository all indistinguishable from success. A freeze recorded a
commit-shaped string in place of a commit because of it.

The disagreement was not arbitrary: a provenance record wants "unknown" and a fetch wants an
error. Both are offered, so a caller chooses deliberately rather than inheriting whichever
policy its copy happened to have.
"""

from __future__ import annotations

import pathlib
import subprocess

#: Long enough for a fetch over a slow link, short enough that a hung command is not forever.
DEFAULT_TIMEOUT = 30


class GitError(Exception):
    """Git could not answer: absent, timed out, or the command failed."""

    def __init__(self, args: tuple[str, ...], detail: str) -> None:
        self.args_run = args
        self.detail = detail
        super().__init__(f"git {' '.join(args)}: {detail}")


def run(
    *args: str, cwd: pathlib.Path | None = None, timeout: int = DEFAULT_TIMEOUT
) -> str:
    """Stdout of one git command. Raises `GitError` on any failure.

    Use where a failure is a fact the caller must handle. Reporting it as an empty string is
    how a repository with no commit reads as one with a commit.
    """
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,  # the return code is inspected below and becomes a typed error
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as e:
        raise GitError(args, str(e)) from e
    if proc.returncode != 0:
        raise GitError(
            args, (proc.stderr or "").strip()[:200] or f"exit {proc.returncode}"
        )
    return proc.stdout.strip()


def try_run(
    *args: str, cwd: pathlib.Path | None = None, timeout: int = DEFAULT_TIMEOUT
):
    """Stdout, or None when git could not answer.

    Use where absence is a legitimate result -- a provenance record for a directory that is
    not a repository is empty, not an error.
    """
    try:
        return run(*args, cwd=cwd, timeout=timeout)
    except GitError:
        return None


def commit(cwd: pathlib.Path | None = None) -> str | None:
    """The full SHA of HEAD, or None where there is no commit to name."""
    return try_run("rev-parse", "HEAD", cwd=cwd)


def is_dirty(cwd: pathlib.Path | None = None) -> bool:
    """Whether the working tree has uncommitted changes.

    A tree at the right commit with edited files holds bytes that exist only on that machine,
    so a result verified against it is not one anybody else can reproduce. An unreadable tree
    answers False: not knowing is not the same as knowing it is dirty, and the caller that
    cares has already checked that git can answer.
    """
    return bool(try_run("status", "--porcelain", cwd=cwd))


def at_commit(cwd: pathlib.Path, expected: str) -> bool:
    """Whether HEAD is exactly the commit named.

    Exact, not a prefix match: an abbreviated SHA that happens to prefix another commit would
    silently accept the wrong revision. A tree git cannot read answers False rather than
    matching an empty expectation.
    """
    head = commit(cwd)
    return head is not None and head == expected


__all__ = [
    "DEFAULT_TIMEOUT",
    "GitError",
    "at_commit",
    "commit",
    "is_dirty",
    "run",
    "try_run",
]
