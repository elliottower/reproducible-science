"""Primitives shared by the reproducible-science tools.

Digests and git references lived in four copies each, drifting quietly. This package is the
one implementation, published only because the tools that need it are published separately
and a workspace path does not survive into a wheel.
"""

from __future__ import annotations

from .digests import NOISE, ZERO, sha256_of_file, sha256_of_text, sha256_of_tree
from .gitref import GitError, at_commit, commit, is_dirty, run, try_run
from .locking import (
    LOCK_SUFFIX,
    SIDECAR_SUFFIXES,
    TMP_SUFFIX,
    LockUnavailableError,
    atomic_write,
    atomic_write_bytes,
    exclusive_lock,
    lock_path,
    shared_lock,
)

__all__ = [
    "LOCK_SUFFIX",
    "NOISE",
    "SIDECAR_SUFFIXES",
    "TMP_SUFFIX",
    "ZERO",
    "GitError",
    "LockUnavailableError",
    "at_commit",
    "atomic_write",
    "atomic_write_bytes",
    "commit",
    "exclusive_lock",
    "is_dirty",
    "lock_path",
    "run",
    "sha256_of_file",
    "sha256_of_text",
    "sha256_of_tree",
    "shared_lock",
    "try_run",
]
