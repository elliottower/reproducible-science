"""An output recorded again under other bytes, with no run of its inputs between."""

from __future__ import annotations

import json

import pytest
from results import cli, ledger


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert cli.main(["init"]) == 0
    (tmp_path / "analysis.py").write_text("print(1)\n")
    (tmp_path / "out.json").write_text(json.dumps({"icc": 0.4213}))
    assert cli.main(["seal", "analysis.py"]) == 0
    assert cli.main(["run", "out.json", "--run-id", "r1"]) == 0
    return tmp_path


def edit_output(root):
    (root / "out.json").write_text(json.dumps({"icc": 0.9913}))


def events(root):
    return ledger.read_ledger(root / ".results" / "ledger.jsonl")


@pytest.mark.parametrize("argv", [["--run-id", "r1", "--anyway"], ["--run-id", "r2"]])
def test_an_edited_output_recorded_again_is_refused(project, capsys, argv):
    edit_output(project)
    before = len(events(project))

    assert cli.main(["run", "out.json", *argv]) == 1

    assert len(events(project)) == before
    assert "nothing has been sealed since" in capsys.readouterr().out


def test_a_rerun_after_sealing_its_inputs_is_recorded_and_verifies(project, capsys):
    (project / "analysis.py").write_text("print(2)\n")
    edit_output(project)
    assert cli.main(["seal", "analysis.py"]) == 0
    assert cli.main(["run", "out.json", "--run-id", "r2"]) == 0
    capsys.readouterr()

    assert cli.main(["verify", "--files"]) == 0
    assert "RESEALED   out.json" in capsys.readouterr().out


def test_an_identical_rerun_needs_no_seal(project):
    assert cli.main(["run", "out.json", "--run-id", "r2"]) == 0


def test_a_ledger_holding_a_rerecord_fails_verify(project, capsys):
    # Written as an older version, or by hand, would write it: the refusal above never ran.
    edit_output(project)
    digest = ledger.sha256_of_file(project / "out.json")
    lp = project / ".results" / "ledger.jsonl"
    ledger.append_event(
        lp, {"event": "run", "run_id": "r2", "outputs": [{"path": "out.json", "sha256": digest}]}
    )
    capsys.readouterr()

    assert cli.main(["verify", "--files"]) == 1
    out = capsys.readouterr().out
    assert "RERECORDED out.json" in out
    assert "RESEALED" not in out
