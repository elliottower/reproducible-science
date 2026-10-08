"""A pinned source that git tracks is reported, and the report changes no verdict.

A claims file pins its source by a sha256, so nothing needs the source committed, and a
committed one is somebody else's text published with the repository. `verify`, `lint --claims`
and `pin` each say so. None of them fails on it, and none of them writes an ignore rule.
"""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import subprocess

import pytest
import yaml
from citations import cli, lint, pin, tracked
from citations import verify as V

PASSAGE = "the range of changes over which a relationship remains invariant"
TEXT = "A generalization is invariant if it continues to hold: " + PASSAGE + " is its domain.\n"
ABSENT = "a sentence the source does not contain anywhere in its text at all"


def git(folder: pathlib.Path, *args: str) -> None:
    # A clean environment: a hook exports `GIT_DIR`, which outranks the directory given here.
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    subprocess.run(["git", *args], cwd=folder, check=True, env=env, capture_output=True)


@pytest.fixture(autouse=True)
def _no_cache():
    V.clear_caches()


def write_claims(root: pathlib.Path, name: str, quote: str = PASSAGE) -> pathlib.Path:
    source = root / "sources" / f"{name}.txt"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(TEXT)
    claims = root / "claims"
    claims.mkdir(exist_ok=True)
    f = claims / f"{name}.yaml"
    f.write_text(
        yaml.safe_dump(
            {
                "source": {
                    "citation": name,
                    "local": f"sources/{name}.txt",
                    "sha256": hashlib.sha256(TEXT.encode()).hexdigest(),
                    "url": f"https://example.org/{name}.txt",
                },
                "claims": {"domain": {"quotes": [{"exact": quote}]}},
            }
        )
    )
    return f


@pytest.fixture
def paper(tmp_path):
    root = tmp_path / "paper"
    root.mkdir()
    write_claims(root, "woodward")
    return root


def verify(root: pathlib.Path, *flags: str) -> int:
    return cli.main(["verify", "--no-cache", *flags, "--claims", str(root / "claims")])


def test_a_tracked_source_is_named_in_the_report(paper, capsys):
    git(paper, "init", "-q")
    git(paper, "add", "sources/woodward.txt")
    assert verify(paper) == 0
    out = capsys.readouterr().out
    assert "git tracks 1 source read here" in out
    source = (paper / "sources" / "woodward.txt").resolve()
    assert f"  tracked  {'woodward':<40}{source}\n" in out
    assert "git rm --cached" in out
    assert "citations fetch" in out


def test_a_source_git_does_not_track_is_not_reported(paper, capsys):
    git(paper, "init", "-q")
    assert verify(paper) == 0
    assert "git tracks" not in capsys.readouterr().out


def test_an_ignored_source_is_not_reported(paper, capsys):
    git(paper, "init", "-q")
    (paper / ".gitignore").write_text("sources/\n")
    git(paper, "add", ".")
    assert verify(paper) == 0
    assert "git tracks" not in capsys.readouterr().out


def test_outside_a_repository_nothing_is_reported(paper, capsys):
    assert verify(paper) == 0
    assert "git tracks" not in capsys.readouterr().out


@pytest.mark.parametrize("flags", [(), ("--strict",)])
@pytest.mark.parametrize(("quote", "code"), [(PASSAGE, 0), (ABSENT, 1)])
def test_tracking_a_source_changes_no_exit_code(tmp_path, capsys, flags, quote, code):
    root = tmp_path / "paper"
    root.mkdir()
    write_claims(root, "woodward", quote)
    assert verify(root, *flags) == code
    git(root, "init", "-q")
    git(root, "add", ".")
    capsys.readouterr()
    assert verify(root, *flags) == code
    assert "git tracks 1 source read here" in capsys.readouterr().out


def test_past_ten_the_report_counts_the_rest_and_names_the_listing(tmp_path, capsys):
    root = tmp_path / "paper"
    root.mkdir()
    for i in range(12):
        write_claims(root, f"paper{i:02d}")
    git(root, "init", "-q")
    git(root, "add", "sources")
    assert verify(root, "--strict") == 0
    out = capsys.readouterr().out
    assert "git tracks 12 sources read here" in out
    assert out.count("\n  tracked  ") == 10
    assert "... and 2 more; `citations lint --claims <dir>` lists every one" in out


def test_lint_lists_every_tracked_source_and_exits_zero(tmp_path, capsys):
    root = tmp_path / "paper"
    root.mkdir()
    for i in range(12):
        write_claims(root, f"paper{i:02d}")
    write_claims(root, "kept-out")
    git(root, "init", "-q")
    git(root, "add", *[f"sources/paper{i:02d}.txt" for i in range(12)])
    assert lint.main(["--claims", str(root / "claims")]) == 0
    out = capsys.readouterr().out
    assert "13 pinned sources on disk, 12 tracked by git" in out
    assert out.count("\n  tracked  ") == 12
    assert "kept-out.txt" not in out


def test_lint_reports_the_same_sources_as_json(paper, capsys):
    git(paper, "init", "-q")
    git(paper, "add", "sources/woodward.txt")
    assert lint.main(["--claims", str(paper / "claims"), "--json"]) == 0
    said = json.loads(capsys.readouterr().out)
    assert said == {
        "sources": 1,
        "tracked": [
            {
                "claims_file": str((paper / "claims" / "woodward.yaml").resolve()),
                "source": str((paper / "sources" / "woodward.txt").resolve()),
                "index": True,
                "head": False,
            }
        ],
    }


def committed_then_untracked(paper: pathlib.Path) -> pathlib.Path:
    """`paper` with its source committed and then taken out of the index, the removal uncommitted."""
    git(paper, "init", "-q")
    git(paper, "add", "sources/woodward.txt")
    git(paper, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "a source")
    git(paper, "rm", "-q", "--cached", "sources/woodward.txt")
    return (paper / "sources" / "woodward.txt").resolve()


def rows(paper: pathlib.Path, capsys) -> list[tuple[bool, bool]]:
    capsys.readouterr()
    assert lint.main(["--claims", str(paper / "claims"), "--json"]) == 0
    return [(r["index"], r["head"]) for r in json.loads(capsys.readouterr().out)["tracked"]]


def test_lint_says_of_each_source_whether_the_index_holds_it_and_whether_the_last_commit_does(
    paper, capsys
):
    assert rows(paper, capsys) == []
    git(paper, "init", "-q")
    assert rows(paper, capsys) == [], "a repository with no commit, and nothing staged"
    git(paper, "add", "sources/woodward.txt")
    assert rows(paper, capsys) == [(True, False)]
    git(paper, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "a source")
    assert rows(paper, capsys) == [(True, True)]
    git(paper, "rm", "-q", "--cached", "sources/woodward.txt")
    assert rows(paper, capsys) == [(False, True)]
    (paper / "sources" / "woodward.txt").unlink()
    assert rows(paper, capsys) == [(False, True)], "deleting the file takes it out of no commit"
    git(paper, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "removed")
    assert rows(paper, capsys) == []


def test_lint_lists_a_source_out_of_the_index_and_still_in_the_last_commit(paper, capsys):
    source = committed_then_untracked(paper)
    assert tracked.tracked([source]) == set()
    assert tracked.committed([source]) == {source}
    assert lint.main(["--claims", str(paper / "claims")]) == 0
    out = capsys.readouterr().out
    assert (
        "1 pinned source on disk, 0 tracked by git, 1 more out of the index and still in the "
        "last commit"
    ) in out
    assert f"  in HEAD  {'woodward.yaml':<40}{source}\n" in out
    assert "commit the removal" in out


@pytest.mark.parametrize("flags", [(), ("--strict",)])
def test_verify_names_a_source_the_last_commit_still_holds_and_changes_no_exit_code(
    paper, capsys, flags
):
    source = committed_then_untracked(paper)
    assert verify(paper, *flags) == 0
    out = capsys.readouterr().out
    assert "git tracks" not in out
    assert (
        "the last commit still holds 1 source read here that git no longer tracks: "
        "commit the removal"
    ) in out
    assert f"  in HEAD  {'woodward':<40}{source}\n" in out
    assert not [line for line in out.splitlines() if line.split()[:2] == ["1", "source"]]


def test_lint_refuses_json_for_claims_and_a_bibliography_together(paper, capsys):
    bib = paper / "refs.bib"
    bib.write_text("@misc{x, title = {A title}}\n")
    code = lint.main(["--claims", str(paper / "claims"), "--bib", str(bib), "--json"])
    assert code == 2
    assert "--json prints one document" in capsys.readouterr().out


def test_lint_refuses_a_claims_directory_that_is_not_there(tmp_path, capsys):
    assert lint.main(["--claims", str(tmp_path / "nowhere")]) == 2
    assert "no claims directory" in capsys.readouterr().out


def test_lint_given_no_directory_reads_the_claims_here_or_the_nearest_above(
    paper, monkeypatch, capsys
):
    git(paper, "init", "-q")
    git(paper, "add", "sources/woodward.txt")
    below = paper / "experiments" / "one"
    below.mkdir(parents=True)
    for folder in (paper, below):
        monkeypatch.chdir(folder)
        assert lint.main(["--claims", "--json"]) == 0
        said = json.loads(capsys.readouterr().out)
        assert [row["source"] for row in said["tracked"]] == [
            str((paper / "sources" / "woodward.txt").resolve())
        ]


def test_lint_given_no_directory_does_not_look_above_the_repository(paper, monkeypatch, capsys):
    inner = paper / "inner"
    inner.mkdir()
    git(inner, "init", "-q")
    monkeypatch.chdir(inner)
    assert lint.main(["--claims"]) == 2
    assert "no claims directory at claims" in capsys.readouterr().out


def test_lint_given_no_directory_outside_a_repository_reads_the_working_directory_alone(
    paper, monkeypatch, capsys
):
    below = paper / "below"
    below.mkdir()
    monkeypatch.chdir(below)
    assert lint.main(["--claims"]) == 2
    assert "no claims directory at claims" in capsys.readouterr().out
    monkeypatch.chdir(paper)
    assert lint.main(["--claims"]) == 0
    assert "1 pinned source on disk, 0 tracked by git" in capsys.readouterr().out


def pinned(paper: pathlib.Path) -> int:
    f = paper / "claims" / "woodward.yaml"
    return pin.main([str(f), "--id", "again", "--quote", "A generalization is invariant if it"])


def test_pin_says_when_the_source_is_tracked(paper, capsys):
    git(paper, "init", "-q")
    git(paper, "add", "sources/woodward.txt")
    assert pinned(paper) == 0
    out = capsys.readouterr().out
    assert "woodward.txt is tracked by git" in out
    assert "git rm --cached" in out


def test_pin_says_when_no_ignore_rule_covers_the_source_and_writes_none(paper, capsys):
    git(paper, "init", "-q")
    assert pinned(paper) == 0
    assert "no ignore rule covers woodward.txt" in capsys.readouterr().out
    assert not (paper / ".gitignore").exists()


def test_pin_says_nothing_of_an_ignored_source(paper, capsys):
    git(paper, "init", "-q")
    (paper / ".gitignore").write_text("sources/\n")
    assert pinned(paper) == 0
    out = capsys.readouterr().out
    assert "tracked by git" not in out
    assert "no ignore rule" not in out
    assert (paper / ".gitignore").read_text() == "sources/\n"


def test_pin_says_nothing_outside_a_repository(paper, capsys):
    assert pinned(paper) == 0
    out = capsys.readouterr().out
    assert "tracked by git" not in out
    assert "no ignore rule" not in out


def test_each_standing_is_reached(paper):
    source = (paper / "sources" / "woodward.txt").resolve()
    assert tracked.standing(source) == "outside"
    git(paper, "init", "-q")
    assert tracked.standing(source) == "unignored"
    git(paper, "add", "sources/woodward.txt")
    assert tracked.standing(source) == "tracked"
    git(paper, "rm", "-q", "--cached", "sources/woodward.txt")
    (paper / ".gitignore").write_text("sources/\n")
    assert tracked.standing(source) == "ignored"


def test_without_git_nothing_is_reported_and_nothing_fails(paper, tmp_path, monkeypatch, capsys):
    git(paper, "init", "-q")
    git(paper, "add", "sources/woodward.txt")
    source = (paper / "sources" / "woodward.txt").resolve()
    empty = tmp_path / "no-programs"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    assert tracked.tracked([source]) == set()
    assert tracked.standing(source) == "outside"
    assert verify(paper, "--strict") == 0
    assert "git tracks" not in capsys.readouterr().out
