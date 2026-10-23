"""A `reported` value against the sentence it stands for, and the precision it is compared at."""

from __future__ import annotations

import json
import pathlib

import pytest
from claims.cli import main
from claims.models import (
    ArtifactRef,
    Claim,
    ComparisonMode,
    Manifest,
    MetricEvidence,
    Outcome,
    QuoteEvidence,
    Warning_,
)
from claims.policy import PUBLICATION, REPORTED_SAID, STRICT, Severity
from claims.verify import verify

STORED = {"icc": 0.4213, "p": 0.0491, "rate": 0.0426, "auc": 0.712, "agreement": 0.92655}


@pytest.fixture
def results(tmp_path) -> pathlib.Path:
    (tmp_path / "out.json").write_text(json.dumps(STORED))
    (tmp_path / "paper.md").write_text("# Results\n\nThe ICC was 0.9913 (Table 2).\n")
    return tmp_path


def manifest(root: pathlib.Path, text: str, *evidence) -> Manifest:
    return Manifest(
        project="p",
        artifacts=(
            ArtifactRef(id="out", path=root / "out.json"),
            ArtifactRef(id="paper", path=root / "paper.md"),
        ),
        claims=(Claim(id="c", text=text, evidence=evidence),),
    )


def metric(reported: str, pointer: str, **kw) -> MetricEvidence:
    return MetricEvidence(artifact="out", name="m", reported=reported, pointer=pointer, **kw)


def noted(assessment) -> set[tuple[str, Severity]]:
    """The violations a policy grades from the notes on `reported`."""
    rules = {f"evidence.{w.value}" for w in REPORTED_SAID}
    return {(v.rule, v.severity) for v in assessment.violations if v.rule in rules}


def decision(found):
    (claim,) = found.claims
    return claim.decisions[0]


def test_a_reported_value_the_claim_and_the_paper_do_not_print_fails_under_strict(results):
    checked = verify(
        manifest(
            results,
            "The ICC was 0.9913",
            metric("0.4213", "/icc"),
            QuoteEvidence(artifact="paper", text="The ICC was 0.9913"),
        )
    )

    found = decision(checked)
    assert found.outcome is Outcome.VERIFIED
    assert Warning_.REPORTED_NOT_IN_CLAIM in found.warnings
    assert Warning_.REPORTED_NOT_IN_MANUSCRIPT in found.warnings
    assert noted(PUBLICATION.assess(checked)) == {
        ("evidence.reported_not_in_claim", Severity.WARNING),
        ("evidence.reported_not_in_manuscript", Severity.WARNING),
    }
    assert noted(STRICT.assess(checked)) == {
        ("evidence.reported_not_in_claim", Severity.ERROR),
        ("evidence.reported_not_in_manuscript", Severity.ERROR),
    }


def test_a_percentage_printed_from_a_stored_fraction_agrees(results):
    checked = verify(
        manifest(results, "agreement was 92.7 per cent", metric("0.92655", "/agreement"))
    )

    assert decision(checked).warnings == ()
    assert noted(STRICT.assess(checked)) == set()


def test_a_claim_printing_no_number_is_not_compared(results):
    checked = verify(manifest(results, "agreement is high", metric("0.92655", "/agreement")))

    assert Warning_.REPORTED_NOT_IN_CLAIM not in decision(checked).warnings


@pytest.mark.parametrize(
    ("text", "reported", "pointer", "conversion"),
    [("p was 0.0", "0.0", "/p", None), ("a rate of 4%", "4", "/rate", "percent")],
)
def test_a_coarse_printed_precision_is_noted(results, text, reported, pointer, conversion):
    evidence = metric(reported, pointer, **({"conversion": conversion} if conversion else {}))
    checked = verify(manifest(results, text, evidence))

    found = decision(checked)
    assert found.outcome is Outcome.VERIFIED
    assert Warning_.COARSE_PRECISION in found.warnings
    assert ("evidence.coarse_precision", Severity.ERROR) in noted(STRICT.assess(checked))


def test_a_mismatch_carries_no_precision_note(tmp_path):
    (tmp_path / "out.json").write_text(json.dumps({"total": 6, "p": 0.0491}))
    (tmp_path / "paper.md").write_text("")
    for text, reported, pointer in (("a total of 7", "7", "/total"), ("p = 0.3", "0.3", "/p")):
        found = decision(verify(manifest(tmp_path, text, metric(reported, pointer))))
        assert found.outcome is Outcome.MISMATCH
        assert Warning_.COARSE_PRECISION not in found.warnings
        assert Warning_.ROUNDING_CROSSES_THRESHOLD not in found.warnings


def test_rounding_across_the_significance_threshold_is_noted(tmp_path):
    (tmp_path / "out.json").write_text(json.dumps({"p": 0.0496}))
    (tmp_path / "paper.md").write_text("")
    checked = verify(manifest(tmp_path, "p = 0.05", metric("0.05", "/p")))

    assert Warning_.ROUNDING_CROSSES_THRESHOLD in decision(checked).warnings


def test_a_tolerance_large_against_the_value_is_noted(results):
    evidence = metric("0.95", "/auc", mode=ComparisonMode.ABSOLUTE, tolerance="0.5")
    checked = verify(manifest(results, "an AUC of 0.95", evidence))

    found = decision(checked)
    assert found.outcome is Outcome.VERIFIED
    assert Warning_.LOOSE_TOLERANCE in found.warnings
    assert noted(PUBLICATION.assess(checked)) == {("evidence.loose_tolerance", Severity.WARNING)}
    assert ("evidence.loose_tolerance", Severity.ERROR) in noted(STRICT.assess(checked))


def test_a_tight_tolerance_is_not_noted(results):
    evidence = metric("0.712", "/auc", mode=ComparisonMode.ABSOLUTE, tolerance="0.001")

    assert decision(verify(manifest(results, "an AUC of 0.712", evidence))).warnings == ()


def unbound_project(root: pathlib.Path) -> pathlib.Path:
    (root / "out.json").write_text(json.dumps(STORED))
    (root / "paper.md").write_text("The ICC was 0.4213. We also saw 17.5 and 33.25.\n")
    (root / "repro.yaml").write_text(
        "schema_version: repro/1\n"
        "project: p\n"
        "artifacts:\n"
        "- {id: out, path: out.json}\n"
        "- {id: paper, path: paper.md}\n"
        "claims:\n"
        "- id: c\n"
        "  text: The ICC was 0.4213.\n"
        "  evidence:\n"
        "  - {kind: metric, artifact: out, name: icc, reported: '0.4213', pointer: /icc}\n"
        "  - {kind: quote, artifact: paper, text: The ICC was 0.4213.}\n"
    )
    return root / "repro.yaml"


def test_unbound_numbers_warn_by_default_and_fail_past_a_declared_limit(tmp_path, capsys):
    path = str(unbound_project(tmp_path))

    assert main(["verify", path]) == 0
    out = capsys.readouterr().out
    assert "numbers.unbound" in out and "2 printed number(s)" in out

    assert main(["verify", path, "--max-unbound", "1"]) == 1
    assert main(["verify", path, "--max-unbound", "2"]) == 0
