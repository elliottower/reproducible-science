"""Keeping git from converting a frozen file's line endings.

A file frozen whole is hashed byte for byte. A checkout with `core.autocrlf` on, as Windows has
by default, rewrites every line ending of a text file, and the plan then differs from its freeze
on a machine where nobody touched it. A `-text` attribute tells git to leave the bytes alone, so
a freeze writes that rule for the plan, its amendments and its log.
"""

from __future__ import annotations

import pathlib

from provenance_core import atomic_write_bytes
from provenance_core.gitref import try_run

ATTRIBUTES = ".gitattributes"


def _nearest(directory: pathlib.Path) -> pathlib.Path:
    """The `.gitattributes` to write: the nearest one at or above `directory` in its
    repository, or a new one in `directory`."""
    top = try_run("rev-parse", "--show-toplevel", cwd=directory)
    if top is not None:
        for d in [directory, *directory.parents]:
            if (d / ATTRIBUTES).is_file():
                return d / ATTRIBUTES
            if d == pathlib.Path(top):
                break
    return directory / ATTRIBUTES


def mark_binary_safe(directory: pathlib.Path, names: list[str]) -> tuple[pathlib.Path, list[str]]:
    """Add a `-text` rule for each of `names` in `directory`, and return the file and the rules
    added. Existing lines are left as they are, and a rule already there is not written again."""
    where = _nearest(directory.resolve())
    held = where.read_bytes() if where.is_file() else b""
    present = {line.strip() for line in held.decode().splitlines()}
    below = directory.resolve().relative_to(where.parent)
    rules = []
    for name in names:
        pattern = (below / name).as_posix()
        # A pattern holding a space is quoted, or git reads it as a pattern and an attribute.
        rule = f'"{pattern}" -text' if " " in pattern else f"{pattern} -text"
        if rule not in present:
            rules.append(rule)
    if rules:
        gap = b"" if not held or held.endswith(b"\n") else b"\n"
        atomic_write_bytes(where, held + gap + "".join(f"{r}\n" for r in rules).encode())
    return where, rules
