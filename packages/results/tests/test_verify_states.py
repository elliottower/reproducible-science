"""What `verify --files` says of a sealed plan whose log grew, and of the ledger's own files."""

from __future__ import annotations

import json
import subprocess

import pytest
from prereg import inplace, log
from prereg.plan import plan_of, sha256_of
from provenance_core import sha256_of_file
from provenance_core.gitref import clean_env
from results import ledger
from results.cli import main

PLAN = """\
# study

**Status:** FROZEN at `0123456789ab`
**Plan sha256:** `{digest}`
**Frozen:** 2026-10-06

## Research questions or hypotheses

**H1.** The effect is positive.

## Inference criteria

H1 holds where the interval excludes zero.
"""


def git(repo, *args) -> None:
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
        cwd=repo,
        env=clean_env(),
        capture_output=True,
        check=True,
    )


def commit(repo) -> None:
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "commit")


@pytest.fixture
def sealed_plan(tmp_path, monkeypatch):
    """A plan frozen in place with one log entry, committed and sealed."""
    monkeypatch.chdir(tmp_path)
    git(tmp_path, "init", "-q")
    plan = tmp_path / "PREREG.md"
    plan.write_text(PLAN.format(digest=sha256_of(plan_of(PLAN.format(digest="")))))
    log.append(plan, "2026-10-06", "frozen", "nothing run")
    assert inplace.in_place(plan.read_text()).state == inplace.UNCHANGED
    assert main(["init"]) == 0
    assert main(["seal", "PREREG.md", "--role", "prereg"]) == 0
    commit(tmp_path)
    return plan


def verify(root):
    code = main(["verify", "--files", "--json", str(root / "found.json")])
    return code, json.loads((root / "found.json").read_text())["files"]


def test_a_sealed_plan_whose_log_grew_is_appended_and_passes(sealed_plan, capsys):
    log.append(sealed_plan, "2026-10-07", "results recorded", "results seen")
    log.append(sealed_plan, "2026-10-08", "an exploratory review", "results seen")
    code, files = verify(sealed_plan.parent)
    printed = capsys.readouterr().out
    assert code == 0, printed
    assert files == [{"path": "PREREG.md", "state": "appended", "entries": 2}]
    assert "APPENDED   PREREG.md\n    a plan frozen in place, unchanged; 2 log entries" in printed


def test_a_sealed_plan_with_an_edited_hypothesis_is_changed(sealed_plan, capsys):
    log.append(sealed_plan, "2026-10-07", "results recorded", "results seen")
    sealed_plan.write_text(sealed_plan.read_text().replace("positive", "negative"))
    code, files = verify(sealed_plan.parent)
    assert code == 1
    assert files == [{"path": "PREREG.md", "state": "changed"}]
    assert "CHANGED    PREREG.md" in capsys.readouterr().out


def test_a_sealed_plan_whose_earlier_log_entry_was_edited_is_changed(sealed_plan):
    log.append(sealed_plan, "2026-10-07", "results recorded", "results seen")
    sealed_plan.write_text(sealed_plan.read_text().replace("frozen", "thawed", 1))
    code, files = verify(sealed_plan.parent)
    assert code == 1 and files[0]["state"] == "changed"


def test_a_sealed_plan_with_a_line_added_below_the_log_is_changed(sealed_plan):
    log.append(sealed_plan, "2026-10-07", "results recorded", "results seen")
    sealed_plan.write_text(sealed_plan.read_text() + "\nAlso accept p < 0.10.\n")
    code, files = verify(sealed_plan.parent)
    assert code == 1 and files[0]["state"] == "changed"


def test_a_plan_sealed_in_bytes_no_commit_holds_is_changed(sealed_plan):
    log.append(sealed_plan, "2026-10-07", "results recorded", "results seen")
    assert main(["seal", "PREREG.md", "--role", "prereg"]) == 0
    log.append(sealed_plan, "2026-10-08", "an exploratory review", "results seen")
    code, files = verify(sealed_plan.parent)
    assert code == 1 and files[0]["state"] == "changed"


def test_a_seal_of_the_ledger_anchor_is_ignored_and_a_new_one_is_refused(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "inputs.json").write_text("[1, 2, 3]")
    assert main(["init"]) == 0
    head = tmp_path / ".results" / "ledger.head"
    lp = tmp_path / ".results" / ledger.LEDGER
    # The seal an earlier version wrote, before `seal` refused the ledger's own files.
    ledger.append_event(
        lp,
        {
            "event": "seal",
            "role": "input",
            "files": [
                {"path": ".results/ledger.head", "sha256": sha256_of_file(head), "kind": "file"}
            ],
        },
    )
    before = lp.read_bytes()
    assert main(["seal", "inputs.json", ".results/ledger.head"]) == 1
    assert main(["seal", "."]) == 1
    assert main(["run", ".results/ledger.jsonl", "--run-id", "r1"]) == 1
    assert lp.read_bytes() == before

    assert main(["seal", "inputs.json"]) == 0
    code, files = verify(tmp_path)
    assert code == 0
    assert files == [
        {
            "path": ".results/ledger.head",
            "state": "ignored",
            "note": "the ledger's own file, which changes with every event; not compared",
        },
        {"path": "inputs.json", "state": "ok"},
    ]


def test_an_ordinary_changed_file_still_fails_beside_the_states_that_pass(sealed_plan):
    data = sealed_plan.parent / "data.csv"
    data.write_text("a\n1\n")
    assert main(["seal", "data.csv"]) == 0
    data.write_text("a\n2\n")
    assert main(["seal", "data.csv"]) == 0
    log.append(sealed_plan, "2026-10-07", "results recorded", "results seen")
    assert verify(sealed_plan.parent)[0] == 0
    data.write_text("a\n3\n")
    code, files = verify(sealed_plan.parent)
    assert code == 1
    assert [file["state"] for file in files] == ["appended", "changed"]
