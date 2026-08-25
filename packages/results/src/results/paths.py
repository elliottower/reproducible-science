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


def record_path(p: pathlib.Path, root: pathlib.Path) -> str:
    """A path relative to the project root, so it resolves from anywhere in the tree.

    Recording relative to the current directory would make a file sealed from a
    subdirectory unfindable when verify runs at the root.
    """
    return os.path.relpath(p, root.parent)
