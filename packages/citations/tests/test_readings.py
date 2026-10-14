"""The second reading of a source at the exact tier: what `spacing_fold` and `rendered_fold` find.

Each case is a quotation that resolved only on the skeleton, as `normalized`, or not at all,
against a source that reads as the quotation does to anyone looking at it.
"""

from __future__ import annotations

import pytest
from citations import verify as V


@pytest.fixture(autouse=True)
def _alone(monkeypatch):
    monkeypatch.setenv("CITATIONS_NO_CACHE", "1")
    V.clear_caches()


def source(tmp_path, text, name="source.txt"):
    p = tmp_path / name
    p.write_text(text)
    return p


def test_a_real_hyphen_at_a_line_end_is_quoted_with_its_hyphen(tmp_path):
    p = source(tmp_path, "The screen covered open-\naccess publications from 2014 to 2020.\n")
    r = V.check_one("The screen covered open-access publications from 2014 to 2020.", p)
    assert r.state == "found"
    assert "normalized" not in r.warnings


def test_a_word_split_at_a_line_end_is_still_quoted_whole(tmp_path):
    p = source(tmp_path, "The screen covered all the publi-\ncations listed in the registry.\n")
    r = V.check_one("The screen covered all the publications listed in the registry.", p)
    assert r.state == "found"
    assert r.warnings == []


def test_a_hyphen_between_digits_at_a_line_end_never_joins_them(tmp_path):
    p = source(tmp_path, "The effect held in cohorts of size 10-\n12 across all sites studied.\n")
    joined = V.check_one("The effect held in cohorts of size 1012 across all sites studied.", p)
    assert joined.state == "not found"
    ranged = V.check_one("The effect held in cohorts of size 10-12 across all sites studied.", p)
    assert ranged.state == "found"
    assert "normalized" in ranged.warnings


def test_a_quotation_ending_where_a_column_line_breaks_is_not_called_truncated(tmp_path):
    # Layout sets the end of one column's line beside the start of the next line, so the
    # first reading welds `some-` and `class` into `someclass`.
    p = source(tmp_path, "and every conforming call returns some-\nclass of results it promised.\n")
    r = V.check_one("and every conforming call returns some", p)
    assert r.state == "found"
    assert "truncated" not in r.warnings


def test_a_quotation_cut_inside_a_word_is_still_truncated(tmp_path):
    p = source(tmp_path, "The model reached an accuracy of 0.95 on the held-out test set.\n")
    r = V.check_one("The model reached an accuracy of 0.9", p)
    assert "truncated" in r.warnings


def test_a_space_a_page_puts_before_punctuation_is_matched_exactly(tmp_path):
    p = source(tmp_path, "DVC records each stage in dvc.lock , including the hashes of outputs .\n")
    r = V.check_one("DVC records each stage in dvc.lock, including the hashes of outputs.", p)
    assert r.state == "found"
    assert "normalized" not in r.warnings


def test_closing_a_space_before_punctuation_keeps_every_mark(tmp_path):
    p = source(tmp_path, "The threshold was p = 0.05 , and the correction was applied once.\n")
    r = V.check_one("The threshold was p < 0.05, and the correction was applied once.", p)
    assert r.state == "not found"


LEAN = (
    "If a theorem or definition makes use of {leanRef}`Quot.sound`, it will show up in the\n"
    "{kw}`#print axioms` command.\n"
)


def test_a_lean_book_sentence_is_quoted_as_the_page_renders_it(tmp_path):
    p = source(tmp_path, LEAN, "AxiomsComputation.lean.txt")
    rendered = (
        "If a theorem or definition makes use of Quot.sound, it will show up in the "
        "#print axioms command."
    )
    r = V.check_one(rendered, p)
    assert r.state == "found"
    assert "normalized" not in r.warnings


def test_a_quotation_that_kept_the_markup_still_resolves(tmp_path):
    p = source(tmp_path, LEAN, "AxiomsComputation.lean.txt")
    kept = "makes use of {leanRef}`Quot.sound`, it will show up in the {kw}`#print axioms` command."
    assert V.check_one(kept, p).state == "found"


def test_inline_html_in_markdown_is_quoted_as_rendered(tmp_path):
    p = source(
        tmp_path,
        "Each mode supports both <b>cache verification</b> (millisecond hash comparison) and "
        "a full rerun.\n",
        "README.md",
    )
    r = V.check_one("Each mode supports both cache verification (millisecond hash comparison)", p)
    assert r.state == "found"
    assert "normalized" not in r.warnings


@pytest.mark.parametrize("name", ["page.html", "article.xml", "output"])
def test_markup_is_kept_where_the_file_is_not_a_page_source(tmp_path, name):
    # HTML is read by `html-text`, XML by `jats-text`, and a file with no suffix is what it says.
    p = source(
        tmp_path, "Each mode supports both <b>cache verification</b> on every capture.\n", name
    )
    assert V.check_one("Each mode supports both cache verification on every capture.", p).state == (
        "not found"
    )


def test_resolve_in_strips_markup_only_when_asked():
    text = "makes use of {leanRef}`Quot.sound`, it will show up in the listing printed later."
    quote = "makes use of Quot.sound, it will show up in the listing printed later."
    assert V.resolve_in(quote, text).state == "not found"
    assert V.resolve_in(quote, text, rendered=True).state == "found"
