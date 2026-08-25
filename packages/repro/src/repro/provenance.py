"""Reading a working tree's revision, for the record.

This never verifies anything. A commit identifies a tree; the pin that establishes what was
read is the artifact's own digest. What a commit buys is the ability to go and fetch the same
bytes, which the digest then confirms.

A dirty working tree is recorded as dirty rather than silently attributed to the commit it
sits on, because a manifest built from uncommitted changes names a revision that does not
contain what was read.
"""

from __future__ import annotations

import pathlib

from provenance_core.gitref import try_run

from repro.models import Provenance


def _git(args: list[str], cwd: pathlib.Path) -> str | None:
    """Run one git command, or None when git is absent or the directory is not a repository."""
    return try_run(*args, cwd=cwd)


def of_tree(path: pathlib.Path, generated_by: str = "") -> Provenance:
    """Where the files under `path` came from, as far as git can say.

    Returns a `Provenance` with empty fields rather than raising when the directory is not a
    repository: a manifest over loose files is legitimate, and it should say that it has no
    revision rather than fail to be written.
    """
    root = path if path.is_dir() else path.parent
    commit = _git(["rev-parse", "HEAD"], root) or ""
    remote = _git(["remote", "get-url", "origin"], root) or ""
    status = _git(["status", "--porcelain"], root)
    return Provenance(
        repository=remote or (str(root) if commit else ""),
        commit=commit,
        dirty=bool(status),
        generated_by=generated_by,
    )
