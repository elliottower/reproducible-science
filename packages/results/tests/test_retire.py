"""`results retire` and what `verify --files` says of a retired path."""

from __future__ import annotations

import json

import pytest
from results import ledger
from results.cli import main


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "old.csv").write_text("a\n1\n")
    (tmp_path / "kept.csv").write_text("b\n2\n")
    assert main(["init"]) == 0
    assert main(["seal", "old.csv", "kept.csv"]) == 0
    return tmp_path


def lines(root):
    return (root / ".results" / ledger.LEDGER).read_bytes()


def verify(root):
    code = main(["verify", "--files", "--json", str(root / "found.json")])
    return code, json.loads((root / "found.json").read_text())["files"]


def test_a_retired_path_that_is_gone_passes_as_retired(project, capsys):
    (project / "old.csv").unlink()
    assert verify(project)[0] == 1
    assert main(["retire", "old.csv", "--note", "superseded by kept.csv"]) == 0
    code, files = verify(project)
    printed = capsys.readouterr().out
    assert code == 0, printed
    assert files == [
        {"path": "kept.csv", "state": "ok"},
        {"path": "old.csv", "state": "retired", "note": "superseded by kept.csv"},
    ]
    assert "RETIRED    old.csv\n    superseded by kept.csv\n" in printed


def test_the_retire_event_names_the_path_from_the_project_root(project, monkeypatch):
    (project / "sub").mkdir()
    monkeypatch.chdir(project / "sub")
    assert main(["retire", "../old.csv", "--note", "dropped"]) == 0
    last = ledger.read_ledger(project / ".results" / ledger.LEDGER)[-1]
    assert (last["event"], last["paths"], last["note"]) == ("retire", ["old.csv"], "dropped")


def test_a_path_never_recorded_is_refused_and_nothing_is_written(project):
    (project / "other.csv").write_text("c\n")
    before = lines(project)
    assert main(["retire", "old.csv", "other.csv", "--note", "dropped"]) == 1
    assert main(["retire", "absent.csv", "--note", "dropped"]) == 1
    assert lines(project) == before


def test_an_empty_note_is_refused_and_nothing_is_written(project):
    before = lines(project)
    assert main(["retire", "old.csv", "--note", "  "]) == 1
    assert lines(project) == before


def test_a_path_already_retired_is_refused(project):
    assert main(["retire", "old.csv", "--note", "dropped"]) == 0
    before = lines(project)
    assert main(["retire", "old.csv", "--note", "dropped again"]) == 1
    assert lines(project) == before


def test_a_retired_file_still_holding_recorded_bytes_passes_and_says_so(project, capsys):
    assert main(["retire", "old.csv", "--note", "dropped"]) == 0
    code, files = verify(project)
    assert code == 0
    assert files[1] == {"path": "old.csv", "state": "retired", "note": "dropped", "present": True}
    assert "still on disk, holding bytes recorded for this path" in capsys.readouterr().out


def test_a_retired_path_holding_new_bytes_fails_as_reappeared(project, capsys):
    assert main(["retire", "old.csv", "--note", "dropped"]) == 0
    (project / "old.csv").write_text("a\n9\n")
    code, files = verify(project)
    assert code == 1
    assert files[1] == {"path": "old.csv", "state": "reappeared", "note": "dropped"}
    assert "REAPPEARED old.csv" in capsys.readouterr().out


def test_a_retired_file_path_now_a_directory_fails_as_reappeared(project):
    assert main(["retire", "old.csv", "--note", "dropped"]) == 0
    (project / "old.csv").unlink()
    (project / "old.csv").mkdir()
    code, files = verify(project)
    assert code == 1 and files[1]["state"] == "reappeared"


def test_a_retired_tree_that_is_gone_passes(project):
    data = project / "data"
    data.mkdir()
    (data / "x.csv").write_text("x\n")
    assert main(["seal", "data"]) == 0
    (data / "x.csv").unlink()
    data.rmdir()
    assert main(["retire", "data", "--note", "moved to the archive"]) == 0
    code, files = verify(project)
    assert code == 0
    assert files[0] == {"path": "data", "state": "retired", "note": "moved to the archive"}


def test_a_path_recorded_again_after_retirement_is_checked_as_live(project):
    assert main(["retire", "old.csv", "--note", "dropped"]) == 0
    (project / "old.csv").write_text("a\n2\n")
    assert main(["seal", "old.csv"]) == 0
    code, files = verify(project)
    assert code == 0
    assert files[1] == {"path": "old.csv", "state": "resealed", "hashes": 2}
    (project / "old.csv").unlink()
    code, files = verify(project)
    assert code == 1 and files[1] == {"path": "old.csv", "state": "missing"}
    assert main(["retire", "old.csv", "--note", "dropped for good"]) == 0
    assert verify(project)[1][1]["note"] == "dropped for good"


def test_retiring_one_path_leaves_a_changed_sibling_failing(project):
    assert main(["retire", "old.csv", "--note", "dropped"]) == 0
    (project / "kept.csv").write_text("b\n3\n")
    code, files = verify(project)
    assert code == 1
    assert [file["state"] for file in files] == ["changed", "retired"]


def test_a_replacement_is_recorded_with_its_digest_and_shown(project, capsys):
    (project / "old.csv").unlink()
    assert main(["retire", "old.csv", "--note", "merged", "--superseded-by", "kept.csv"]) == 0
    last = ledger.read_ledger(project / ".results" / ledger.LEDGER)[-1]
    assert last["superseded_by"] == "kept.csv"
    assert last["superseded_by_sha256"] == ledger.sha256_of_file(project / "kept.csv")
    code, files = verify(project)
    assert code == 0
    assert files[1] == {
        "path": "old.csv",
        "state": "retired",
        "note": "merged",
        "superseded_by": "kept.csv",
    }
    assert "RETIRED    old.csv\n    merged\n    superseded by kept.csv\n" in capsys.readouterr().out


def test_a_replacement_the_ledger_does_not_record_carries_no_digest(project):
    (project / "new.csv").write_text("n\n")
    assert main(["retire", "old.csv", "--note", "merged", "--superseded-by", "new.csv"]) == 0
    last = ledger.read_ledger(project / ".results" / ledger.LEDGER)[-1]
    assert last["superseded_by"] == "new.csv" and "superseded_by_sha256" not in last


def test_a_replacement_that_does_not_exist_is_refused_and_nothing_is_written(project):
    before = lines(project)
    assert main(["retire", "old.csv", "--note", "merged", "--superseded-by", "nowhere.csv"]) == 1
    assert lines(project) == before
