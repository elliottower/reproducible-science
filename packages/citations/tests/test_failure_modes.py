"""A verification tool fails in one direction that matters: saying a passage was checked when
it was not. These pin the ways that can happen.
"""

from __future__ import annotations

import pytest
from citations import verify as V


@pytest.fixture(autouse=True)
def _no_cache():
    for f in (V.extract, V.fold, V.skeleton):
        if hasattr(f, "cache_clear"):
            f.cache_clear()


@pytest.fixture
def pinned(tmp_path, monkeypatch):
    def make(text: str, per_page: dict[int, str] | None = None):
        p = tmp_path / "source.pdf"
        p.write_bytes(b"%PDF-1.4")

        def stub(pdf, page=None, extract_cmd=None, allowed=None):
            if page is not None:
                return (per_page or {}).get(page, "")
            return text

        monkeypatch.setattr(V, "extract", stub)
        return p

    return make


LONG = "a passage long enough that it carries its own qualifiers without truncation"


# --- an unreadable source is never a pass ----------------------------------------------------


def test_absent_file_is_unchecked(tmp_path):
    assert V.check_one(LONG, tmp_path / "absent.pdf").state == "unchecked"


def test_file_that_yields_no_text_is_unchecked(pinned):
    assert V.check_one(LONG, pinned("")).state == "unchecked"


def test_unreadable_is_distinct_from_absent_text(pinned, tmp_path):
    absent = V.check_one(LONG, pinned("the source says something else entirely"))
    unreadable = V.check_one(LONG, tmp_path / "gone.pdf")
    assert absent.state == "not found"
    assert unreadable.state == "unchecked"


def test_unchecked_carries_the_reason(tmp_path, pinned):
    assert V.check_one(LONG, tmp_path / "gone.pdf").detail == "file not found"
    assert V.check_one(LONG, pinned("")).detail == "no text extracted"


# --- a truncated quote is found, and flagged -------------------------------------------------

SOURCE = (
    "We trained 50 refits each for 2, 4, and 8 layered variants and 5 refits each "
    "for 12 layered (GPT2-small) architectures."
)


def test_truncated_quote_is_found_but_warned(pinned):
    r = V.check_one("We trained 50", pinned(SOURCE))
    assert r.state == "found", "it is in the source; saying otherwise would be false"
    assert "short" in r.warnings, "but the next clause changes what it means"


def test_quoting_through_the_qualifier_is_clean(pinned):
    r = V.check_one(
        "We trained 50 refits each for 2, 4, and 8 layered variants and 5 refits "
        "each for 12 layered",
        pinned(SOURCE),
    )
    assert r.state == "found"
    assert r.warnings == []


def test_ending_mid_clause_warns_even_when_long(pinned):
    src = "We average these values over OpenWebText for the purposes of comparison."
    r = V.check_one("We average these values over OpenWebText for", pinned(src))
    assert "short" in r.warnings


# --- normalization is a note on how it matched, not a different outcome ----------------------


def test_punctuation_difference_still_counts_as_found(pinned):
    r = V.check_one(
        "the model attends to the subject token , not the indirect object",
        pinned("the model attends to the subject token, not the indirect object"),
    )
    assert r.state == "found"


def test_normalized_match_distinguishes_a_sign():
    """It once did not. The fallback stripped every non-alphanumeric character, so a sign, an
    inequality and a decimal point all vanished before the comparison."""
    assert V.skeleton("the effect is a - b") != V.skeleton("the effect is a + b")


@pytest.mark.parametrize(
    "quoted",
    [
        "the correlation was -0.42",
        "the effect reached p < 0.05",
        "the effect reached p > 0.05",
        "we used n >= 50 participants",
        "accuracy fell to 0.042",
    ],
)
def test_a_misquoted_number_is_not_found(pinned, quoted):
    """Each of these differs from the source only in characters the fallback used to delete."""
    source = "the correlation was 0.42 and the effect reached p = 0.05 with n = 50 participants"
    assert V.check_one(quoted, pinned(source)).state == "not found"


def test_a_quotation_that_folds_away_entirely_is_not_found(pinned):
    """`"" in doc` is True, so an empty folded quote once matched every source."""
    assert V.check_one("\x01\x02", pinned("any text at all")).state == "not found"


def test_an_extractor_dropping_a_space_is_still_found(pinned):
    """What the fallback is actually for: extractors join and split words, and nothing else."""
    result = V.check_one("the logit difference was large", pinned("the logitdifference was large"))
    assert result.state == "found"
    assert "normalized" in result.warnings


def test_smart_quotes_and_dashes_are_not_a_miss(pinned):
    r = V.check_one(
        "the model's behaviour - measured by logit difference - holds",
        pinned("the model’s behaviour — measured by logit difference — holds"),
    )
    assert r.state == "found"


def test_hyphenation_across_a_line_break_is_normalized():
    assert V.fold("inter-\npretable") == "interpretable"


def test_glyph_codes_from_a_figure_do_not_hide_the_passage(pinned):
    # pdftotext emits a figure's embedded font as raw UTF-16 glyph codes. They land mid-page and
    # must not swallow the surrounding prose.
    junk = "\x00$\x00F\x00F\x00X\x00U\x00D\x00F"
    r = V.check_one(
        "ranks first in Language, eighth in Vision",
        pinned(f"we observe that CKA {junk} ranks first in Language, eighth in Vision"),
    )
    assert r.state == "found"


def test_control_characters_separate_words_rather_than_joining_them():
    # deleting them outright would manufacture a word that is in neither text
    assert V.fold("logit\x00difference") == "logit difference"
    assert V.fold("a\x13b\x11c") == "a b c"


def test_page_break_still_reads_as_whitespace():
    assert V.fold("end of page\x0cstart of next") == "end of page start of next"


# --- a page claim that is wrong does not make the passage absent -----------------------------


def test_right_passage_wrong_page_is_found_and_warned(pinned):
    art = pinned(LONG, per_page={1: "something else entirely on page one"})
    r = V.check_one(LONG, art, page=1)
    assert r.state == "found"
    assert "page" in r.warnings


# --- what counts as failure ------------------------------------------------------------------


def test_a_run_that_measured_nothing_is_not_a_pass():
    assert V.Report().ok is False


def test_only_not_found_is_a_failure():
    rep = V.Report(checked=3)
    rep.problems = [
        ("s", "t", V.Result("unchecked")),
        ("s", "t", V.Result("found", warnings=["short"])),
        ("s", "t", V.Result("found", warnings=["normalized"])),
    ]
    assert rep.ok, "unchecked and warned are reported, not failed"
    rep.problems.append(("s", "t", V.Result("not found")))
    assert not rep.ok


# --- identity is content, never a filename ---------------------------------------------------


def test_same_bytes_different_names_hash_alike(tmp_path):
    a, b = tmp_path / "PREREGISTRATION.md", tmp_path / "PREREG_PRIMARY.md"
    a.write_bytes(b"identical")
    b.write_bytes(b"identical")
    assert V.sha256(a) == V.sha256(b)


def test_same_name_different_bytes_hash_apart(tmp_path):
    a, b = tmp_path / "x" / "paper.pdf", tmp_path / "y" / "paper.pdf"
    a.parent.mkdir()
    b.parent.mkdir()
    a.write_bytes(b"Chughtai, Chan, Nanda 2023 - group operations")
    b.write_bytes(b"Chughtai, Cooney, Nanda 2024 - factual recall")
    assert V.sha256(a) != V.sha256(b)


# --- a quote can be genuinely present and still misstate the source ----------------------------


def _src(tmp_path, text):
    f = tmp_path / "src.txt"
    f.write_text(text)
    return f


def test_a_quote_cut_mid_number_is_flagged(tmp_path):
    f = _src(tmp_path, "The model reached an accuracy of 0.95 on the held-out split.")
    r = V.check_one("The model reached an accuracy of 0.9", f, None)
    assert r.state == "found", "it is genuinely in the source; the point is the warning"
    assert "truncated" in r.warnings, "0.9 quoted from 0.95 carried no signal"


def test_a_quote_cut_mid_word_is_flagged(tmp_path):
    f = _src(tmp_path, "We evaluated the catalogue of every registered variant.")
    r = V.check_one("We evaluated the catalog", f, None)
    assert "truncated" in r.warnings


def test_a_quote_ending_on_a_whole_word_is_not_flagged(tmp_path):
    f = _src(tmp_path, "The model reached an accuracy of 0.95 on the held-out split.")
    r = V.check_one("The model reached an accuracy of 0.95", f, None)
    assert "truncated" not in r.warnings


def test_a_quote_ending_in_punctuation_is_not_flagged(tmp_path):
    f = _src(tmp_path, "Effects were rare. We report them anyway.")
    r = V.check_one("Effects were rare.", f, None)
    assert "truncated" not in r.warnings


def test_a_quote_that_lands_cleanly_somewhere_is_not_flagged(tmp_path):
    """One occurrence cutting a word does not matter if another occurrence does not."""
    f = _src(tmp_path, "the catalogue is long. the catalog is short.")
    r = V.check_one("the catalog", f, None)
    assert r.state == "found"
    assert "truncated" not in r.warnings


def test_truncation_is_independent_of_length(tmp_path):
    """A long quote ending one digit early is the convincing version, and `short` will not fire."""
    body = (
        "We describe a procedure that was applied to every held-out example without "
        "exception, and the resulting accuracy was 0.87"
    )
    f = _src(tmp_path, body + "4 across all folds.")
    r = V.check_one(body, f, None)
    assert "short" not in r.warnings, "quote is long enough that `short` says nothing"
    assert "truncated" in r.warnings
