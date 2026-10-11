"""A quotation enters a claims file only if the pinned source contains it.

The error this closes is not exotic. A passage is transcribed from a viewer, a ligature or a
line-wrapped hyphen differs from what the extractor produces, and the file is written anyway.
`verify` reports it later, over a corpus, against a file nobody is looking at. Resolving at
write time moves the report to the moment the author can still see the source.
"""

from __future__ import annotations

import hashlib
import pathlib

import pytest
import yaml
from citations import cli, pin
from citations import verify as V

PASSAGE = "the range of changes over which a relationship remains invariant"


@pytest.fixture(autouse=True)
def _no_cache():
    V.clear_caches()


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


def test_a_source_recording_nowhere_to_fetch_it_from_is_named_when_pinning(paper, capsys):
    assert pin.main([str(paper), "--id", "domain", "--quote", PASSAGE]) == 0
    assert "records no url, doi or arxiv id" in capsys.readouterr().out


def test_a_source_with_a_doi_draws_no_remark_about_fetching(paper, capsys):
    paper.write_text(paper.read_text().replace("  local:", "  doi: 10.1000/x\n  local:"))
    assert pin.main([str(paper), "--id", "domain", "--quote", PASSAGE]) == 0
    assert "arxiv id" not in capsys.readouterr().out


# --- a passage the source repeats is pinned by naming the occurrence ---------------------------

REPEATED = "the model reached an accuracy of 0.94 on the split"
THRICE = (
    f"In the pilot {REPEATED}. We repeated the procedure on new data. "
    f"In the replication {REPEATED}. A third laboratory ran it again, and "
    f"in their hands {REPEATED} as well."
)


@pytest.fixture
def repeating(tmp_path):
    def make(text: str) -> pathlib.Path:
        (tmp_path / "source.txt").write_text(text)
        d = tmp_path / "claims"
        d.mkdir()
        f = d / "runs.yaml"
        digest = hashlib.sha256(text.encode()).hexdigest()
        f.write_text(
            f"source:\n  citation: runs\n  local: source.txt\n  sha256: {digest}\nclaims: {{}}\n"
        )
        return f

    return make


def strict(f: pathlib.Path, capsys) -> tuple[int, str]:
    capsys.readouterr()
    code = cli.main(["verify", "--strict", "--no-cache", "--claims", str(f.parent)])
    return code, capsys.readouterr().out


def test_a_repeated_passage_is_still_refused_and_the_refusal_names_the_flag(repeating, capsys):
    f = repeating(THRICE)
    before = f.read_text()
    assert pin.main([str(f), "--id", "c", "--quote", REPEATED]) == 1
    assert f.read_text() == before
    out = capsys.readouterr().out
    assert "ambiguous" in out and "occurs 3 times" in out
    assert "--occurrence" in out
    assert "nothing written" in out


@pytest.mark.parametrize(
    ("occurrence", "before", "after"),
    [(1, "in the pilot ", ". we"), (2, "the replication ", ". a"), (3, "hands ", " as well.")],
)
def test_each_occurrence_is_written_with_anchors_that_verify_strictly(
    repeating, capsys, occurrence, before, after
):
    f = repeating(THRICE)
    assert (
        pin.main([str(f), "--id", "c", "--quote", REPEATED, "--occurrence", str(occurrence)]) == 0
    )
    q = read(f)["claims"]["c"]["quotes"][0]
    assert q["exact"] == REPEATED
    assert q["prefix"].endswith(before)
    assert q["suffix"].startswith(after)
    assert V.passage_fold(THRICE).count(V.passage_fold(q["prefix"] + REPEATED + q["suffix"])) == 1
    code, out = strict(f, capsys)
    assert code == 0, out
    assert "all found." in out


def test_the_three_occurrences_get_three_different_pairs_of_anchors(repeating):
    f = repeating(THRICE)
    for n in (1, 2, 3):
        assert pin.main([str(f), "--id", f"c{n}", "--quote", REPEATED, "--occurrence", str(n)]) == 0
    claims = read(f)["claims"]
    pairs = {(c["quotes"][0]["prefix"], c["quotes"][0]["suffix"]) for c in claims.values()}
    assert len(pairs) == 3


def test_an_occurrence_the_source_does_not_have_is_refused(repeating, capsys):
    f = repeating(THRICE)
    before = f.read_text()
    assert pin.main([str(f), "--id", "c", "--quote", REPEATED, "--occurrence", "4"]) == 1
    assert f.read_text() == before
    out = capsys.readouterr().out
    assert "occurs 3 times" in out and "no occurrence 4" in out
    assert "nothing written" in out


@pytest.mark.parametrize("n", ["0", "-1"])
@pytest.mark.parametrize("quote", [REPEATED, "a passage the source does not have at all"])
def test_an_occurrence_below_one_is_refused_whatever_the_passage(repeating, capsys, n, quote):
    f = repeating(THRICE)
    before = f.read_text()
    assert pin.main([str(f), "--id", "c", "--quote", quote, "--occurrence", n]) == 2
    assert f.read_text() == before
    assert "counts from 1" in capsys.readouterr().out


def test_an_occurrence_below_one_is_refused_before_the_source_is_read(repeating, capsys):
    f = repeating(THRICE)
    (f.parent.parent / "source.txt").unlink()
    assert pin.main([str(f), "--id", "c", "--quote", REPEATED, "--occurrence", "0"]) == 2
    assert "unchecked" not in capsys.readouterr().out


def test_white_space_at_the_ends_of_the_quotation_is_not_written_or_anchored(repeating, capsys):
    f = repeating("first it reached 0.94. then it reached 0.94, ok")
    assert pin.main([str(f), "--id", "c", "--quote", " it reached 0.94 ", "--occurrence", "1"]) == 0
    q = read(f)["claims"]["c"]["quotes"][0]
    assert q["exact"] == "it reached 0.94"
    assert (q["prefix"], q["suffix"][:6]) == ("first ", ". then")
    code, out = strict(f, capsys)
    assert code == 0, out


def test_a_passage_matched_only_with_spacing_ignored_is_anchored_in_that_text(repeating, capsys):
    f = repeating(
        "In run one the logitdifference was large and stable. "
        "In run two the logitdifference was large and noisy."
    )
    quote = "the logit difference was large"
    assert pin.main([str(f), "--id", "c", "--quote", quote, "--occurrence", "2"]) == 0
    q = read(f)["claims"]["c"]["quotes"][0]
    assert " " not in q["prefix"] + q["suffix"]
    assert q["suffix"].startswith("andnoisy")
    code, out = strict(f, capsys)
    assert code == 0, out
    assert "normalized" in out


def test_anchors_past_the_limit_are_refused_and_the_refusal_says_why(repeating, capsys):
    block = f"In every run {REPEATED}. " + "Filler sentence number one goes here. " * 60
    assert len(block) > 2 * V.MAX_ANCHOR_CHARS
    f = repeating(block * 3)
    before = f.read_text()
    assert pin.main([str(f), "--id", "c", "--quote", REPEATED, "--occurrence", "2"]) == 1
    assert f.read_text() == before
    out = capsys.readouterr().out
    assert f"{V.MAX_ANCHOR_CHARS:,} characters" in out and "by hand" in out
    assert "nothing written" in out


def test_single_out_returns_no_anchor_past_the_limit_and_a_short_one_where_it_will_do():
    block = f"In every run {REPEATED}. " + "Filler sentence number one goes here. " * 60
    for n in (1, 2, 3):
        assert V.single_out(REPEATED, block * 3, n) is None
    assert V.single_out(REPEATED, f"Once, {REPEATED}. " + block * 3, 1) == (
        "once, ",
        ". in every run the",
    )


def test_an_occurrence_in_fully_duplicated_blocks_is_singled_out(repeating, capsys):
    block = f"Methods. We trained it once. Results. In every run {REPEATED}. Discussion follows."
    f = repeating(f"{block} {block}")
    for n in (1, 2):
        assert pin.main([str(f), "--id", f"c{n}", "--quote", REPEATED, "--occurrence", str(n)]) == 0
    first, second = (read(f)["claims"][k]["quotes"][0] for k in ("c1", "c2"))
    doc = V.passage_fold(f"{block} {block}")
    passage = V.passage_fold(REPEATED)
    for q, nth in ((first, doc.find(passage)), (second, doc.rfind(passage))):
        anchored = V.passage_fold(q["prefix"] + REPEATED + q["suffix"])
        assert doc.count(anchored) == 1
        assert doc.find(anchored) + len(q["prefix"]) == nth
    code, out = strict(f, capsys)
    assert code == 0, out
    assert "all found." in out


def test_the_first_occurrence_of_a_passage_that_occurs_once_needs_no_anchors(paper):
    assert pin.main([str(paper), "--id", "c", "--quote", PASSAGE, "--occurrence", "1"]) == 0
    assert read(paper)["claims"]["c"]["quotes"][0] == {"exact": PASSAGE}


def test_a_second_occurrence_of_a_passage_that_occurs_once_is_refused(paper, capsys):
    before = paper.read_text()
    assert pin.main([str(paper), "--id", "c", "--quote", PASSAGE, "--occurrence", "2"]) == 1
    assert paper.read_text() == before
    assert "occurs once" in capsys.readouterr().out


def test_occurrence_does_not_rescue_a_passage_the_source_lacks(repeating, capsys):
    f = repeating(THRICE)
    before = f.read_text()
    changed = REPEATED.replace("0.94", "0.95")
    assert pin.main([str(f), "--id", "c", "--quote", changed, "--occurrence", "1"]) == 1
    assert f.read_text() == before
    assert "not found" in capsys.readouterr().out


def test_check_with_an_occurrence_reports_and_writes_nothing(repeating, capsys):
    f = repeating(THRICE)
    before = f.read_text()
    assert pin.main([str(f), "--id", "c", "--quote", REPEATED, "--occurrence", "2", "--check"]) == 0
    assert f.read_text() == before
    out = capsys.readouterr().out
    assert "would add" in out and "occurrence 2" in out
