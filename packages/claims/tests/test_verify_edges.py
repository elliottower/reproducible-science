"""Conditions where the engine could report a defect, or the wrong subject, instead of a fact.

Each test here corresponds to a case that once produced a misleading report: an arithmetic
limit surfacing as a backend defect, a broken selector blamed on the table, and a file that
does not exist described as authoritative.
"""

from __future__ import annotations

import decimal
import json

import pytest
from claims.adapters.tree import _resolve_tree
from claims.models import (
    ArtifactRef,
    Claim,
    ComparisonMode,
    CorrespondenceEvidence,
    CorrespondenceSide,
    Digest,
    Manifest,
    MetricEvidence,
    Outcome,
    Reason,
    TableCellEvidence,
    TreeLocator,
    Validity,
)
from claims.policy import EXPLORATORY, PUBLICATION, STRICT
from claims.verify import (
    CorrespondenceBackend,
    MetricBackend,
    TableBackend,
    compare_decimal,
    verify,
)

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
    decision = MetricBackend().check(CLAIM, metric("3.20"), {"a": path})
    assert decision.outcome is Outcome.MISMATCH
    assert decision.reason is Reason.VALUE_MISMATCH


@pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity"])
def test_a_non_finite_stored_value_is_not_a_quantity_to_compare(tmp_path, literal):
    path = write_json(tmp_path, f'{{"x": {literal}}}')
    decision = MetricBackend().check(CLAIM, metric("3.20"), {"a": path})
    assert decision.reason is Reason.VALUE_NOT_NUMERIC
    assert decision.outcome is Outcome.NOT_FOUND


def test_rounding_to_printed_precision_still_holds_where_it_can(tmp_path):
    path = write_json(tmp_path, json.dumps({"x": 3.2001}))
    assert MetricBackend().check(CLAIM, metric("3.20"), {"a": path}).outcome is Outcome.VERIFIED


def test_a_tolerance_comparison_survives_a_non_finite_value():
    evidence = metric("3.20", mode=ComparisonMode.ABSOLUTE, tolerance="0.5")
    assert compare_decimal(decimal.Decimal("NaN"), evidence) is False


# -- a broken selector is the manifest's defect, not the table's ----------------------------

TABLE = "model,accuracy\nresnet,0.91\nvit,0.88\n"


def cell(**kw) -> TableCellEvidence:
    return TableCellEvidence(artifact="a", name="acc", reported="0.91", column="accuracy", **kw)


def test_a_selector_naming_a_column_the_table_lacks_is_reported_as_the_selector(tmp_path):
    path = tmp_path / "t.csv"
    path.write_text(TABLE)
    decision = TableBackend().check(CLAIM, cell(where={"nosuchcolumn": "resnet"}), {"a": path})
    assert decision.reason is Reason.ROW_SELECTOR_INVALID
    assert "nosuchcolumn" in decision.detail
    assert "accuracy" in decision.detail, "the columns that do exist should be named"


def test_a_selector_on_a_real_column_with_no_matching_row_is_an_absent_row(tmp_path):
    path = tmp_path / "t.csv"
    path.write_text(TABLE)
    decision = TableBackend().check(CLAIM, cell(where={"model": "nothere"}), {"a": path})
    assert decision.reason is Reason.ROW_ABSENT


def test_the_two_are_distinguishable(tmp_path):
    path = tmp_path / "t.csv"
    path.write_text(TABLE)
    backend = TableBackend()
    bad_column = backend.check(CLAIM, cell(where={"nope": "resnet"}), {"a": path}).reason
    bad_value = backend.check(CLAIM, cell(where={"model": "nope"}), {"a": path}).reason
    assert bad_column is not bad_value


# -- a file that does not exist is not the authoritative version of itself ------------------


def absent_manifest(tmp_path) -> Manifest:
    return Manifest(
        project="p",
        artifacts=(
            ArtifactRef(
                id="a",
                path=tmp_path / "never_written.json",
                digest=Digest(algorithm="sha256", value="0" * 64),
            ),
        ),
        claims=(Claim(id="c", text="t", evidence=(metric("3.20"),)),),
    )


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
        "a draft may name a file the analysis has not written yet, but it is still reported"
    )


# -- a file that is not the one pinned is reported by the policy, not just by the engine ----


def broken_pin_manifest(tmp_path) -> Manifest:
    """A real, readable file whose bytes no longer match the digest the manifest records."""
    path = write_json(tmp_path, json.dumps({"x": 3.2}))
    return Manifest(
        project="p",
        artifacts=(
            ArtifactRef(id="a", path=path, digest=Digest(algorithm="sha256", value="de" * 32)),
        ),
        claims=(Claim(id="c", text="t", evidence=(metric("3.20"),)),),
    )


def test_a_broken_pin_fails_publication_even_though_the_value_matched(tmp_path):
    # The engine sets BROKEN_PIN and the SARIF renderer prints it, but nothing asserted that a
    # policy fails over it -- so a paper whose numbers all agree with a file that is provably
    # not the pinned one passed the publication gate.
    report = verify(broken_pin_manifest(tmp_path))
    assert report.decisions[0].outcome is Outcome.VERIFIED, "the comparison still ran"
    assert report.decisions[0].is_authoritative is False

    assessment = PUBLICATION.assess(report)
    assert assessment.passed is False
    violation = next(v for v in assessment.errors if v.rule == "artifact.pin")
    assert "de" in violation.detail and violation.subject == "a", (
        "the violation has to name the artifact and both digests"
    )


def test_strict_agrees_and_exploratory_still_reports_the_broken_pin(tmp_path):
    report = verify(broken_pin_manifest(tmp_path))
    assert STRICT.assess(report).passed is False
    # EXPLORATORY relaxes `unpinned`, never `broken`: a draft may not have pinned a file yet,
    # but a pin that no longer holds is the same error at every stage.
    assert any(v.rule == "artifact.pin" for v in EXPLORATORY.assess(report).errors)


# -- a run that evaluated nothing is not a pass ---------------------------------------------


def test_a_report_with_no_evidence_anywhere_fails_rather_than_passing_vacuously(tmp_path):
    report = verify(Manifest(project="p", artifacts=(), claims=()))
    assert report.decisions == ()
    for policy in (EXPLORATORY, PUBLICATION, STRICT):
        assessment = policy.assess(report)
        assert assessment.passed is False, f"{policy.name} passed a run that checked nothing"
        assert any(v.rule == "report.empty" for v in assessment.errors)


def test_require_one_check_is_what_makes_that_fail(tmp_path):
    # The negative half: the emptiness has to be why it failed, not some other condition.
    report = verify(Manifest(project="p", artifacts=(), claims=()))
    relaxed = PUBLICATION.model_copy(update={"require_one_check": False})
    assert relaxed.assess(report).passed is True


def test_a_claim_offering_no_evidence_is_reported_and_not_silently_skipped(tmp_path):
    path = write_json(tmp_path, json.dumps({"x": 3.2}))
    report = verify(
        Manifest(
            project="p",
            artifacts=(ArtifactRef(id="a", path=path),),
            claims=(
                Claim(id="bare", text="asserted with nothing behind it"),
                Claim(id="c", text="t", evidence=(metric("3.20"),)),
            ),
        )
    )
    offered = [v for v in PUBLICATION.assess(report).warnings if v.rule == "claim.no_evidence"]
    assert [v.subject for v in offered] == ["bare"]
    assert any(v.rule == "claim.no_evidence" for v in STRICT.assess(report).errors), (
        "strict makes an unsupported claim an error"
    )
    assert not any(v.rule == "claim.no_evidence" for v in EXPLORATORY.assess(report).violations), (
        "a draft may carry a claim it has not evidenced yet"
    )


# -- a number in a tree file is the digits the file wrote -----------------------------------


def write_tree(tmp_path, literal: str, suffix: str):
    path = tmp_path / f"results{suffix}"
    path.write_text(f'{{"x": {literal}}}' if suffix == ".json" else f"x: {literal}\n")
    return path


def stored(path) -> str:
    _, found, _ = _resolve_tree(TreeLocator(pointer="/x"), path)
    assert found is not None
    return found.raw


TREES = [".json", ".yaml"]

AS_WRITTEN = [
    "0.910",
    "0.12345678901234567890",
    "1.0",
    "-0.0",
    "9007199254740993.0",
    "123456789012345678901234567890",
    "1.50e-7",
    "1.0e400",
]


@pytest.mark.parametrize("suffix", TREES)
@pytest.mark.parametrize("literal", [*AS_WRITTEN, "1e-7", "1E5"])
def test_a_json_number_is_read_as_the_digits_the_file_wrote(tmp_path, literal, suffix):
    if suffix == ".yaml" and "." not in literal:
        pytest.skip("YAML reads a number with an exponent and no point as a string")
    assert stored(write_tree(tmp_path, literal, suffix)) == literal


@pytest.mark.parametrize("suffix", TREES)
@pytest.mark.parametrize(
    ("literal", "reported", "outcome"),
    [
        ("0.910", "0.910", Outcome.VERIFIED),
        ("0.910", "0.91", Outcome.VERIFIED),
        ("0.914", "0.91", Outcome.VERIFIED),
        ("0.914", "0.910", Outcome.MISMATCH),
        ("0.12345678901234567890", "0.12345678901234567890", Outcome.VERIFIED),
        ("0.12345678901234567890", "0.12345678901234567891", Outcome.MISMATCH),
        ("0.12345678901234567890", "0.12345678901234568", Outcome.VERIFIED),
        ("1.0e-7", "0.0000001", Outcome.VERIFIED),
        ("1.0", "1", Outcome.VERIFIED),
        ("1", "1.0", Outcome.VERIFIED),
        ("9007199254740993", "9007199254740993", Outcome.VERIFIED),
        ("9007199254740993.0", "9007199254740993", Outcome.VERIFIED),
        ("9007199254740993.0", "9007199254740992", Outcome.MISMATCH),
        ("-0.0", "0.0", Outcome.VERIFIED),
        ("-0.0", "-0.0", Outcome.VERIFIED),
        ("1.0e400", "1e400", Outcome.VERIFIED),
        ("1.0e-400", "1e-400", Outcome.VERIFIED),
        ("1.0e-400", "2e-400", Outcome.MISMATCH),
    ],
)
def test_a_tree_number_is_compared_as_the_decimal_the_file_wrote(
    tmp_path, literal, reported, outcome, suffix
):
    path = write_tree(tmp_path, literal, suffix)
    assert MetricBackend().check(CLAIM, metric(reported), {"a": path}).outcome is outcome


@pytest.mark.parametrize("suffix", TREES)
def test_a_matching_decision_shows_the_trailing_zero_the_file_wrote(tmp_path, suffix):
    path = write_tree(tmp_path, "0.910", suffix)
    assert MetricBackend().check(CLAIM, metric("0.91"), {"a": path}).detail == "/x = 0.910"


@pytest.mark.parametrize(("literal", "kind"), [("0.910", "float"), ("7", "int"), ("true", "bool")])
@pytest.mark.parametrize("suffix", TREES)
def test_the_native_type_of_a_tree_value_is_named_as_before(tmp_path, literal, kind, suffix):
    _, found, _ = _resolve_tree(TreeLocator(pointer="/x"), write_tree(tmp_path, literal, suffix))
    assert found is not None and found.native_type == kind


@pytest.mark.parametrize("literal", [".inf", "-.inf", ".nan"])
def test_a_non_finite_yaml_number_is_still_not_a_quantity_to_compare(tmp_path, literal):
    decision = MetricBackend().check(
        CLAIM, metric("3.20"), {"a": write_tree(tmp_path, literal, ".yaml")}
    )
    assert decision.reason is Reason.VALUE_NOT_NUMERIC


@pytest.mark.parametrize(
    ("literal", "reported"), [("1_000.5", "1000.5"), ("1:30.5", "90.5"), ("0x1F", "31")]
)
def test_a_yaml_number_in_a_form_only_yaml_has_is_read_as_its_value(tmp_path, literal, reported):
    path = write_tree(tmp_path, literal, ".yaml")
    assert MetricBackend().check(CLAIM, metric(reported), {"a": path}).outcome is Outcome.VERIFIED


@pytest.mark.parametrize("suffix", TREES)
def test_a_quoted_number_in_a_tree_is_still_the_text_it_holds(tmp_path, suffix):
    assert stored(write_tree(tmp_path, '"0.910"', suffix)) == "0.910"


@pytest.mark.parametrize(
    ("left", "right", "outcome"),
    [
        ("0.910", "0.914", Outcome.MISMATCH),
        ("0.91", "0.914", Outcome.VERIFIED),
        ("0.910", "0.9104", Outcome.VERIFIED),
    ],
)
def test_two_tree_files_correspond_at_the_coarser_precision_either_wrote(
    tmp_path, left, right, outcome
):
    one, two = tmp_path / "one.json", tmp_path / "two.json"
    one.write_text(f'{{"x": {left}}}')
    two.write_text(f'{{"x": {right}}}')
    evidence = CorrespondenceEvidence(
        name="n",
        sides=(
            CorrespondenceSide(name="one", artifact="one", locator=TreeLocator(pointer="/x")),
            CorrespondenceSide(name="two", artifact="two", locator=TreeLocator(pointer="/x")),
        ),
    )
    decision = CorrespondenceBackend().check(CLAIM, evidence, {"one": one, "two": two})
    assert decision.outcome is outcome
