"""A quotation points at one passage. These pin what happens when it points at several.

`passage in document` answers a weaker question than the record asks, and answered it as
`found` for a passage occurring three times. The W3C `TextQuoteSelector` neighbours are how a
record says which occurrence it means, and `ambiguous` is what it gets until it does.
"""

from __future__ import annotations

import pytest
from citations import verify as V
from citations.models import ClaimFile


@pytest.fixture(autouse=True)
def _no_cache():
    V.clear_caches()


def _src(tmp_path, text):
    f = tmp_path / "src.txt"
    f.write_text(text)
    return f


TWICE = (
    "In the pilot the model reached an accuracy of 0.94 on the split. "
    "We repeated the whole procedure on new data. "
    "In the replication the model reached an accuracy of 0.94 on the split."
)
PASSAGE = "the model reached an accuracy of 0.94 on the split"


# --- a passage that occurs more than once is not identified by its own words -----------------


def test_a_passage_occurring_twice_is_ambiguous_not_found(tmp_path):
    r = V.check_one(PASSAGE, _src(tmp_path, TWICE), None)
    assert r.state == "ambiguous"
    assert "occurs 2 times" in r.detail


def test_the_ambiguous_detail_names_the_remedy(tmp_path):
    r = V.check_one(PASSAGE, _src(tmp_path, TWICE), None)
    assert "prefix" in r.detail and "suffix" in r.detail


def test_a_passage_occurring_once_is_found(tmp_path):
    once = "In the pilot the model reached an accuracy of 0.94 on the split."
    assert V.check_one(PASSAGE, _src(tmp_path, once), None).state == "found"


# --- the anchors are what settle it ----------------------------------------------------------


def test_a_prefix_that_singles_one_out_resolves_the_ambiguity(tmp_path):
    r = V.check_one(PASSAGE, _src(tmp_path, TWICE), None, prefix="In the replication ")
    assert r.state == "found"


def test_the_other_prefix_selects_the_other_occurrence(tmp_path):
    r = V.check_one(PASSAGE, _src(tmp_path, TWICE), None, prefix="In the pilot ")
    assert r.state == "found"


def test_a_suffix_alone_can_settle_it(tmp_path):
    doc = f"{PASSAGE} in July. Later, {PASSAGE} in August."
    r = V.check_one(PASSAGE, _src(tmp_path, doc), None, suffix=" in August")
    assert r.state == "found"


def test_anchors_that_still_do_not_single_one_out_stay_ambiguous(tmp_path):
    doc = f"We note that {PASSAGE} here. We note that {PASSAGE} here."
    r = V.check_one(PASSAGE, _src(tmp_path, doc), None, prefix="We note that ", suffix=" here")
    assert r.state == "ambiguous"
    assert "widen" in r.detail


def test_anchors_on_a_unique_passage_change_nothing(tmp_path):
    once = "In the pilot the model reached an accuracy of 0.94 on the split."
    bare = V.check_one(PASSAGE, _src(tmp_path, once), None)
    anchored = V.check_one(PASSAGE, _src(tmp_path, once), None, prefix="wrong ", suffix=" wrong")
    assert bare.state == anchored.state == "found"


def test_an_anchor_that_matches_nothing_does_not_manufacture_a_match(tmp_path):
    absent = "This document says nothing of the kind, at considerable length, twice over."
    r = V.check_one(PASSAGE, _src(tmp_path, absent), None, prefix="In the pilot ")
    assert r.state == "not found"


# --- a longer word beginning with the passage is not a second occurrence ---------------------


def test_a_shared_prefix_is_not_an_occurrence(tmp_path):
    doc = "We evaluated the catalogue of variants. The catalog of variants is short."
    r = V.check_one("the catalog of variants", _src(tmp_path, doc), None)
    assert r.state == "found"


def test_a_passage_that_only_ever_cuts_a_word_is_still_found_and_warned(tmp_path):
    doc = "The model reached an accuracy of 0.95 on the held-out split."
    r = V.check_one("The model reached an accuracy of 0.9", _src(tmp_path, doc), None)
    assert r.state == "found"
    assert "truncated" in r.warnings


# --- the dotless i -----------------------------------------------------------------------------


def test_a_dotless_i_in_the_source_resolves_against_an_ordinary_one(tmp_path):
    doc = "The construction is due to Krzyżosiak and colleagues, who report it in full."
    quoted = doc.replace("i", "ı")
    assert V.check_one(doc, _src(tmp_path, quoted), None).state == "found"


def test_a_dotted_capital_i_folds_to_a_plain_one(tmp_path):
    doc = "İstanbul is where the replication was run, over the following eighteen months."
    quoted = doc.replace("İ", "I")
    assert V.check_one(quoted, _src(tmp_path, doc), None).state == "found"


# --- what an ambiguous verdict does to a report ------------------------------------------------


def test_ambiguous_counts_as_unresolved_so_strict_refuses_it():
    rep = V.Report(checked=1, counts={"ambiguous": 1})
    assert rep.unresolved == 1
    assert not rep.strict_ok


def test_ambiguous_is_not_a_failure_the_way_not_found_is():
    rep = V.Report(checked=1, counts={"ambiguous": 1})
    assert rep.ok


# --- the selector survives the trip through a claims file --------------------------------------


def test_a_claims_file_carries_prefix_and_suffix_into_the_model():
    cf = ClaimFile.model_validate(
        {
            "source": {"local": "s.pdf"},
            "claims": {
                "C1": {
                    "quotes": [
                        {"exact": PASSAGE, "prefix": "In the pilot ", "suffix": ".", "section": "1"}
                    ]
                }
            },
        }
    )
    q = cf.claims["C1"].quotes[0]
    assert (q.text, q.prefix, q.suffix) == (PASSAGE, "In the pilot ", ".")


def test_a_claims_file_without_them_defaults_to_empty():
    cf = ClaimFile.model_validate(
        {"source": {"local": "s.pdf"}, "claims": {"C1": {"quotes": [{"exact": PASSAGE}]}}}
    )
    q = cf.claims["C1"].quotes[0]
    assert (q.prefix, q.suffix) == ("", "")


def test_the_space_that_separates_prefix_from_passage_survives_validation():
    """The strip that `_Base` applies elsewhere would weld the anchor into one bad word."""
    cf = ClaimFile.model_validate(
        {
            "source": {"local": "s.pdf"},
            "claims": {"C1": {"quotes": [{"exact": PASSAGE, "prefix": "In the pilot "}]}},
        }
    )
    q = cf.claims["C1"].quotes[0]
    assert q.prefix.endswith(" ")
    assert V.fold(q.prefix + q.text).startswith("in the pilot the model")


def test_an_anchored_quotation_resolves_through_the_claims_file(tmp_path):
    cf = ClaimFile.model_validate(
        {
            "source": {"local": "s.pdf"},
            "claims": {"C1": {"quotes": [{"exact": PASSAGE, "prefix": "In the replication "}]}},
        }
    )
    q = cf.claims["C1"].quotes[0]
    r = V.check_one(q.text, _src(tmp_path, TWICE), None, prefix=q.prefix, suffix=q.suffix)
    assert r.state == "found"


# --- the verdict without a file ----------------------------------------------------------------


def test_resolve_in_finds_a_unique_passage():
    m = V.resolve_in(PASSAGE, f"Before. {PASSAGE}. After.")
    assert (m.state, m.count, m.normalized) == ("found", 1, False)


def test_resolve_in_reports_a_repeated_passage_as_ambiguous():
    m = V.resolve_in(PASSAGE, TWICE)
    assert (m.state, m.count) == ("ambiguous", 2)


def test_resolve_in_takes_the_anchors():
    assert V.resolve_in(PASSAGE, TWICE, prefix="In the replication ").state == "found"


def test_resolve_in_says_when_it_needed_the_skeleton():
    welded = f"Before. {PASSAGE.replace(' ', '')}. After."
    m = V.resolve_in(PASSAGE, welded)
    assert (m.state, m.normalized) == ("found", True)


def test_resolve_in_reports_an_absent_passage():
    m = V.resolve_in(PASSAGE, "This document is about something else entirely, at length.")
    assert (m.state, m.count) == ("not found", 0)


def test_resolve_in_never_returns_a_state_about_reading_a_file():
    for text in ("", PASSAGE, TWICE, "unrelated prose of a reasonable length goes here"):
        assert V.resolve_in(PASSAGE, text).state not in ("unchecked", "indeterminate")


def test_check_one_and_resolve_in_agree_on_the_same_text(tmp_path):
    """The one matcher, reached two ways: `_verdict` must not drift from `resolve_in`."""
    docs = (f"Before. {PASSAGE}. After.", TWICE, "nothing of the sort, at some length")
    for i, doc in enumerate(docs):
        # A distinct path per document: `extract` memoizes on the path, so reusing one file
        # would compare the second document against the first one's cached text.
        f = tmp_path / f"src{i}.txt"
        f.write_text(doc)
        assert V.resolve_in(PASSAGE, doc).state == V.check_one(PASSAGE, f, None).state, doc


# --- a not-found says where it stopped matching ------------------------------------------------


def test_divergence_reports_the_longest_prefix_the_source_contains():
    doc = "The effect was measured at 0.42 across every replication we attempted here."
    quote = "The effect was measured at -0.42 across every replication"
    n, quoted, found = V.divergence(quote, doc)
    assert n == len("the effect was measured at ")
    assert "-0.42" in quoted and "0.42" in found


def test_the_not_found_detail_names_the_point_of_divergence(tmp_path):
    # This is the message that would have saved three manual binary searches.
    doc = "compositionality, e.g. vec('king') vec('man') + vec('woman') = vec('queen') approximated"
    f = tmp_path / "src.txt"
    f.write_text(doc)
    r = V.check_one("compositionality, e.g. vec('king') - vec('man') + vec('woman')", f, None)
    assert r.state == "not found"
    assert "quoted:" in r.detail and "source:" in r.detail
    assert "adjacent fragments" in r.detail


def test_a_passage_absent_from_the_start_gets_the_plain_message(tmp_path):
    # Nothing matched, so there is no divergence point to report and the advice would mislead.
    f = tmp_path / "src.txt"
    f.write_text("This document is about something else entirely, at considerable length.")
    r = V.check_one("a passage that appears nowhere in that document whatsoever", f, None)
    assert r.state == "not found"
    assert "quoted:" not in r.detail
    assert "read the source" in r.detail


def test_the_two_fragments_a_split_produces_both_resolve(tmp_path):
    # The repair the message recommends, carried out: the dropped character sits between them.
    doc = "compositionality, e.g. vec('king') vec('man') + vec('woman') = vec('queen') approximated"
    f = tmp_path / "src.txt"
    f.write_text(doc)
    for fragment in (
        "compositionality, e.g. vec('king')",
        "vec('man') + vec('woman') = vec('queen')",
    ):
        assert V.resolve_in(fragment, doc).state == "found", fragment
