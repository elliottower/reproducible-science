"""One matching rule, applied to every lookup source.

Four hand-written lookups drifted: the arXiv one never checked the year, so it would accept a
paper from any year with a close enough title. The rule lives in one place now, and a service
supplies only candidates.
"""

from __future__ import annotations

from citations.models import Record
from citations.resolve import match
from citations.services import SERVICES, Candidate
from citations.text import surname


def rec(**kw) -> Record:
    base = dict(
        slug="s",
        title="Attention Is All You Need",
        authors=["Vaswani, Ashish"],
        year="2017",
        venue="Advances in Neural Information Processing Systems",
    )
    base.update(kw)
    return Record(**base)


def cand(**kw) -> Candidate:
    base = dict(
        title="Attention Is All You Need",
        surnames=frozenset({"vaswani"}),
        year=2017,
        venue="",
        identifier=("arxiv", "1706.03762"),
    )
    base.update(kw)
    return Candidate(**base)


def test_a_near_identical_title_by_other_authors_is_rejected():
    # Crossref really returns "Is Attention All You Need?" for this query, at 0.88 similarity
    # against a 0.87 threshold, by different people, in a different year. Title alone accepts it.
    impostor = cand(
        title="Is Attention All You Need?",
        surnames=frozenset({"smith"}),
        year=2025,
        identifier=("doi", "10.9999/wrong"),
    )
    assert match(rec(), [impostor]) is None


def test_the_right_paper_is_accepted():
    assert match(rec(), [cand()]) == ("arxiv", "1706.03762")


def test_the_year_is_checked_for_every_service_including_arxiv():
    assert match(rec(), [cand(year=2011)]) is None
    assert match(rec(), [cand(year=2018)]) is not None, "a year either side is a preprint"


def test_a_candidate_with_no_identifier_cannot_win_however_well_it_matches():
    assert match(rec(), [cand(identifier=None)]) is None


def test_an_unknown_year_on_either_side_is_not_a_mismatch():
    assert match(rec(year=""), [cand(year=2001)]) is not None
    assert match(rec(), [cand(year=None)]) is not None


def test_the_venue_breaks_a_tie_toward_the_version_we_cite():
    preprint = cand(venue="arXiv", identifier=("arxiv", "1706.03762"))
    published = cand(
        venue="Advances in Neural Information Processing Systems",
        identifier=("doi", "10.5555/3295222"),
    )
    assert match(rec(), [preprint, published])[0] == "doi"


def test_a_surname_is_read_out_of_either_name_order():
    assert surname("Vaswani, Ashish") == surname("Ashish Vaswani") == "vaswani"


def test_the_refusal_threshold_cannot_drift_from_the_service_count():
    # The old code compared against a literal 3 while four services were tried, so an
    # all-refused record fell through and was reported as simply not found.
    assert len(SERVICES) == len({s.name for s in SERVICES})
    assert len(SERVICES) >= 4
