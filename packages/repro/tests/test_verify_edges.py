"""Conditions where the engine could report a defect, or the wrong subject, instead of a fact.

Each test here corresponds to a case that once produced a misleading report: an arithmetic
limit surfacing as a backend defect, a broken selector blamed on the table, and a file that
does not exist described as authoritative.
"""
from __future__ import annotations

import decimal
import json

import pytest
from repro.models import (
    ArtifactRef,
    Claim,
    ComparisonMode,
    Digest,
    Manifest,
    MetricEvidence,
    Outcome,
    Reason,
    TableCellEvidence,
    Validity,
)
from repro.policy import EXPLORATORY, PUBLICATION, STRICT
from repro.verify import MetricBackend, TableBackend, compare_decimal, verify

CLAIM = Claim(id="c", text="t")


def metric(reported: str, pointer: str = "/x", **kw) -> MetricEvidence:
    return MetricEvidence(artifact="a", name="m", reported=reported, pointer=pointer, **kw)


def write_json(tmp_path, payload: str):
    path = tmp_path / "results.json"
    path.write_text(payload)
    return path


# -- an arithmetic limit is not a defect ----------------------------------------------------

@pytest.mark.parametrize("stored", ["1E+30", "-1E+30", "1234567890123456789012345678901.5"])
def test_a_value_too_large_to_round_to_printed_precision_disagrees(stored):
    assert compare_decimal(decimal.Decimal(stored), metric("3.20")) is False


def test_a_huge_stored_value_is_a_mismatch_and_not_an_engine_error(tmp_path):
    path = write_json(tmp_path, json.dumps({"x": 1e30}))
    decision = MetricBackend().check(CLAIM, metric("3.20"), path)
    assert decision.outcome is Outcome.MISMATCH
    assert decision.reason is Reason.VALUE_MISMATCH


@pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity"])
def test_a_non_finite_stored_value_is_not_a_quantity_to_compare(tmp_path, literal):
    path = write_json(tmp_path, '{"x": %s}' % literal)
    decision = MetricBackend().check(CLAIM, metric("3.20"), path)
    assert decision.reason is Reason.VALUE_NOT_NUMERIC
    assert decision.outcome is Outcome.NOT_FOUND


def test_rounding_to_printed_precision_still_holds_where_it_can(tmp_path):
    path = write_json(tmp_path, json.dumps({"x": 3.2001}))
    assert MetricBackend().check(CLAIM, metric("3.20"), path).outcome is Outcome.VERIFIED


def test_a_tolerance_comparison_survives_a_non_finite_value():
    evidence = metric("3.20", mode=ComparisonMode.ABSOLUTE, tolerance="0.5")
    assert compare_decimal(decimal.Decimal("NaN"), evidence) is False


# -- a broken selector is the manifest's defect, not the table's ----------------------------

TABLE = "model,accuracy\nresnet,0.91\nvit,0.88\n"


def cell(**kw) -> TableCellEvidence:
    return TableCellEvidence(artifact="a", name="acc", reported="0.91",
                             column="accuracy", **kw)


def test_a_selector_naming_a_column_the_table_lacks_is_reported_as_the_selector(tmp_path):
    path = tmp_path / "t.csv"
    path.write_text(TABLE)
    decision = TableBackend().check(CLAIM, cell(where={"nosuchcolumn": "resnet"}), path)
    assert decision.reason is Reason.ROW_SELECTOR_INVALID
    assert "nosuchcolumn" in decision.detail
    assert "accuracy" in decision.detail, "the columns that do exist should be named"


def test_a_selector_on_a_real_column_with_no_matching_row_is_an_absent_row(tmp_path):
    path = tmp_path / "t.csv"
    path.write_text(TABLE)
    decision = TableBackend().check(CLAIM, cell(where={"model": "nothere"}), path)
    assert decision.reason is Reason.ROW_ABSENT


def test_the_two_are_distinguishable(tmp_path):
    path = tmp_path / "t.csv"
    path.write_text(TABLE)
    backend = TableBackend()
    bad_column = backend.check(CLAIM, cell(where={"nope": "resnet"}), path).reason
    bad_value = backend.check(CLAIM, cell(where={"model": "nope"}), path).reason
    assert bad_column is not bad_value


# -- a file that does not exist is not the authoritative version of itself ------------------

def absent_manifest(tmp_path) -> Manifest:
    return Manifest(
        project="p",
        artifacts=(ArtifactRef(id="a", path=tmp_path / "never_written.json",
                               digest=Digest(algorithm="sha256", value="0" * 64)),),
        claims=(Claim(id="c", text="t", evidence=(metric("3.20"),)),))


def test_an_absent_artifact_is_not_authoritative(tmp_path):
    report = verify(absent_manifest(tmp_path))
    state = report.artifacts[0]
    assert state.exists is False
    assert state.validity is Validity.ARTIFACT_ABSENT


def test_no_decision_against_an_absent_artifact_claims_to_describe_it(tmp_path):
    report = verify(absent_manifest(tmp_path))
    decision = report.claims[0].decisions[0]
    assert decision.is_authoritative is False
    assert decision.outcome is Outcome.UNCHECKED


def test_a_manifest_naming_a_file_that_was_never_produced_fails_publication(tmp_path):
    report = verify(absent_manifest(tmp_path))
    assessment = PUBLICATION.assess(report)
    assert assessment.passed is False
    assert any(v.rule == "artifact.absent" for v in assessment.errors)


def test_strict_agrees_and_exploratory_only_warns(tmp_path):
    report = verify(absent_manifest(tmp_path))
    assert STRICT.assess(report).passed is False
    exploratory = EXPLORATORY.assess(report)
    assert any(v.rule == "artifact.absent" for v in exploratory.warnings), (
        "a draft may name a file the analysis has not written yet, but it is still reported")
