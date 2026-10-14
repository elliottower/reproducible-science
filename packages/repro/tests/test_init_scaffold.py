from __future__ import annotations

import json
import os
import pathlib
import subprocess

import pytest
from repro.cli import main
from repro.manifest import DEFAULT_NAME
from repro.open_items import DRAFT_NAME, ITEMS_NAME, read

ROOT = pathlib.Path(__file__).resolve().parents[3]
DOCS = ROOT / "site" / "src" / "content" / "docs" / "tools" / "repro.md"

SCAFFOLDED = """\
  scaffolded, nothing verified: 5 numbers left open, 1 with one candidate
    repro.draft.yaml   2 result files and paper.md pinned, a claim per number, no assertion
    open-items.json    an item per number, with the places the result files hold it
"""
ROW = (
    "  manifest     created          repro.draft.yaml, open-items.json "
    "(a draft; no repro.yaml written)\n"
)
NEXT = """\
  manifest     fill open-items.json with an agent (the open-items skill, or the tools
               of `repro mcp`), review repro.draft.yaml, and rename it to repro.yaml
"""


@pytest.fixture
def run_repro(monkeypatch, capsys, tmp_path):
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
    """The project the README shows for `repro verify` with no manifest."""
    root = tmp_path / "my_experiment"
    (root / "results").mkdir(parents=True)
    (root / "results" / "metrics.json").write_text(
        json.dumps({"model": "lasso", "scores": {"accuracy": 0.9312, "n": 480, "rate": 0.0426}})
    )
    (root / "results" / "table.csv").write_text("model,auc\nlasso,0.71\n")
    (root / "paper.md").write_text(
        "# Results\n\n"
        "In 2024 we fit the lasso to 480 participants.\n"
        "Held-out accuracy was 0.931, and the error rate was 4.3% (Table 2).\n"
        "We ran 3 seeds; the AUC was 0.71, not 0.55.\n"
    )
    plain = {name: value for name, value in os.environ.items() if not name.startswith("GIT_")}
    subprocess.run(["git", "init", "-q", "."], cwd=root, check=True, capture_output=True, env=plain)
    return root


def test_init_scaffolds_the_claims_and_says_nothing_is_verified(project, run_repro):
    code, out = run_repro("init", cwd=project)
    assert code == 0, out
    assert ROW in out and SCAFFOLDED in out and NEXT in out
    assert "edit the claims in repro.yaml" not in out
    # One manifest to rename: no starter is written beside the draft.
    assert not (project / DEFAULT_NAME).exists()
    items = read(project / ITEMS_NAME)
    assert items.manifest == DRAFT_NAME
    assert items.source.reader == "repro init"
    assert [item.unique for item in items.items] == [False, True, False, False, False]
    # The block and the next step, as the documentation shows them.
    docs = DOCS.read_text()
    assert ROW in docs and SCAFFOLDED in docs and NEXT in docs


def test_the_fresh_draft_fails_strict(project, run_repro):
    assert run_repro("init", cwd=project)[0] == 0
    code, out = run_repro("verify", DRAFT_NAME, "--policy", "strict", cwd=project)
    assert code == 1
    assert "policy strict: FAILED" in out
    assert "claim offers no evidence" in out


def test_an_existing_manifest_is_left_alone_and_nothing_is_scaffolded(project, run_repro):
    (project / DEFAULT_NAME).write_text("# mine\nschema_version: repro/1\nproject: mine\n")
    before = (project / DEFAULT_NAME).read_bytes()

    code, out = run_repro("init", cwd=project)
    assert code == 0, out
    assert (project / DEFAULT_NAME).read_bytes() == before
    assert "repro.yaml exists and was left alone, so nothing was scaffolded" in out
    assert not (project / DRAFT_NAME).exists()
    assert not (project / ITEMS_NAME).exists()


def test_a_draft_is_never_overwritten_without_force(project, run_repro):
    assert run_repro("init", cwd=project)[0] == 0
    (project / DRAFT_NAME).write_text("edited by hand\n")
    items = (project / ITEMS_NAME).read_bytes()

    code, out = run_repro("init", cwd=project)
    assert code == 0, out
    assert (project / DRAFT_NAME).read_text() == "edited by hand\n"
    assert (project / ITEMS_NAME).read_bytes() == items
    assert "neither was replaced; --force replaces both" in out
    assert "scaffolded, nothing verified" not in out
    assert "already present  repro.draft.yaml (a draft" in out
    assert not (project / DEFAULT_NAME).exists()

    code, out = run_repro("init", "--force", cwd=project)
    assert code == 0, out
    assert SCAFFOLDED in out
    assert (project / DRAFT_NAME).read_text().startswith("schema_version:")
    assert not (project / DEFAULT_NAME).exists()


def test_with_nothing_to_scaffold_the_starter_is_written(project, run_repro):
    (project / "paper.md").unlink()
    code, out = run_repro("init", cwd=project)
    assert code == 0, out
    assert "claims: no manuscript found, so nothing was scaffolded" in out
    assert "created          repro.yaml (artifacts pinned: 2" in out
    assert (project / DEFAULT_NAME).is_file()
    assert not (project / DRAFT_NAME).exists()


def test_no_scaffold_writes_neither_file(project, run_repro):
    code, out = run_repro("init", "--no-scaffold", cwd=project)
    assert code == 0, out
    assert not (project / DRAFT_NAME).exists()
    assert not (project / ITEMS_NAME).exists()
    assert "scaffolded" not in out and "  claims: " not in out and DRAFT_NAME not in out
    assert (project / DEFAULT_NAME).is_file()


def test_manifest_init_writes_no_draft(project, run_repro):
    code, out = run_repro("manifest", "init", cwd=project)
    assert code == 0, out
    assert (project / DEFAULT_NAME).is_file()
    assert not (project / DRAFT_NAME).exists()
    assert not (project / ITEMS_NAME).exists()
