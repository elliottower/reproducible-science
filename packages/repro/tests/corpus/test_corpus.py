"""The corpus and regression entries, run against real repositories.

Marked `corpus` and deselected by default: these read repositories that are not part of this
one and may fetch them. Run explicitly:

    pytest -m corpus
    REPRO_OFFLINE=1 pytest -m corpus     # cached checkouts only

An entry that cannot be obtained is reported as skipped with its name. A corpus run that
silently skipped everything would report nothing and look like a clean pass, which is the
failure this package exists to prevent.
"""

from __future__ import annotations

import pathlib
import subprocess

import pytest
import yaml
from repro.corpus import (
    Corpus,
    CorpusEntry,
    EntryState,
    RegressionCorpus,
    _is_pinned_revision,
    ensure,
)
from repro.regression import FindingState, _manifest_against, run

HERE = pathlib.Path(__file__).parent
pytestmark = pytest.mark.corpus


def _load(name: str, model):
    p = HERE / name
    if not p.is_file():
        pytest.skip(f"{name} is not present")
    return model.model_validate({**(yaml.safe_load(p.read_text()) or {}), "path": p})


def corpus_entries():
    p = HERE / "corpus.yaml"
    if not p.is_file():
        return []
    return (yaml.safe_load(p.read_text()) or {}).get("entries", [])


def findings():
    p = HERE / "regressions.yaml"
    if not p.is_file():
        return []
    return (yaml.safe_load(p.read_text()) or {}).get("findings", [])


@pytest.mark.parametrize("entry", corpus_entries(), ids=lambda e: e["name"])
def test_corpus_entry_is_at_its_pinned_revision(entry):
    corpus = _load("corpus.yaml", Corpus)
    status = next(s for s in corpus.status() if s.name == entry["name"])
    if status.state is EntryState.ABSENT:
        pytest.skip(f"{status.name} could not be obtained")
    assert status.state is EntryState.MEASURED, (
        f"{status.name}: expected {status.expected_commit[:12]}, found {status.actual_commit[:12]}"
    )
    assert not status.artifacts_differing, status.artifacts_differing
    assert not status.artifacts_missing, status.artifacts_missing
    assert status.usable


@pytest.mark.parametrize(
    "entry", [e for e in corpus_entries() if e.get("manifest")], ids=lambda e: e["name"]
)
def test_corpus_entry_verifies_to_its_recorded_counts(entry):
    """A project audited at a pinned revision still produces what it produced."""
    corpus = _load("corpus.yaml", Corpus)
    item = next(e for e in corpus.entries if e.name == entry["name"])
    root = ensure(item, HERE)
    if root is None:
        pytest.skip(f"{item.name} could not be obtained")
    report = _manifest_against(HERE / item.manifest, root)
    assert report.counts == item.expected, (
        f"{item.name}: recorded {item.expected}, got {report.counts}"
    )


@pytest.mark.parametrize("finding", findings(), ids=lambda f: f["name"])
def test_recorded_finding_still_reproduces(finding):
    corpus = _load("regressions.yaml", RegressionCorpus)
    entry = next(f for f in corpus.findings if f.name == finding["name"])
    result = run(entry, HERE)
    if result.state is FindingState.UNAVAILABLE:
        pytest.skip(f"{result.name}: {result.detail}")
    assert result.state in (FindingState.OPEN, FindingState.FIXED), result.detail
    assert result.before is not None and result.before.matches_expected, result.detail


def test_every_entry_that_cannot_be_reproduced_elsewhere_is_named():
    # An entry with no remote reproduces only where the repository already exists. That is a
    # legitimate state for a project not yet published, and it is reported rather than left to
    # be discovered by someone whose run silently skips it.
    corpus = _load("regressions.yaml", RegressionCorpus)
    without = corpus.without_remote
    if without:
        pytest.skip(f"no public remote recorded for: {', '.join(without)}")


def test_a_dirty_working_tree_is_not_the_pinned_revision(tmp_path):
    """A checkout at the right commit with uncommitted edits holds bytes only that machine
    has. Verifying against them produces a result nobody else can reproduce, so `ensure`
    prefers a clean copy where one can be fetched."""
    repo = tmp_path / "repo"
    repo.mkdir()

    def run(*a):
        return subprocess.run(["git", *a], cwd=repo, capture_output=True, check=True, timeout=30)

    run("init", "-q")
    run("config", "user.email", "t@t")
    run("config", "user.name", "t")
    # A throwaway fixture must not inherit the machine's signing config: where commits are
    # signed through an external agent, `git commit` blocks on it and the test fails for a
    # reason that has nothing to do with what it checks.
    run("config", "commit.gpgsign", "false")
    run("config", "tag.gpgsign", "false")
    (repo / "x.txt").write_text("one\n")
    run("add", "x.txt")
    run("commit", "-qm", "one")
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True
    ).stdout.strip()

    entry = CorpusEntry(name="t", commit=commit, local_path=str(repo))
    assert _is_pinned_revision(entry, repo), "a clean tree at the pinned commit is the revision"

    (repo / "x.txt").write_text("two\n")
    assert not _is_pinned_revision(entry, repo), (
        "the commit is unchanged and the bytes are not; that is not the pinned revision"
    )
