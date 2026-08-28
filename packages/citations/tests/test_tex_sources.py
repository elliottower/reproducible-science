"""A LaTeX source is read by the reader LaTeX obviously wants.

A `.pdf` has always had a default reader. A `.tex` did not, so it reached `pdftotext`, answered
`Syntax Error: Couldn't read xref table`, and every quotation in it graded `unchecked` until the
author declared `detex` by hand. That is the most common manuscript format in the domain these
tools serve.
"""

from __future__ import annotations

import shutil

import pytest
from citations import verify as V

detex = pytest.mark.skipif(shutil.which("detex") is None, reason="detex is not installed")

TEX = r"""\documentclass{article}
\begin{document}
The authors report that \emph{the effect} was measured at 0.42 across every
replication attempted, which is the number this claim rests upon.
\end{document}
"""

PASSAGE = "the effect was measured at 0.42 across every replication attempted"


@pytest.fixture(autouse=True)
def _no_cache():
    V.clear_caches()


def _tex(tmp_path, text=TEX, name="paper.tex"):
    p = tmp_path / name
    p.write_text(text)
    return p


@detex
def test_a_tex_source_resolves_without_declaring_an_extractor(tmp_path):
    r = V.check_one(PASSAGE, _tex(tmp_path), None)
    assert r.state == "found"


@detex
def test_the_reader_it_chose_is_named_on_the_result(tmp_path):
    """Chosen is not the same as hidden: a decision resting on a reader says which one."""
    assert V.check_one(PASSAGE, _tex(tmp_path), None).extractor == "detex"


@detex
def test_markup_between_the_words_does_not_break_the_quotation(tmp_path):
    """`\\emph{the effect}` is the quoted words plus markup, and detex is what removes it."""
    assert V.check_one("that the effect was measured", _tex(tmp_path), None).state == "found"


@detex
def test_a_declared_extractor_still_wins(tmp_path):
    """An author naming a renderer has said which program produces the text they quote."""
    r = V.check_one(PASSAGE, _tex(tmp_path), None, extract_cmd="detex")
    assert r.state == "found"
    assert r.extractor == "detex"


@detex
def test_a_passage_absent_from_a_tex_source_is_reported_absent_not_unchecked(tmp_path):
    """The point of reading it at all: `not found` becomes reachable for LaTeX."""
    r = V.check_one("a passage that appears nowhere in this document at all", _tex(tmp_path), None)
    assert r.state == "not found"


def test_a_pdf_is_unaffected(tmp_path):
    """The suffix table adds a case; it does not take one away."""
    assert ".pdf" not in V.BY_SUFFIX
    assert V.BY_SUFFIX[".tex"] == "detex"


def test_the_suffix_can_only_choose_a_reader_that_runs_unasked():
    """The suffix grants no program a right it did not already have.

    `check_one` passes the caller's `allowed` only where a command was declared -- a source
    declaring none "must not start reaching them for a new one" -- so the undeclared path always
    sees `DEFAULT_EXTRACTORS`. That makes this relationship the actual guarantee: every reader
    the suffix table can choose is one the default allowlist already permits. A future entry
    naming something else would be granting consent the caller never gave.
    """
    assert set(V.BY_SUFFIX.values()) <= V.DEFAULT_EXTRACTORS


def test_a_plain_text_source_is_still_read_off_disk(tmp_path):
    p = tmp_path / "note.md"
    p.write_text(f"Before. {PASSAGE}. After.")
    r = V.check_one(PASSAGE, p, None)
    assert r.state == "found"
    assert r.extractor == V.PLAIN_TEXT
