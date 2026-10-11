from __future__ import annotations

import json
import os
import subprocess

import pytest
from repro.cli import main
from repro.manifest import DEFAULT_NAME, load
from repro.models import MetricEvidence, Outcome, QuoteEvidence, Validity
from repro.policy import PUBLICATION
from repro.starter import MAX_DISCOVERED
from repro.verify import verify


@pytest.fixture
def run_repro(monkeypatch, capsys):
    # A hook sets `GIT_DIR`, which outranks the directory a git command is run in.
    for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
        monkeypatch.delenv(name, raising=False)

    def run(*args: str, cwd) -> tuple[int, str]:
        monkeypatch.chdir(cwd)
        code = main(list(args))
        return code, capsys.readouterr().out

    return run


def rules(assessment) -> list[str]:
    return [v.rule for v in assessment.errors]


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "study"
    (root / "results").mkdir(parents=True)
    (root / "results" / "metrics.json").write_text(
        json.dumps({"model": "lasso", "scores": {"accuracy": 0.9312, "n": 480}})
    )
    return root


def test_the_starter_verifies_as_written_with_a_number_read_from_the_pinned_file(
    project, run_repro
):
    code, out = run_repro("manifest", "init", cwd=project)
    assert code == 0, out

    manifest = load(project / DEFAULT_NAME)
    assert [(a.id, a.path.as_posix()) for a in manifest.artifacts] == [
        ("metrics", "results/metrics.json")
    ]
    (evidence,) = manifest.claims[0].evidence
    assert isinstance(evidence, MetricEvidence)
    assert (evidence.pointer, evidence.reported) == ("/scores/accuracy", "0.9312")

    report = verify(manifest)
    assert [d.outcome for d in report.decisions] == [Outcome.VERIFIED]
    assert all(a.validity is Validity.AUTHORITATIVE for a in report.artifacts)
    assert PUBLICATION.assess(report).passed is True
    assert run_repro("verify", cwd=project)[0] == 0


def test_editing_a_pinned_file_afterwards_breaks_its_pin(project, run_repro):
    assert run_repro("manifest", "init", cwd=project)[0] == 0
    (project / "results" / "metrics.json").write_text(
        json.dumps({"model": "lasso", "scores": {"accuracy": 0.9312, "n": 481}})
    )

    report = verify(load(project / DEFAULT_NAME))
    assert [a.validity for a in report.artifacts] == [Validity.BROKEN_PIN]
    assert rules(PUBLICATION.assess(report)) == ["artifact.pin"]
    assert run_repro("verify", cwd=project)[0] == 1


def test_an_existing_manifest_is_refused_and_its_bytes_are_unchanged(project, run_repro):
    existing = b"schema_version: repro/1\nproject: mine\n# a comment I wrote\n"
    (project / DEFAULT_NAME).write_bytes(existing)

    code, out = run_repro("manifest", "init", cwd=project)
    assert code != 0
    assert "exists" in out and "nothing was written" in out
    assert (project / DEFAULT_NAME).read_bytes() == existing


def test_with_nothing_to_point_at_the_examples_are_comments_and_no_claim_is_declared(
    tmp_path, run_repro
):
    (tmp_path / "results").mkdir()
    (tmp_path / "results" / "labels.json").write_text(json.dumps({"model": "lasso"}))

    code, out = run_repro("manifest", "init", cwd=tmp_path)
    assert code == 0, out
    assert "report.empty" in out

    manifest = load(tmp_path / DEFAULT_NAME)
    assert manifest.claims == ()
    report = verify(manifest)
    assert [a.validity for a in report.artifacts] == [Validity.AUTHORITATIVE]
    assert report.decisions == ()
    # A manifest that checks nothing is not a pass, and that is the only thing wrong with it.
    assert rules(PUBLICATION.assess(report)) == ["report.empty"]


def test_the_commented_examples_are_claims_the_loader_accepts_once_uncommented(tmp_path, run_repro):
    assert run_repro("manifest", "init", cwd=tmp_path)[0] == 0
    path = tmp_path / DEFAULT_NAME
    document, _, examples = path.read_text().partition("# claims:\n")
    assert examples
    uncommented = "\n".join(line[2:] for line in examples.splitlines())
    path.write_text(f"{document}claims:\n{uncommented}\n")

    kinds = [type(e) for claim in load(path).claims for e in claim.evidence]
    assert kinds == [MetricEvidence, QuoteEvidence]


@pytest.mark.parametrize("named", ["missing.json", "../outside.json", "results"])
def test_a_named_file_that_cannot_be_pinned_is_refused_and_nothing_is_written(
    project, named, run_repro
):
    (project.parent / "outside.json").write_text(json.dumps({"n": 1}))

    code, out = run_repro("manifest", "init", "results/metrics.json", named, cwd=project)
    assert code != 0
    assert "nothing was written" in out
    assert (project / named).resolve().name in out
    assert not (project / DEFAULT_NAME).exists()


def test_named_files_are_pinned_whatever_their_format_and_only_those(project, run_repro):
    (project / "analysis.py").write_text("print(1)\n")
    (project / "notes.md").write_text(
        "The same line of prose, long enough to be quoted, appears twice.\n"
        "The same line of prose, long enough to be quoted, appears twice.\n"
        "This line of prose, also long enough to quote, appears only once.\n"
    )

    code, out = run_repro("manifest", "init", "analysis.py", "notes.md", cwd=project)
    assert code == 0, out

    manifest = load(project / DEFAULT_NAME)
    assert [(a.id, a.media_type) for a in manifest.artifacts] == [
        ("analysis", "text/x-python"),
        ("notes", "text/markdown"),
    ]
    # The repeated line is ambiguous in its source, so the example is the line that resolves.
    (claim,) = manifest.claims
    (evidence,) = claim.evidence
    assert isinstance(evidence, QuoteEvidence)
    assert evidence.text == "This line of prose, also long enough to quote, appears only once."
    assert PUBLICATION.assess(verify(manifest)).passed is True


def test_run_below_the_top_of_a_repository_it_writes_at_the_git_root(project, run_repro):
    # Run under a git hook, `GIT_DIR` names the repository the hook belongs to, and `git init`
    # would act on that one and leave this directory outside any repository.
    plain = {name: value for name, value in os.environ.items() if not name.startswith("GIT_")}
    subprocess.run(
        ["git", "init", "-q", "."], cwd=project, check=True, capture_output=True, env=plain
    )

    code, out = run_repro("manifest", "init", "metrics.json", cwd=project / "results")
    assert code == 0, out
    assert not (project / "results" / DEFAULT_NAME).exists()

    manifest = load(project / DEFAULT_NAME)
    assert [a.path.as_posix() for a in manifest.artifacts] == ["results/metrics.json"]
    assert PUBLICATION.assess(verify(manifest)).passed is True


def test_discovery_takes_the_shallowest_results_and_says_when_it_stops_at_the_cap(
    tmp_path, run_repro
):
    results = tmp_path / "results"
    (results / "per_seed").mkdir(parents=True)
    (results / "per_seed" / "deep.json").write_text(json.dumps({"n": 1}))
    for index in range(MAX_DISCOVERED + 5):
        (results / f"run_{index:02d}.json").write_text(json.dumps({"n": index}))
    for ignored in ("node_modules", ".cache"):
        (tmp_path / "data" / ignored).mkdir(parents=True)
        (tmp_path / "data" / ignored / "package.json").write_text(json.dumps({"n": 1}))
    (tmp_path / "config.json").write_text(json.dumps({"n": 1}))

    code, out = run_repro("manifest", "init", cwd=tmp_path)
    assert code == 0, out
    assert f"more than {MAX_DISCOVERED} files were found" in out

    paths = [a.path.as_posix() for a in load(tmp_path / DEFAULT_NAME).artifacts]
    assert paths == [f"results/run_{index:02d}.json" for index in range(MAX_DISCOVERED)]


def test_one_manuscript_is_pinned_and_two_candidates_are_left_for_the_author(tmp_path, run_repro):
    (tmp_path / "paper.md").write_text("We measured twelve subjects before and after the change.\n")
    assert run_repro("manifest", "init", cwd=tmp_path)[0] == 0
    manifest = load(tmp_path / DEFAULT_NAME)
    assert [a.id for a in manifest.artifacts] == ["paper"]
    assert PUBLICATION.assess(verify(manifest)).passed is True

    (tmp_path / DEFAULT_NAME).unlink()
    (tmp_path / "main.tex").write_text("\\documentclass{article}\n")
    code, out = run_repro("manifest", "init", cwd=tmp_path)
    assert code == 0, out
    assert "main.tex" in out and "none was pinned" in out
    assert load(tmp_path / DEFAULT_NAME).artifacts == ()
