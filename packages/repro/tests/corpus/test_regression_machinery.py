"""The machinery that runs a recorded finding, exercised without a private repository.

`regressions.yaml` holds findings against projects that have no public remote, so on every
machine but the author's they report `UNAVAILABLE` and skip. That left `repro.regression`
executed by nothing -- the state its own module docstring calls the failure this package
exists to prevent.

The fixtures here are synthetic: a real git repository built in `tmp_path`, with a stored
number that disagrees with the manuscript at one commit and agrees at the next, served over a
`file://`-style local remote. No network, no private artifact, and the same code path the
real corpus entries take.
"""

from __future__ import annotations

import json
import pathlib
import subprocess

import pytest
import yaml
from repro.corpus import FindingState, Regression, Revision
from repro.regression import run

MANIFEST = {
    "schema_version": "repro/1",
    "project": "synthetic",
    "artifacts": [{"id": "res", "path": "results.json"}],
    "claims": [
        {
            "id": "c",
            "text": "the manuscript reports an accuracy of 0.91",
            "evidence": [
                {
                    "kind": "metric",
                    "artifact": "res",
                    "name": "accuracy",
                    "reported": "0.91",
                    "pointer": "/accuracy",
                }
            ],
        }
    ],
}


def git(*args, cwd):
    return subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


@pytest.fixture
def project(tmp_path, monkeypatch):
    """A repository whose stored accuracy disagrees with 0.91, then agrees.

    Returns (remote, corpus_dir, before_commit, after_commit).
    """
    monkeypatch.delenv("REPRO_OFFLINE", raising=False)

    work = tmp_path / "work"
    work.mkdir()
    git("init", "-q", "-b", "main", cwd=work)

    (work / "results.json").write_text(json.dumps({"accuracy": 0.5}) + "\n")
    git("add", "results.json", cwd=work)
    git("commit", "-q", "-m", "results as first computed", cwd=work)
    before = git("rev-parse", "HEAD", cwd=work)

    (work / "results.json").write_text(json.dumps({"accuracy": 0.91}) + "\n")
    git("add", "results.json", cwd=work)
    git("commit", "-q", "-m", "recompute after the fix", cwd=work)
    after = git("rev-parse", "HEAD", cwd=work)

    remote = tmp_path / "remote.git"
    git("clone", "--quiet", "--bare", str(work), str(remote), cwd=tmp_path)

    corpus = tmp_path / "corpus"
    (corpus / "manifests").mkdir(parents=True)
    (corpus / "manifests" / "m.yaml").write_text(yaml.safe_dump(MANIFEST, sort_keys=False))
    return remote, corpus, before, after


def entry(remote, *, before_commit, before_expected, after=None, name="synthetic") -> Regression:
    return Regression(
        name=name,
        summary="a stored value that disagrees with the printed one",
        repository=str(remote),
        before=Revision(
            commit=before_commit, manifest="manifests/m.yaml", expected=before_expected
        ),
        after=after,
    )


def test_a_finding_that_still_reproduces_and_has_no_fix_is_open(project, tmp_path):
    remote, corpus, before, _ = project
    result = run(
        entry(remote, before_commit=before, before_expected={"mismatch": 1}),
        corpus,
        cache=tmp_path / "cache",
    )
    assert result.state is FindingState.OPEN, result.detail
    assert result.before is not None and result.before.available
    assert result.before.counts == {"mismatch": 1}
    assert result.before.matches_expected


def test_a_finding_absent_at_the_later_revision_is_fixed(project, tmp_path):
    remote, corpus, before, after = project
    result = run(
        entry(
            remote,
            before_commit=before,
            before_expected={"mismatch": 1},
            after=Revision(commit=after, manifest="manifests/m.yaml", expected={"verified": 1}),
        ),
        corpus,
        cache=tmp_path / "cache",
    )
    assert result.state is FindingState.FIXED, result.detail
    assert result.after is not None and result.after.counts == {"verified": 1}


def test_a_finding_that_no_longer_reproduces_where_it_was_recorded_is_not_a_pass(project, tmp_path):
    """Either it was fixed with no `after` recorded, or the entry is wrong. Both need saying.

    Silently passing here would let the corpus report a tool that catches things while every
    entry in it had quietly stopped reproducing.
    """
    remote, corpus, _, after = project
    result = run(
        entry(remote, before_commit=after, before_expected={"mismatch": 1}),
        corpus,
        cache=tmp_path / "cache",
    )
    assert result.state is FindingState.UNREPRODUCED, result.detail
    assert "got {'verified': 1}" in result.detail


def test_a_revision_that_cannot_be_obtained_is_unavailable_and_never_fixed(project, tmp_path):
    remote, corpus, before, _ = project
    result = run(
        entry(
            remote,
            before_commit=before,
            before_expected={"mismatch": 1},
            after=Revision(commit="0" * 40, manifest="manifests/m.yaml", expected={"verified": 1}),
        ),
        corpus,
        cache=tmp_path / "cache",
    )
    assert result.state is FindingState.UNAVAILABLE, result.detail
    assert result.after is not None and result.after.available is False


def test_a_manifest_the_corpus_does_not_hold_is_unavailable_rather_than_reproduced(
    project, tmp_path
):
    remote, corpus, before, _ = project
    bad = entry(remote, before_commit=before, before_expected={"mismatch": 1})
    bad = bad.model_copy(
        update={"before": bad.before.model_copy(update={"manifest": "manifests/nope.yaml"})}
    )
    result = run(bad, corpus, cache=tmp_path / "cache")
    assert result.state is FindingState.UNAVAILABLE


def test_the_project_under_test_is_only_read(project, tmp_path):
    """The manifest lives in the corpus, and its paths are rewritten in a temporary copy.

    A tool that writes into the repository it is auditing changes the thing it measures.
    """
    remote, corpus, before, _ = project
    cache = tmp_path / "cache"
    run(entry(remote, before_commit=before, before_expected={"mismatch": 1}), corpus, cache=cache)
    checkout = cache / "synthetic"
    assert (checkout / ".git").is_dir(), "the fixture did not exercise the fetch path"
    assert not (checkout / "repro.yaml").exists()
    assert git("status", "--porcelain", cwd=checkout) == ""
    assert sorted(p.name for p in checkout.iterdir() if p.name != ".git") == ["results.json"]


def test_a_stored_value_is_read_from_the_pinned_revision_not_the_working_tree(project, tmp_path):
    """Both commits differ only in the number, so a run against the wrong one is visible.

    `ensure` returns an existing checkout unchanged where an entry has no remote. Nothing
    re-checked which revision that was, so counts measured at whatever HEAD happened to be
    were reported under the pinned commit.
    """
    remote, corpus, before, after = project
    cache = tmp_path / "cache"
    first = run(
        entry(remote, before_commit=before, before_expected={"mismatch": 1}), corpus, cache=cache
    )
    second = run(
        entry(remote, before_commit=after, before_expected={"verified": 1}), corpus, cache=cache
    )
    assert first.before is not None and second.before is not None
    assert first.before.counts == {"mismatch": 1}
    assert second.before.counts == {"verified": 1}, (
        "the second run reused the cached checkout and never moved to the pinned commit"
    )


def test_a_dirty_checkout_of_the_pinned_commit_is_refused(project, tmp_path):
    remote, corpus, before, _ = project
    cache = tmp_path / "cache"
    run(entry(remote, before_commit=before, before_expected={"mismatch": 1}), corpus, cache=cache)

    checkout = cache / "synthetic"
    (checkout / "results.json").write_text(json.dumps({"accuracy": 0.91}) + "\n")
    local = Regression(
        name="synthetic",
        repository="",
        local_path=str(checkout),
        before=Revision(commit=before, manifest="manifests/m.yaml", expected={"mismatch": 1}),
    )
    result = run(local, corpus, cache=pathlib.Path(tmp_path / "empty-cache"))
    assert result.state is FindingState.UNAVAILABLE, (
        "an edited working tree holds bytes only this machine has; verifying against them "
        "produces a result nobody can reproduce"
    )
