"""What the four copies disagreed about, asserted once."""

from __future__ import annotations

import hashlib
import os
import pathlib
import subprocess

import pytest

from provenance_core import gitref
from provenance_core.digests import ZERO, sha256_of_file, sha256_of_text


def test_a_file_and_its_bytes_hash_alike(tmp_path):
    p = tmp_path / "a.bin"
    body = b"the measured angle matches the Haar expectation\n"
    p.write_bytes(body)
    assert sha256_of_file(p) == hashlib.sha256(body).hexdigest()


def test_a_file_larger_than_one_block_hashes_correctly(tmp_path):
    # The copies read in 1 MB and 64 KB blocks. Both are right only if the loop is right.
    p = tmp_path / "big.bin"
    body = bytes(range(256)) * 20_000  # ~5 MB, several blocks
    p.write_bytes(body)
    assert sha256_of_file(p) == hashlib.sha256(body).hexdigest()


def test_text_is_hashed_as_utf8_whatever_the_platform_default(tmp_path):
    # One copy used a bare `.encode()`. A digest that depends on a platform default is not a
    # content address.
    text = "ångström — naïve — 日本語"
    assert sha256_of_text(text) == hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_the_zero_digest_is_a_sha256_shaped_string_addressing_nothing():
    assert len(ZERO) == 64 and set(ZERO) == {"0"}


# -- git: one policy per caller, chosen rather than inherited --------------------------------


def git(*args, cwd):
    """Run git against `cwd` and nowhere else.

    `cwd` does not decide which repository git acts on: `GIT_INDEX_FILE`, `GIT_DIR` and
    `GIT_WORK_TREE` outrank it. Pre-commit sets `GIT_INDEX_FILE` while it stashes, so a test
    inheriting the environment stages into the *outer* worktree's index, and a commit against
    that index with one file staged leaves every other tracked file staged as deleted. That is
    a wrecked checkout produced by a passing test, and under `pytest -n auto` the workers race
    on the same index. Dropping every `GIT_*` variable is what makes `cwd` mean what it reads
    as meaning.
    """
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    return subprocess.run(
        args, cwd=cwd, env=env, check=True, capture_output=True, text=True
    )


@pytest.fixture
def repo(tmp_path):
    git("git", "init", "-q", cwd=tmp_path)
    (tmp_path / "f.txt").write_text("one\n")
    git("git", "add", "f.txt", cwd=tmp_path)
    git(
        "git",
        "-c",
        "user.email=t@t",
        "-c",
        "user.name=t",
        "commit",
        "-q",
        "-m",
        "c",
        cwd=tmp_path,
    )
    return tmp_path


def test_run_raises_where_try_run_returns_none(tmp_path):
    """The distinction the three copies disagreed about, in one assertion.

    A directory that is not a repository is a fact a provenance record reports as unknown and
    a fetch reports as an error. Returning "" for it, as one copy did, made a repository with
    no commit indistinguishable from one with a commit.
    """
    with pytest.raises(gitref.GitError):
        gitref.run("rev-parse", "HEAD", cwd=tmp_path)
    assert gitref.try_run("rev-parse", "HEAD", cwd=tmp_path) is None
    assert gitref.commit(tmp_path) is None


def test_commit_names_head(repo):
    head = git("git", "rev-parse", "HEAD", cwd=repo).stdout.strip()
    assert gitref.commit(repo) == head
    assert gitref.at_commit(repo, head)


def test_at_commit_is_exact_and_refuses_a_prefix(repo):
    head = gitref.commit(repo)
    assert head is not None
    assert not gitref.at_commit(repo, head[:8]), (
        "an abbreviation could prefix another commit"
    )
    assert not gitref.at_commit(repo, "")
    assert not gitref.at_commit(pathlib.Path(repo) / "nope", head)


def test_a_directory_that_is_not_a_repository_is_not_at_any_commit(tmp_path):
    assert not gitref.at_commit(tmp_path, "0" * 40)
    assert not gitref.at_commit(tmp_path, "")


def test_dirty_tracks_the_working_tree(repo):
    assert not gitref.is_dirty(repo)
    (repo / "f.txt").write_text("two\n")
    assert gitref.is_dirty(repo)


def test_a_missing_git_binary_is_an_error_not_an_empty_answer(repo, monkeypatch):
    def absent(*a, **kw):
        raise FileNotFoundError("git")

    monkeypatch.setattr(gitref.subprocess, "run", absent)
    with pytest.raises(gitref.GitError) as e:
        gitref.run("rev-parse", "HEAD", cwd=repo)
    assert "git" in str(e.value)
    assert gitref.try_run("rev-parse", "HEAD", cwd=repo) is None


def test_git_acts_on_cwd_even_when_the_environment_names_another_index(tmp_path):
    outer, inner = tmp_path / "outer", tmp_path / "inner"
    for d in (outer, inner):
        d.mkdir()
        git("git", "init", "-q", cwd=d)
    (outer / "kept.txt").write_text("x\n")
    git("git", "add", "kept.txt", cwd=outer)
    git(
        "git",
        "-c",
        "user.email=t@t",
        "-c",
        "user.name=t",
        "commit",
        "-q",
        "-m",
        "c",
        cwd=outer,
    )
    (inner / "f.txt").write_text("one\n")

    poisoned = dict(os.environ, GIT_INDEX_FILE=str(outer / ".git" / "index"))
    subprocess.run(["git", "add", "f.txt"], cwd=inner, env=poisoned, check=False)
    assert git("git", "status", "--short", cwd=outer).stdout.strip(), (
        "the inherited environment should have staged into the outer index; if this is empty "
        "the demonstration no longer demonstrates anything and the test below proves nothing"
    )

    git("git", "reset", "-q", "--hard", cwd=outer)
    git("git", "add", "f.txt", cwd=inner)
    assert git("git", "status", "--short", cwd=outer).stdout.strip() == ""


# -- cwd names the repository, and outranks an environment that names another ------------------


@pytest.fixture
def elsewhere(tmp_path_factory):
    """A second repository with one commit, to be named by the environment and not obeyed."""
    d = tmp_path_factory.mktemp("elsewhere")
    git("git", "init", "-q", cwd=d)
    (d / "other.txt").write_text("other\n")
    git("git", "add", "other.txt", cwd=d)
    git(
        "git",
        "-c",
        "user.email=t@t",
        "-c",
        "user.name=t",
        "commit",
        "-q",
        "-m",
        "o",
        cwd=d,
    )
    return d


@pytest.mark.parametrize("var", ["GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"])
def test_the_commit_named_is_the_one_in_cwd_not_the_one_in_the_environment(
    repo, elsewhere, monkeypatch, var
):
    # Every git hook exports GIT_DIR, and pre-commit exports GIT_INDEX_FILE while it stashes.
    # Under either, `of_tree(path)` used to record the invoking repository's commit as the
    # provenance of `path` -- a provenance record naming a repository nobody asked about.
    target = elsewhere / ".git" if var != "GIT_WORK_TREE" else elsewhere
    monkeypatch.setenv(
        var, str(target / "index" if var == "GIT_INDEX_FILE" else target)
    )
    mine = git("git", "rev-parse", "HEAD", cwd=repo).stdout.strip()
    theirs = git("git", "rev-parse", "HEAD", cwd=elsewhere).stdout.strip()
    assert mine != theirs
    assert gitref.commit(repo) == mine


def test_a_directory_outside_any_repository_is_still_outside_one(
    tmp_path, elsewhere, monkeypatch
):
    monkeypatch.setenv("GIT_DIR", str(elsewhere / ".git"))
    plain = tmp_path / "plain"
    plain.mkdir()
    assert gitref.commit(plain) is None
    with pytest.raises(gitref.GitError):
        gitref.run("rev-parse", "HEAD", cwd=plain)


def test_a_clean_tree_reads_clean_while_the_environment_names_a_dirty_one(
    repo, elsewhere, monkeypatch
):
    (elsewhere / "scratch.txt").write_text("uncommitted\n")
    monkeypatch.setenv("GIT_DIR", str(elsewhere / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(elsewhere))
    assert gitref.is_dirty(elsewhere)
    assert not gitref.is_dirty(repo)


def test_a_caller_that_names_no_directory_still_inherits_the_environment(
    elsewhere, monkeypatch
):
    # The other half of the rule. `cwd=None` means "wherever we are", so an inherited GIT_DIR
    # is the answer rather than an override, and dropping it would break a caller inside a hook
    # that meant the hook's repository.
    monkeypatch.setenv("GIT_DIR", str(elsewhere / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(elsewhere))
    theirs = git("git", "rev-parse", "HEAD", cwd=elsewhere).stdout.strip()
    assert gitref.commit() == theirs


def test_a_variable_that_configures_git_rather_than_relocating_it_survives(
    repo, monkeypatch
):
    # The list is narrow on purpose: dropping every GIT_* would take GIT_SSH_COMMAND and the
    # identity variables with it, which a caller that set them meant.
    #
    # Both halves are set, because `git var GIT_AUTHOR_IDENT` needs a name and an address and
    # will take the address from anywhere it can: a global config, or failing that a synthetic
    # `user@host`. On a developer machine it always resolves, so setting only the name passed
    # here and failed intermittently on runners that have neither -- a test whose verdict
    # depended on the machine rather than on the code under it.
    monkeypatch.setenv("GIT_AUTHOR_NAME", "Someone Named")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "someone@example.invalid")
    assert "GIT_AUTHOR_NAME" not in gitref.REDIRECTS
    assert gitref.run("var", "GIT_AUTHOR_IDENT", cwd=repo).startswith("Someone Named")
