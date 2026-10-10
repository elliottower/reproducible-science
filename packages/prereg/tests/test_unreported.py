"""A plan can pass every freeze check and never reach the paper it was written for."""

from __future__ import annotations

from prereg.plan import hypotheses_of, unreported

TEMPLATE_STYLE = """# Does it?

**H1.** The first thing.

**H2b.** The second thing.

**H10.** The tenth thing.
"""

HEADING_STYLE = """# Does it?

## H1: the first thing

### HP3: a Perturb-seq thing

## H_tissue1: a tissue thing
"""


def test_both_label_styles_are_found():
    assert hypotheses_of(TEMPLATE_STYLE) == ["H1", "H2b", "H10"]
    assert hypotheses_of(HEADING_STYLE) == ["H1", "HP3", "H_tissue1"]


def test_a_label_repeated_in_the_plan_is_listed_once():
    assert hypotheses_of(TEMPLATE_STYLE + "\n**H1.** restated\n") == ["H1", "H2b", "H10"]


def test_every_hypothesis_mentioned_is_nothing_to_report():
    assert unreported(TEMPLATE_STYLE, "we tested H1, H2b and H10 and here is what happened") == []


def test_the_one_the_manuscript_never_mentions_is_named():
    assert unreported(TEMPLATE_STYLE, "we tested H1 and H2b") == ["H10"]


def test_a_longer_label_does_not_report_a_shorter_one_as_present():
    # `H1` is a substring of `H10`, so a naive search passes a manuscript that
    # mentions only the tenth hypothesis and never the first.
    assert "H1" in unreported(TEMPLATE_STYLE, "we tested H10 and H2b")


def test_a_plan_declared_out_of_scope_reports_nothing():
    out_of_scope = TEMPLATE_STYLE + "\n**Manuscript:** none\n"
    assert unreported(out_of_scope, "this manuscript mentions no hypothesis at all") == []


def test_the_log_is_not_searched_for_hypotheses():
    # `plan_of` cuts the log, so a label quoted in a deviation entry is not a
    # registered hypothesis and must not be demanded of the manuscript.
    with_log = TEMPLATE_STYLE + "\n---\n\n## Log\n\n**H99.** quoted in a deviation\n"
    assert "H99" not in hypotheses_of(with_log)
