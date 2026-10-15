"""`repro ci init --pr-bot`: the two caller workflows of the pull-request bot."""

from __future__ import annotations

import re
import subprocess

import pytest
import yaml
from repro import ci, pr_bot
from repro.cli import main


def git(root, *args):
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


@pytest.fixture
def repository(tmp_path, monkeypatch):
    git(tmp_path, "init", "--quiet")
    (tmp_path / "repro.yaml").write_text("project: study\n")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def written(root) -> dict[str, tuple[str, dict]]:
    return {
        path.name: (path.read_text(), yaml.safe_load(path.read_text()))
        for path in sorted((root / ci.WORKFLOWS).iterdir())
    }


def test_the_two_callers_grant_least_privilege_and_call_the_pinned_reusable_workflow(
    repository, capsys
):
    assert main(["ci", "init", "--pr-bot"]) == 0
    flows = written(repository)
    assert set(flows) == {pr_bot.CHECK_FILE, pr_bot.RESPOND_FILE}
    for text, flow in flows.values():
        assert text.startswith(pr_bot.MARKER)
        assert "pull_request_target" not in text and "checkout" not in text
        assert flow["permissions"] == {}
        (job,) = flow["jobs"].values()
        assert re.fullmatch(rf"{re.escape(pr_bot.REUSABLE)}@\S+", job["uses"])
        assert "steps" not in job and job["with"]["manifest"] == "repro.yaml"

    _, check = flows[pr_bot.CHECK_FILE]
    # PyYAML reads the key `on` as a boolean.
    assert set(check[True]) == {"pull_request", "workflow_dispatch"}
    assert check[True]["workflow_dispatch"]["inputs"]["pull_request"]["required"] is True
    assert check["jobs"]["check"]["permissions"] == {"contents": "read"}

    _, respond = flows[pr_bot.RESPOND_FILE]
    assert respond[True] == {
        "workflow_run": {"workflows": [check["name"]], "types": ["completed"]},
        "issue_comment": {"types": ["created"]},
        "pull_request_review_comment": {"types": ["created"]},
    }
    assert respond["jobs"]["respond"]["permissions"] == {
        "actions": "write",
        "contents": "write",
        "issues": "write",
        "pull-requests": "write",
    }
    assert respond["jobs"]["respond"]["with"]["dispatch"] == pr_bot.CHECK_FILE
    out = capsys.readouterr().out
    assert "only from the default branch" in out


def test_the_callers_name_a_manifest_below_the_top_and_quote_it(tmp_path, monkeypatch):
    git(tmp_path, "init", "--quiet")
    (tmp_path / "paper one").mkdir()
    (tmp_path / "paper one" / "repro.yaml").write_text("project: study\n")
    monkeypatch.chdir(tmp_path / "paper one")
    assert main(["ci", "init", "--pr-bot"]) == 0
    for _, flow in written(tmp_path).values():
        (job,) = flow["jobs"].values()
        assert job["with"]["manifest"] == "paper one/repro.yaml"


def test_the_bot_starts_again_each_check_repro_ci_init_wrote(repository, capsys):
    assert main(["ci", "init"]) == 0
    (repository / ci.WORKFLOWS / "theirs.yml").write_text("on: [workflow_dispatch]\n")
    assert main(["ci", "init", "--pr-bot"]) == 0
    assert pr_bot.dispatchable(repository) == ["claims.yml"]
    _, respond = written(repository)[pr_bot.RESPOND_FILE]
    assert respond["jobs"]["respond"]["with"]["dispatch"] == f"{pr_bot.CHECK_FILE} claims.yml"


def test_a_check_written_before_it_could_be_started_by_hand_is_named(repository, capsys):
    workflows = repository / ci.WORKFLOWS
    workflows.mkdir(parents=True)
    (workflows / "claims.yml").write_text(f"{ci.MARKER}\non:\n  pull_request:\n")
    assert main(["ci", "init", "--pr-bot"]) == 0
    assert "claims.yml cannot be started that way" in capsys.readouterr().out


def test_a_caller_it_did_not_write_is_never_replaced_even_when_forced(repository, capsys):
    theirs = repository / ci.WORKFLOWS / pr_bot.RESPOND_FILE
    theirs.parent.mkdir(parents=True)
    theirs.write_text("name: something else\n")
    for flags in ([], ["--force"]):
        assert main(["ci", "init", "--pr-bot", *flags]) == 2
        assert "did not write it, so it is never replaced" in capsys.readouterr().out
        assert theirs.read_text() == "name: something else\n"
    assert not (theirs.parent / pr_bot.CHECK_FILE).exists()


def test_its_own_callers_are_replaced_only_when_forced(repository, capsys):
    assert main(["ci", "init", "--pr-bot"]) == 0
    target = repository / ci.WORKFLOWS / pr_bot.CHECK_FILE
    target.write_text(pr_bot.MARKER + "\nname: edited\n")
    assert main(["ci", "init", "--pr-bot"]) == 2
    assert "`--force` replaces" in capsys.readouterr().out
    assert main(["ci", "init", "--pr-bot", "--force"]) == 0
    assert yaml.safe_load(target.read_text())["name"] == pr_bot.CHECK_NAME


def test_with_no_manifest_nothing_is_written(tmp_path, monkeypatch, capsys):
    git(tmp_path, "init", "--quiet")
    monkeypatch.chdir(tmp_path)
    assert main(["ci", "init", "--pr-bot"]) == 2
    assert "repro manifest init" in capsys.readouterr().out
    assert not (tmp_path / ".github").exists()
