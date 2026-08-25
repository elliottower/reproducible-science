"""What the four copies disagreed about, asserted once."""

from __future__ import annotations

import hashlib
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


@pytest.fixture
def repo(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "f.txt").write_text("one\n")
    subprocess.run(["git", "add", "f.txt"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "c"],
        cwd=tmp_path,
        check=True,
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
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
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
