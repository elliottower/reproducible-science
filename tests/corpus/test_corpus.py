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

import pytest
import yaml

from repro.corpus import Corpus, EntryState, RegressionCorpus
from repro.regression import FindingState, run

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
        f"{status.name}: expected {status.expected_commit[:12]}, "
        f"found {status.actual_commit[:12]}")
    assert not status.artifacts_differing, status.artifacts_differing
    assert not status.artifacts_missing, status.artifacts_missing
    assert status.usable


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
