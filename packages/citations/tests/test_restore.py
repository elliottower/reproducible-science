"""The source's passage for a quotation that leaves text out, written apart from the quotation.

`restore` is the one command here that writes text nobody quoted, so what these pin is mostly
what it will not do: touch the original, choose between two passages, restore a misquotation,
or let a restored passage be counted as a quotation that resolved as written.
"""

from __future__ import annotations

import hashlib
import pathlib
import shutil

import pytest
import yaml
from citations import cli, restore
from citations import verify as V


@pytest.fixture(autouse=True)
def _no_cache():
    V.clear_caches()


FIRST = "Higher circulating levels of the protein were"
SECOND = "associated with lower risk of the disease"
SOURCE = (
    f"BACKGROUND.  {FIRST.replace('protein', 'Protein')} strongly\n"
    f"   {SECOND} in two cohorts (odds ratio 0.81). Conclusions follow.\n"
)
ONE_OUT = f"{FIRST} {SECOND}"
TWO_OUT = f"{FIRST} {SECOND} in cohorts (odds ratio 0.81)."


def project(root: pathlib.Path, quotes: dict[str, str], source: str = SOURCE) -> pathlib.Path:
    (root / "claims").mkdir(parents=True)
    (root / "source.txt").write_text(source)
    f = root / "claims" / "notes.yaml"
    f.write_text(
        "# kept exactly as written\n"
        + yaml.safe_dump(
            {
                "source": {
                    "citation": "notes2026",
                    "local": "source.txt",
                    "sha256": hashlib.sha256(source.encode()).hexdigest(),
                },
                "claims": {k: {"quotes": [{"exact": q}]} for k, q in quotes.items()},
            },
            sort_keys=False,
        )
    )
    return f


def record(f: pathlib.Path, claim: str = "c-restored") -> dict:
    return yaml.safe_load(restore.sidecar(f).read_text())["claims"][claim]


# --- one token left out ------------------------------------------------------------------------


def test_a_one_token_omission_is_restored_to_the_sources_passage(tmp_path, capsys):
    f = project(tmp_path, {"c": ONE_OUT})
    assert restore.main([str(f), "--id", "c"]) == 0
    start = SOURCE.index("Higher")
    assert record(f)["quotes"] == [{"exact": SOURCE[start : SOURCE.index(" in two cohorts")]}]
    out = capsys.readouterr().out
    assert "restored  c as c-restored in notes.restored.yaml" in out
    assert "not what the quoting party wrote" in out


def test_the_original_file_is_byte_identical_afterwards(tmp_path):
    f = project(tmp_path, {"c": ONE_OUT})
    before = f.read_bytes()
    assert restore.main([str(f), "--id", "c"]) == 0
    assert f.read_bytes() == before


def test_the_record_carries_where_the_passage_and_the_omitted_token_sit(tmp_path):
    f = project(tmp_path, {"c": ONE_OUT})
    assert restore.main([str(f), "--id", "c"]) == 0
    r = record(f)["restored"]
    assert set(r) == {
        "from",
        "notice",
        "original",
        "source",
        "text",
        "passage",
        "omitted",
        "rule",
        "software",
    }
    assert (r["from"], r["original"]) == ("c", ONE_OUT)
    assert "not what the quoting party wrote" in r["notice"]
    digest = hashlib.sha256(SOURCE.encode()).hexdigest()
    assert r["source"] == {"citation": "notes2026", "local": "source.txt", "sha256": digest}
    assert r["text"] == {"extractor": "text", "sha256": digest}
    passage = SOURCE[r["passage"]["start"] : r["passage"]["end"]]
    assert passage == record(f)["quotes"][0]["exact"]
    (omitted,) = r["omitted"]
    assert SOURCE[omitted["start"] : omitted["end"]] == "strongly"
    assert (omitted["tokens"], omitted["position"]) == (1, 8)
    assert passage.split()[omitted["position"] - 1] == "strongly"
    assert r["rule"] == {
        "name": "bounded-passage",
        "version": 1,
        "max_omitted_tokens": 1,
        "min_piece_chars": V.MIN_PIECE_CHARS,
    }
    assert r["software"]["citations"]


def test_the_passage_is_bounded_by_the_pieces_and_takes_no_context(tmp_path):
    f = project(tmp_path, {"c": ONE_OUT})
    assert restore.main([str(f), "--id", "c"]) == 0
    exact = record(f)["quotes"][0]["exact"]
    assert exact.startswith("Higher") and exact.endswith("disease")
    assert V.passage_fold(exact) == V.passage_fold(f"{FIRST} strongly {SECOND}")


def test_the_same_inputs_give_the_same_bytes(tmp_path):
    made = []
    for name in ("one", "two"):
        f = project(tmp_path / name, {"c": ONE_OUT})
        assert restore.main([str(f), "--id", "c"]) == 0
        made.append(restore.sidecar(f).read_bytes())
    assert made[0] == made[1]


def test_restoring_the_same_claim_again_is_refused_and_changes_nothing(tmp_path, capsys):
    f = project(tmp_path, {"c": ONE_OUT})
    assert restore.main([str(f), "--id", "c"]) == 0
    before = restore.sidecar(f).read_bytes()
    assert restore.main([str(f), "--id", "c"]) == 1
    assert restore.sidecar(f).read_bytes() == before
    assert "already defines" in capsys.readouterr().out


def test_check_decides_and_writes_nothing(tmp_path, capsys):
    f = project(tmp_path, {"c": ONE_OUT})
    assert restore.main([str(f), "--id", "c", "--check"]) == 0
    assert not restore.sidecar(f).exists()
    assert "would restore" in capsys.readouterr().out


# --- what verify makes of it -------------------------------------------------------------------


def test_the_derived_record_verifies_strictly_and_is_counted_apart(tmp_path, capsys):
    f = project(tmp_path, {"c": ONE_OUT})
    assert restore.main([str(f), "--id", "c"]) == 0
    alone = tmp_path / "alone"
    (alone / "claims").mkdir(parents=True)
    shutil.copy(tmp_path / "source.txt", alone / "source.txt")
    shutil.copy(restore.sidecar(f), alone / "claims" / "notes.restored.yaml")
    capsys.readouterr()
    assert cli.main(["verify", "--strict", "--no-cache", "--claims", str(alone / "claims")]) == 0
    out = capsys.readouterr().out
    assert "all found." in out
    assert "restored  1 of the 1" in out and "not what the quoting party wrote" in out


def test_the_original_is_still_not_found_beside_its_restoration(tmp_path, capsys):
    f = project(tmp_path, {"c": ONE_OUT, "whole": SECOND})
    assert restore.main([str(f), "--id", "c"]) == 0
    capsys.readouterr()
    assert cli.main(["verify", "--no-cache", "--claims", str(f.parent)]) == 1
    out = capsys.readouterr().out
    assert "3 quotes" in out and "1 not found." in out
    assert "restored  1 of the 3" in out


def test_a_run_with_nothing_restored_prints_no_restored_line(tmp_path, capsys):
    f = project(tmp_path, {"whole": SECOND})
    assert cli.main(["verify", "--no-cache", "--claims", str(f.parent)]) == 0
    assert "restored" not in capsys.readouterr().out


# --- the limit ---------------------------------------------------------------------------------


def test_two_omitted_tokens_are_refused_under_the_default_limit(tmp_path, capsys):
    f = project(tmp_path, {"c": TWO_OUT})
    assert len(V.omission(TWO_OUT, SOURCE).gaps) == 2
    assert restore.main([str(f), "--id", "c"]) == 1
    assert restore.main([str(f), "--id", "c", "--max-omitted-tokens", "1"]) == 1
    assert not restore.sidecar(f).exists()
    out = capsys.readouterr().out
    assert "leaves out 2 tokens and the limit is 1" in out and "nothing written" in out


def test_a_limit_that_is_asked_for_admits_them_and_is_recorded(tmp_path):
    f = project(tmp_path, {"c": TWO_OUT})
    assert restore.main([str(f), "--id", "c", "--max-omitted-tokens", "2"]) == 0
    r = record(f)["restored"]
    assert r["rule"]["max_omitted_tokens"] == 2
    assert [SOURCE[o["start"] : o["end"]] for o in r["omitted"]] == ["strongly", "two"]
    assert [(o["tokens"], o["position"]) for o in r["omitted"]] == [(1, 8), (1, 17)]


def test_two_adjacent_tokens_left_out_are_one_gap_of_two_and_refused_at_one(tmp_path, capsys):
    quote = f"{FIRST} strongly associated with risk of the disease in two cohorts"
    source = SOURCE.replace("lower risk", "much lower risk")
    f = project(tmp_path, {"c": quote}, source)
    assert [g.text for g in V.omission(quote, source).gaps] == ["much lower"]
    assert restore.main([str(f), "--id", "c"]) == 1
    assert "leaves out 2 tokens and the limit is 1" in capsys.readouterr().out
    assert not restore.sidecar(f).exists()


def test_a_limit_below_one_is_a_usage_error(tmp_path):
    f = project(tmp_path, {"c": ONE_OUT})
    assert restore.main([str(f), "--id", "c", "--max-omitted-tokens", "0"]) == 2


# --- more than one way to fit ------------------------------------------------------------------


def refused(tmp_path, quote: str, source: str, *extra: str) -> str:
    f = project(tmp_path, {"c": quote}, source)
    before = f.read_bytes()
    with pytest.MonkeyPatch.context() as m, pathlib.Path(tmp_path / "out.txt").open("w") as sink:
        m.setattr("sys.stdout", sink)
        code = restore.main([str(f), "--id", "c", "--max-omitted-tokens", "50", *extra])
    assert code == 1
    assert f.read_bytes() == before
    assert not restore.sidecar(f).exists()
    return (tmp_path / "out.txt").read_text()


def test_a_piece_the_source_has_twice_is_refused(tmp_path):
    source = f"{FIRST} briefly noted. Later, {FIRST} strongly {SECOND}."
    assert V.omission(ONE_OUT, source) is not None
    assert V.alignments(ONE_OUT, source) == 2
    assert "more than one way" in refused(tmp_path, ONE_OUT, source)


def test_a_cut_that_could_fall_either_side_of_a_repeated_word_is_refused(tmp_path):
    source = f"{FIRST} very very {SECOND}."
    quote = f"{FIRST} very {SECOND}"
    assert V.omission(quote, source) is not None
    assert V.alignments(quote, source) == 2
    assert "more than one way" in refused(tmp_path, quote, source)


def test_a_way_that_leaves_out_more_than_the_limit_is_not_a_second_way(tmp_path, capsys):
    source = f"{FIRST} strongly {SECOND}. Much later, and elsewhere, {SECOND} again."
    quote = f"{FIRST} associated with lower risk of the disease"
    assert V.alignments(quote, source) == 2
    assert V.alignments(quote, source, max_omitted_tokens=1) == 1
    f = project(tmp_path, {"c": quote}, source)
    assert restore.main([str(f), "--id", "c", "--max-omitted-tokens", "1"]) == 0
    assert record(f)["quotes"][0]["exact"] == f"{FIRST} strongly {SECOND}"
    assert restore.main([str(f), "--id", "c", "--as", "wide", "--max-omitted-tokens", "50"]) == 1
    assert "more than one way that leaves out at most 50 tokens" in capsys.readouterr().out
    assert set(yaml.safe_load(restore.sidecar(f).read_text())["claims"]) == {"c-restored"}


def test_one_way_to_fit_counts_as_one():
    assert V.alignments(ONE_OUT, SOURCE) == 1
    assert V.alignments(ONE_OUT.replace("lower", "higher"), SOURCE) == 0


# --- a misquotation is never restored ----------------------------------------------------------


@pytest.mark.parametrize(
    ("quote", "source"),
    [
        (f"{FIRST} strongly {SECOND} in two cohorts (odds ratio 0.18).", SOURCE),
        (f"{FIRST} {SECOND} in two cohorts (odds ratio 0.8", SOURCE),
        (f"{FIRST} {SECOND.replace('lower', 'higher')}", SOURCE),
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
            "the association with the outcome was significant after adjustment for age",
            "Overall the association with the outcome was non-significant after adjustment for age.",
        ),
    ],
    ids=["digit", "number-cut-at-the-end", "word", "sign", "decimal", "hyphenated"],
)
def test_a_changed_or_cut_token_is_never_restorable(tmp_path, quote, source):
    assert "nothing is restored" in refused(tmp_path, quote, source)


def test_a_quotation_the_source_has_is_not_restored(tmp_path):
    assert "there is no omission" in refused(tmp_path, SECOND, SOURCE)


def test_a_source_that_is_not_the_pinned_one_is_refused(tmp_path, capsys):
    f = project(tmp_path, {"c": ONE_OUT})
    (tmp_path / "source.txt").write_text(SOURCE + "One more line.\n")
    assert restore.main([str(f), "--id", "c"]) == 1
    assert "not the file that was pinned" in capsys.readouterr().out
    assert not restore.sidecar(f).exists()


def test_a_restored_claim_is_not_restored_again(tmp_path, capsys):
    f = project(tmp_path, {"c": ONE_OUT})
    assert restore.main([str(f), "--id", "c"]) == 0
    assert restore.main([str(restore.sidecar(f)), "--id", "c-restored"]) == 1
    assert "itself a restored claim" in capsys.readouterr().out


def test_the_command_is_reached_through_the_cli(tmp_path, capsys):
    f = project(tmp_path, {"c": ONE_OUT})
    assert cli.main(["restore", str(f), "--id", "c", "--as", "c-source"]) == 0
    assert record(f, "c-source")["restored"]["from"] == "c"
