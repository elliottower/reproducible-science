"""Readers of other reproducibility tools' files.

Each reads the other tool's own files and imports nothing of it, writes a draft manifest and
the open items its source leaves (`claims.open_items`), and never writes into the other tool's
files or under its identifiers. A reader writes into its output folder only; anything to be
written beside another tool's file belongs in a sidecar, `reproducible-science-claim-check.jsonl`,
and never in that file.

Every file is read the same guarded way. A path that resolves outside the folder it was named
in, through `..` or a symbolic link, is never read. A Git LFS pointer is a pointer and not the
file, so it is reported as not checked and never pinned. A YAML mapping that names one key
twice is refused, since the two readers of it would disagree about which value it holds, and
so is YAML that uses an alias or nests deeper than `MAX_DEPTH`: an alias is how a file of a
few hundred bytes expands to billions of nodes, and depth is how it exhausts the stack.
"""

from __future__ import annotations

import pathlib
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict

from claims.exceptions import ReproError

#: Where a reader writes anything it has to say about another tool's file.
SIDECAR = "reproducible-science-claim-check.jsonl"

#: The first line of every Git LFS pointer file (https://github.com/git-lfs/git-lfs/blob/main/docs/spec.md).
LFS_POINTER = b"version https://git-lfs.github.com/spec/v1"


#: The deepest a parsed file may nest. Results files are shallow; a deep one is hostile.
MAX_DEPTH = 64


class RefusedYamlError(ReproError):
    """YAML read here refuses: a key twice, an alias, or nesting past `MAX_DEPTH`."""


class DuplicateKeyError(RefusedYamlError):
    """A YAML mapping names one key twice."""


class _UniqueKeyLoader(yaml.SafeLoader):
    """The safe loader, refusing a mapping that names a key twice. PyYAML keeps the last value
    and says nothing, so the file reads one way here and may read another elsewhere."""

    def construct_mapping(self, node, deep=False):
        seen = set()
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=deep)
            if key in seen:
                raise DuplicateKeyError(
                    f"line {key_node.start_mark.line + 1}: the key {key!r} is given twice"
                )
            seen.add(key)
        return super().construct_mapping(node, deep=deep)


def _shape_is_safe(text: str | bytes) -> None:
    """Refuse an alias or nesting past `MAX_DEPTH`, from the event stream, which PyYAML parses
    without recursing, before anything is composed."""
    depth = 0
    for event in yaml.parse(text, Loader=yaml.SafeLoader):
        if isinstance(event, yaml.AliasEvent):
            raise RefusedYamlError(
                f"line {event.start_mark.line + 1}: an alias, which is refused here"
            )
        if isinstance(event, yaml.CollectionStartEvent):
            depth += 1
            if depth > MAX_DEPTH:
                raise RefusedYamlError(f"nested deeper than {MAX_DEPTH}, which is refused here")
        elif isinstance(event, yaml.CollectionEndEvent):
            depth -= 1


def load_yaml(text: str | bytes) -> Any:
    """YAML read with the safe loader, refusing a key given twice in one mapping, an alias, and
    nesting past `MAX_DEPTH`."""
    _shape_is_safe(text)
    return yaml.load(text, Loader=_UniqueKeyLoader)


def inside(root: pathlib.Path, path: pathlib.Path) -> bool:
    """Whether `path`, with every symbolic link followed, is in `root`."""
    return path.resolve().is_relative_to(root.resolve())


def is_lfs_pointer(path: pathlib.Path) -> bool:
    """Whether the file is a Git LFS pointer rather than the content it points to."""
    try:
        with path.open("rb") as handle:
            return handle.read(len(LFS_POINTER)) == LFS_POINTER
    except OSError:
        return False


class PassedOver(BaseModel):
    """Something in the source a reader wrote nothing for, and why."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    file: str
    reason: str


class Written(BaseModel):
    """What one reading wrote."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    open_items: str
    draft: str
    artifacts: int
    pinned: int
    claims: int
    items: int
    passed_over: tuple[PassedOver, ...] = ()
    unpinned: tuple[PassedOver, ...] = ()
    """Files named and declared without a pin, each with why: not on disk where it is named,
    or no copy of the bundle given."""
    not_checked: tuple[PassedOver, ...] = ()
    """Files named and not read: a Git LFS pointer, a link out of the folder, YAML with a key
    given twice. Each is declared without a pin where it is declared at all."""


def named(path: pathlib.Path) -> str:
    """A path as an open-items file records it: from the working directory where it lies under
    it, and its file name otherwise. Never absolute, since the file may be published."""
    here, resolved = pathlib.Path.cwd().resolve(), path.resolve()
    return resolved.relative_to(here).as_posix() if resolved.is_relative_to(here) else path.name
