"""A quotation enters a claims file only if the pinned source contains it.

The error this closes is not exotic. A passage is transcribed from a viewer, a ligature or a
line-wrapped hyphen differs from what the extractor produces, and the file is written anyway.
`verify` reports it later, over a corpus, against a file nobody is looking at. Resolving at
write time moves the report to the moment the author can still see the source.
"""

from __future__ import annotations

import pathlib

import pytest
import yaml
from citations import pin

PASSAGE = "the range of changes over which a relationship remains invariant"


@pytest.fixture
def paper(tmp_path):
    (tmp_path / "source.txt").write_text(
        "A generalization is invariant if it continues to hold: " + PASSAGE + " is its domain.\n"
    )
    d = tmp_path / "claims"
    d.mkdir()
    f = d / "woodward.yaml"
    f.write_text("source:\n  citation: woodward\n  local: source.txt\nclaims: {}\n")
    return f


def read(f: pathlib.Path) -> dict:
    return yaml.safe_load(f.read_text())


def test_a_passage_in_the_source_is_written(paper, capsys):
    assert pin.main([str(paper), "--id", "domain", "--quote", PASSAGE]) == 0
    doc = read(paper)
    assert doc["claims"]["domain"]["quotes"][0]["exact"] == PASSAGE
    assert "added" in capsys.readouterr().out


def test_a_passage_not_in_the_source_is_refused_and_nothing_is_written(paper, capsys):
    before = paper.read_text()
    assert pin.main([str(paper), "--id", "nope", "--quote", "a sentence the source lacks"]) == 1
    assert paper.read_text() == before
    out = capsys.readouterr().out
    assert "not found" in out
    assert "nothing written" in out


def test_a_characterization_needs_an_owner(paper, capsys):
    before = paper.read_text()
    code = pin.main([str(paper), "--id", "x", "--quote", PASSAGE, "--says", "something"])
    assert code == 2
    assert paper.read_text() == before
    assert "--says needs --whose" in capsys.readouterr().out


def test_the_reading_is_written_with_its_owner(paper):
    pin.main(
        [
            str(paper),
            "--id",
            "domain",
            "--quote",
            PASSAGE,
            "--says",
            "The operating envelope is a domain of invariance",
            "--whose",
            "ours",
        ]
    )
    reading = read(paper)["claims"]["domain"]["interpretation"]
    assert reading["whose"] == "ours"
    assert "envelope" in reading["says"]


def test_a_contested_reading_carries_its_contest(paper):
    pin.main(
        [
            str(paper),
            "--id",
            "domain",
            "--quote",
            PASSAGE,
            "--says",
            "A reading someone disputes",
            "--whose",
            "othercite",
            "--status",
            "contested",
            "--contest",
            "The phrase sits elsewhere.",
        ]
    )
    reading = read(paper)["claims"]["domain"]["interpretation"]
    assert reading["status"] == "contested"
    assert reading["contest"]


def test_an_identifier_the_file_already_uses_is_refused(paper):
    pin.main([str(paper), "--id", "domain", "--quote", PASSAGE])
    with pytest.raises(pin.PinRefused):
        pin.main([str(paper), "--id", "domain", "--quote", PASSAGE])


def test_check_resolves_and_writes_nothing(paper, capsys):
    before = paper.read_text()
    assert pin.main([str(paper), "--id", "domain", "--quote", PASSAGE, "--check"]) == 0
    assert paper.read_text() == before
    assert "would add" in capsys.readouterr().out


def test_what_was_already_in_the_file_survives(paper):
    pin.main([str(paper), "--id", "one", "--quote", PASSAGE])
    pin.main([str(paper), "--id", "two", "--quote", "A generalization is invariant"])
    doc = read(paper)
    assert set(doc["claims"]) == {"one", "two"}
    assert doc["source"]["citation"] == "woodward"
