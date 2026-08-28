"""Primitives shared by the reproducible-science tools.

Digests and git references lived in four copies each, drifting quietly. This package is the
one implementation, published only because the tools that need it are published separately
and a workspace path does not survive into a wheel.
"""

from __future__ import annotations

from .digests import NOISE, ZERO, sha256_of_file, sha256_of_text, sha256_of_tree
from .gitref import GitError, at_commit, commit, is_dirty, run, try_run

__all__ = [
    "NOISE",
    "ZERO",
    "GitError",
    "at_commit",
    "commit",
    "is_dirty",
    "run",
    "sha256_of_file",
    "sha256_of_text",
    "sha256_of_tree",
    "try_run",
]
