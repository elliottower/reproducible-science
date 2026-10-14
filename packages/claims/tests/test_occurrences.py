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
from claims.cli import main
from claims.manifest import load
from claims.models import (
    CorrespondenceEvidence,
    ExtractionStatus,
    Outcome,
    Reason,
    Standing,
)
from claims.numbers import numbers
from claims.policy import PUBLICATION, STRICT, Severity
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
        "(8.35 as a percentage); abstract and measured an exact tie between 8.3 and 8.4; "
        "results and measured an exact tie between 8.3 and 8.4; abstract and results disagree"
    )


def test_every_tied_pair_is_recorded_with_its_sides(tmp_path):
    decision = only(project(tmp_path, [ABSTRACT, RESULTS, MEASURED]))
    assert [(paired.sides, paired.tie.lower, paired.tie.upper) for paired in decision.ties] == [
        (("abstract", "measured"), "8.3", "8.4"),
        (("results", "measured"), "8.3", "8.4"),
    ]
    assert decision.tie == decision.ties[0].tie, "`tie` stays the first, as with two sides"


def test_a_two_sided_decision_records_its_tie_as_before_and_no_ties(tmp_path):
    decision = only(project(tmp_path, [ABSTRACT, MEASURED]))
    assert decision.tie is not None
    assert (decision.tie.lower, decision.tie.upper) == ("8.3", "8.4")
    assert decision.ties == ()
    assert "ties" not in decision.model_dump(), "it serializes as before the field existed"
    assert decision.detail == (
        "accuracy: abstract 8.3, measured 0.0835 (8.35 as a percentage), "
        "an exact tie between 8.3 and 8.4"
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


def test_a_tolerance_holds_place_against_place_as_well_as_place_against_file(tmp_path):
    """8.30 and 8.36 are each within 0.05 of a stored 8.33 and 0.06 from each other."""
    sides = [
        {
            "name": "a",
            "artifact": "paper",
            "locator": {"kind": "prose", "before": "a", "after": "x"},
        },
        {
            "name": "b",
            "artifact": "paper",
            "locator": {"kind": "prose", "before": "b", "after": "x"},
        },
        {
            "name": "file",
            "artifact": "results",
            "locator": {"kind": "tree", "pointer": "/accuracy"},
        },
    ]
    decision = only(
        project(
            tmp_path,
            sides,
            paper="a 8.30 x. b 8.36 x.",
            stored={"accuracy": 8.33},
            mode="absolute",
            tolerance="0.05",
        )
    )
    assert decision.outcome is Outcome.MISMATCH
    assert decision.disagreements == (("a", "b"),)


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
    assert "declare `form: grouped` on the locator to read it as 1062" in decision.detail


@pytest.mark.parametrize("printed", ["12,13", "1,0620"])
def test_commas_that_do_not_group_in_threes_are_not_read_as_grouping(tmp_path, printed):
    decision = only(
        project(tmp_path, [ENROLLED, CELL], paper=GROUPED_PAPER.replace("1,062", printed))
    )
    assert decision.reason is Reason.VALUE_NOT_NUMERIC
    assert "form: grouped" not in decision.detail, "these are not grouped digits"


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


# -- one anchor pair, several occurrences ------------------------------------------------------


def stated(tmp_path, paper, reported="8.3", form="decimal"):
    """The decision for one value read at one anchor pair that may occur more than once."""
    (tmp_path / "paper.md").write_text(paper)
    manifest = {
        "schema_version": "repro/1",
        "project": "t",
        "artifacts": [{"id": "paper", "path": "paper.md"}],
        "claims": [
            {
                "id": "c",
                "text": "t",
                "evidence": [
                    {
                        "kind": "value",
                        "artifact": "paper",
                        "name": "accuracy",
                        "reported": reported,
                        "locator": {
                            "kind": "prose",
                            "before": "an accuracy of",
                            "after": "%",
                            "form": form,
                        },
                    }
                ],
            }
        ],
    }
    path = tmp_path / "repro.yaml"
    path.write_text(yaml.safe_dump(manifest, sort_keys=False))
    return only(path)


TWICE = (
    "Abstract. The classifier reached an accuracy of 8.3% on the held-out split.\n"
    "\n"
    "Results. After tuning it reached an accuracy of {}% on the same split.\n"
)


def test_an_ambiguous_anchor_says_where_each_value_sits(tmp_path):
    decision = stated(tmp_path, TWICE.format("8.4"))
    assert decision.reason is Reason.PASSAGE_AMBIGUOUS
    assert decision.outcome is Outcome.NOT_FOUND
    assert decision.detail == (
        '"an accuracy of" ... "%" selects 2 different values in paper.md: '
        '8.3 at line 1 ("reached an accuracy of 8.3% on the held-out split."), '
        '8.4 at line 3 ("reached an accuracy of 8.4% on the same split.")'
    )


@pytest.mark.parametrize("second", ["8.3", "8.30"])
def test_occurrences_equal_as_numbers_are_one_value(tmp_path, second):
    decision = stated(tmp_path, TWICE.format(second))
    assert decision.outcome is Outcome.VERIFIED
    assert decision.extracted == "8.3", "the value is what the first place prints"


SPELLED = "Abstract: an accuracy of 8.3 x.\n\nTable: an accuracy of 8.30 x.\n"
SPELLED_SIDE = {
    "name": "abstract",
    "artifact": "paper",
    "locator": {"kind": "prose", "before": "an accuracy of", "after": "x"},
}
FILE = {"name": "file", "artifact": "results", "locator": {"kind": "tree", "pointer": "/accuracy"}}


def test_each_spelling_of_one_number_is_compared_at_its_own_precision(tmp_path):
    """8.3 against a stored 8.35 is a tie; 8.30 against it is a mismatch, at its own line."""
    decision = only(
        project(tmp_path, [SPELLED_SIDE, FILE], paper=SPELLED, stored={"accuracy": 8.35})
    )
    assert decision.outcome is Outcome.MISMATCH
    assert decision.disagreements == (("abstract at line 3", "file"),)
    assert [paired.sides for paired in decision.ties] == [("abstract at line 1", "file")]
    assert "abstract at line 3 (paper) 8.30" in decision.detail
    assert decision.sides[0].extracted == "8.3", "the abstract is not recorded as printing 8.30"


def test_one_number_printed_to_two_precisions_agrees_with_a_file_both_round_to(tmp_path):
    decision = only(
        project(tmp_path, [SPELLED_SIDE, FILE], paper=SPELLED, stored={"accuracy": 8.301})
    )
    assert decision.outcome is Outcome.VERIFIED


@pytest.mark.parametrize("second", ["8.34", "8.4", "-8.3"])
def test_occurrences_that_are_different_numbers_stay_ambiguous(tmp_path, second):
    assert stated(tmp_path, TWICE.format(second)).reason is Reason.PASSAGE_AMBIGUOUS


def test_a_grouped_and_an_ungrouped_spelling_are_one_value_under_grouped(tmp_path):
    paper = TWICE.replace("8.3%", "1,062%").format("1062")
    assert stated(tmp_path, paper, reported="1062", form="grouped").outcome is Outcome.VERIFIED
    assert stated(tmp_path, paper, reported="1062").reason is Reason.PASSAGE_AMBIGUOUS


def test_a_word_and_a_numeral_are_one_value_under_cardinal_word(tmp_path):
    paper = TWICE.replace("8.3%", "eighteen%").format("18")
    decision = stated(tmp_path, paper, reported="18", form="cardinal_word")
    assert decision.outcome is Outcome.VERIFIED


# -- two sides reading one place ---------------------------------------------------------------

ONE_PLACE = "Abstract: an accuracy of 8.4 x.\n\nResults: acc2 8.3 x.\n"


@pytest.mark.parametrize(
    "other",
    [
        {"kind": "prose", "before": "an accuracy of", "after": "x", "form": "grouped"},
        {"kind": "prose", "before": "an accuracy of", "after": "x", "form": "cardinal_word"},
        {"kind": "prose", "before": "accuracy of", "after": "x"},
    ],
)
def test_two_sides_reading_one_place_are_not_a_pass(tmp_path, other):
    sides = [SPELLED_SIDE, {"name": "results", "artifact": "paper", "locator": other}]
    decision = only(project(tmp_path, sides, paper=ONE_PLACE, stored={"accuracy": 8.3}))
    assert decision.outcome is Outcome.UNCHECKED
    assert decision.reason is Reason.SIDES_READ_ONE_PLACE
    assert decision.detail.startswith(
        "sides abstract and results read the same place in paper, 8.4 at line 1"
    )


def test_two_sides_reading_two_places_in_one_document_are_compared(tmp_path):
    other = {"kind": "prose", "before": "acc2", "after": "x"}
    sides = [SPELLED_SIDE, {"name": "results", "artifact": "paper", "locator": other}]
    decision = only(project(tmp_path, sides, paper=ONE_PLACE, stored={"accuracy": 8.3}))
    assert decision.outcome is Outcome.MISMATCH


# -- what a reader sees ------------------------------------------------------------------------


def test_why_names_each_tied_pair_and_each_disagreeing_pair(tmp_path, capsys):
    path = project(tmp_path, [ABSTRACT, RESULTS, MEASURED])
    assert main(["why", "accuracy", str(path)]) == 0
    out = capsys.readouterr().out
    assert "abstract and measured: an exact tie between 8.3 and 8.4" in out
    assert "results and measured: an exact tie between 8.3 and 8.4" in out
    assert "abstract and results disagree" in out


def test_a_full_stop_closing_a_sentence_is_not_part_of_the_number(tmp_path):
    paper = "acc 8.3 y. acc 8.3. y"
    side = {"name": "p", "artifact": "paper", "locator": {"kind": "prose", "before": "acc"}}
    decision = only(project(tmp_path, [side, FILE], paper=paper, stored={"accuracy": 8.3}))
    assert decision.outcome is Outcome.VERIFIED
    assert decision.sides[0].extracted == "8.3"


def test_a_grouped_value_is_shown_as_printed(tmp_path):
    side = {
        "name": "n",
        "artifact": "paper",
        "locator": {"kind": "prose", "before": "n", "after": "x", "form": "grouped"},
    }
    paper = "n 1,062e3 x."
    decision = only(project(tmp_path, [side, FILE], paper=paper, stored={"accuracy": 1062000}))
    assert decision.outcome is Outcome.VERIFIED
    assert decision.detail == "accuracy: n 1,062e3, file 1062000"


# -- one file under two ids --------------------------------------------------------------------


def aliased(tmp_path, second_path="paper.md", second_text=None):
    """Two artifact ids, the second naming `second_path`, with one locator on each."""
    (tmp_path / "paper.md").write_text(ONE_PLACE)
    if second_text is not None:
        (tmp_path / second_path).write_text(second_text)
    locator = {"kind": "prose", "before": "an accuracy of", "after": "x"}
    manifest = {
        "schema_version": "repro/1",
        "project": "t",
        "artifacts": [
            {"id": "paper", "path": "paper.md"},
            {"id": "paper_again", "path": second_path},
        ],
        "claims": [
            {
                "id": "c",
                "text": "t",
                "evidence": [
                    {
                        "kind": "correspondence",
                        "name": "c",
                        "sides": [
                            {"name": "abstract", "artifact": "paper", "locator": locator},
                            {"name": "results", "artifact": "paper_again", "locator": locator},
                        ],
                    }
                ],
            }
        ],
    }
    path = tmp_path / "repro.yaml"
    path.write_text(yaml.safe_dump(manifest, sort_keys=False))
    return verify(load(path))


@pytest.mark.parametrize(
    ("second_path", "second_text"),
    [("paper.md", None), ("./sub/../paper.md", None), ("copy.md", ONE_PLACE)],
)
def test_one_file_under_two_ids_is_not_compared_with_itself(tmp_path, second_path, second_text):
    (tmp_path / "sub").mkdir()
    report = aliased(tmp_path, second_path, second_text)
    decision = report.decisions[0]
    assert decision.outcome is Outcome.UNCHECKED
    assert decision.reason is Reason.SIDES_READ_ONE_PLACE
    assert "in paper and paper_again, which are one file, 8.4 at line 1" in decision.detail


@pytest.mark.parametrize(
    ("second_path", "second_text", "said"),
    [
        ("paper.md", None, "paper and paper_again name the same file"),
        ("copy.md", ONE_PLACE, "paper and paper_again hold the same bytes"),
    ],
)
def test_two_ids_for_one_file_are_a_policy_finding_naming_both(
    tmp_path, second_path, second_text, said
):
    report = aliased(tmp_path, second_path, second_text)
    found = [v for v in PUBLICATION.assess(report).violations if v.rule == "artifact.alias"]
    assert len(found) == 1, "one finding per pair"
    assert found[0].severity is Severity.WARNING
    assert found[0].subject == "paper"
    assert found[0].detail.startswith(said)
    assert [v.severity for v in STRICT.assess(report).violations if v.rule == "artifact.alias"] == [
        Severity.ERROR
    ]


def test_two_files_with_different_bytes_are_neither_aliased_nor_refused(tmp_path):
    report = aliased(tmp_path, "copy.md", ONE_PLACE.replace("8.4", "8.5"))
    assert not [v for v in PUBLICATION.assess(report).violations if v.rule == "artifact.alias"]
    assert report.decisions[0].outcome is Outcome.MISMATCH
    assert "same_path_as" not in report.artifacts[0].model_dump()


# -- one side matching more places than the other ----------------------------------------------

PARTLY = "Title\nAbstract: the accuracy was 8.4 x.\n\n\n\nTable\nResults: the accuracy was 8.3 x.\n"


def test_a_side_whose_anchors_also_match_the_other_sides_place_is_refused_and_says_where(
    tmp_path,
):
    sides = [
        {
            "name": "abstract",
            "artifact": "paper",
            "locator": {"kind": "prose", "before": "the accuracy was", "after": "x"},
        },
        {
            "name": "results",
            "artifact": "paper",
            "locator": {"kind": "prose", "before": "Results: the accuracy was", "after": "x"},
        },
    ]
    paper = PARTLY.replace("8.4", "8.3")
    decision = only(project(tmp_path, sides, paper=paper, stored={"accuracy": 8.3}))
    assert decision.outcome is Outcome.UNCHECKED, "never a pass on a place compared with itself"
    assert decision.reason is Reason.SIDES_READ_ONE_PLACE
    assert decision.detail == (
        "sides abstract and results read the same place in paper: results reads line 7, "
        "which abstract's anchors also match at line 7; abstract also matches line 2. "
        "Narrow abstract's anchors so they select only the place abstract is meant for"
    )
