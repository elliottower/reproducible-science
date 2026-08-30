"""Where a manifest says its files came from.

This module was covered by nothing, and its behaviour is entirely about the cases git cannot
answer for: a directory that is not a repository, a tree with uncommitted changes, a checkout
with no remote. Each returns a different record and none raises, because a manifest over loose
files is legitimate and should say it has no revision rather than fail to be written.
"""

from __future__ import annotations

import os
import pathlib
import subprocess

import pytest
from repro.provenance import of_tree


def git(*args: str, cwd: pathlib.Path) -> None:
    # A clean environment: a hook sets `GIT_DIR` and it outranks the path given to `git init`,
    # so the repository lands somewhere else and the test reads a directory that is not one.
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, env=env)


@pytest.fixture
def repo(tmp_path):
    git("init", "-q", ".", cwd=tmp_path)
    git("config", "user.email", "t@t", cwd=tmp_path)
    git("config", "user.name", "t", cwd=tmp_path)
    (tmp_path / "a.txt").write_text("one\n")
    git("add", "a.txt", cwd=tmp_path)
    git("commit", "-qm", "c", cwd=tmp_path)
    return tmp_path


def test_a_directory_that_is_no_repository_yields_an_empty_record(tmp_path):
    """The case that must not raise: a manifest over loose files says it has no revision."""
    p = of_tree(tmp_path)
    assert p.commit == ""
    assert p.repository == ""
    assert p.dirty is False


def test_a_clean_checkout_carries_its_commit(repo):
    p = of_tree(repo)
    assert len(p.commit) == 40
    assert p.dirty is False


def test_an_uncommitted_change_is_recorded_as_dirty(repo):
    """A manifest built from uncommitted changes names a revision that does not contain what
    was read, so the dirty flag is the whole point of the module."""
    assert of_tree(repo).dirty is False
    (repo / "a.txt").write_text("two\n")
    assert of_tree(repo).dirty is True


def test_an_untracked_file_also_makes_the_tree_dirty(repo):
    (repo / "new.txt").write_text("x\n")
    assert of_tree(repo).dirty is True


def test_a_checkout_with_no_remote_names_the_directory_instead(repo):
    """`repository` falls back to the path, so a record from a local-only checkout still says
    where it was read rather than leaving the field blank beside a real commit."""
    p = of_tree(repo)
    assert p.repository == str(repo)
    assert p.commit


def test_the_remote_is_preferred_over_the_path(repo):
    git("remote", "add", "origin", "https://example.invalid/x.git", cwd=repo)
    assert of_tree(repo).repository == "https://example.invalid/x.git"


def test_a_file_is_read_against_the_directory_holding_it(repo):
    """Callers pass an artifact path, not always a directory."""
    assert of_tree(repo / "a.txt").commit == of_tree(repo).commit


def test_generated_by_is_carried_through(repo):
    assert of_tree(repo, generated_by="scripts/build.py").generated_by == "scripts/build.py"
