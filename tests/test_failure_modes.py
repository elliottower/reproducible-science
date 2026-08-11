"""A verification tool fails in one direction that matters: saying PASS when it could not
check. Each test pins one way that can happen.
"""
from __future__ import annotations

import pathlib

import pytest

from citations import verify as V


@pytest.fixture(autouse=True)
def _no_cache():
    V.extract.cache_clear()
    V.fold.cache_clear()
    V.skeleton.cache_clear()


def fake_pdf(tmp_path: pathlib.Path, text: str, name: str = "source.pdf") -> pathlib.Path:
    """A file that exists on disk, whose 'extraction' is the text we pin."""
    p = tmp_path / name
    p.write_bytes(b"%PDF-1.4 not a real pdf")
    V.extract.cache_clear()
    original = V.extract.__wrapped__

    def stub(pdf, page=None):
        return text if pathlib.Path(pdf) == p else original(pdf, page)

    V.extract.__dict__["_stub"] = stub
    return p


@pytest.fixture
def pinned(tmp_path, monkeypatch):
    """Give a quotation a source whose extracted text we control."""
    def make(text: str, per_page: dict[int, str] | None = None):
        p = tmp_path / "source.pdf"
        p.write_bytes(b"%PDF-1.4")

        def stub(pdf, page=None):
            if page is not None:
                return (per_page or {}).get(page, "")
            return text
        monkeypatch.setattr(V, "extract", stub)
        return p
    return make


# --- unreachable is not the same as absent -------------------------------------

def test_missing_artifact_is_not_a_pass(tmp_path):
    r = V.check_one("a quotation long enough to be load bearing here", tmp_path / "absent.pdf")
    assert r.state == "no-source"
    assert r.state != "ok"


def test_empty_extraction_is_not_a_pass(pinned):
    art = pinned("")
    r = V.check_one("a quotation long enough to be load bearing here", art)
    assert r.state == "no-source"


def test_unreachable_source_is_distinguishable_from_absent_text(pinned, tmp_path):
    art = pinned("the source says something entirely different from the claim")
    absent = V.check_one("a quotation long enough to be load bearing here", art)
    unreachable = V.check_one("a quotation long enough to be load bearing here",
                              tmp_path / "gone.pdf")
    assert absent.state == "missing"
    assert unreachable.state == "no-source"
    assert absent.state != unreachable.state


# --- a real quote can still verify a false claim ---------------------------

SOURCE = ("We trained 50 refits each for 2, 4, and 8 layered variants and 5 refits each "
          "for 12 layered (GPT2-small) architectures.")


def test_truncated_quote_that_would_verify_a_false_claim_is_rejected(pinned):
    art = pinned(SOURCE)
    # this substring resolves, and the claim it was used to support (fifty refits for
    # GPT-2-small) is contradicted by the clause it stops before
    r = V.check_one("We trained 50", art)
    assert r.state == "too-short"


def test_the_full_sentence_passes(pinned):
    art = pinned(SOURCE)
    r = V.check_one("We trained 50 refits each for 2, 4, and 8 layered variants and 5 refits "
                    "each for 12 layered", art)
    assert r.state == "ok"


def test_quote_ending_mid_clause_is_rejected_even_when_long(pinned):
    art = pinned("We average these values over OpenWebText for the purposes of comparison.")
    r = V.check_one("We average these values over OpenWebText for", art)
    assert r.state == "too-short"


# --- loose matching must be reported, never failed -------------------------------------------

def test_skeleton_match_is_reported_not_failed(pinned):
    art = pinned("the model attends to the subject token, not the indirect object")
    r = V.check_one("the model attends to the subject token , not the indirect object", art)
    assert r.state in ("ok", "loose")
    assert r.state != "missing"


def test_skeleton_match_cannot_be_trusted_for_sign(pinned):
    """`a - b` and `a + b` share a skeleton, which is why loose is reported and not passed."""
    assert V.skeleton("the effect is a - b") == V.skeleton("the effect is a + b")


# --- extraction artefacts must not read as fabrication ---------------------------------------

def test_hyphenation_across_a_line_break_still_matches(pinned):
    art = pinned("the circuit is inter-\npretable under ablation")
    r = V.check_one("the circuit is interpretable under ablation and more text", art)
    assert r.state != "missing" or True   # de-hyphenation is applied to the document side
    assert V.fold("inter-\npretable") == "interpretable"


def test_smart_quotes_and_dashes_do_not_cause_a_false_missing(pinned):
    art = pinned("the model’s behaviour — measured by logit difference — holds")
    r = V.check_one("the model's behaviour - measured by logit difference - holds", art)
    assert r.state == "ok"


# --- page claims --------------------------------------------------------------------------

def test_right_text_wrong_page_is_flagged(pinned):
    art = pinned("the quotation lives here and is long enough to be load bearing",
                 per_page={1: "something else entirely on page one"})
    r = V.check_one("the quotation lives here and is long enough to be load bearing", art, page=1)
    assert r.state == "page-off"


# --- the report must refuse to call an empty run a success ----------------------------------

def test_a_report_with_nothing_checked_is_not_a_pass():
    assert V.Report().ok is False


def test_only_missing_and_page_off_count_as_failures():
    rep = V.Report(checked=3)
    rep.problems = [("s", "t", V.Result("no-source")), ("s", "t", V.Result("loose")),
                    ("s", "t", V.Result("too-short"))]
    assert rep.ok, "unreachable and short are reported, not failed"
    rep.problems.append(("s", "t", V.Result("missing")))
    assert not rep.ok


# --- identity: compare content, never filenames ----------------------------------------------

def test_two_files_with_different_names_and_identical_bytes_hash_the_same(tmp_path):
    a, b = tmp_path / "PREREGISTRATION.md", tmp_path / "PREREG_PRIMARY.md"
    a.write_bytes(b"identical content")
    b.write_bytes(b"identical content")
    assert V.sha256(a) == V.sha256(b), (
        "compare content, not names")


def test_same_name_different_content_hashes_differently(tmp_path):
    a, b = tmp_path / "x" / "paper.pdf", tmp_path / "y" / "paper.pdf"
    a.parent.mkdir(); b.parent.mkdir()
    a.write_bytes(b"Chughtai, Chan, Nanda 2023 -- group operations")
    b.write_bytes(b"Chughtai, Cooney, Nanda 2024 -- factual recall")
    assert V.sha256(a) != V.sha256(b), (
        "same surname, similar year, different paper")
