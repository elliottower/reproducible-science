"""A quotation that is the source with text left out, and says nothing about the gap.

`not found` covers a misquotation and it covers this, and the two are repaired differently: a
misquotation by reading the source, this one by pinning the pieces apart. Every word of such a
quotation is in the source, so the report says so, says where the gap falls and how much was
left out, and stays `not found`.
"""

from __future__ import annotations

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
    assert V.omission(JOINED, SOURCE) == [Gap(len(FIRST), len(BETWEEN))]


def test_three_pieces_report_two_gaps_in_order():
    gaps = V.omission(f"{FIRST} {SECOND} {THIRD}", SOURCE)
    assert [g.at for g in gaps] == [len(FIRST), len(f"{FIRST} {SECOND}")]
    assert gaps[0].skipped == len(BETWEEN)
    assert gaps[1].skipped == len(". Colocalization supported a shared variant,")


def test_the_detail_shows_both_sides_of_the_gap_and_names_the_remedy(tmp_path):
    r = V.check_one(JOINED, _src(tmp_path), None)
    assert f"({len(BETWEEN)} characters of the source left out)" in r.detail
    assert "associated with lower risk" in r.detail
    assert "the association replicated" in r.detail
    assert "pin each piece" in r.detail and "ellipsis" in r.detail


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


def plain(quote: str, source: str = SOURCE) -> bool:
    m = V.resolve_in(quote, source)
    return m.state == "not found" and V.omission(quote, source) == []


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
