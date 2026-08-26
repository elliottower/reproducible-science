"""Coverage asks the question `verify` cannot: is the quotation pinned at all?"""

from __future__ import annotations

import pathlib

import pytest
from citations import coverage as C
from citations.models import ClaimFile


def claim_file(name: str, *quotes: str, citation: str = "", local: str = "") -> ClaimFile:
    cf = ClaimFile.model_validate(
        {
            "source": {"citation": citation or name, "local": local, "sha256": "x" * 64},
            "claims": {"c1": {"statement": "s", "quotes": [{"exact": q} for q in quotes]}},
        }
    )
    return cf.model_copy(update={"path": pathlib.Path(f"{name}.yaml")})


def only(tex: str) -> C.Quotation:
    got = C.quotations(tex)
    assert len(got) == 1, f"expected one quotation, got {len(got)}"
    return got[0]


def status(tex: str, *pinned: str) -> str:
    return C.cover(only(tex), C.pinned_spans([claim_file("s", *pinned)])).status


# --- what the manuscript says, against what is pinned ------------------------------------------


def test_a_quotation_that_is_a_span_of_a_pinned_quote_is_covered():
    assert (
        status("``the model performs well here''", "we found the model performs well here too")
        == "covered"
    )


def test_a_quotation_no_pinned_quote_contains_is_uncovered():
    assert (
        status("``the model performs badly here''", "we found the model performs well here")
        == "uncovered"
    )


def test_the_sentences_own_period_does_not_make_a_quotation_uncovered():
    # American typesetting puts the period inside the closing quotation mark, so the source
    # does not contain it. Every quotation ending a sentence would otherwise be reported.
    assert (
        status(
            "``a healthy culture of nosological pluralism.''",
            "sustained by a healthy culture of nosological pluralism (aftab 2024)",
        )
        == "covered"
    )


@pytest.mark.parametrize("tail", [",", ";", ":", ".", "'", '"'])
def test_trailing_typesetting_punctuation_is_not_part_of_the_quotation(tail):
    assert (
        status(f"``the model performs well{tail}''", "the model performs well and fast")
        == "covered"
    )


# --- LaTeX is markup, and markup is not text ---------------------------------------------------


def test_an_emphasis_inside_a_quotation_is_not_part_of_the_words():
    assert (
        status(r"``the model \emph{clearly} performs well''", "the model clearly performs well")
        == "covered"
    )


@pytest.mark.parametrize("ligature,rendered", [("--", "-"), ("---", "-")])
def test_a_dash_ligature_matches_the_character_a_source_renders(ligature, rendered):
    assert (
        status(
            f"``an expansion in the DSM{ligature}5 edition''",
            f"an expansion in the DSM{rendered}5 edition",
        )
        == "covered"
    )


def test_a_thin_space_before_a_closing_quote_is_not_a_character():
    assert (
        status(
            r"``use DSM categories as the `gold standard'\,''",
            "we cannot use dsm categories as the 'gold standard' at all",
        )
        == "covered"
    )


def test_an_escaped_percent_is_a_percent_sign():
    assert (
        status(r"``a rise of 40\% over the decade''", "reported a rise of 40% over the decade")
        == "covered"
    )


def test_a_commented_out_quotation_is_not_checked():
    assert C.quotations("% ``a draft line that was cut''\ntext") == []


def test_a_line_number_survives_a_stripped_comment():
    # The line number is how the quotation is found. A comment that shortened the file would
    # send the reader to the wrong line.
    tex = "% cut\n\n\n``the model performs well here''"
    assert only(tex).line == 4


# --- an ellipsis is omitted text ---------------------------------------------------------------


def test_each_fragment_of_an_elided_quotation_must_appear():
    assert (
        status(
            "``the model performs well ... on every held-out split''",
            "the model performs well, and it does so on every held-out split",
        )
        == "covered"
    )


def test_contiguity_is_not_required_across_an_ellipsis():
    pinned = "the model performs well. " + "x" * 400 + " on every held-out split"
    assert status("``the model performs well ... on every held-out split''", pinned) == "covered"


def test_a_fragment_that_is_absent_is_not_rescued_by_the_others():
    assert (
        status(
            "``the model performs well ... on no held-out split''",
            "the model performs well, and it does so on every held-out split",
        )
        == "uncovered"
    )


# --- what cannot be decided is not a failure ---------------------------------------------------


def test_a_quotation_too_short_to_distinguish_from_noise_is_unresolvable():
    # Not covered and not uncovered: "loci moved" appears in a great many documents, so its
    # appearing in one establishes nothing either way.
    assert status("``Loci moved''", "the loci moved between editions") == "unresolvable"


def test_a_manuscript_with_no_pinned_quotes_at_all_reports_every_quotation():
    q = only("``the model performs well here''")
    assert C.cover(q, []).status == "uncovered"


# --- the normalization must not reach further than typesetting ---------------------------------


def test_an_inequality_is_not_normalized_away():
    # The regression `verify.skeleton` records: stripping every non-alphanumeric character
    # made `p < 0.05` match a source reading `p = 0.05`. A coverage check that did that would
    # report a reversed inequality as quoted verbatim.
    assert (
        status(
            "``the effect was significant at p < 0.05''", "the effect was significant at p = 0.05"
        )
        == "uncovered"
    )


def test_a_flipped_sign_is_not_normalized_away():
    assert (
        status("``a correlation of -0.42 across sites''", "a correlation of 0.42 across sites")
        == "uncovered"
    )


def test_a_different_number_is_not_normalized_away():
    assert (
        status("``an expansion to 636,120 combinations''", "an expansion to 636,121 combinations")
        == "uncovered"
    )


# --- attribution: which source the sentence credits --------------------------------------------


def test_a_passage_in_a_source_cited_nearby_is_attributed():
    q = only(r"As \citep{smith2020} put it, ``the model performs well here''.")
    assert (
        C.attribute(q, {"smith2020": "we found the model performs well here too"}, set()).status
        == "covered"
    )


def test_a_passage_in_none_of_the_nearby_sources_is_uncovered():
    q = only(r"As \citep{smith2020} put it, ``the model performs well here''.")
    assert (
        C.attribute(q, {"smith2020": "an unrelated sentence entirely"}, set()).status == "uncovered"
    )


def test_an_unreadable_neighbour_makes_the_question_undecided_rather_than_a_misattribution():
    # The passage may well belong to the source that would not open. Reporting it as
    # misattributed would blame the manuscript for a missing file.
    q = only(r"As \citep{smith2020, jones2019} put it, ``the model performs well here''.")
    got = C.attribute(q, {"smith2020": "an unrelated sentence"}, {"jones2019"})
    assert got.status == "unresolvable"
    assert "jones2019" in got.detail


def test_a_quotation_with_no_citation_anywhere_near_it_is_undecided():
    q = only("``the model performs well here''")
    assert (
        C.attribute(q, {"smith2020": "the model performs well here"}, set()).status
        == "unresolvable"
    )


def test_a_citation_beyond_the_window_is_not_treated_as_the_source():
    far = r"\citep{smith2020}" + " filler" * 300 + " ``the model performs well here''"
    assert only(far).keys == ()


def test_every_key_in_the_window_is_offered_not_only_the_nearest():
    # The nearest key is often not the source: "the same document restricts" leaves the real
    # one several sentences back, behind an intervening cite.
    q = only(r"\citep{aaa2001} ... and \citep{bbb2002} ``the model performs well here''")
    assert set(q.keys) == {"aaa2001", "bbb2002"}
