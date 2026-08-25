"""Assertions whose two sides are both artifacts, and the prose locator that makes one.

Every other kind compares an artifact against a literal in the manifest. Where both sides are
artifacts -- a sentence about the code, and a count of the code -- writing one of them into the
manifest creates a third copy that nothing checks. The tests here are about what that costs and
what the engine must refuse to conclude.
"""

from __future__ import annotations

import json

import pytest
import yaml
from pydantic import ValidationError
from repro.manifest import load
from repro.models import (
    ComparisonStatus,
    CorrespondenceEvidence,
    CorrespondenceSide,
    ExtractionStatus,
    NumberForm,
    Outcome,
    ProseLocator,
    Reason,
    TreeLocator,
    Validity,
)
from repro.verify import verify

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


def test_an_empty_leading_anchor_anchors_nothing():
    with pytest.raises(ValidationError):
        ProseLocator(before="", after="fixtures")


def test_a_side_is_frozen():
    side = CorrespondenceSide(name="s", artifact="doc", locator=TreeLocator(pointer="/x"))
    with pytest.raises(ValidationError):
        side.name = "other"
