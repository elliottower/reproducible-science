"""A freeze is refused where git holds a pinned source, before anything is written.

A freeze names a commit. A source text in that commit can only be taken out later by rewriting
history, which gives the commit another identifier, so `prereg freeze` asks `citations` which
pinned sources the index or the last commit holds, and refuses where there are any unless `--allow-tracked-sources` is
given. It asks the installed command and imports nothing of it, and a question that could not
be asked refuses nothing. Every repository here is a real one made in `tmp_path`, and the
`citations` asked is the one installed beside these tests, except where a test names a stand-in.
"""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import sysconfig

import pytest
from prereg import amendment, cli, sources
from provenance_core.gitref import clean_env

TEXT = "A generalization is invariant if it continues to hold under some interventions.\n"

WHY = """\
A freeze names a commit, and a source in that commit can only be removed later by
rewriting history, which changes the commit's identifier.
"""

UNTRACK = """\
`{label}`: untrack each with `git rm --cached <file>`, add an ignore
rule, commit, and freeze again. The record's sha256 still pins the file.
"""

COMMIT_THE_REMOVAL = """\
`in HEAD`: no longer tracked, and still in the last commit. Commit the removal,
then freeze.
"""

ALLOW = "--allow-tracked-sources"


def listed(label: str) -> str:
    return (
        "git holds 1 source this project's quotations are pinned to\n"
        f"  {label:<7}  study/sources/woodward.txt\n"
    )


def refusal(path: pathlib.Path, label: str) -> str:
    """What a freeze of `path` prints when its one pinned source stands as `label` says."""
    remedy = COMMIT_THE_REMOVAL if label == "in HEAD" else UNTRACK.format(label=label)
    return (
        f"{path} was not frozen, and nothing was written.\n"
        + listed(label)
        + WHY
        + remedy
        + f"Or keep them and freeze with {ALLOW}.\n"
    )


def warning(label: str) -> str:
    return (
        "\n"
        + listed(label)
        + f"  Frozen with {ALLOW}. A source in the commit a freeze names can only\n"
        "  be removed later by rewriting history, which changes that commit's identifier.\n"
    )


def git(repo: pathlib.Path, *args: str) -> str:
    # `clean_env`, because the pre-push hook runs this suite with `GIT_DIR` exported and these
    # commits would otherwise land in the repository being pushed. No maintenance after a commit:
    # it runs detached and holds `.git/objects/maintenance.lock` while a test copies the repository.
    return subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "-c", "maintenance.auto=false", *args],
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


def state(top: pathlib.Path) -> dict[str, tuple[int, bytes]]:
    """Every file in the working tree with its mode, and what git holds, as one comparison."""
    files = {
        p.relative_to(top).as_posix(): (p.stat().st_mode, p.read_bytes())
        for p in top.rglob("*")
        if p.is_file() and ".git" not in p.relative_to(top).parts[:1]
    }
    held = "\n".join(
        git(top, *args)
        for args in (("status", "--porcelain"), ("rev-parse", "HEAD"), ("ls-files", "--stage"))
    )
    return files | {"<git>": (0, held.encode())}


def track(repo: pathlib.Path, *paths: str) -> None:
    """Commit `paths`, so the index and the last commit both hold them."""
    git(repo, "add", *paths)
    git(repo, "commit", "-q", "-m", "sources")


def test_a_tracked_source_refuses_the_freeze_and_nothing_is_written(repo, monkeypatch, capsys):
    write_claims(repo / "study", "woodward")
    track(repo, "study/sources/woodward.txt")
    before = state(repo)

    code, out = freeze(repo / "study", monkeypatch, capsys)

    assert code == 1
    assert out == refusal(repo / "study" / "PREREG.md", "tracked")
    assert state(repo) == before
    assert not list(repo.rglob("*.provenance-lock")), "not even the lock's sidecar"
    assert not (repo / "study" / ".prereg").exists()
    assert cli.main(["check"]) == 2, "the plan is still a draft"


def test_a_source_staged_and_not_yet_committed_refuses_the_freeze(repo, monkeypatch, capsys):
    write_claims(repo / "study", "woodward")
    git(repo, "add", "study/sources/woodward.txt")
    before = state(repo)

    code, out = freeze(repo / "study", monkeypatch, capsys)

    assert code == 1
    assert out == refusal(repo / "study" / "PREREG.md", "staged")
    assert state(repo) == before


def test_a_source_untracked_and_still_in_the_last_commit_refuses_until_the_removal_is_committed(
    repo, monkeypatch, capsys
):
    write_claims(repo / "study", "woodward")
    track(repo, "study/sources/woodward.txt")
    git(repo, "rm", "-q", "--cached", "study/sources/woodward.txt")
    (repo / ".gitignore").write_text("sources/\n")
    git(repo, "add", ".gitignore")
    assert "woodward.txt" not in git(repo, "ls-files")
    before = state(repo)

    code, out = freeze(repo / "study", monkeypatch, capsys)
    assert code == 1
    assert out == refusal(repo / "study" / "PREREG.md", "in HEAD")
    assert state(repo) == before

    git(repo, "commit", "-q", "-m", "the source is kept out")
    code, out = freeze(repo / "study", monkeypatch, capsys)
    assert code == 0
    assert "git holds" not in out


def test_a_source_deleted_from_disk_and_still_in_the_last_commit_refuses(repo, monkeypatch, capsys):
    write_claims(repo / "study", "woodward")
    track(repo, "study/sources/woodward.txt")
    git(repo, "rm", "-q", "study/sources/woodward.txt")
    assert not (repo / "study" / "sources" / "woodward.txt").exists()

    code, out = freeze(repo / "study", monkeypatch, capsys)
    assert code == 1
    assert out == refusal(repo / "study" / "PREREG.md", "in HEAD")


def test_each_source_is_listed_as_it_stands_and_each_case_has_its_way_out(
    repo, monkeypatch, capsys
):
    for name in ("committed", "removed", "staged"):
        write_claims(repo / "study", name)
    track(repo, "study/sources/committed.txt", "study/sources/removed.txt")
    git(repo, "rm", "-q", "--cached", "study/sources/removed.txt")
    git(repo, "add", "study/sources/staged.txt")

    code, out = freeze(repo / "study", monkeypatch, capsys)
    assert code == 1
    assert (
        "git holds 3 sources this project's quotations are pinned to\n"
        "  tracked  study/sources/committed.txt\n"
        "  in HEAD  study/sources/removed.txt\n"
        "  staged   study/sources/staged.txt\n"
    ) in out
    assert "`tracked` and `staged`: untrack each with `git rm --cached <file>`" in out
    assert COMMIT_THE_REMOVAL in out


def test_a_plan_already_frozen_is_told_so_and_not_asked_about_its_sources(
    repo, monkeypatch, capsys
):
    assert freeze(repo / "study", monkeypatch, capsys)[0] == 0
    write_claims(repo / "study", "woodward")
    track(repo, "study/sources/woodward.txt")
    code, out = freeze(repo / "study", monkeypatch, capsys)
    assert code == 1
    assert "is already frozen, and a frozen file never changes." in out
    assert "git holds" not in out


def test_with_the_flag_the_sources_are_named_and_the_freeze_is_the_one_made_without_them(
    repo, tmp_path, monkeypatch, capsys
):
    write_claims(repo / "study", "woodward")
    tracked = tmp_path / "tracked"
    shutil.copytree(repo, tracked)
    git(tracked, "add", "study/sources/woodward.txt")
    assert git(tracked, "rev-parse", "HEAD") == git(repo, "rev-parse", "HEAD")

    plain_code, plain_out = freeze(repo / "study", monkeypatch, capsys)
    code, out = freeze(tracked / "study", monkeypatch, capsys, ALLOW)

    assert (plain_code, code) == (0, 0)
    assert "git holds" not in plain_out
    assert out.replace(str(tracked), str(repo)) == plain_out + warning("staged")
    assert written(tracked / "study") == written(repo / "study")
    assert cli.main(["check"]) == 0


def test_the_flag_changes_nothing_where_no_source_is_tracked(repo, monkeypatch, capsys):
    write_claims(repo / "study", "woodward")
    code, out = freeze(repo / "study", monkeypatch, capsys, ALLOW)
    assert code == 0
    assert "git holds" not in out
    assert ALLOW not in out


@pytest.mark.parametrize("ignored", [False, True])
def test_a_source_git_does_not_track_refuses_nothing(repo, monkeypatch, capsys, ignored):
    write_claims(repo / "study", "woodward")
    if ignored:
        (repo / ".gitignore").write_text("sources/\n")
        git(repo, "add", ".gitignore", "study/claims")
    code, out = freeze(repo / "study", monkeypatch, capsys)
    assert code == 0
    assert "git holds" not in out
    assert sources.tracked(repo / "study") == []


def test_a_project_with_no_claims_directory_is_frozen_and_told_nothing(repo, monkeypatch, capsys):
    (repo / "study" / "sources").mkdir()
    (repo / "study" / "sources" / "woodward.txt").write_text(TEXT)
    git(repo, "add", "study/sources")
    code, out = freeze(repo / "study", monkeypatch, capsys)
    assert code == 0
    assert "git holds" not in out


def test_claims_kept_at_the_top_of_the_repository_are_asked_about_from_a_plan_below_it(
    repo, monkeypatch, capsys
):
    write_claims(repo, "woodward")
    git(repo, "add", "sources")
    code, out = freeze(repo / "study", monkeypatch, capsys)
    assert code == 1
    assert "\n  staged   sources/woodward.txt\n" in out
    assert not (repo / "study" / ".prereg").exists()


def test_past_ten_the_refusal_counts_the_rest(repo, monkeypatch, capsys):
    for i in range(12):
        write_claims(repo / "study", f"paper{i:02d}")
    git(repo, "add", "study/sources")
    code, out = freeze(repo / "study", monkeypatch, capsys)
    assert code == 1
    assert "git holds 12 sources this project's quotations are pinned to" in out
    assert out.count("\n  staged   ") == 10
    assert "\n  staged   study/sources/paper09.txt\n" in out
    assert "paper10.txt" not in out
    assert "  ... and 2 more; `citations lint --claims` lists every one\n" in out


def test_a_forced_refreeze_of_a_plan_frozen_in_place_is_refused_the_same_way(
    repo, frozen_in_place, monkeypatch, capsys
):
    (repo / "study" / "PREREG.md").write_bytes(frozen_in_place)
    write_claims(repo / "study", "woodward")
    git(repo, "add", "study/PREREG.md", "study/sources")
    git(repo, "commit", "-q", "-m", "frozen in place, with a source")
    before = state(repo)

    again = ("--force", "--access", "nothing run")
    code, out = freeze(repo / "study", monkeypatch, capsys, *again)
    assert code == 1
    assert out == refusal(repo / "study" / "PREREG.md", "tracked")
    assert state(repo) == before

    code, out = freeze(repo / "study", monkeypatch, capsys, *again, ALLOW)
    assert code == 0
    assert out.endswith(warning("tracked"))


def test_an_amendment_is_refused_the_same_way(repo, monkeypatch, capsys):
    study = repo / "study"
    assert freeze(study, monkeypatch, capsys)[0] == 0
    assert cli.main(["amend"]) == 0
    amended = study / "PREREG_AMENDMENT_1.md"
    text = amended.read_text()
    text = text.replace(amendment.HINTS[amendment.SECTIONS], "Replaces `Sample size`.")
    text = text.replace(amendment.HINTS[amendment.REASON], "The first sample was too small.")
    text = re.sub(r"^\*\*Access level:\*\*.*$", "**Access level:** nothing run", text, flags=re.M)
    amended.write_text(text)
    write_claims(study, "woodward")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "an amendment, and a source")
    before = state(repo)

    code, out = freeze(study, monkeypatch, capsys, amended.name)
    assert code == 1
    assert out == refusal(amended, "tracked")
    assert state(repo) == before
    assert freeze(study, monkeypatch, capsys, amended.name, ALLOW)[0] == 0


def test_a_refused_freeze_sends_nothing_to_osf(repo, fake_osf, monkeypatch, capsys):
    write_claims(repo / "study", "woodward")
    git(repo, "add", "study/sources")
    code, out = freeze(repo / "study", monkeypatch, capsys, "--osf")
    assert code == 1
    assert "was not frozen, and nothing was written." in out
    assert fake_osf.calls == []


def test_outside_a_repository_nothing_is_found(tmp_path):
    write_claims(tmp_path, "woodward")
    assert sources.tracked(tmp_path) == []


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
    assert sources.tracked(repo / "study") == [
        sources.Held("study/sources/woodward.txt", index=True, head=False)
    ]
    without_citations(monkeypatch)
    code, out = freeze(repo / "study", monkeypatch, capsys)
    assert code == 0
    assert "git holds" not in out
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
    assert "git holds" not in out
