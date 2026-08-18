from __future__ import annotations

import subprocess
import sys

import pytest


def run_repro(*args: str, cwd=None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "repro", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
    )


def test_version():
    r = run_repro("--version")
    assert "0.1.0" in r.stdout + r.stderr


def test_no_args_prints_help():
    r = run_repro()
    assert r.returncode == 1
    assert "usage" in r.stdout.lower() or "usage" in r.stderr.lower()


def test_init_creates_directory(tmp_path):
    r = run_repro("init", "my_exp", "--directory", str(tmp_path / "my_exp"))
    assert (tmp_path / "my_exp").is_dir()
    assert (tmp_path / "my_exp" / "CLAUDE.md").exists()
    assert (tmp_path / "my_exp" / "claims").is_dir()
    assert (tmp_path / "my_exp" / "data").is_dir()
    assert (tmp_path / "my_exp" / "scripts").is_dir()
    assert (tmp_path / "my_exp" / "figures").is_dir()


def test_init_claude_md_contains_name(tmp_path):
    run_repro("init", "test_experiment", "--directory", str(tmp_path / "test_experiment"))
    content = (tmp_path / "test_experiment" / "CLAUDE.md").read_text()
    assert "test_experiment" in content
    assert "prereg" in content
    assert "results" in content
    assert "citations" in content


def test_init_does_not_overwrite_existing_claude_md(tmp_path):
    target = tmp_path / "existing"
    target.mkdir()
    (target / "CLAUDE.md").write_text("existing content")
    run_repro("init", "existing", "--directory", str(target))
    assert (target / "CLAUDE.md").read_text() == "existing content"
