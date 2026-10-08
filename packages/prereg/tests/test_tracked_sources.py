"""A freeze says which pinned sources git tracks, and is otherwise the freeze it would have been.

A freeze names a commit. A source text in that commit can only be taken out later by rewriting
history, which gives the commit another identifier, so `prereg freeze` asks `citations` which
pinned sources git tracks and prints them. It asks the installed command and imports nothing of
it. Every repository here is a real one made in `tmp_path`, and the `citations` asked is the one
installed beside these tests, except where a test names a stand-in.
"""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sysconfig

import pytest
from prereg import cli, sources
from provenance_core.gitref import clean_env

TEXT = "A generalization is invariant if it continues to hold under some interventions.\n"

WARNING = """
git tracks 1 source this project's quotations are pinned to
  tracked  study/sources/woodward.txt
  A source in the commit a freeze names can only be removed later by rewriting history,
  which changes that commit's identifier. Untrack and ignore the files before freezing.
"""


def git(repo: pathlib.Path, *args: str) -> str:
    # `clean_env`, because the pre-push hook runs this suite with `GIT_DIR` exported and these
    # commits would otherwise land in the repository being pushed.
    return subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
        cwd=repo,
        env=clean_env(),
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def write_claims(root: pathlib.Path, name: str) -> None:
    """A claims file under `root/claims` and the source it pins under `root/sources`."""
    (root / "sources").mkdir(exist_ok=True)
    (root / "sources" / f"{name}.txt").write_text(TEXT)
    (root / "claims").mkdir(exist_ok=True)
    (root / "claims" / f"{name}.yaml").write_text(
        json.dumps(
            {
                "source": {
                    "citation": name,
                    "local": f"sources/{name}.txt",
                    "sha256": hashlib.sha256(TEXT.encode()).hexdigest(),
                },
                "claims": {"c1": {"quotes": [{"exact": "continues to hold"}]}},
            }
        )
    )


@pytest.fixture(autouse=True)
def citations_installed(monkeypatch):
    """This environment's `citations` first on `PATH`, where an activated environment has it."""
    scripts = sysconfig.get_path("scripts")
    assert shutil.which("citations", path=scripts), "the workspace installs citations"
    monkeypatch.setenv("PATH", os.pathsep.join([scripts, os.environ["PATH"]]))


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A repository whose one commit holds a plan in `study/`, with nothing else tracked."""
    top = tmp_path / "repo"
    top.mkdir()
    git(top, "init", "-q")
    monkeypatch.chdir(top)
    assert cli.main(["new", "study"]) == 0
    git(top, "add", "study/PREREG.md", "study/.gitignore")
    git(top, "commit", "-q", "-m", "plan")
    return top


def freeze(study: pathlib.Path, monkeypatch, capsys, *argv: str) -> tuple[int, str]:
    monkeypatch.chdir(study)
    capsys.readouterr()
    code = cli.main(["freeze", *argv])
    return code, capsys.readouterr().out


def written(study: pathlib.Path) -> dict[str, bytes]:
    """Every file a freeze of `study` left there, the freeze's own time taken out of its record."""
    files = {
        p.relative_to(study).as_posix(): p.read_bytes() for p in study.rglob("*") if p.is_file()
    }
    record = json.loads(files[".prereg/PREREG.md.json"])
    del record["frozen_at"]
    return files | {".prereg/PREREG.md.json": json.dumps(record, sort_keys=True).encode()}


def test_a_tracked_source_is_named_and_the_freeze_is_the_one_made_without_it(
    repo, tmp_path, monkeypatch, capsys
):
    write_claims(repo / "study", "woodward")
    tracked = tmp_path / "tracked"
    shutil.copytree(repo, tracked)
    git(tracked, "add", "study/sources/woodward.txt")
    assert git(tracked, "rev-parse", "HEAD") == git(repo, "rev-parse", "HEAD")

    plain_code, plain_out = freeze(repo / "study", monkeypatch, capsys)
    code, out = freeze(tracked / "study", monkeypatch, capsys)

    assert (plain_code, code) == (0, 0)
    assert "git tracks" not in plain_out
    assert out.replace(str(tracked), str(repo)) == plain_out + WARNING
    assert written(tracked / "study") == written(repo / "study")
    assert cli.main(["check"]) == 0


@pytest.mark.parametrize("ignored", [False, True])
def test_a_source_git_does_not_track_is_not_reported(repo, monkeypatch, capsys, ignored):
    write_claims(repo / "study", "woodward")
    if ignored:
        (repo / ".gitignore").write_text("sources/\n")
        git(repo, "add", ".gitignore", "study/claims")
    code, out = freeze(repo / "study", monkeypatch, capsys)
    assert code == 0
    assert "git tracks" not in out
    assert sources.tracked(repo / "study") == []


def test_a_project_with_no_claims_directory_is_told_nothing(repo, monkeypatch, capsys):
    (repo / "study" / "sources").mkdir()
    (repo / "study" / "sources" / "woodward.txt").write_text(TEXT)
    git(repo, "add", "study/sources")
    code, out = freeze(repo / "study", monkeypatch, capsys)
    assert code == 0
    assert "git tracks" not in out


def test_claims_kept_at_the_top_of_the_repository_are_asked_about_from_a_plan_below_it(
    repo, monkeypatch, capsys
):
    write_claims(repo, "woodward")
    git(repo, "add", "sources")
    code, out = freeze(repo / "study", monkeypatch, capsys)
    assert code == 0
    assert "git tracks 1 source this project's quotations are pinned to" in out
    assert "\n  tracked  sources/woodward.txt\n" in out


def test_past_ten_the_warning_counts_the_rest(repo, monkeypatch, capsys):
    for i in range(12):
        write_claims(repo / "study", f"paper{i:02d}")
    git(repo, "add", "study/sources")
    code, out = freeze(repo / "study", monkeypatch, capsys)
    assert code == 0
    assert "git tracks 12 sources this project's quotations are pinned to" in out
    assert out.count("\n  tracked  ") == 10
    assert "\n  tracked  study/sources/paper09.txt\n" in out
    assert "paper10.txt" not in out
    assert "  ... and 2 more; `citations lint --claims` lists every one\n" in out


def test_a_plan_frozen_in_place_is_told_when_it_is_frozen_again(
    repo, frozen_in_place, monkeypatch, capsys
):
    (repo / "study" / "PREREG.md").write_bytes(frozen_in_place)
    write_claims(repo / "study", "woodward")
    git(repo, "add", "study/PREREG.md", "study/sources")
    git(repo, "commit", "-q", "-m", "frozen in place, with a source")
    code, out = freeze(repo / "study", monkeypatch, capsys, "--force", "--access", "nothing run")
    assert code == 0
    assert out.endswith(WARNING)


def without_citations(monkeypatch) -> None:
    """`PATH` with every directory that holds a `citations` taken out, and git still on it."""
    kept = [
        d for d in os.environ["PATH"].split(os.pathsep) if not shutil.which("citations", path=d)
    ]
    monkeypatch.setenv("PATH", os.pathsep.join(kept))
    assert shutil.which("citations") is None
    assert shutil.which("git")


def test_without_citations_on_path_nothing_is_reported_and_the_freeze_succeeds(
    repo, monkeypatch, capsys
):
    write_claims(repo / "study", "woodward")
    git(repo, "add", "study/sources")
    assert sources.tracked(repo / "study") == ["study/sources/woodward.txt"]
    without_citations(monkeypatch)
    code, out = freeze(repo / "study", monkeypatch, capsys)
    assert code == 0
    assert "git tracks" not in out
    assert "frozen  " in out
    assert json.loads((repo / "study" / ".prereg" / "PREREG.md.json").read_text())["sha256"] == (
        hashlib.sha256((repo / "study" / "PREREG.md").read_bytes()).hexdigest()
    )


@pytest.mark.parametrize(
    "script",
    [
        "exit 2",
        "echo 'usage: citations lint: error: argument --claims: expected one argument' >&2; exit 2",
        "echo 'not a document'",
        """echo '{"sources": 1}'""",
        """echo '{"sources": 1, "tracked": [{"claims_file": "c.yaml"}]}'""",
        "exec sleep 5",
    ],
)
def test_a_citations_that_cannot_be_asked_is_passed_over(
    repo, tmp_path, monkeypatch, capsys, script
):
    write_claims(repo / "study", "woodward")
    git(repo, "add", "study/sources")
    without_citations(monkeypatch)
    stand_in = tmp_path / "bin" / "citations"
    stand_in.parent.mkdir()
    stand_in.write_text(f"#!/bin/sh\n{script}\n")
    stand_in.chmod(0o755)
    monkeypatch.setenv("PATH", os.pathsep.join([str(stand_in.parent), os.environ["PATH"]]))
    monkeypatch.setattr(sources, "TIMEOUT", 0.5)
    code, out = freeze(repo / "study", monkeypatch, capsys)
    assert code == 0
    assert "git tracks" not in out
