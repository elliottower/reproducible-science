"""Conditions an audit found reported wrongly.

Each is a case where the tool agreed with something it had not established: a fabricated
record verified from a hand-written cache, an entry checked against its neighbour's DOI, a
green CI run over quotations nothing had read.
"""

from __future__ import annotations

import pytest
from citations import bibtex
from citations import resolve as R
from citations.models import Record
from citations.services import Candidate

# -- a regex cannot split a .bib ------------------------------------------------------------

STYLES = """@article{good1,
  title = {A Genuine Paper},
  author = {Smith, Jane},
  doi = {10.1/aaa}
}

@article{suspect,
  title = {Paper With The Wrong Author List},
  author = {Jones, Bob},
  doi = {10.1038/s41586-021-03819-3},
  }

@article{good2,
  title = {Another},
  author = {Roe, Jane},
  doi = {10.1/bbb}}
"""


def test_every_closing_brace_style_yields_its_own_entry():
    """The old pattern required a brace at column zero. An entry closing any other way ran
    into the next one, so an entry vanished and its neighbour was audited against the wrong
    DOI and the wrong authors."""
    found = bibtex.entries(STYLES)
    assert [key for _, key, _ in found] == ["good1", "suspect", "good2"]


@pytest.mark.parametrize(
    "key,doi",
    [("good1", "10.1/aaa"), ("suspect", "10.1038/s41586-021-03819-3"), ("good2", "10.1/bbb")],
)
def test_no_entry_inherits_its_neighbours_doi(key, doi):
    body = next(b for _, k, b in bibtex.entries(STYLES) if k == key)
    assert doi in body


def test_an_unbalanced_entry_costs_only_itself():
    truncated = STYLES + "\n@article{broken,\n  title = {Never closed},\n"
    assert [key for _, key, _ in bibtex.entries(truncated)] == ["good1", "suspect", "good2"]


def test_a_latin_1_bibliography_is_read_rather_than_raising(tmp_path):
    """Bibliographies predate UTF-8 and are still written in latin-1."""
    path = tmp_path / "refs.bib"
    path.write_bytes("@article{a, author = {Ang\xe9lique}, doi = {10.1/x}}\n".encode("latin-1"))
    assert [key for _, key, _ in bibtex.entries(bibtex.read(path))] == ["a"]


# -- an identifier is not a guess -----------------------------------------------------------


def test_a_record_with_no_author_and_no_year_is_not_matched_on_title():
    """`want` is empty without authors and `year_ok` passes an empty year, so title similarity
    was the only guard left -- on exactly the records this runs over, the ones with no
    identifier. `Attention Is All You Need` scores 0.88 against `Is Attention All You Need?`,
    a different paper by different authors."""
    record = Record(slug="x", title="Attention Is All You Need", authors=[], year="")
    candidate = Candidate(
        title="Is Attention All You Need?",
        surnames=frozenset({"merrill"}),
        year="2023",
        identifier=("arxiv", "2309.99999"),
        venue="arXiv",
    )
    assert R.match(record, [candidate]) is None


def test_a_record_with_a_year_is_still_matched():
    record = Record(slug="x", title="Attention Is All You Need", authors=[], year="2017")
    candidate = Candidate(
        title="Attention Is All You Need",
        surnames=frozenset(),
        year="2017",
        identifier=("arxiv", "1706.03762"),
        venue="NeurIPS",
    )
    assert R.match(record, [candidate]) == ("arxiv", "1706.03762")
