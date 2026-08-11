"""The command must never report success on a run that examined nothing."""
from __future__ import annotations

import pathlib
import subprocess
import sys

import pytest
import yaml


def run(args, cwd, env_home=None):
    env = {"PATH": "/usr/bin:/bin:/usr/local/bin", "HOME": str(cwd)}
    if env_home:
        env["CITATIONS_HOME"] = str(env_home)
    return subprocess.run([sys.executable, "-m", "citations.cli", *args],
                          cwd=cwd, capture_output=True, text=True, env=env)


@pytest.fixture
def library(tmp_path):
    (tmp_path / "records").mkdir()
    return tmp_path


def test_zero_quotations_does_not_exit_zero(library):
    r = run(["verify"], library, library)
    assert r.returncode != 0, "a run that checked nothing must not look like a pass"
    assert "nothing to check" in r.stdout
    assert "claims" in r.stdout


def test_zero_quotations_says_why_and_what_to_do(library):
    r = run(["verify"], library, library)
    assert "--claims" in r.stdout, "must tell the user where quotations actually live"


def test_missing_library_is_an_error_not_an_empty_pass(tmp_path):
    r = run(["verify"], tmp_path, tmp_path / "nowhere")
    assert r.returncode != 0


def test_a_claims_directory_with_no_quotes_still_refuses(tmp_path):
    claims = tmp_path / "claims"
    claims.mkdir()
    (claims / "empty.yaml").write_text(yaml.safe_dump(
        {"claim": "empty", "source": {"citation": "x"}, "evidence": {}}))
    r = run(["verify", "--claims", str(claims)], tmp_path, tmp_path)
    assert r.returncode != 0
    assert "nothing to check" in r.stdout


def test_help_lists_every_subcommand(tmp_path):
    r = run([], tmp_path)
    for c in ("verify", "resolve", "build", "lint", "link"):
        assert c in r.stdout
