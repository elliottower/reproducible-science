"""Assertions whose two sides are both artifacts, and the prose locator that makes one.

Every other kind compares an artifact against a literal in the manifest. Where both sides are
artifacts -- a sentence about the code, and a count of the code -- writing one of them into the
manifest creates a third copy that nothing checks. The tests here are about what that costs and
what the engine must refuse to conclude.
"""

from __future__ import annotations

import decimal
import importlib
import json

import pytest
import yaml
from claims.manifest import load
from claims.models import (
    ComparisonStatus,
    CorrespondenceEvidence,
    CorrespondenceSide,
    Digest,
    ExtractionStatus,
    NumberForm,
    Outcome,
    ProseLocator,
    Reason,
    TreeLocator,
    Validity,
)
from claims.toolchain import UNKNOWN
from claims.verify import _exponent, verify
from pydantic import ValidationError

DOC = "The conformance suite holds eighteen fixtures, each with canonical expected JSON.\n"
COUNTS = {"fixtures": 19}


def project(tmp_path, doc=DOC, counts=None, sides=None, **kw):
    """A manifest with one correspondence over a document and a count."""
    (tmp_path / "doc.md").write_text(doc)
    (tmp_path / "counts.json").write_text(json.dumps(counts if counts is not None else COUNTS))
    manifest = {
        "schema_version": "repro/1",
        "project": "t",
        "artifacts": [
            {"id": "doc", "path": "doc.md"},
            {"id": "counts", "path": "counts.json"},
        ],
        "claims": [
            {
                "id": "c",
                "text": "t",
                "evidence": [
                    {
                        "kind": "correspondence",
                        "name": "fixture-count",
                        "sides": sides
                        or [
                            {
                                "name": "stated",
                                "artifact": "doc",
                                "locator": {
                                    "kind": "prose",
                                    "before": "suite holds",
                                    "after": "fixtures",
                                    "form": "cardinal_word",
                                },
                            },
                            {
                                "name": "measured",
                                "artifact": "counts",
                                "locator": {"kind": "tree", "pointer": "/fixtures"},
                            },
                        ],
                        **kw,
                    }
                ],
            }
        ],
    }
    path = tmp_path / "repro.yaml"
    path.write_text(yaml.safe_dump(manifest, sort_keys=False))
    return path


def only(path):
    return verify(load(path)).decisions[0]


# -- the defect the kind exists to remove ---------------------------------------------------


def test_neither_value_appears_in_the_manifest(tmp_path):
    """The reason for the kind, stated as a property of what it produces.

    Expressing this claim with a `metric` requires writing `18` into the manifest, and the
    self-audit that motivated this variant showed that rewriting every such field to the
    measured value passes the whole manifest while the document stays wrong. There is nothing
    here to rewrite.
    """
    text = project(tmp_path).read_text()
    for number in ("18", "19", "eighteen", "nineteen"):
        assert number not in text, f"{number!r} is transcribed into the manifest"


def test_the_disagreement_is_settled_only_by_editing_a_document(tmp_path):
    path = project(tmp_path)
    assert only(path).outcome is Outcome.MISMATCH
    (tmp_path / "doc.md").write_text(DOC.replace("eighteen", "nineteen"))
    assert only(path).outcome is Outcome.VERIFIED


def test_a_mismatch_reports_both_values_and_names_neither_as_wrong(tmp_path):
    decision = only(project(tmp_path))
    assert decision.reason is Reason.VALUE_MISMATCH
    assert "18" in decision.detail and "19" in decision.detail
    assert decision.artifact_id == "", "naming one artifact would rank a side"
    assert [(s.name, s.extracted) for s in decision.sides] == [("stated", "18"), ("measured", "19")]


def test_the_outcome_does_not_depend_on_the_order_of_the_sides(tmp_path):
    forward = only(project(tmp_path))
    swapped = only(
        project(
            tmp_path,
            sides=[
                {
                    "name": "measured",
                    "artifact": "counts",
                    "locator": {"kind": "tree", "pointer": "/fixtures"},
                },
                {
                    "name": "stated",
                    "artifact": "doc",
                    "locator": {
                        "kind": "prose",
                        "before": "suite holds",
                        "after": "fixtures",
                        "form": "cardinal_word",
                    },
                },
            ],
        )
    )
    assert forward.outcome is swapped.outcome
    assert forward.comparison is swapped.comparison


# -- two extractions, one comparison --------------------------------------------------------


def test_a_side_that_does_not_extract_is_not_a_disagreement(tmp_path):
    """Silence is not contradiction, with two sides instead of one.

    A count file holding no such key does not assert that the document's number is wrong. The
    comparison never happened, and reporting `mismatch` would manufacture a finding out of a
    gap.
    """
    decision = only(project(tmp_path, counts={"other": 19}))
    assert decision.extraction is ExtractionStatus.ABSENT
    assert decision.comparison is ComparisonStatus.NOT_APPLICABLE
    assert decision.outcome is Outcome.NOT_FOUND
    assert decision.reason is Reason.POINTER_ABSENT


def test_the_failing_side_is_named_and_keeps_its_own_reason(tmp_path):
    decision = only(project(tmp_path, doc="A document stating nothing countable.\n"))
    assert decision.reason is Reason.PASSAGE_ABSENT
    assert "stated" in decision.detail and "doc" in decision.detail


def test_the_side_that_did_extract_still_records_what_it_read(tmp_path):
    decision = only(project(tmp_path, counts={"other": 19}))
    read = {s.name: s.extracted for s in decision.sides}
    assert read == {"stated": "18", "measured": None}


def test_a_decision_binds_the_locator_of_each_side(tmp_path):
    decision = only(project(tmp_path))
    digests = [s.locator_digest for s in decision.sides]
    assert all(digests) and len(set(digests)) == 2
    moved = only(
        project(
            tmp_path,
            sides=[
                {
                    "name": "stated",
                    "artifact": "doc",
                    "locator": {
                        "kind": "prose",
                        "before": "holds",
                        "after": "fixtures",
                        "form": "cardinal_word",
                    },
                },
                {
                    "name": "measured",
                    "artifact": "counts",
                    "locator": {"kind": "tree", "pointer": "/fixtures"},
                },
            ],
        )
    )
    assert moved.sides[0].locator_digest != digests[0], (
        "an anchor edited after the fact must change the record"
    )


def test_a_decision_is_no_more_authoritative_than_the_weaker_of_its_two_artifacts(tmp_path):
    path = project(tmp_path)
    manifest = yaml.safe_load(path.read_text())
    manifest["artifacts"][0]["digest"] = {"algorithm": "sha256", "value": "0" * 64}
    path.write_text(yaml.safe_dump(manifest, sort_keys=False))
    decision = only(path)
    assert decision.validity is Validity.BROKEN_PIN
    assert {s.validity for s in decision.sides} == {
        Validity.BROKEN_PIN,
        Validity.UNPINNED_ARTIFACT,
    }


# -- comparing two extracted values ---------------------------------------------------------


@pytest.mark.parametrize(
    ("stated_text", "measured", "outcome"),
    [
        ("3.2", 3.2004, Outcome.VERIFIED),
        ("3.2", 3.9, Outcome.MISMATCH),
        ("3.2000", 3.2004, Outcome.MISMATCH),
        ("0.65", 0.6478999999999999, Outcome.VERIFIED),
    ],
)
def test_printed_precision_compares_at_the_coarser_of_the_two(
    tmp_path, stated_text, measured, outcome
):
    """Neither side is the reference, so the looser precision governs both.

    A sentence printing one decimal is not contradicted by a file holding four; a sentence
    printing four is.
    """
    path = project(
        tmp_path,
        doc=f"Improvement reached {stated_text} percentage points.\n",
        counts={"fixtures": measured},
        sides=[
            {
                "name": "stated",
                "artifact": "doc",
                "locator": {
                    "kind": "prose",
                    "before": "Improvement reached",
                    "after": "percentage points",
                },
            },
            {
                "name": "measured",
                "artifact": "counts",
                "locator": {"kind": "tree", "pointer": "/fixtures"},
            },
        ],
    )
    assert only(path).outcome is outcome


def test_two_sides_addressing_one_value_are_refused(tmp_path):
    """An assertion that agrees with itself whatever the file holds is not an assertion."""
    side = {"name": "a", "artifact": "counts", "locator": {"kind": "tree", "pointer": "/fixtures"}}
    with pytest.raises(ValidationError, match="agrees with itself"):
        CorrespondenceEvidence.model_validate({"name": "n", "sides": [side, {**side, "name": "b"}]})


def test_a_relative_tolerance_is_refused_for_want_of_a_reference(tmp_path):
    sides = [
        {"name": "a", "artifact": "doc", "locator": {"kind": "prose", "before": "holds"}},
        {"name": "b", "artifact": "counts", "locator": {"kind": "tree", "pointer": "/fixtures"}},
    ]
    with pytest.raises(ValidationError, match="neither side is the reference"):
        CorrespondenceEvidence.model_validate(
            {"name": "n", "sides": sides, "mode": "relative", "tolerance": "0.01"}
        )


def test_both_sides_must_be_distinguishable_in_a_report():
    sides = [
        {"name": "same", "artifact": "doc", "locator": {"kind": "prose", "before": "holds"}},
        {"name": "same", "artifact": "counts", "locator": {"kind": "tree", "pointer": "/f"}},
    ]
    with pytest.raises(ValidationError, match="which held what"):
        CorrespondenceEvidence.model_validate({"name": "n", "sides": sides})


# -- locating a value in prose --------------------------------------------------------------


def test_a_spelled_out_number_is_refused_until_the_locator_asks_for_it(tmp_path):
    """Reading `eighteen` as 18 is a semantic decision, and the manifest has to make it.

    Refusing without saying why would send an author looking for a broken anchor, so the
    refusal carries its own reason rather than reporting that no number was found.
    """
    guess = {
        "name": "s",
        "artifact": "doc",
        "locator": {"kind": "prose", "before": "suite holds", "after": "fixtures"},
    }
    measured = {
        "name": "m",
        "artifact": "counts",
        "locator": {"kind": "tree", "pointer": "/fixtures"},
    }
    decision = only(project(tmp_path, sides=[guess, measured]))
    assert decision.reason is Reason.NUMBER_AS_WORD
    assert decision.outcome is Outcome.NOT_FOUND
    assert "cardinal_word" in decision.detail, "the refusal has to say what would lift it"


def test_the_declared_conversion_is_recorded_in_the_decision(tmp_path):
    decision = only(project(tmp_path, doc=DOC.replace("eighteen", "nineteen")))
    assert '"nineteen"' in decision.detail or decision.sides[0].extracted == "19"


def test_a_number_stated_twice_in_one_document_is_not_ambiguous(tmp_path):
    """Repetition is normal prose. Two *different* values between one pair of anchors is not.

    A `quote` is satisfied by any occurrence, so a count stated in an abstract and again in a
    section stays verified when one of the two is edited. A value locator that resolved to the
    first match would inherit that. This resolves only when the occurrences agree.
    """
    twice = DOC + "As stated above, the suite holds eighteen fixtures in total.\n"
    assert only(project(tmp_path, doc=twice)).sides[0].extracted == "18"

    disagreeing = DOC + "Elsewhere the suite holds twenty fixtures.\n"
    decision = only(project(tmp_path, doc=disagreeing))
    assert decision.reason is Reason.PASSAGE_AMBIGUOUS
    assert decision.outcome is Outcome.NOT_FOUND


def test_an_anchor_matches_across_a_line_break_in_the_document(tmp_path):
    wrapped = "The conformance suite\nholds eighteen fixtures.\n"
    assert only(project(tmp_path, doc=wrapped)).sides[0].extracted == "18"


def test_the_locator_carries_its_form_into_its_digest():
    """Two locators differing only in what they authorize are two locators."""
    plain = ProseLocator(before="holds", after="fixtures")
    asking = ProseLocator(before="holds", after="fixtures", form=NumberForm.CARDINAL_WORD)
    assert plain.digest != asking.digest


def test_a_prose_locator_addresses_a_value_without_a_correspondence(tmp_path):
    """The locator is useful on its own: it checks a number transcribed into the manifest.

    That is a smaller thing than a correspondence and a different one -- it establishes that
    the manifest agrees with the document, and says nothing about the code.
    """
    (tmp_path / "doc.md").write_text(DOC)
    manifest = {
        "schema_version": "repro/1",
        "project": "t",
        "artifacts": [{"id": "doc", "path": "doc.md"}],
        "claims": [
            {
                "id": "c",
                "text": "t",
                "evidence": [
                    {
                        "kind": "value",
                        "artifact": "doc",
                        "name": "m",
                        "reported": "18",
                        "locator": {
                            "kind": "prose",
                            "before": "suite holds",
                            "after": "fixtures",
                            "form": "cardinal_word",
                        },
                    }
                ],
            }
        ],
    }
    path = tmp_path / "repro.yaml"
    path.write_text(yaml.safe_dump(manifest, sort_keys=False))
    assert only(path).outcome is Outcome.VERIFIED


PRINTED = (
    "## $north\n"
    "##\n"
    "## |   N (sites)| Slope|    se|   pval|\n"
    "## |-----------:|-----:|-----:|------:|\n"
    "## |           7| 0.318| 0.107| 0.0271|\n"
    "##\n"
    "## $south\n"
    "##\n"
    "## |   N (sites)| Slope|    se|   pval|\n"
    "## |-----------:|-----:|-----:|------:|\n"
    "## |           5| 0.212|   n/a| 0.0412|\n"
)


def printed(tmp_path, reported, before, after="", doc=PRINTED):
    """The decision for one value read out of printed text by a prose locator."""
    (tmp_path / "output.txt").write_text(doc)
    manifest = {
        "schema_version": "repro/1",
        "project": "t",
        "artifacts": [{"id": "out", "path": "output.txt"}],
        "claims": [
            {
                "id": "c",
                "text": "t",
                "evidence": [
                    {
                        "kind": "value",
                        "artifact": "out",
                        "name": "m",
                        "reported": reported,
                        "locator": {"kind": "prose", "before": before, "after": after},
                    }
                ],
            }
        ],
    }
    path = tmp_path / "repro.yaml"
    path.write_text(yaml.safe_dump(manifest, sort_keys=False))
    return only(path)


@pytest.mark.parametrize(
    ("reported", "before"),
    [
        ("0.318", "| 7|"),
        ("0.107", "| 7| 0.318|"),
        ("0.0271", "$north ## ## | N (sites)| Slope| se| pval| ## | 7| 0.318| 0.107|"),
        ("0.212", "| 5|"),
    ],
)
def test_a_cell_of_a_printed_table_is_bound_by_its_leading_cells_and_its_divider(
    tmp_path, reported, before
):
    doc = PRINTED.replace("## |-----------:|-----:|-----:|------:|\n", "")
    decision = printed(tmp_path, reported, before, "|", doc=doc)
    assert decision.outcome is Outcome.VERIFIED
    assert decision.reason is Reason.VALUE_MATCH
    assert decision.extraction is ExtractionStatus.EXTRACTED


def test_a_cell_bound_by_its_divider_is_compared_and_can_disagree(tmp_path):
    decision = printed(tmp_path, "0.381", "| 7|", "|")
    assert decision.outcome is Outcome.MISMATCH
    assert decision.reason is Reason.VALUE_MISMATCH
    assert "0.318" in decision.detail


def test_anchors_written_on_one_line_match_text_broken_over_several(tmp_path):
    before = (
        "## $north ## ## | N (sites)| Slope| se| pval| "
        "## |-----------:|-----:|-----:|------:| ## | 7|"
    )
    assert printed(tmp_path, "0.318", before, "| 0.107| 0.0271| ## ## $south").outcome is (
        Outcome.VERIFIED
    )


def test_a_leading_anchor_the_text_does_not_hold_is_absent(tmp_path):
    decision = printed(tmp_path, "0.318", "| 4|", "|")
    assert decision.reason is Reason.PASSAGE_ABSENT
    assert decision.extraction is ExtractionStatus.ABSENT
    assert decision.comparison is ComparisonStatus.NOT_APPLICABLE
    assert decision.outcome is Outcome.NOT_FOUND


def test_a_trailing_anchor_that_does_not_follow_the_value_is_absent(tmp_path):
    decision = printed(tmp_path, "0.318", "| 7|", "| 0.108|")
    assert decision.reason is Reason.PASSAGE_ABSENT
    assert decision.outcome is Outcome.NOT_FOUND


@pytest.mark.parametrize(
    ("before", "after", "read"),
    [
        ("| 5| 0.212|", "|", "n/a"),
        ("| 7|", "", "0.318|"),
        ("| 7|", "0.107|", "0.318|"),
    ],
)
def test_text_between_found_anchors_that_is_not_a_number_keeps_its_own_reason(
    tmp_path, before, after, read
):
    decision = printed(tmp_path, "0.318", before, after)
    assert decision.reason is Reason.VALUE_NOT_NUMERIC
    assert decision.extraction is ExtractionStatus.INVALID
    assert decision.comparison is ComparisonStatus.NOT_APPLICABLE
    assert decision.outcome is Outcome.NOT_FOUND
    assert f"'{read}'" in decision.detail, "the refusal has to show what was read"


@pytest.mark.parametrize(
    ("doc", "before", "after", "reported"),
    [
        ("## | 7| 0.318| 0.107|\n", "| 7|", "|", "0.318"),
        ("|7|0.318|0.107|\n", "|7|", "|", "0.318"),
        ("Accuracy was 93.1% overall.\n", "Accuracy was", "%", "93.1"),
        ("The ratio is 3.14.\n", "ratio is", ".", "3.14"),
        ("The dose was 12.5(3) mg.\n", "dose was", "(", "12.5"),
        ("Loss fell to 2.5e-3. Then rose.\n", "fell to", ".", "2.5e-3"),
    ],
)
def test_a_trailing_anchor_cuts_the_run_where_it_touches_the_number(
    tmp_path, doc, before, after, reported
):
    decision = printed(tmp_path, reported, before, after, doc=doc)
    assert decision.outcome is Outcome.VERIFIED
    assert decision.extraction_digest == Digest.of_text(reported).value


def test_the_first_full_stop_inside_a_number_is_passed_over_for_the_one_that_ends_it(tmp_path):
    # Cut at the first full stop the value would be 3, which agrees with a reported 3.0.
    decision = printed(tmp_path, "3.0", "ratio is", ".", doc="The ratio is 3.14.\n")
    assert decision.outcome is Outcome.MISMATCH
    assert "3.14" in decision.detail


@pytest.mark.parametrize(
    ("doc", "before", "after", "number"),
    [
        ("Slope was 0.318 rows.\n", "Slope was", "8", "0.318"),
        ("Slope was 0.318 rows.\n", "Slope was", ".", "0.318"),
        ("Slope was 0.318 rows.\n", "Slope was", "318", "0.318"),
        ("We kept 1,234 items.\n", "We kept", ",", "1,234"),
        ("We kept 1_234 items.\n", "We kept", "_", "1_234"),
        ("Loss fell to 2.5e-3 here.\n", "fell to", "e", "2.5e-3"),
        ("Loss fell to 2.5e-3 here.\n", "fell to", "-", "2.5e-3"),
        ("Slope was 0.318 rows.\n", "0.3", "rows", "0.318"),
        ("Slope was 0.318 rows.\n", "was 0.", "", "0.318"),
        ("We kept 1,234 items.\n", "kept 1,", "items", "1,234"),
        ("Here x=0.318 rows.\n", "x=0.3", "", "0.318"),
        ("Here (0.318 rows.\n", "(0.3", "", "0.318"),
        ("Here p<0.05 held.\n", "p<0.", "", "0.05"),
        ("Here run_0.318 rows.\n", "run_0.3", "", "0.318"),
        ("Mass was 12.5kg total.\n", "Mass was", ".5kg", "12.5"),
        ("Slope was 0.318rows here.\n", "Slope was", "8rows", "0.318"),
        ("Here x=-0.42 held.\n", "x=-", "", "-0.42"),
        ("## | -0.42| 0.1|\n", "| -", "|", "-0.42"),
        ("Effect (-0.42) held.\n", "(-", ")", "-0.42"),
        ("Here x=+3 held.\n", "x=+", "", "+3"),
        ("Effect was \u22120.42 overall.\n", "Effect was \u2212", "", "-0.42"),
        ("\u22120.42 was the effect.\n", "\u2212", "", "-0.42"),
        ("Effect was -0.42 overall.\n", "Effect was", "0.42", "-0.42"),
        ("Build v-0.5 released.\n", "v-0.", "", "0.5"),
    ],
)
def test_an_anchor_never_splits_a_number(tmp_path, doc, before, after, number):
    decision = printed(tmp_path, "0", before, after, doc=doc)
    assert decision.reason is Reason.PASSAGE_ABSENT
    assert decision.extraction is ExtractionStatus.ABSENT
    assert decision.comparison is ComparisonStatus.NOT_APPLICABLE
    assert decision.outcome is Outcome.NOT_FOUND
    assert decision.extraction_digest == UNKNOWN, "no part of the number was read"
    assert f"would split {number}" in decision.detail


@pytest.mark.parametrize(
    ("doc", "before", "after", "read"),
    [
        ("Build v0.5 released today.\n", "v0.", "", "5"),
        ("Build v0.5 released today.\n", "v0.", "released", "5"),
        ("Here H10 holds for all.\n", "H1", "", "0"),
        ("Build v0.5 released today.\n", "Build v", ".5", "0"),
        ("Layer x2 scored well.\n", "Layer x", "", "2"),
    ],
)
def test_digits_attached_to_a_letter_are_a_name_an_anchor_may_fall_inside(
    tmp_path, doc, before, after, read
):
    decision = printed(tmp_path, read, before, after, doc=doc)
    assert decision.outcome is Outcome.VERIFIED
    assert decision.extraction_digest == Digest.of_text(read).value


@pytest.mark.parametrize(
    ("doc", "before", "after", "reported", "read"),
    [
        ("Here x=-0.42 held.\n", "x=", "", "-0.42", "-0.42"),
        ("## | -0.42| 0.1|\n", "## |", "|", "-0.42", "-0.42"),
        ("Effect (-0.42) held.\n", "(", ")", "-0.42", "-0.42"),
        ("Here x=+3 held.\n", "x=", "", "3", "+3"),
        ("Effect was \u22120.42 overall.\n", "Effect was", "", "-0.42", "-0.42"),
        ("Rows 10-12 were kept.\n", "10-", "", "12", "12"),
        ("Rows 10\u201312 were kept.\n", "10\u2013", "", "12", "12"),
        ("Data pre-2020 were kept.\n", "pre-", "", "2020", "2020"),
        ("Build v-0.5 released.\n", "v-", "", "0.5", "0.5"),
    ],
)
def test_a_sign_belongs_to_its_number_unless_a_digit_or_a_letter_precedes_it(
    tmp_path, doc, before, after, reported, read
):
    decision = printed(tmp_path, reported, before, after, doc=doc)
    assert decision.outcome is Outcome.VERIFIED
    assert decision.extraction_digest == Digest.of_text(read).value


def test_a_bare_divider_between_two_different_cells_is_ambiguous(tmp_path):
    decision = printed(tmp_path, "0.318", "|", "|", doc="|0.318|0.107|\n")
    assert decision.reason is Reason.PASSAGE_AMBIGUOUS
    assert "0.318" in decision.detail and "0.107" in decision.detail


def test_a_trailing_anchor_past_the_run_is_taken_before_one_inside_it(tmp_path):
    decision = printed(tmp_path, "0.5", "share of", "% of", doc="A share of 0.5% % of all.\n")
    assert decision.reason is Reason.VALUE_NOT_NUMERIC
    assert "'0.5%'" in decision.detail


def test_an_empty_leading_anchor_anchors_nothing():
    with pytest.raises(ValidationError):
        ProseLocator(before="", after="fixtures")


def test_a_side_is_frozen():
    side = CorrespondenceSide(name="s", artifact="doc", locator=TreeLocator(pointer="/x"))
    with pytest.raises(ValidationError):
        side.name = "other"


# -- a value with no precision to compare ---------------------------------------------------


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_a_non_finite_side_is_refused_before_any_comparison(tmp_path, value):
    """`json.loads` accepts NaN and the infinities, so a count file can carry one.

    None of them has a precision, so neither is coarser or finer than the other side and
    there is nothing for `printed_precision` to round to. The value was located and is not of
    the type the assertion requires, which is what `value_not_numeric` names.
    """
    decision = only(project(tmp_path, counts={"fixtures": value}))
    assert decision.reason is Reason.VALUE_NOT_NUMERIC
    assert decision.extraction is ExtractionStatus.INVALID
    assert decision.comparison is ComparisonStatus.NOT_APPLICABLE
    assert decision.outcome is Outcome.NOT_FOUND
    assert "measured" in decision.detail, "the refusal has to say which side held it"


@pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity"])
def test_reaching_the_comparison_with_a_non_finite_value_is_a_defect(literal):
    """The guard above is what makes `_exponent` unreachable with one of these.

    A future edit that drops the guard must not silently compare two values at a precision
    nothing chose. `Decimal.as_tuple().exponent` is a tagged union whose string arms mean
    "not a number", and reading one as an exponent is the arithmetic defect this raises on.
    Per §5 a defect reaches the report as `error`, never as an abstention.
    """
    with pytest.raises(ValueError, match="no exponent"):
        _exponent(decimal.Decimal(literal))


def test_a_defect_in_the_comparison_reaches_the_report_as_an_error(tmp_path, monkeypatch):
    """The raise has to arrive as `error`, not as two artifacts that disagree.

    Letting an arithmetic defect read as a mismatch would report a contradicted document on
    the strength of a bug, which is the one thing this package must never do.
    """
    path = project(tmp_path)
    assert only(path).outcome is Outcome.MISMATCH

    def defective(_value):
        raise ValueError("no exponent: a defect standing in for a dropped guard")

    # `claims.verify` as an attribute of `claims` is the exported function, not the module,
    # so the module is fetched by name.
    monkeypatch.setattr(importlib.import_module("claims.verify"), "_exponent", defective)
    decision = only(path)
    assert decision.execution.value == "failed"
    assert decision.reason is Reason.BACKEND_DEFECT
    assert decision.outcome is Outcome.ERROR


# -- what each side's extractor produced ----------------------------------------------------


def test_each_side_records_what_its_own_extractor_produced(tmp_path):
    """One digest per side, because a decision-level digest cannot say which of two moved."""
    decision = only(project(tmp_path))
    digests = {s.name: s.extraction_digest for s in decision.sides}
    assert digests["stated"] == Digest.of_text("18").value
    assert digests["measured"] == Digest.of_text("19").value


def test_a_side_that_extracted_nothing_has_nothing_to_hash(tmp_path):
    decision = only(project(tmp_path, counts={"other": 19}))
    by_name = {s.name: s for s in decision.sides}
    assert by_name["stated"].extraction_digest == Digest.of_text("18").value
    assert by_name["measured"].extraction_digest == UNKNOWN
    assert by_name["measured"].extracted is None


def test_the_decision_digest_moves_when_either_side_moves(tmp_path):
    """It covers both extractions, so it is never `unknown`: both were sought."""
    before = only(project(tmp_path))
    assert before.extraction_digest not in ("", UNKNOWN)

    moved_right = only(project(tmp_path, counts={"fixtures": 20}))
    moved_left = only(project(tmp_path, doc=DOC.replace("eighteen", "seventeen")))
    assert (
        len({before.extraction_digest, moved_right.extraction_digest, moved_left.extraction_digest})
        == 3
    )


@pytest.mark.parametrize("name", ["output", "run.log", "session.Rout"])
def test_a_text_file_whose_suffix_names_no_reader_is_read_as_text(tmp_path, name):
    (tmp_path / name).write_text("epoch 9\ntrain loss: 0.0459 at the end\n")
    manifest = {
        "schema_version": "repro/1",
        "project": "t",
        "artifacts": [{"id": "log", "path": name}],
        "claims": [
            {
                "id": "c",
                "text": "t",
                "evidence": [
                    {
                        "kind": "value",
                        "artifact": "log",
                        "name": "loss",
                        "reported": "0.0459",
                        "locator": {
                            "kind": "prose",
                            "before": "train loss:",
                            "after": "at the end",
                        },
                    }
                ],
            }
        ],
    }
    path = tmp_path / "repro.yaml"
    path.write_text(yaml.safe_dump(manifest, sort_keys=False))
    decision = only(path)
    assert decision.outcome is Outcome.VERIFIED
    assert decision.extraction is ExtractionStatus.EXTRACTED
