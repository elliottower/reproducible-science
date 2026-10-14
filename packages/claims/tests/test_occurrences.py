"""One number printed in several places of a manuscript, and the places that must agree.

An abstract printing 8.3% while the results print 8.4% is a manuscript contradicting itself.
Each place checked against the stored 0.0835 alone agrees with it, since 8.35 is an exact tie
at one decimal, so a check that compares every place with the file and none with each other
passes a manuscript that states two values. A `correspondence` with a side per place compares
every pair.
"""

from __future__ import annotations

import itertools
import json

import pytest
import yaml
from claims.manifest import load
from claims.models import (
    CorrespondenceEvidence,
    ExtractionStatus,
    Outcome,
    Reason,
    Standing,
)
from claims.numbers import numbers
from claims.verify import verify
from pydantic import ValidationError

PAPER = (
    "Abstract. The classifier reached an accuracy of 8.3% on the held-out split.\n\n"
    "Results. On the held-out split the accuracy was 8.4% after tuning.\n"
)

ABSTRACT = {
    "name": "abstract",
    "artifact": "paper",
    "locator": {"kind": "prose", "before": "an accuracy of", "after": "%"},
}
RESULTS = {
    "name": "results",
    "artifact": "paper",
    "locator": {"kind": "prose", "before": "the accuracy was", "after": "%"},
}
MEASURED = {
    "name": "measured",
    "artifact": "results",
    "locator": {"kind": "tree", "pointer": "/accuracy"},
    "conversion": "percent",
}


def project(tmp_path, sides, paper=PAPER, stored=None, **kw):
    """A manifest with one claim whose correspondence has the given sides."""
    (tmp_path / "paper.md").write_text(paper)
    (tmp_path / "results.json").write_text(json.dumps(stored or {"accuracy": 0.0835}))
    manifest = {
        "schema_version": "repro/1",
        "project": "t",
        "artifacts": [
            {"id": "paper", "path": "paper.md"},
            {"id": "results", "path": "results.json"},
        ],
        "claims": [
            {
                "id": "accuracy",
                "text": "The classifier reaches 8.3% accuracy.",
                "evidence": [{"kind": "correspondence", "name": "accuracy", "sides": sides, **kw}],
            }
        ],
    }
    path = tmp_path / "repro.yaml"
    path.write_text(yaml.safe_dump(manifest, sort_keys=False))
    return path


def only(path):
    return verify(load(path)).decisions[0]


# -- the defect --------------------------------------------------------------------------------


def test_each_place_agrees_with_the_file_alone(tmp_path):
    """The gap stated as a fact: two places checked one at a time against the file both pass."""
    assert only(project(tmp_path, [ABSTRACT, MEASURED])).outcome is Outcome.VERIFIED
    assert only(project(tmp_path, [RESULTS, MEASURED])).outcome is Outcome.VERIFIED


def test_two_places_printing_different_values_fail_and_the_report_names_both(tmp_path):
    decision = only(project(tmp_path, [ABSTRACT, RESULTS, MEASURED]))
    assert decision.outcome is Outcome.MISMATCH
    assert decision.reason is Reason.VALUE_MISMATCH
    assert "abstract (paper) 8.3" in decision.detail
    assert "results (paper) 8.4" in decision.detail
    assert "abstract and results disagree" in decision.detail
    assert "measured disagree" not in decision.detail, "each place agrees with the file"
    assert [(s.name, s.extracted) for s in decision.sides] == [
        ("abstract", "8.3"),
        ("results", "8.4"),
        ("measured", "0.0835"),
    ]


def test_the_report_reads_as_the_specification_shows_it(tmp_path):
    decision = only(project(tmp_path, [ABSTRACT, RESULTS, MEASURED]))
    assert decision.detail == (
        "accuracy: abstract (paper) 8.3, results (paper) 8.4, measured (results) 0.0835 "
        "(8.35 as a percentage), an exact tie between 8.3 and 8.4; abstract and results disagree"
    )


def test_places_compared_with_no_file_still_disagree(tmp_path):
    decision = only(project(tmp_path, [ABSTRACT, RESULTS]))
    assert decision.outcome is Outcome.MISMATCH
    assert decision.detail == "accuracy: abstract 8.3, results 8.4"


def test_the_same_value_in_every_place_passes(tmp_path):
    paper = PAPER.replace("8.4%", "8.3%")
    decision = only(project(tmp_path, [ABSTRACT, RESULTS, MEASURED], paper=paper))
    assert decision.outcome is Outcome.VERIFIED
    assert "disagree" not in decision.detail


def test_the_outcome_does_not_depend_on_the_order_of_the_sides(tmp_path):
    outcomes = {
        only(project(tmp_path, list(order))).outcome
        for order in itertools.permutations([ABSTRACT, RESULTS, MEASURED])
    }
    assert outcomes == {Outcome.MISMATCH}


def test_a_declared_tolerance_applies_to_every_pair(tmp_path):
    sides = [ABSTRACT, RESULTS, MEASURED]
    assert only(project(tmp_path, sides, mode="absolute", tolerance="0.1")).outcome is (
        Outcome.VERIFIED
    )
    assert only(project(tmp_path, sides, mode="absolute", tolerance="0.05")).outcome is (
        Outcome.MISMATCH
    )


def test_a_place_that_does_not_extract_is_not_a_disagreement(tmp_path):
    paper = PAPER.replace("the accuracy was", "accuracy came to")
    decision = only(project(tmp_path, [ABSTRACT, RESULTS, MEASURED], paper=paper))
    assert decision.extraction is ExtractionStatus.ABSENT
    assert decision.outcome is Outcome.NOT_FOUND
    assert decision.reason is Reason.PASSAGE_ABSENT
    assert "results (paper)" in decision.detail


# -- equivalent forms --------------------------------------------------------------------------

TABLE = "| model | accuracy |\n| tuned | 0.083 |\n"


@pytest.mark.parametrize(
    ("cell", "outcome"), [("0.083", Outcome.VERIFIED), ("0.084", Outcome.MISMATCH)]
)
def test_a_percentage_and_a_fraction_are_compared_under_a_declared_conversion(
    tmp_path, cell, outcome
):
    """8.3% in prose and 0.083 in a table are one value once the prose side is a fraction."""
    paper = "Abstract. We report an accuracy of 8.3% here.\n\n" + TABLE.replace("0.083", cell)
    sides = [
        {**ABSTRACT, "conversion": "fraction"},
        {
            "name": "table",
            "artifact": "paper",
            "locator": {"kind": "prose", "before": "| tuned |", "after": "|"},
        },
        {"name": "measured", "artifact": "results", "locator": MEASURED["locator"]},
    ]
    decision = only(project(tmp_path, sides, paper=paper, stored={"accuracy": 0.0834}))
    assert decision.outcome is outcome


GROUPED_PAPER = "We enrolled 1,062 participants.\n\n| arm | n |\n| all | 1062 |\n"
ENROLLED = {
    "name": "abstract",
    "artifact": "paper",
    "locator": {
        "kind": "prose",
        "before": "We enrolled",
        "after": "participants",
        "form": "grouped",
    },
}
CELL = {
    "name": "table",
    "artifact": "paper",
    "locator": {"kind": "prose", "before": "| all |", "after": "|"},
}


@pytest.mark.parametrize(
    ("printed", "outcome"), [("1,062", Outcome.VERIFIED), ("1,063", Outcome.MISMATCH)]
)
def test_a_grouped_number_is_compared_as_the_number_without_its_commas(tmp_path, printed, outcome):
    paper = GROUPED_PAPER.replace("1,062", printed)
    decision = only(project(tmp_path, [ENROLLED, CELL], paper=paper))
    assert decision.outcome is outcome
    assert decision.sides[0].extracted == printed.replace(",", "")


def test_a_grouped_number_is_not_numeric_unless_the_locator_asks_for_grouping(tmp_path):
    plain = {**ENROLLED, "locator": {k: v for k, v in ENROLLED["locator"].items() if k != "form"}}
    decision = only(project(tmp_path, [plain, CELL], paper=GROUPED_PAPER))
    assert decision.reason is Reason.VALUE_NOT_NUMERIC
    assert decision.outcome is Outcome.NOT_FOUND


@pytest.mark.parametrize("printed", ["12,13", "1,0620"])
def test_commas_that_do_not_group_in_threes_are_not_read_as_grouping(tmp_path, printed):
    decision = only(
        project(tmp_path, [ENROLLED, CELL], paper=GROUPED_PAPER.replace("1,062", printed))
    )
    assert decision.reason is Reason.VALUE_NOT_NUMERIC


# -- what the manifest accepts -----------------------------------------------------------------


def test_one_side_is_refused():
    with pytest.raises(ValidationError):
        CorrespondenceEvidence.model_validate({"name": "n", "sides": [ABSTRACT]})


def test_two_of_several_sides_sharing_a_name_are_refused():
    with pytest.raises(ValidationError, match="which held what"):
        CorrespondenceEvidence.model_validate(
            {"name": "n", "sides": [ABSTRACT, MEASURED, {**RESULTS, "name": "abstract"}]}
        )


def test_two_of_several_sides_addressing_one_value_are_refused():
    with pytest.raises(ValidationError, match="agrees with itself"):
        CorrespondenceEvidence.model_validate(
            {"name": "n", "sides": [ABSTRACT, MEASURED, {**ABSTRACT, "name": "again"}]}
        )


# -- the manuscript's numbers ------------------------------------------------------------------


def test_every_place_binds_the_number_it_prints(tmp_path):
    report = numbers(load(project(tmp_path, [ABSTRACT, RESULTS, MEASURED])))
    printed = {n.value: n for n in report.texts[0].numbers}
    for value in ("8.3", "8.4"):
        assert printed[value].standing is Standing.BOUND
        assert printed[value].claims == ("accuracy",)
