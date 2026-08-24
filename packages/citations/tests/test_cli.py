"""The command must never report success on a run that examined nothing."""
from __future__ import annotations

import pathlib
import subprocess
import sys

import pytest
import yaml

from citations import cli as C
from citations.models import load_claim_file


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


def test_claims_block_is_read_under_either_name(tmp_path):
    # One repo writes `evidence:`, another writes `claims:`. Reading one spelling made the
    # command find zero quotes and say so, which reads identically to a paper with none.
    src = tmp_path / "s.txt"
    src.write_text("the measured angle matches the Haar expectation")
    for name, block in (("a.yaml", "evidence"), ("b.yaml", "claims")):
        (tmp_path / name).write_text(
            f"source:\n  citation: x\n  local: {src}\n{block}:\n  c1:\n    quotes:\n"
            f"      - exact: 'matches the Haar expectation'\n")
    files = [load_claim_file(tmp_path / n) for n in ("a.yaml", "b.yaml")]
    assert [len(f.claims) for f in files] == [1, 1]
    assert {f.name for f in files} == {"a", "b"}
    assert all(f.claims["c1"].quotes[0].text == "matches the Haar expectation" for f in files)


# --- which library did that clean run actually check? ------------------------------------------

def test_origin_reports_the_rule_that_found_the_library(tmp_path, monkeypatch):
    # the walk-up only applies when the env var is not set, and it is set on the machine this
    # library was written on -- without clearing it the test asserts the wrong rule
    monkeypatch.delenv("CITATIONS_HOME", raising=False)
    from citations import paths
    proj = tmp_path / "paper"
    (proj / ".citations" / "records").mkdir(parents=True)
    deep = proj / "sections" / "intro"
    deep.mkdir(parents=True)
    p, origin = paths.find_with_origin(deep)
    assert origin == "project"
    assert p == (proj / ".citations").resolve() or p == proj / ".citations"


def test_env_overrides_the_walk_up(tmp_path, monkeypatch):
    from citations import paths
    proj = tmp_path / "paper"
    (proj / ".citations" / "records").mkdir(parents=True)
    other = tmp_path / "elsewhere"
    other.mkdir()
    monkeypatch.setenv("CITATIONS_HOME", str(other))
    _, origin = paths.find_with_origin(proj)
    assert origin == "CITATIONS_HOME", "an env override that is silently ignored is the worst case"


def test_find_still_returns_just_the_path(tmp_path):
    from citations import paths
    proj = tmp_path / "paper"
    (proj / ".citations" / "records").mkdir(parents=True)
    assert paths.find(proj) == paths.find_with_origin(proj)[0]


def test_verify_names_the_library_it_checked(library):
    (library / "records" / "r.yaml").write_text(yaml.safe_dump(
        {"slug": "r", "quotes": [{"text": "anything at all", "page": None}]}))
    r = run(["verify"], library, library)
    assert str(library) in r.stdout, \
        "a clean run against the wrong library reads exactly like a clean run against the right one"
