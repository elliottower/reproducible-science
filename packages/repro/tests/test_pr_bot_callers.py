"""`repro ci init --pr-bot`: the two caller workflows of the pull-request bot."""

from __future__ import annotations

import importlib.util
import pathlib
import re
import subprocess
import tomllib

import pytest
import repro
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
        "issue_comment": {"types": ["created", "edited"]},
        "pull_request_review_comment": {"types": ["created", "edited"]},
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


REUSABLE = pathlib.Path(__file__).resolve().parents[3] / ".github" / "workflows" / "pr-bot.yml"


def test_the_reusable_workflow_the_callers_name_is_in_this_repository():
    owner_repo, _, path = pr_bot.REUSABLE.partition("/.github/")
    assert owner_repo == "elliottower/reproducible-science"
    assert REUSABLE.as_posix().endswith(f".github/{path}")


def test_the_reusable_workflow_keeps_the_split_each_job_holding_only_its_token():
    flow = yaml.safe_load(REUSABLE.read_text())
    called = flow[True]["workflow_call"]
    assert flow["permissions"] == {} and set(called) == {"inputs"}
    for caller in pr_bot.callers("repro.yaml", ("claims.yml",)):
        (job,) = yaml.safe_load(caller.text)["jobs"].values()
        assert set(job["with"]) <= set(called["inputs"])
    jobs = flow["jobs"]
    assert jobs["check"]["permissions"] == {"contents": "read"}
    (checkout,) = [s for s in jobs["check"]["steps"] if "checkout" in s.get("uses", "")]
    assert checkout["with"]["persist-credentials"] is False
    assert jobs["post"]["permissions"] == {
        "actions": "read",
        "issues": "write",
        "pull-requests": "write",
    }
    assert jobs["reply"]["permissions"]["contents"] == "write"
    for name in ("post", "reply"):
        steps = jobs[name]["steps"]
        assert not any("checkout" in step.get("uses", "") for step in steps)
        assert jobs[name]["concurrency"]["cancel-in-progress"] is False
        assert "workflow_run" in jobs["post"]["if"] and "comment" in jobs["reply"]["if"]
    text = REUSABLE.read_text()
    assert "pull_request_target" not in text and "github.event.comment.body" not in text
    uses = [s["uses"] for job in jobs.values() for s in job["steps"] if "uses" in s]
    assert all(re.fullmatch(r"[\w./-]+@[0-9a-f]{40}", used) for used in uses)
    assert text.count("uvx --no-config --from reproducible-science-pr-bot==") == 3


def test_the_pr_bot_extra_pins_the_bot_to_this_release_series_and_all_includes_it():
    manifest = REUSABLE.parents[2] / "packages" / "repro" / "pyproject.toml"
    project = tomllib.loads(manifest.read_text())["project"]
    extras = project["optional-dependencies"]
    major, minor, _ = project["version"].split(".", 2)
    assert extras["pr-bot"] == [
        f"reproducible-science-pr-bot>={major}.{minor},<{major}.{int(minor) + 1}"
    ]
    (everything,) = extras["all"]
    named = everything.split("[", 1)[1].rstrip("]").split(",")
    assert set(named) == set(extras) - {"all"}


def test_the_callers_name_the_tag_of_this_release_and_the_workflow_runs_this_release():
    version = repro.__version__
    for caller in pr_bot.callers():
        (job,) = yaml.safe_load(caller.text)["jobs"].values()
        assert job["uses"] == f"{pr_bot.REUSABLE}@v{version}"
    pins = re.findall(r"reproducible-science-pr-bot==(\S+)", REUSABLE.read_text())
    assert len(pins) == 3 and set(pins) == {version}


def test_versions_bump_moves_the_workflows_pins_and_check_refuses_one_left_behind(
    tmp_path, monkeypatch
):
    spec = importlib.util.spec_from_file_location(
        "versions", REUSABLE.parents[2] / "scripts" / "versions.py"
    )
    versions = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(versions)
    copy = tmp_path / versions.BOT_WORKFLOW
    copy.parent.mkdir(parents=True)
    copy.write_text(REUSABLE.read_text())
    monkeypatch.setattr(versions, "PROJECT_ROOT", tmp_path)
    manifest = tmp_path / "pyproject.toml"
    manifest.write_text('[project]\nname = "x"\nversion = "0.6.1"\n')
    monkeypatch.setattr(versions, "PACKAGES", {"reproducible-science-pr-bot": manifest})
    monkeypatch.setattr(versions, "PLUGIN_MANIFESTS", ())
    for name in ("CITATION", "HOOKS", "HOOK_README"):
        monkeypatch.setattr(versions, name, tmp_path / "absent")
    with monkeypatch.context() as later:
        later.setattr(versions, "declared", lambda: dict.fromkeys(versions.PACKAGES, "0.7.1"))
        assert any("pr-bot.yml" in problem for problem in versions.check())
    assert versions.BOT_WORKFLOW.as_posix() in versions.bump("0.7.1", realign=True)
    assert set(re.findall(r"reproducible-science-pr-bot==(\S+)", copy.read_text())) == {"0.7.1"}
    assert REUSABLE.read_text() != copy.read_text()
