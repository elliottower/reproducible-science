"""A claim's numbers against what its run wrote, and claims whose run no longer names a file."""

from __future__ import annotations

import decimal
import json

import pytest
from results import cli, ledger, outputs


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert cli.main(["init"]) == 0
    (tmp_path / "out.json").write_text(json.dumps({"icc": 0.4213, "n": 57, "rate": 0.0426}))
    assert cli.main(["run", "out.json", "--run-id", "r1"]) == 0
    return tmp_path


def claims(root):
    return [
        e for e in ledger.read_ledger(root / ".results" / "ledger.jsonl") if e["event"] == "claim"
    ]


def test_a_claim_printing_a_number_its_run_never_wrote_is_warned(project, capsys):
    capsys.readouterr()
    assert cli.main(["claim", "The ICC was 0.9913", "--run-id", "r1"]) == 0

    out = capsys.readouterr().out
    assert "warning" in out and "0.9913" in out
    assert len(claims(project)) == 1


def test_strict_refuses_it_and_writes_nothing(project, capsys):
    assert cli.main(["claim", "The ICC was 0.9913", "--run-id", "r1", "--strict"]) == 1

    assert claims(project) == []
    assert "nothing was written" in capsys.readouterr().out


def test_a_number_the_run_wrote_at_the_printed_precision_is_not_warned(project, capsys):
    capsys.readouterr()
    sentence = "The ICC was 0.42 over 57 participants, and the rate 4.26%"
    assert cli.main(["claim", sentence, "--run-id", "r1", "--strict"]) == 0

    assert "warning" not in capsys.readouterr().out


def test_verify_reports_the_claim_and_fails_it_only_under_strict(project, capsys):
    assert cli.main(["claim", "The ICC was 0.9913", "--run-id", "r1"]) == 0
    capsys.readouterr()

    assert cli.main(["verify", "--files"]) == 0
    out = capsys.readouterr().out
    assert "1 claim(s) print numbers their run's outputs do not hold; list with --explain" in out
    assert "0.9913" not in out
    assert cli.main(["verify", "--files", "--explain"]) == 0
    assert "no output rounds to 0.9913" in capsys.readouterr().out
    assert cli.main(["verify", "--files", "--strict"]) == 1


def test_a_claim_whose_run_had_its_only_output_retired_is_flagged(project, capsys):
    assert cli.main(["claim", "The ICC was 0.4213", "--run-id", "r1"]) == 0
    assert cli.main(["retire", "out.json", "--note", "replaced"]) == 0
    (project / "out.json").unlink()
    capsys.readouterr()

    assert cli.main(["verify", "--files"]) == 0
    assert "every output was retired" in capsys.readouterr().out
    assert cli.main(["verify", "--files", "--strict"]) == 1


def test_rounding_either_way_and_a_percentage_are_held():
    held = outputs.Held([])
    held.values = {
        decimal.Decimal("0.125"),
        decimal.Decimal("0.0426"),
        decimal.Decimal("57"),
    }

    assert held.holds("0.13") and held.holds("0.12")
    assert held.holds("4.26", percent=True) and held.holds("4.3", percent=True)
    assert not held.holds("4.26")
    assert held.holds("57")
    assert not held.holds("0.14")
    assert not held.holds("4.27")
    assert not held.holds("58")


def test_a_bare_number_is_not_held_by_a_stored_fraction_a_hundred_times_smaller(project, capsys):
    capsys.readouterr()
    assert cli.main(["claim", "The rate was 4.26", "--run-id", "r1", "--strict"]) == 1
    assert cli.main(["claim", "The rate was 4.26 percent", "--run-id", "r1", "--strict"]) == 0


def test_an_output_holding_a_huge_exponent_is_read_past(project, capsys):
    (project / "big.txt").write_text("overflow 1e999999 and 0.4213\n")
    assert cli.main(["run", "big.txt", "--run-id", "r2"]) == 0
    capsys.readouterr()
    assert cli.main(["claim", "The ICC was 0.42", "--run-id", "r2", "--strict"]) == 0
    assert cli.main(["verify", "--files", "--strict"]) == 0


def test_a_zero_width_character_inside_a_number_is_removed_and_warned(project, capsys):
    capsys.readouterr()
    assert cli.main(["claim", "The ICC was 0.42\u200b13", "--run-id", "r1", "--strict"]) == 0
    out = capsys.readouterr().out
    assert "1 format character(s)" in out
    assert "rounds to" not in out


def test_a_derived_claim_is_recorded_shown_and_not_compared(project, capsys):
    how = "the mean of the per-family values in out.json"
    sentence = "The mean ICC across families was 0.872"
    assert cli.main(["claim", sentence, "--run-id", "r1", "--derived", how, "--strict"]) == 0
    assert claims(project)[0]["derived"] == how
    capsys.readouterr()

    assert cli.main(["verify", "--files", "--strict"]) == 0
    out = capsys.readouterr().out
    assert f"derived: {how}" in out
    assert "do not hold" not in out


def test_a_derived_claim_still_gets_the_format_character_warning(project, capsys):
    capsys.readouterr()
    assert cli.main(["claim", "The mean was 0.87​2", "--run-id", "r1", "--derived", "a mean"]) == 0
    assert "1 format character(s)" in capsys.readouterr().out


def test_a_claim_is_not_checked_against_an_output_edited_since_its_run(project, capsys):
    (project / "out.json").write_text(json.dumps({"icc": 0.9913}))
    capsys.readouterr()

    assert cli.main(["claim", "The ICC was 0.9913", "--run-id", "r1", "--strict"]) == 1
    assert claims(project) == []
    out = capsys.readouterr().out
    assert "out.json is not the bytes run 'r1' recorded" in out
    assert "no output of run 'r1' is the bytes it recorded" in out
    assert "can read as text" not in out


def test_a_claim_whose_run_output_a_later_run_overwrote_is_unchecked_and_fails_strict(
    project, capsys
):
    assert cli.main(["claim", "The ICC was 0.9913", "--run-id", "r1"]) == 0
    assert cli.main(["verify", "--strict"]) == 1
    (project / "out.json").write_text(json.dumps({"icc": 0.1234}))
    assert cli.main(["run", "out.json", "--run-id", "r2"]) == 0
    capsys.readouterr()

    assert cli.main(["verify", "--files", "--json", "found.json"]) == 0
    out = capsys.readouterr().out
    assert "1 claim(s) could not be checked: their run's outputs were overwritten" in out
    assert "out.json: rewritten by run 'r2'" in out
    found = json.loads((project / "found.json").read_text())
    assert found["claims_unchecked"][0]["outputs"] == {"out.json": "rewritten by run 'r2'"}
    assert cli.main(["verify", "--strict"]) == 1
    assert cli.main(["verify", "--files", "--strict"]) == 1
