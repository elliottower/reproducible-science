"""Where the ledger lives, and how a path is written into it.

Every command begins the same way: find the `.results/` governing this directory, and resolve
the ledger inside it. That lookup sat in `cli.py` beside the argparse handlers, so the only
caller that could reach it was a command, and a library caller -- the coverage hook, a
notebook, a test -- had to import the CLI module to ask where the ledger was.

`record_path` is the other half. What goes in the ledger is a path relative to the project
root, not to the directory the command ran in, so a file sealed from a subdirectory is still
findable when `verify` runs at the top.
"""

from __future__ import annotations

import os
import pathlib

from provenance_core import SIDECAR_SUFFIXES

from results import ledger

RESULTS_DIR = ".results"


def find_root(start: pathlib.Path | None = None) -> pathlib.Path | None:
    here = (start or pathlib.Path.cwd()).resolve()
    for d in [here, *here.parents]:
        if (d / RESULTS_DIR).is_dir():
            return d / RESULTS_DIR
    return None


def require_root() -> pathlib.Path:
    """The governing `.results/`, or raise.

    Raises rather than exits: this is reached through library calls, and a function that kills
    the interpreter cannot be used from anything that is not a terminal.
    """
    root = find_root()
    if root is None:
        raise ledger.NoLedgerRootError(str(pathlib.Path.cwd()))
    return root


def ledger_path(root: pathlib.Path) -> pathlib.Path:
    return root / ledger.LEDGER


def ledger_own(recorded: str) -> bool:
    """Whether a recorded path is one of the ledger's own files, which no seal can hold still.

    `recorded` is a path as the ledger writes it, from the project root. Everything under
    `.results/` is written by this tool -- the ledger, its anchor `ledger.head`, the timestamp
    proofs -- and changes with every event, so a seal of one is out of date at the next command.
    A lock or temporary sidecar is written by the locking every tool shares and holds nothing.
    """
    parts = pathlib.PurePath(recorded).parts
    return (bool(parts) and parts[0] == RESULTS_DIR) or recorded.endswith(tuple(SIDECAR_SUFFIXES))


def record_path(p: pathlib.Path, root: pathlib.Path) -> str:
    """A path relative to the project root, so it resolves from anywhere in the tree.

    Recording relative to the current directory would make a file sealed from a
    subdirectory unfindable when verify runs at the root.
    """
    return os.path.relpath(p, root.parent)
