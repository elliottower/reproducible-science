"""`results verify --json PATH` writes what the run found beside what it prints."""

from __future__ import annotations

import json

import pytest
from results.cli import main


@pytest.fixture
def recorded(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "inputs.json").write_text("[1, 2, 3]")
    (tmp_path / "results.json").write_text('{"total": 6}')
    assert main(["init"]) == 0
    assert main(["seal", "inputs.json"]) == 0
    assert main(["run", "results.json", "--run-id", "r1"]) == 0
    return tmp_path


def found(root, *flags):
    code = main(["verify", *flags, "--json", str(root / "found.json")])
    return code, json.loads((root / "found.json").read_text())


def test_each_recorded_file_is_written_with_its_state_and_the_states_add_up(recorded, capsys):
    (recorded / "results.json").write_text('{"total": 7}')
    (recorded / "inputs.json").unlink()
    code, account = found(recorded, "--files")
    printed = capsys.readouterr().out
    assert code == 1 == account["exit"]
    assert account["chain"] == "intact" and account["events"] == 3
    assert account["files"] == [
        {"path": "inputs.json", "state": "missing"},
        {"path": "results.json", "state": "changed"},
    ]
    assert "MISSING    inputs.json" in printed and "CHANGED    results.json" in printed


def test_unchanged_files_are_ok_and_without_files_none_is_compared(recorded):
    code, account = found(recorded, "--files")
    assert code == 0
    assert [file["state"] for file in account["files"]] == ["ok", "ok"]
    code, account = found(recorded)
    assert code == 0 and account["files"] == [] and account["files_checked"] is False


def test_a_chain_that_does_not_verify_is_named_and_no_file_is_compared(recorded):
    ledger = recorded / ".results" / "ledger.jsonl"
    ledger.write_text(ledger.read_text().replace("r1", "r2"))
    code, account = found(recorded, "--files")
    assert code == 1
    assert account["chain"] == "edited" and account["problems"]
    assert account["files"] == [] and "events" not in account
