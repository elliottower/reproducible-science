"""Each profile grades the quotations `citations verify` reports `corrected`."""

from __future__ import annotations

from claims.policy import EXPLORATORY, PUBLICATION, STRICT, Severity


def test_a_corrected_quotation_warns_under_publication_and_strict_and_is_ignored_in_a_draft():
    counts = {"found": 9, "corrected": 2}
    for profile in (PUBLICATION, STRICT):
        graded = profile.assess_citations(counts)
        assert graded.passed
        assert [v.rule for v in graded.warnings] == ["citations.corrected"]
    assert EXPLORATORY.assess_citations(counts).violations == ()


def test_a_project_that_makes_corrected_an_error_fails_and_none_corrected_passes():
    project = PUBLICATION.model_copy(update={"quotation_corrected": Severity.ERROR})
    assert not project.assess_citations({"corrected": 1}).passed
    assert project.assess_citations({"found": 3, "corrected": 0}).violations == ()
