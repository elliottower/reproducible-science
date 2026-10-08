"""Is a pinned source in git, where publishing the repository republishes its text?

A claims file names its source by a path and pins it by a sha256. The check needs the file on
disk and nothing more: `verify` reads it from the path, or from the library where its bytes
match the pin, and a clone that holds neither reports the quotations `unchecked`. So the source
itself never has to be committed, and a committed one is a copy of somebody else's text that
goes wherever the repository goes. Removing it later means rewriting every commit that held it.

This answers three questions and changes nothing. `tracked` says which of a set of files git
has in its index, and `committed` which of them the last commit holds: the two differ between
a `git rm --cached` and the commit that records it. `standing` says where one file stands:
tracked, covered by an ignore rule, covered by none, or outside any repository. Where git is absent or the directory is not a
repository there is nothing to report, and nothing is reported.

A warning, never a failure. Text under an open licence is the author's to commit, and nothing
here reads a licence.
"""

from __future__ import annotations

import collections
import pathlib
from collections.abc import Iterable
from typing import Literal

from provenance_core import try_run

Standing = Literal["tracked", "ignored", "unignored", "outside"]

#: What to do about a tracked source, said once wherever one is reported.
REMEDY = (
    "untrack with `git rm --cached` and add an ignore rule; the record's sha256 still pins "
    "the file, and its url lets `citations fetch` restore it. A commit already pushed keeps "
    "the text until the history is rewritten"
)


def top(folder: pathlib.Path) -> pathlib.Path | None:
    """The top of the repository `folder` is in, or None outside one and where git is absent."""
    shown = try_run("rev-parse", "--show-toplevel", cwd=folder)
    return pathlib.Path(shown).resolve() if shown else None


def tracked(sources: Iterable[pathlib.Path]) -> set[pathlib.Path]:
    """Which of these files git has in its index.

    One `git ls-files` for each directory the files sit in, so a folder of two thousand
    sources is one question. A directory that is not in a repository, and a machine without
    git, answer with nothing.
    """
    by_folder: dict[pathlib.Path, set[str]] = collections.defaultdict(set)
    for source in sources:
        by_folder[source.parent].add(source.name)
    held: set[pathlib.Path] = set()
    for folder, names in by_folder.items():
        if not folder.is_dir():
            continue
        listed = try_run("ls-files", "-z", cwd=folder)
        if not listed:
            continue
        held |= {folder / name for name in names & set(listed.split("\0"))}
    return held


def committed(sources: Iterable[pathlib.Path]) -> set[pathlib.Path]:
    """Which of these files the last commit holds, whatever the index holds now.

    The index and the last commit answer different questions. `git rm --cached` takes a file
    out of the index at once and out of no commit: `HEAD` holds it until the removal is
    committed, and a record that names `HEAD` names a commit with the text in it. A file need
    not be on disk to be asked about, since deleting it takes it out of no commit either.

    One `git ls-tree` for each repository the files sit in. Outside a repository, in one with
    no commit yet, and on a machine without git, the answer is nothing.
    """
    tops: dict[pathlib.Path, pathlib.Path | None] = {}
    by_top: dict[pathlib.Path, set[pathlib.Path]] = collections.defaultdict(set)
    for source in sources:
        folder = next((d for d in source.parents if d.is_dir()), None)
        if folder is None:
            continue
        if folder not in tops:
            tops[folder] = top(folder)
        root = tops[folder]
        if root is not None:
            by_top[root].add(source)
    held: set[pathlib.Path] = set()
    for root, wanted in by_top.items():
        listed = try_run("ls-tree", "-r", "-z", "--name-only", "--full-tree", "HEAD", cwd=root)
        if listed:
            held |= wanted & {root / name for name in listed.split("\0") if name}
    return held


def standing(source: pathlib.Path) -> Standing:
    """Where one file stands with git: tracked, ignored, covered by no ignore rule, or outside."""
    folder = source.parent
    if not folder.is_dir() or try_run("rev-parse", "--is-inside-work-tree", cwd=folder) != "true":
        return "outside"
    if source in tracked([source]):
        return "tracked"
    # `check-ignore` exits 0 where a rule covers the path and 1 where none does.
    covered = try_run("check-ignore", "-q", "--", source.name, cwd=folder) is not None
    return "ignored" if covered else "unignored"


def advice(source: pathlib.Path) -> str:
    """One line for whoever just pinned against this source, or nothing where none is owed."""
    where = standing(source)
    if where == "tracked":
        return (
            f"{source.name} is tracked by git, so publishing the repository republishes its "
            f"text: {REMEDY}"
        )
    if where == "unignored":
        return (
            f"no ignore rule covers {source.name}, so `git add` will take it and publishing the "
            f"repository republishes its text: add one. The record's sha256 pins the file, and "
            f"its url lets `citations fetch` restore it"
        )
    return ""
