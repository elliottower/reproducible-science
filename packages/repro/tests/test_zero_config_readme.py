from __future__ import annotations

import json
import pathlib
import subprocess

from repro.cli import main

ROOT = pathlib.Path(__file__).resolve().parents[3]
READMES = (
    ROOT / "packages" / "repro" / "README.md",
    ROOT / "site" / "src" / "content" / "docs" / "tools" / "repro.md",
)


def test_the_readme_shows_what_verify_prints_for_the_project_it_describes(
    tmp_path, monkeypatch, capsys
):
    for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
        monkeypatch.delenv(name, raising=False)
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
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    monkeypatch.chdir(root)
    assert main(["verify"]) == 2
    printed = capsys.readouterr().out
    for readme in READMES:
        text = readme.read_text()
        assert f"```text\n{printed}```" in text, readme
        assert (
            '{"model": "lasso", "scores": {"accuracy": 0.9312, "n": 480, "rate": 0.0426}}' in text
        )
