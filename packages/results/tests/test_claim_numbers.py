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
    assert "print numbers their run's outputs do not hold" in out
    assert "0.9913" in out
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
    assert held.holds("4.26") and held.holds("4.3")
    assert held.holds("57")
    assert not held.holds("0.14")
    assert not held.holds("4.27")
    assert not held.holds("58")
