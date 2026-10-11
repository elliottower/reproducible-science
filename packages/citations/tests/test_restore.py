"""The source's passage for a quotation that leaves text out, written apart from the quotation.

`restore` is the one command here that writes text nobody quoted, so what these pin is mostly
what it will not do: touch the original, choose between two passages, restore a misquotation,
or let a restored passage be counted as a quotation that resolved as written.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
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
        "fittings",
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
    assert r["fittings"] == {"found": 1, "others_contain_passage": True}
    assert r["rule"] == {
        "name": "bounded-passage",
        "version": 2,
        "max_omitted_tokens": 1,
        "min_piece_chars": V.MIN_PIECE_CHARS,
        "max_fittings": V.MAX_FITTINGS,
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


def test_check_decides_and_leaves_the_directory_as_it_found_it(tmp_path, capsys):
    f = project(tmp_path, {"c": ONE_OUT})
    before = sorted(p.name for p in tmp_path.rglob("*"))
    assert restore.main([str(f), "--id", "c", "--check"]) == 0
    assert sorted(p.name for p in tmp_path.rglob("*")) == before
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


# --- the only passage it can have been taken from ----------------------------------------------

A = "the treatment reduced mortality in the trial population"
B1 = "at twelve months of follow-up"
B2 = "in both arms of the study"
MODEL = "the model reached an accuracy of 0.94"
SPLIT = "on the held-out split of the second dataset"
LIMITS = ["1", "2", "50"]


def attempt(root: pathlib.Path, quote: str, source: str, *extra: str) -> tuple[int, str, str]:
    """Exit code, what was printed, and the restored passage where one was written."""
    f = project(root, {"c": quote}, source)
    before = f.read_bytes()
    printed = io.StringIO()
    with contextlib.redirect_stdout(printed):
        code = restore.main([str(f), "--id", "c", *extra])
    assert f.read_bytes() == before
    assert restore.sidecar(f).exists() == (code == 0)
    return code, printed.getvalue(), record(f)["quotes"][0]["exact"] if code == 0 else ""


def refused(tmp_path, quote: str, source: str, *extra: str) -> str:
    code, printed, _ = attempt(tmp_path, quote, source, *extra)
    assert code == 1
    return printed


@pytest.mark.parametrize("limit", LIMITS)
def test_a_longer_way_that_contains_the_passage_does_not_stop_it_at_any_limit(tmp_path, limit):
    source = f"Overall {A} significantly {B1} {B2}. Adverse events were similar {B2}."
    code, _, exact = attempt(tmp_path, f"{A} {B1} {B2}", source, "--max-omitted-tokens", limit)
    assert code == 0
    assert exact == f"{A} significantly {B1} {B2}"
    f = tmp_path / "claims" / "notes.yaml"
    assert record(f)["restored"]["fittings"] == {"found": 3, "others_contain_passage": True}


@pytest.mark.parametrize("limit", LIMITS)
def test_two_passages_neither_inside_the_other_are_refused_at_every_limit(tmp_path, limit):
    source = f"In men {A} significantly {B1} {B2}. In women {A} not once {B1} {B2}."
    said = refused(tmp_path, f"{A} {B1} {B2}", source, "--max-omitted-tokens", limit)
    assert "not inside all the others" in said and "whatever the limit" in said


def test_the_shortest_passage_is_restored_inside_a_sentence_that_is_another_reading(tmp_path):
    b = f"{B1} {B2}"
    source = f"Critics deny that {A} at all (the sponsor wrote that {A} reliably {b}) or {b}."
    code, _, exact = attempt(tmp_path, f"{A} {b}", source)
    assert (code, exact) == (0, f"{A} reliably {b}")
    f = tmp_path / "claims" / "notes.yaml"
    assert record(f)["restored"]["fittings"] == {"found": 24, "others_contain_passage": True}


def test_the_uniqueness_check_is_reached_at_the_default_limit(tmp_path):
    source = f"In men {A} significantly {B1} {B2}. In women {A} never {B1} {B2}."
    assert "not inside all the others" in refused(tmp_path, f"{A} {B1} {B2}", source)


@pytest.mark.parametrize("glue", ["\x00", "\u00b4"], ids=["control", "acute"])
@pytest.mark.parametrize("limit", LIMITS)
def test_a_one_token_way_beside_another_one_token_way_is_refused(tmp_path, glue, limit):
    source = f"In men {A} never{glue}once {B1} {B2}. In women {A} truly {B1} {B2}."
    quote = f"{A} {B1} {B2}"
    assert {g.tokens for g in V.omission(quote, source).gaps} == {1}
    said = refused(tmp_path, quote, source, "--max-omitted-tokens", limit)
    assert "not inside all the others" in said


@pytest.mark.parametrize("limit", ["1", "5000"])
def test_a_near_way_and_a_far_way_are_refused_the_same_at_every_limit(tmp_path, limit):
    filler = "Filler sentence number one goes here. " * 50
    source = f"{MODEL} x1. {filler}{SPLIT}. Later {MODEL} only {SPLIT}."
    said = refused(tmp_path, f"{MODEL} {SPLIT}", source, "--max-omitted-tokens", limit)
    assert "fit the source in 4 ways" in said and "not inside all the others" in said
    assert "tokens and the limit" not in said


def test_raising_the_limit_never_changes_what_is_restored(tmp_path):
    source = f"Overall {A} significantly more {B1} {B2}. Adverse events were similar {B2}."
    quote = f"{A} {B1} {B2}"
    assert attempt(tmp_path / "one", quote, source)[0] == 1
    passages = {
        attempt(tmp_path / limit, quote, source, "--max-omitted-tokens", limit)[2]
        for limit in ("2", "3", "50", "5000")
    }
    assert passages == {f"{A} significantly more {B1} {B2}"}


def test_an_earlier_copy_of_a_piece_gives_a_longer_way_and_the_near_one_is_restored(tmp_path):
    source = f"{FIRST} briefly noted. Later, {FIRST} strongly {SECOND}."
    found = V.omission(ONE_OUT, source)
    assert (found.fittings, found.unique) == (2, True)
    code, _, exact = attempt(tmp_path, ONE_OUT, source)
    assert (code, exact) == (0, f"{FIRST} strongly {SECOND}")


def test_a_cut_that_could_fall_either_side_of_a_repeated_word_is_refused(tmp_path):
    source = f"{FIRST} very very {SECOND}."
    assert "fit the source in 2 ways" in refused(tmp_path, f"{FIRST} very {SECOND}", source)


def test_more_ways_than_the_listing_holds_are_refused(tmp_path):
    sentence = "the quick brown fox jumps over the lazy dog near the old river bank today "
    words = sentence.split()
    quote = " ".join(" ".join(words[:7] + words[8:]) for _ in range(4))
    said = refused(tmp_path, quote, sentence * 40, "--max-omitted-tokens", "5000")
    assert f"more than {V.MAX_FITTINGS:,} ways" in said


# --- one count of tokens -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("left_out", "restorable"),
    [
        ("very\x00strongly", True),
        ("very-\nstrongly", True),
        ("very strongly", False),
        ("very\u00a0strongly", False),
    ],
    ids=["control-char", "line-break-hyphen", "two-words", "no-break-space"],
)
def test_the_limit_counts_tokens_as_the_omission_does(tmp_path, left_out, restorable):
    source = f"X. {FIRST} {left_out} {SECOND} here."
    code, said, exact = attempt(tmp_path, ONE_OUT, source)
    assert (code == 0) == restorable, said
    if restorable:
        assert exact == f"{FIRST} {left_out} {SECOND}"
        f = tmp_path / "claims" / "notes.yaml"
        assert [o["tokens"] for o in record(f)["restored"]["omitted"]] == [1]
    else:
        assert "leaves out 2 tokens and the limit is 1" in said


def test_position_counts_a_word_the_source_breaks_across_a_line_once(tmp_path):
    source = f"X. Higher circu-\nlating levels of the protein were strongly {SECOND} here."
    f = project(tmp_path, {"c": ONE_OUT}, source)
    assert restore.main([str(f), "--id", "c"]) == 0
    (omitted,) = record(f)["restored"]["omitted"]
    assert (omitted["tokens"], omitted["position"]) == (1, 8)
    assert source[omitted["start"] : omitted["end"]] == "strongly"


@pytest.mark.parametrize(
    ("in_source", "quoted"),
    [
        ("12\u202f500", "500"),
        ("12\u2009500", "12"),
        ("na\u00a8ive value", "ive value"),
        ("don\u00b4t respond", "don respond"),
        ("logit\x00difference", "logit"),
    ],
    ids=["narrow-no-break", "thin", "diaeresis", "acute", "control"],
)
def test_a_token_the_fold_would_split_is_never_restorable(tmp_path, in_source, quoted):
    lead, tail = (
        "the dose given to the treated group was",
        "in the second phase of the trial overall",
    )
    source = f"We note {lead} {in_source} {tail}."
    assert "nothing is restored" in refused(tmp_path, f"{lead} {quoted} {tail}", source)


def test_a_passage_ending_on_a_combining_mark_is_restored_with_the_mark(tmp_path):
    cafe = "cafe\u0301"
    source = f"X. {FIRST} strongly associated with lower risk of the {cafe} here."
    code, _, exact = attempt(tmp_path, f"{FIRST} associated with lower risk of the cafe", source)
    assert code == 0
    assert exact.endswith(cafe)
    f = tmp_path / "claims" / "notes.yaml"
    span = record(f)["restored"]["passage"]
    assert source[span["start"] : span["end"]] == exact


# --- the file the record goes into -------------------------------------------------------------


def test_a_sidecar_written_against_an_earlier_pin_is_refused_and_left_alone(tmp_path, capsys):
    source = f"X. {FIRST} strongly {SECOND} here. Also {MODEL} only {SPLIT}."
    f = project(tmp_path, {"c": ONE_OUT, "d": f"{MODEL} {SPLIT}"}, source)
    assert restore.main([str(f), "--id", "c"]) == 0
    held = restore.sidecar(f).read_bytes()
    changed = source + " An erratum line was added.\n"
    (tmp_path / "source.txt").write_text(changed)
    doc = yaml.safe_load(f.read_text())
    doc["source"]["sha256"] = hashlib.sha256(changed.encode()).hexdigest()
    f.write_text(yaml.safe_dump(doc, sort_keys=False))
    V.clear_caches()
    capsys.readouterr()
    assert restore.main([str(f), "--id", "d"]) == 1
    assert "another `source` block" in capsys.readouterr().out
    assert restore.sidecar(f).read_bytes() == held


def test_a_key_added_to_the_source_block_since_does_not_block_a_later_restore(tmp_path):
    source = f"X. {FIRST} strongly {SECOND} here. Also {MODEL} only {SPLIT}."
    f = project(tmp_path, {"c": ONE_OUT, "d": f"{MODEL} {SPLIT}"}, source)
    assert restore.main([str(f), "--id", "c"]) == 0
    doc = yaml.safe_load(f.read_text())
    doc["source"] |= {"doi": "10.1000/x", "local": "./source.txt"}
    doc["source"]["sha256"] = doc["source"]["sha256"].upper()
    f.write_text(yaml.safe_dump(doc, sort_keys=False))
    assert restore.main([str(f), "--id", "d"]) == 0
    assert set(yaml.safe_load(restore.sidecar(f).read_text())["claims"]) == {
        "c-restored",
        "d-restored",
    }


@pytest.mark.parametrize(
    ("body", "says"),
    [
        ("source: {citation: other, local: elsewhere.txt}\nclaims: {}\n", "another `source` block"),
        ("claims: [unclosed\n", "cannot be read as YAML"),
        ("- a\n- b\n", "is not a claims file"),
        ("source: {}\nclaims: 3\n", "is not a claims file"),
    ],
    ids=["another-source", "unparseable", "a-list", "claims-not-a-mapping"],
)
def test_a_sidecar_that_is_not_this_files_own_is_refused_and_left_alone(
    tmp_path, capsys, body, says
):
    f = project(tmp_path, {"c": ONE_OUT})
    restore.sidecar(f).write_text(body)
    assert restore.main([str(f), "--id", "c"]) == 1
    assert says in capsys.readouterr().out
    assert restore.sidecar(f).read_text() == body


def test_a_sidecar_whose_claims_are_empty_takes_the_record(tmp_path):
    f = project(tmp_path, {"c": ONE_OUT})
    source = yaml.safe_load(f.read_text())["source"]
    restore.sidecar(f).write_text(yaml.safe_dump({"source": source, "claims": None}))
    assert restore.main([str(f), "--id", "c"]) == 0
    assert record(f)["restored"]["from"] == "c"


def test_an_unpinned_source_is_refused(tmp_path, capsys):
    f = project(tmp_path, {"c": ONE_OUT})
    doc = yaml.safe_load(f.read_text())
    del doc["source"]["sha256"]
    f.write_text(yaml.safe_dump(doc, sort_keys=False))
    assert restore.main([str(f), "--id", "c"]) == 1
    assert "records no sha256" in capsys.readouterr().out
    assert not restore.sidecar(f).exists()


def test_a_claims_file_using_restored_for_something_of_its_own_still_loads(tmp_path, capsys):
    f = project(tmp_path, {"c": ONE_OUT, "whole": SECOND})
    doc = yaml.safe_load(f.read_text())
    doc["claims"]["whole"]["restored"] = True
    doc["claims"]["c"]["restored"] = "2026-01-01"
    f.write_text(yaml.safe_dump(doc, sort_keys=False))
    assert cli.main(["verify", "--no-cache", "--claims", str(f.parent)]) == 1
    out = capsys.readouterr().out
    assert "2 quotes" in out and "skipped" not in out and "restored  " not in out
    assert restore.main([str(f), "--id", "c"]) == 0


def test_a_passage_another_reader_finds_whole_is_not_an_omission(tmp_path, monkeypatch, capsys):
    f = project(tmp_path, {"c": ONE_OUT})
    monkeypatch.setattr(V, "check_one", lambda *a, **k: V.Result("found", extractor="pypdf"))
    assert restore.main([str(f), "--id", "c"]) == 1
    assert "is `found` in the source; there is no omission" in capsys.readouterr().out
    assert not restore.sidecar(f).exists()


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
