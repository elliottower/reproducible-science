"""A sealed plan whose log has grown since the seal.

A plan `prereg freeze` froze in place holds its log in the same file, and `prereg log` rewrites
the file on every entry. A seal of such a plan is therefore out of date at the next entry,
though the plan it fixed is the same plan, and `verify --files` reported every such seal as
`CHANGED`. Whether two versions of a plan differ only in what `prereg log` writes is
`prereg`'s question, answered by `prereg.inplace.entries_appended`, the rule `prereg check`
applies; it is asked here, and not restated.

The ledger holds a digest and not the bytes it named, so the bytes are read from the
repository's history: the version of the path, in some commit, whose sha256 is the recorded
one. Where history holds no such version the question cannot be asked, and the path stays
`CHANGED`.
"""

from __future__ import annotations

import hashlib
import pathlib
import subprocess

from prereg import inplace, record
from provenance_core.gitref import DEFAULT_TIMEOUT, clean_env, try_run

#: Larger than any plan. A changed data file is not read whole to learn it is not one.
LARGEST_PLAN = 1 << 24


def _git_bytes(base: pathlib.Path, *args: str) -> bytes | None:
    """Stdout of a git command as bytes, unstripped, or None where git could not answer.

    `provenance_core.gitref.run` strips its output, and a blob that lost its last newline no
    longer has the digest it was sealed under.
    """
    try:
        done = subprocess.run(
            ["git", *args],
            cwd=base,
            env=clean_env(),
            capture_output=True,
            timeout=DEFAULT_TIMEOUT,
            check=False,  # a path absent from a commit is an answer, not an error
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return done.stdout if done.returncode == 0 else None


def recorded_text(base: pathlib.Path, path: str, digest: str) -> str | None:
    """The text of `path` as it was when hashed to `digest`, from git history, or None.

    Each commit that touched the path is read, newest first, until one holds those bytes.
    """
    commits = try_run("log", "--format=%H", "--", path, cwd=base)
    for commit in (commits or "").split():
        blob = _git_bytes(base, "cat-file", "blob", f"{commit}:./{path}")
        if blob is not None and hashlib.sha256(blob).hexdigest() == digest:
            try:
                return blob.decode("utf-8")
            except UnicodeDecodeError:
                return None
    return None


def entries_appended(base: pathlib.Path, path: str, digest: str) -> int:
    """How many log entries the plan at `path` holds beyond the version sealed as `digest`.

    Nonzero only where `path` is a plan frozen in place, `prereg check` finds it unchanged, and
    it differs from the sealed version only by entries appended to its log and the recount of
    its `**Log:**` line. A plan frozen whole never changes and has its log beside it, so it is
    never one of these.
    """
    p = base / path
    if p.stat().st_size > LARGEST_PLAN:
        return 0
    try:
        now = p.read_bytes().decode("utf-8")
    except UnicodeDecodeError:
        return 0
    if not inplace.FROZEN_DIGEST.search(now) or record.read(p) is not None:
        return 0
    sealed = recorded_text(base, path, digest)
    return 0 if sealed is None else inplace.entries_appended(sealed, now)
