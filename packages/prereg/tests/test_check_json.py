"""`prereg check --json PATH` writes what the check found beside what it prints."""

from __future__ import annotations

import json
import os
import subprocess

import pytest
from prereg.cli import main


def git(root, *args):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
        cwd=root,
        env=env,
        check=True,
        capture_output=True,
    )


@pytest.fixture
def study(tmp_path, monkeypatch):
    monkeypatch.setenv("PROVENANCE_CALENDARS", "")
    monkeypatch.chdir(tmp_path)
    git(tmp_path, "init", "-q")
    assert main(["new", ".", "--title", "study"]) == 0
    git(tmp_path, "add", "PREREG.md")
    git(tmp_path, "commit", "-q", "-m", "plan")
    return tmp_path


def found(root):
    code = main(["check", "--json", str(root / "found.json")])
    return code, json.loads((root / "found.json").read_text())


def test_a_plan_never_frozen_is_written_as_not_frozen(study):
    code, account = found(study)
    (plan,) = account["plans"]
    assert code == 2
    assert plan["frozen"] is False and plan["sha256"] is None and plan["check"] == "not frozen"


def test_a_frozen_plan_is_written_with_its_digest_and_its_log_entries_counted(study, capsys):
    assert main(["freeze"]) == 0
    assert main(["log", "tolerance from fixtures", "--access", "no results seen"]) == 0
    assert main(["log", "second note", "--access", "no results seen"]) == 0
    capsys.readouterr()
    code, account = found(study)
    (plan,) = account["plans"]
    assert code == 0
    assert plan["frozen"] is True and plan["check"] == "unchanged" and len(plan["sha256"]) == 64
    assert (plan["amendments"], plan["amendment_drafts"], plan["log_entries"]) == (0, 0, 2)
    assert "2 entries, chain intact" in capsys.readouterr().out


def test_a_frozen_plan_edited_afterwards_is_written_as_changed(study):
    assert main(["freeze"]) == 0
    (study / "PREREG.md").chmod(0o644)
    (study / "PREREG.md").write_text((study / "PREREG.md").read_text() + "\nAlso p < 0.10.\n")
    code, account = found(study)
    assert code == 1
    assert account["plans"][0]["frozen"] is True and account["plans"][0]["check"] == "changed"


def test_an_amendment_not_yet_frozen_is_counted_as_a_draft_of_a_frozen_plan(study):
    assert main(["freeze"]) == 0
    assert main(["amend"]) == 0
    code, account = found(study)
    (plan,) = account["plans"]
    assert code == 2
    assert plan["frozen"] is True and plan["check"] == "not frozen"
    assert (plan["amendments"], plan["amendment_drafts"]) == (0, 1)
