"""A quotation that is the source with text left out, and says nothing about the gap.

`not found` covers a misquotation and it covers this, and the two are repaired differently: a
misquotation by reading the source, this one by pinning the pieces apart. Every word of such a
quotation is in the source, so the report says so, says where the gap falls and how much was
left out, and stays `not found`.
"""

from __future__ import annotations

import dataclasses
import json

import pytest
import yaml
from citations import cli, pin
from citations import verify as V
from citations.verify import Gap


@pytest.fixture(autouse=True)
def _no_cache():
    V.clear_caches()


FIRST = "Higher circulating levels of the protein were associated with lower risk"
BETWEEN = "in the discovery cohort (odds ratio 0.81 per standard deviation), and"
SECOND = "the association replicated in two independent cohorts of European ancestry"
THIRD = "with no evidence of horizontal pleiotropy in sensitivity analyses"
SOURCE = (
    f"Background. {FIRST} {BETWEEN} {SECOND}. Colocalization supported a shared variant, "
    f"{THIRD}. Conclusions follow."
)
JOINED = f"{FIRST} {SECOND}"


def _src(tmp_path, text=SOURCE):
    tmp_path.mkdir(parents=True, exist_ok=True)
    f = tmp_path / "source.txt"
    f.write_text(text)
    return f


# --- two pieces of the source with the text between them left out ------------------------------


def test_two_pieces_joined_are_not_found_and_say_why(tmp_path):
    r = V.check_one(JOINED, _src(tmp_path), None)
    assert r.state == "not found"
    assert r.reason == V.OMISSION
    assert "every word of the quotation is in the source, as 2 pieces" in r.detail


def test_the_gap_is_where_the_first_piece_ends_and_as_long_as_what_was_left_out():
    assert where(JOINED, SOURCE) == [(len(FIRST), len(BETWEEN))]


def test_three_pieces_report_two_gaps_in_order():
    quote = f"{FIRST} {SECOND}. {THIRD}"
    gaps = V.omission(quote, SOURCE).gaps
    assert [g.at for g in gaps] == [len(FIRST), len(f"{FIRST} {SECOND}.")]
    assert gaps[0].skipped == len(BETWEEN)
    assert gaps[1].skipped == len("Colocalization supported a shared variant,")


def test_a_gap_of_one_character_is_reported_in_the_singular(tmp_path):
    source = f"{FIRST} a {SECOND}."
    r = V.check_one(JOINED, _src(tmp_path, source), None)
    assert r.gaps == [Gap(len(FIRST), 1, "a", len(FIRST) + 1, tokens=1, position=12)]
    assert "left out (1 token of the source, 1 character): [[a]]" in r.detail


def test_the_detail_shows_both_sides_of_the_gap_and_names_the_remedy(tmp_path):
    r = V.check_one(JOINED, _src(tmp_path), None)
    assert (
        f"left out (11 tokens of the source, {len(BETWEEN)} characters): [[{BETWEEN}]]" in r.detail
    )
    assert f"{FIRST} [[{BETWEEN}]] {SECOND}" in r.detail
    assert "associated with lower risk" in r.detail
    assert "the association replicated" in r.detail
    assert "quote the passage as the source reads" in r.detail and "ellipsis" in r.detail
    assert "`not found`, with or without `--strict`" in r.detail


def test_the_fold_applies_to_each_piece(tmp_path):
    wrapped = SOURCE.replace("protein were", "protein\n   were").replace("European", "EUROPEAN")
    assert V.check_one(JOINED, _src(tmp_path, wrapped), None).reason == V.OMISSION


def test_a_whole_passage_is_found_and_carries_no_reason(tmp_path):
    r = V.check_one(f"{FIRST} {BETWEEN} {SECOND}", _src(tmp_path), None)
    assert (r.state, r.reason, r.gaps) == ("found", "", [])


def test_each_piece_pinned_on_its_own_is_found(tmp_path):
    for piece in (FIRST, SECOND):
        assert V.check_one(piece, _src(tmp_path), None).state == "found"


# --- what must stay a plain not found ----------------------------------------------------------


def where(quote: str, source: str) -> list[tuple[int, int]]:
    found = V.omission(quote, source)
    assert found is not None
    return [(g.at, g.skipped) for g in found.gaps]


def plain(quote: str, source: str = SOURCE) -> bool:
    m = V.resolve_in(quote, source)
    return m.state == "not found" and V.omission(quote, source) is None


def test_a_changed_digit_is_not_an_omission():
    assert plain(f"{FIRST} {BETWEEN} {SECOND}".replace("0.81", "0.18"))
    assert plain(f"{FIRST} {BETWEEN}".replace("0.81", "0.18"))


def test_a_changed_word_is_not_an_omission():
    assert plain(JOINED.replace("lower risk", "higher risk"))
    assert plain(JOINED.replace("two independent", "three independent"))


def test_a_changed_word_beside_a_real_gap_is_not_an_omission():
    assert plain(f"{FIRST} {SECOND}".replace("European", "African"))


def test_pieces_in_the_wrong_order_are_not_an_omission():
    assert plain(f"{SECOND} {FIRST}")


def test_a_piece_under_the_minimum_length_is_not_an_omission():
    short = "lower risk"
    assert len(short) < V.MIN_PIECE_CHARS
    assert short in SOURCE and SOURCE.index(short) < SOURCE.index(SECOND)
    assert plain(f"{short} {SECOND}")
    assert plain(f"{FIRST} in two independent")


def test_a_quotation_cannot_be_assembled_from_fragments_the_source_holds_in_order():
    source = "The red fox ran. A quick dog slept. Then brown owls flew over the lazy river bank."
    assert plain("The red quick dog brown owls lazy river", source)


def test_a_piece_cut_inside_a_word_is_not_an_omission():
    source = f"{FIRST}ier outcomes overall. Later on, {SECOND}."
    assert plain(JOINED, source)


def test_adjacent_pieces_are_one_passage_and_are_found(tmp_path):
    r = V.check_one(f"{BETWEEN} {SECOND}", _src(tmp_path), None)
    assert (r.state, r.reason) == ("found", "")


def test_a_written_ellipsis_in_a_claims_quotation_stays_a_plain_not_found():
    assert plain(f"{FIRST} ... {SECOND}")
    assert plain(f"{FIRST} […] {SECOND}")


def test_an_absent_passage_keeps_the_message_it_had(tmp_path):
    r = V.check_one(
        "a passage that appears nowhere in that document whatsoever", _src(tmp_path), None
    )
    assert (r.state, r.reason, r.gaps) == ("not found", "", [])
    assert "read the source" in r.detail


# --- a cut never falls inside a token ----------------------------------------------------------


@pytest.mark.parametrize(
    ("quote", "source"),
    [
        (
            "the change in the primary outcome was 0.42 standard deviations in the treated group",
            "We found that the change in the primary outcome was -0.42 standard deviations in "
            "the treated group.",
        ),
        (
            "the pooled odds ratio for the outcome was 1 in the discovery cohort overall",
            "Here the pooled odds ratio for the outcome was 1.81 in the discovery cohort overall.",
        ),
        (
            "the trial enrolled a total of 500 participants across the eleven sites",
            "In all, the trial enrolled a total of 12,500 participants across the eleven sites.",
        ),
        (
            "the association with the outcome was significant after adjustment for age",
            "Overall the association with the outcome was non-significant after adjustment for age.",
        ),
        (
            "the response rate was 5 in the treated group overall",
            "And the response rate was 5.3% in the treated group overall.",
        ),
        (
            "the estimate in the first cohort was 5. the association replicated in two cohorts",
            "Thus the estimate in the first cohort was 5.2 overall and the association replicated "
            "in two cohorts.",
        ),
    ],
    ids=["sign", "decimal", "thousands", "hyphenated", "percent", "decimal-point-kept"],
)
def test_a_number_or_compound_cut_short_is_not_an_omission(tmp_path, quote, source):
    assert plain(quote, source)
    r = V.check_one(quote, _src(tmp_path, source), None)
    assert (r.state, r.reason, r.gaps, r.passage) == ("not found", "", [], "")
    assert "[[" not in r.detail and "the source reads" not in r.detail


@pytest.mark.parametrize("joint", [", ", "/", "; ", " (", ") "])
def test_punctuation_left_out_between_two_pieces_is_not_an_omission(joint):
    left = "levels were associated with lower risk"
    right = "the association replicated in two cohorts"
    assert plain(f"{left} {right}", f"Circulating {left}{joint}{right}.")


def test_a_piece_that_stops_before_its_tokens_punctuation_is_not_an_omission():
    assert V.omission(f"{FIRST} {SECOND}. {THIRD}", SOURCE)
    assert plain(f"{FIRST} {SECOND} {THIRD}")


def test_a_piece_that_keeps_its_tokens_punctuation_is_an_omission():
    source = (
        "Patients were enrolled in the study (n = 828) at baseline; "
        "the association replicated in two cohorts."
    )
    quote = "were enrolled in the study (n = 828) the association replicated in two cohorts"
    assert where(quote, source) == [(len("were enrolled in the study (n = 828)"), 12)]
    assert V.omission(quote, source).gaps[0].text == "at baseline;"


def test_the_ends_of_the_quotation_may_stop_before_punctuation_and_not_inside_a_word():
    assert V.omission(JOINED, f'"{FIRST} {BETWEEN} {SECOND}".')
    assert plain(JOINED, f"un{FIRST} {BETWEEN} {SECOND}.")
    assert plain(JOINED, f"{FIRST} {BETWEEN} {SECOND}s.")


# --- a piece the source repeats ----------------------------------------------------------------


def test_a_repeated_piece_is_paired_with_the_occurrence_nearest_the_next_piece():
    a = "the model reached an accuracy of 0.94"
    b = "on the held-out split of the second dataset"
    between = "when evaluated, as measured"
    source = (
        f"First {a} in the pilot. "
        + "Filler sentence number one goes here. " * 50
        + f"Then {a} {between} {b}."
    )
    assert where(f"{a} {b}", source) == [(len(a), len(between))]
    assert V.omission(f"{a} {b}", source).passage == f"{a} {between} {b}"


def test_each_of_three_pieces_is_placed_as_late_as_the_next_allows():
    a = "alpha beta gamma delta epsilon"
    b = "zeta eta theta iota kappa lambda"
    c = "mu nu xi omicron pi rho sigma tau"
    source = f"{a} one two. {b} three. {a} four {b} five six {c}."
    assert where(f"{a} {b} {c}", source) == [(len(a), 4), (len(f"{a} {b}"), 8)]


# --- what was left out, and what the source reads ----------------------------------------------

RAW = (
    "BACKGROUND.  Higher circulating levels of the Protein were associated\n"
    "   with lower risk in the DISCOVERY cohort (odds ratio 0.81). That estimate held after\n"
    "adjustment.  Na\u00efve models agreed; and the association replicated in two independent\n"
    "cohorts of European ancestry. Colocalization supported a shared variant, with no\n"
    "evidence of horizontal pleiotropy in sensitivity analyses. Conclusions follow."
)


def test_a_one_token_gap_carries_that_token_and_the_passage_as_the_source_has_them():
    quote = "levels of the protein associated with lower risk"
    found = V.omission(quote, RAW)
    assert not found.folded
    assert [g.text for g in found.gaps] == ["were"]
    assert found.passage == "levels of the Protein were associated\n   with lower risk"
    assert RAW[RAW.index(found.passage) + found.gaps[0].offset :].startswith("were associated")


def test_a_gap_of_several_sentences_carries_them_in_the_sources_own_characters():
    quote = f"{FIRST} {SECOND}"
    found = V.omission(quote, RAW)
    left_out = (
        "in the DISCOVERY cohort (odds ratio 0.81). That estimate held after\n"
        "adjustment.  Na\u00efve models agreed; and"
    )
    assert not found.folded
    assert [g.text for g in found.gaps] == [left_out]
    start = RAW.index("Higher circulating")
    assert found.passage == RAW[start : RAW.index("ancestry.") + len("ancestry")]
    g = found.gaps[0]
    assert found.passage[g.offset : g.offset + len(g.text)] == left_out
    assert g.skipped == len(V.passage_fold(left_out))


def test_three_pieces_carry_two_gaps_and_one_passage_that_spans_all_three():
    found = V.omission(f"{FIRST} {SECOND}. {THIRD}", RAW)
    assert [g.text for g in found.gaps][1] == "Colocalization supported a shared variant,"
    assert found.gaps[0].text.startswith("in the DISCOVERY cohort") and found.gaps[0].text.endswith(
        "and"
    )
    assert found.passage == RAW[RAW.index("Higher") : RAW.index(" Conclusions") - 1]
    rebuilt, at = "", 0
    for g in found.gaps:
        assert found.passage[g.offset : g.offset + len(g.text)] == g.text
        rebuilt += found.passage[at : g.offset]
        at = g.offset + len(g.text)
    rebuilt += found.passage[at:]
    assert V.passage_fold(rebuilt) == V.passage_fold(f"{FIRST} {SECOND}. {THIRD}")


def test_the_result_carries_the_passage_and_the_gap_text_in_full_and_serializes(tmp_path):
    long_gap = " ".join(f"filler{i} sentence goes here." for i in range(200))
    source = f"Start. {FIRST} {long_gap} {SECOND}. End."
    r = V.check_one(JOINED, _src(tmp_path, source), None)
    assert r.gaps[0].text == long_gap
    assert r.passage == f"{FIRST} {long_gap} {SECOND}"
    assert not r.passage_folded
    assert long_gap not in r.detail
    assert (
        f"left out (800 tokens of the source, {len(long_gap):,} characters, the first "
        f"{V.SHOWN_GAP_CHARS} shown): [[{long_gap[: V.SHOWN_GAP_CHARS]}]]"
    ) in r.detail
    shown = r.detail.split("left-out text in [[ ]]): ")[1].splitlines()[0]
    assert f"({len(r.passage):,} characters, the first {V.SHOWN_PASSAGE_CHARS} shown" in r.detail
    assert shown.count("[[") == shown.count("]]") == 1
    assert len(shown.replace("[[", "").replace("]]", "")) == V.SHOWN_PASSAGE_CHARS
    again = json.loads(json.dumps(dataclasses.asdict(r)))
    assert again["passage"] == r.passage
    assert again["gaps"][0] == {
        "at": len(FIRST),
        "skipped": len(V.passage_fold(long_gap)),
        "text": long_gap,
        "offset": len(FIRST) + 1,
        "tokens": 800,
        "position": 12,
    }


def test_a_word_the_source_breaks_across_a_line_is_shown_as_the_source_breaks_it():
    source = f"{FIRST} in the dis-\ncovery cohort, and {SECOND}."
    found = V.omission(f"{FIRST} in the and {SECOND}", source)
    assert not found.folded
    assert [(g.text, g.skipped) for g in found.gaps] == [("dis-\ncovery cohort,", 17)]
    assert found.passage == source[:-1]


def test_text_whose_own_characters_cannot_be_recovered_is_shown_folded_and_says_so(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(V, "_stretch", lambda *a: None)
    r = V.check_one(JOINED, _src(tmp_path, RAW), None)
    assert r.passage_folded
    assert r.gaps[0].text == (
        "in the discovery cohort (odds ratio 0.81). that estimate held after adjustment. "
        "naive models agreed; and"
    )
    assert r.passage == V.passage_fold(RAW[RAW.index("Higher") : RAW.index("ancestry.") + 8])
    assert "shown folded, in lower case with single spaces" in r.detail


def test_text_in_the_sources_own_characters_draws_no_remark_about_folding(tmp_path):
    r = V.check_one(JOINED, _src(tmp_path, RAW), None)
    assert not r.passage_folded
    assert "DISCOVERY" in r.detail and "folded" not in r.detail


# --- a token is what a reader of the source sees between white space ----------------------------

LEAD = "the dose given to the treated group was"
TAIL = "in the second phase of the trial overall"


@pytest.mark.parametrize(
    ("in_source", "quoted"),
    [
        ("12\u202f500", "500"),
        ("12\u2009500", "12"),
        ("12\u00a0500", "500"),
        ("na\u00a8ive value", "ive value"),
        ("don\u00b4t respond", "don respond"),
        ("logit\x00difference", "logit"),
    ],
    ids=["narrow-no-break", "thin", "no-break", "diaeresis", "acute", "control"],
)
def test_a_space_the_fold_made_inside_a_token_is_not_a_place_to_cut(tmp_path, in_source, quoted):
    source = f"We note {LEAD} {in_source} {TAIL}."
    quote = f"{LEAD} {quoted} {TAIL}"
    assert " " in V.passage_fold(in_source)
    assert plain(quote, source)
    r = V.check_one(quote, _src(tmp_path, source), None)
    assert (r.state, r.reason, r.passage) == ("not found", "", "")


def test_a_no_break_space_between_a_number_and_a_word_is_white_space():
    source = f"We note {LEAD} 5\u00a0mg {TAIL}."
    assert [g.text for g in V.omission(f"{LEAD} 5 {TAIL}", source).gaps] == ["mg"]


@pytest.mark.parametrize(
    ("left_out", "tokens"),
    [
        ("very\x00strongly", 1),
        ("very-\nstrongly", 1),
        ("never\u00b4once", 1),
        ("12\u202f500", 1),
        ("very strongly", 2),
        ("very\u00a0strongly", 2),
    ],
)
def test_tokens_left_out_are_counted_as_the_source_has_them(left_out, tokens):
    source = f"X. {FIRST} {left_out} {SECOND} here."
    found = V.omission(JOINED, source)
    assert [(g.text, g.tokens) for g in found.gaps] == [(left_out, tokens)]


def test_position_counts_a_word_broken_across_a_line_as_one_token():
    source = f"X. {FIRST.replace('circulating', 'circu-' + chr(10) + 'lating')} strongly {SECOND}."
    (gap,) = V.omission(JOINED, source).gaps
    assert (gap.text, gap.tokens, gap.position) == ("strongly", 1, 12)


def test_a_combining_mark_after_the_last_letter_is_kept_with_it():
    cafe = "cafe\u0301"
    assert V.omission(JOINED, f"X. {FIRST} {cafe} {SECOND} here.").gaps[0].text == cafe
    ends_on_it = V.omission(
        f"{FIRST} with lower risk of the cafe",
        f"X. {FIRST} strongly associated with lower risk of the {cafe} here.",
    )
    assert ends_on_it.passage.endswith(cafe)
    assert not ends_on_it.folded


# --- which way of fitting is reported ----------------------------------------------------------

MODEL = "the model reached an accuracy of 0.94"
SPLIT = "on the held-out split of the second dataset"
FILLER = "Filler sentence number one goes here. " * 50


def test_the_shortest_passage_is_reported_wherever_in_the_source_it_is():
    source = f"{MODEL} x1. {FILLER}{SPLIT}. Later {MODEL} only {SPLIT}."
    found = V.omission(f"{MODEL} {SPLIT}", source)
    assert found.passage == f"{MODEL} only {SPLIT}"
    assert [(g.text, g.tokens) for g in found.gaps] == [("only", 1)]
    assert (found.fittings, found.unique) == (4, False)


def test_one_way_to_fit_is_unique():
    found = V.omission(JOINED, SOURCE)
    assert (found.fittings, found.unique, found.capped) == (1, True, False)


TREATMENT = "the treatment reduced mortality in the trial population"
MONTHS = "at twelve months of follow-up"
ARMS = "in both arms of the study"


def test_a_longer_way_that_contains_the_shortest_passage_leaves_it_unique():
    source = (
        f"Overall {TREATMENT} significantly {MONTHS} {ARMS}. Adverse events were similar {ARMS}."
    )
    found = V.omission(f"{TREATMENT} {MONTHS} {ARMS}", source)
    assert found.passage == f"{TREATMENT} significantly {MONTHS} {ARMS}"
    assert (found.fittings, found.unique) == (3, True)


def test_two_passages_neither_inside_the_other_are_not_unique():
    source = f"In men {TREATMENT} significantly {MONTHS}. In women {TREATMENT} not once {MONTHS}."
    found = V.omission(f"{TREATMENT} {MONTHS}", source)
    assert not found.unique and found.fittings > 1


def test_two_ways_spanning_the_same_passage_are_not_unique():
    found = V.omission(f"{FIRST} very {SECOND}", f"{FIRST} very very {SECOND}.")
    assert (found.fittings, found.unique) == (2, False)


def test_a_count_that_reaches_the_cap_is_capped_and_never_unique():
    sentence = "the quick brown fox jumps over the lazy dog near the old river bank today "
    words = sentence.split()
    quote = " ".join(" ".join(words[:7] + words[8:]) for _ in range(4))
    found = V.omission(quote, sentence * 40)
    assert (found.fittings, found.capped, found.unique) == (V.MAX_FITTINGS, True, False)


def test_the_detail_says_when_the_shortest_passage_is_not_the_only_candidate(tmp_path):
    source = f"In men {TREATMENT} significantly {MONTHS}. In women {TREATMENT} not once {MONTHS}."
    r = V.check_one(f"{TREATMENT} {MONTHS}", _src(tmp_path, source), None)
    assert "ways; this is the shortest passage, and not the only candidate" in r.detail
    one = V.check_one(JOINED, _src(tmp_path / "one", SOURCE), None)
    assert "ways" not in one.detail


# --- what it does to a run ---------------------------------------------------------------------


@pytest.fixture
def claims(tmp_path):
    _src(tmp_path)
    d = tmp_path / "claims"
    d.mkdir()
    f = d / "s.yaml"
    f.write_text(
        yaml.safe_dump(
            {
                "source": {"local": "source.txt"},
                "claims": {
                    "whole": {"quotes": [{"exact": FIRST}]},
                    "c": {"quotes": [{"exact": JOINED}]},
                },
            }
        )
    )
    return d


@pytest.mark.parametrize("flags", [[], ["--strict"]])
def test_verify_fails_on_an_omission_and_counts_it_under_not_found(claims, capsys, flags):
    assert cli.main(["verify", "--no-cache", *flags, "--claims", str(claims)]) == 1
    out = capsys.readouterr().out
    assert "1 in the source in pieces, with text left out between them" in out
    assert "1 not found." in out
    assert "all found." not in out


def test_pin_refuses_an_omission_and_writes_nothing(claims, capsys):
    f = claims / "s.yaml"
    before = f.read_text()
    assert pin.main([str(f), "--id", "joined", "--quote", JOINED]) == 1
    assert f.read_text() == before
    out = capsys.readouterr().out
    assert "not found" in out and "2 pieces" in out and "nothing written" in out
