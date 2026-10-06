from __future__ import annotations

import hashlib
import os
import pathlib
import subprocess

import pytest
from repro.cli import main
from repro.manifest import DEFAULT_NAME, load

RECORDS = ("plan", "ledger", "citations", "manifest")


@pytest.fixture
def run_repro(monkeypatch, capsys, tmp_path):
    # A hook sets `GIT_DIR`, which outranks the directory a git command is run in. The library
    # variables are cleared because `citations` reads a shared library from either, and a
    # machine that has one would report this project's library as already present.
    for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "CITATIONS_HOME"):
        monkeypatch.delenv(name, raising=False)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_DATA_HOME", str(home / "data"))

    def run(*args: str, cwd) -> tuple[int, str]:
        monkeypatch.chdir(cwd)
        code = main(list(args))
        return code, capsys.readouterr().out

    return run


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "study"
    root.mkdir()
    # Run under a git hook, `GIT_DIR` names the repository the hook belongs to, and `git init`
    # would act on that one and leave this directory outside any repository.
    plain = {name: value for name, value in os.environ.items() if not name.startswith("GIT_")}
    subprocess.run(["git", "init", "-q", "."], cwd=root, check=True, capture_output=True, env=plain)
    return root


def tree(root: pathlib.Path) -> dict[str, str]:
    """Every path below `root` outside `.git`, with a digest of each file's bytes."""
    return {
        path.relative_to(root).as_posix(): (
            hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else "directory"
        )
        for path in sorted(root.rglob("*"))
        if ".git" not in path.relative_to(root).parts
    }


def states(out: str) -> dict[str, str]:
    """`created` or `already present` per record, read off the report."""
    found = {}
    for line in out.split("\n\n")[1].splitlines():
        label, _, rest = line.strip().partition(" ")
        found[label] = "created" if rest.strip().startswith("created") else rest.strip()[:15]
    return found


def test_in_an_empty_project_it_creates_all_four_and_each_tool_reads_what_it_made(
    project, run_repro
):
    code, out = run_repro("init", cwd=project)
    assert code == 0, out
    assert states(out) == dict.fromkeys(RECORDS, "created")

    assert (project / "PREREG.md").is_file()
    assert (project / ".results" / "ledger.jsonl").is_file()
    assert (project / ".citations" / "records").is_dir()
    assert not (project / ".citations" / ".git").exists(), "a repository nested in a repository"
    assert (project / "claims").is_dir()
    assert load(project / DEFAULT_NAME).artifacts == ()

    # Nothing is pinned and no claim is declared, and a manifest that checks nothing fails.
    code, out = run_repro("verify", cwd=project)
    assert code == 1
    assert "report.empty" in out and "no evidence assertion was evaluated" in out

    code, out = run_repro("results", "verify", cwd=project)
    assert code == 0
    assert "chain intact: 1 events, anchored" in out

    # The plan is a draft, which `prereg check` reports with its own exit code and no failure.
    code, out = run_repro("prereg", "check", cwd=project)
    assert code == 2
    assert "not frozen" in out and "Nothing to check against yet" in out


def test_a_second_run_changes_no_file_and_reports_every_record_present(project, run_repro):
    assert run_repro("init", cwd=project)[0] == 0
    before = tree(project)
    assert len(before) > len(RECORDS)

    code, out = run_repro("init", cwd=project)
    assert code == 0
    assert states(out) == dict.fromkeys(RECORDS, "already present")
    assert "nothing was created" in out
    assert tree(project) == before


def test_only_the_missing_records_are_created_and_the_existing_ones_keep_their_bytes(
    project, run_repro
):
    assert run_repro("results", "init", cwd=project)[0] == 0
    (project / "PREREG.md").write_text("# My plan\n\nH1. Written by hand.\n")
    before = tree(project)

    code, out = run_repro("init", cwd=project)
    assert code == 0, out
    assert states(out) == {
        "plan": "already present",
        "ledger": "already present",
        "citations": "created",
        "manifest": "created",
    }
    after = tree(project)
    assert {path: after[path] for path in before} == before
    assert (project / ".citations" / "records").is_dir()
    assert (project / DEFAULT_NAME).is_file()
    assert not (project / "tests").exists(), "the plan's scaffold ran over an existing plan"


def test_a_plan_under_another_name_is_left_alone_and_no_template_is_put_beside_it(
    project, run_repro
):
    (project / "prereg_sweep_v2.md").write_text("# Sweep\n\nCommit SHA: abc\n")

    code, out = run_repro("init", cwd=project)
    assert code == 0, out
    assert states(out)["plan"] == "already present"
    assert "prereg_sweep_v2.md" in out
    assert not (project / "PREREG.md").exists()


def test_a_named_project_gets_its_manifest_in_its_own_directory(project, run_repro):
    code, out = run_repro("init", "pilot", cwd=project)
    assert code == 0, out
    assert load(project / "pilot" / DEFAULT_NAME).project == "pilot"
    assert not (project / DEFAULT_NAME).exists()
    assert (project / "pilot" / "pilot" / "PREREG.md").is_file()
    assert (project / "pilot" / ".results").is_dir()


def test_a_directory_without_a_name_is_refused_and_nothing_is_created(project, run_repro):
    code, out = run_repro("init", "--directory", str(project / "elsewhere"), cwd=project)
    assert code == 2
    assert "needs a name" in out
    assert tree(project) == {}
