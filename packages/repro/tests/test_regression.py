"""Checking a recorded finding at the revisions it was recorded at.

This module had no test and no importer. What it does is the part of the corpus machinery that
distinguishes a tool that runs from a tool that found something: an entry names a repository, a
revision where a finding reproduced, and optionally a revision where it stopped, and `run`
checks out each in turn and verifies a manifest against it.

Every state it can return needs pinning, because three of the four are ways of declining to
say a finding is fixed, and collapsing any of them into a pass is how a corpus of findings
becomes a corpus of green ticks.
"""

from __future__ import annotations

import json
import os
import pathlib
import subprocess

import pytest
import yaml
from repro.corpus import FindingState, Regression, Revision
from repro.regression import run


def git(*args: str, cwd: pathlib.Path) -> str:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    out = subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True, env=env
    )
    return out.stdout.strip()


def manifest_for(value: str) -> dict:
    return {
        "schema_version": "repro/1",
        "project": "under-test",
        "artifacts": [{"id": "data", "path": "data.json", "media_type": "application/json"}],
        "claims": [
            {
                "id": "c1",
                "text": "The value is as printed.",
                "evidence": [
                    {
                        "kind": "metric",
                        "artifact": "data",
                        "name": "value",
                        "reported": value,
                        "pointer": "/value",
                    }
                ],
            }
        ],
    }


@pytest.fixture
def corpus(tmp_path):
    """A repository whose stored value changes between two commits, and a corpus beside it.

    At `first` the artifact holds 1 while the manifest reports 2, which is the finding. At
    `second` the artifact holds 2 and the same claim verifies, which is the fix.
    """
    repo = tmp_path / "under-test"
    repo.mkdir()
    git("init", "-q", ".", cwd=repo)
    git("config", "user.email", "t@t", cwd=repo)
    git("config", "user.name", "t", cwd=repo)

    (repo / "data.json").write_text(json.dumps({"value": 1}))
    git("add", "data.json", cwd=repo)
    git("commit", "-qm", "one", cwd=repo)
    first = git("rev-parse", "HEAD", cwd=repo)

    (repo / "data.json").write_text(json.dumps({"value": 2}))
    git("add", "data.json", cwd=repo)
    git("commit", "-qm", "two", cwd=repo)
    second = git("rev-parse", "HEAD", cwd=repo)

    # A local remote, so `ensure` can check out a revision the working copy is not at. With
    # no remote it can only offer the revision already checked out, which is the design and
    # makes `before` and `after` untestable in one entry.
    origin = tmp_path / "origin.git"
    git("clone", "-q", "--bare", str(repo), str(origin), cwd=tmp_path)

    corpus_dir = tmp_path / "corpus"
    corpus_dir.mkdir()
    (corpus_dir / "m.yaml").write_text(yaml.safe_dump(manifest_for("2")))
    return corpus_dir, origin, first, second


def entry(repo, name="finding", before=None, after=None) -> Regression:
    return Regression(name=name, repository=str(repo), local_path="", before=before, after=after)


def test_a_finding_reproduced_and_never_closed_is_open(corpus, tmp_path):
    corpus_dir, repo, first, _ = corpus
    e = entry(repo, before=Revision(commit=first, manifest="m.yaml", expected={"mismatch": 1}))
    r = run(e, corpus_dir, cache=tmp_path / "cache")
    assert r.state is FindingState.OPEN
    assert r.before.available and r.before.matches_expected


def test_a_finding_reproduced_then_absent_is_fixed(corpus, tmp_path):
    corpus_dir, repo, first, second = corpus
    e = entry(
        repo,
        before=Revision(commit=first, manifest="m.yaml", expected={"mismatch": 1}),
        after=Revision(commit=second, manifest="m.yaml", expected={"verified": 1}),
    )
    r = run(e, corpus_dir, cache=tmp_path / "cache")
    assert r.state is FindingState.FIXED
    assert "reproduced at before, absent at after" in r.detail


def test_a_before_that_no_longer_shows_it_is_not_a_pass(corpus, tmp_path):
    """The entry claims a mismatch at a commit where the value verifies. Either it was fixed
    without recording an `after`, or the entry is wrong; both need a person, and neither is
    a finding that is closed."""
    corpus_dir, repo, _, second = corpus
    e = entry(repo, before=Revision(commit=second, manifest="m.yaml", expected={"mismatch": 1}))
    r = run(e, corpus_dir, cache=tmp_path / "cache")
    assert r.state is FindingState.UNREPRODUCED


def test_an_after_that_still_shows_it_is_unreproduced(corpus, tmp_path):
    corpus_dir, repo, first, _ = corpus
    e = entry(
        repo,
        before=Revision(commit=first, manifest="m.yaml", expected={"mismatch": 1}),
        after=Revision(commit=first, manifest="m.yaml", expected={"verified": 1}),
    )
    r = run(e, corpus_dir, cache=tmp_path / "cache")
    assert r.state is FindingState.UNREPRODUCED


def test_a_revision_nobody_can_obtain_is_unavailable(corpus, tmp_path):
    corpus_dir, repo, _, _ = corpus
    e = entry(
        repo,
        before=Revision(commit="0" * 40, manifest="m.yaml", expected={"mismatch": 1}),
    )
    r = run(e, corpus_dir, cache=tmp_path / "cache")
    assert r.state is FindingState.UNAVAILABLE
    assert r.before.available is False


def test_a_missing_manifest_is_unavailable_rather_than_a_pass(corpus, tmp_path):
    corpus_dir, repo, first, _ = corpus
    e = entry(repo, before=Revision(commit=first, manifest="absent.yaml", expected={"x": 1}))
    r = run(e, corpus_dir, cache=tmp_path / "cache")
    assert r.state is FindingState.UNAVAILABLE


def test_an_entry_naming_no_revision_is_unavailable(corpus, tmp_path):
    corpus_dir, repo, _, _ = corpus
    r = run(entry(repo, before=Revision()), corpus_dir, cache=tmp_path / "cache")
    assert r.state is FindingState.UNAVAILABLE


def test_nothing_is_written_into_the_repository_under_test(corpus, tmp_path):
    """The manifest is rewritten to absolute paths in a temporary directory, so nothing lands
    in a project that has not adopted this tool."""
    corpus_dir, origin, first, _ = corpus
    cache = tmp_path / "cache"
    run(
        entry(origin, before=Revision(commit=first, manifest="m.yaml", expected={"mismatch": 1})),
        corpus_dir,
        cache=cache,
    )
    checkout = cache / "finding"
    assert checkout.is_dir(), "the entry was never obtained, so this proves nothing"
    assert not (checkout / "repro.yaml").exists()
    assert git("status", "--porcelain", cwd=checkout) == ""
