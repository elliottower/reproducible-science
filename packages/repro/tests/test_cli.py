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


def test_version_reports_the_installed_package_version():
    import repro

    r = run_repro("--version")
    assert repro.__version__ in r.stdout + r.stderr


def test_no_args_prints_help():
    r = run_repro()
    assert r.returncode == 1
    assert "usage" in r.stdout.lower() or "usage" in r.stderr.lower()


def test_init_creates_directory(tmp_path):
    result = run_repro("init", "my_exp", "--directory", str(tmp_path / "my_exp"))
    assert result.returncode == 0, result.stderr
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


def test_the_docstring_names_exactly_the_commands_the_parser_offers(capsys):
    """`repro bib` was documented for months and was never a command, while `pin` and
    `projects` were commands nobody had written down. The docstring is the first thing a
    reader of this module sees, and nothing compared it to the parser."""
    import re

    from repro import cli

    with pytest.raises(SystemExit):
        cli.main(["--help"])
    offered = set(re.search(r"\{([a-z0-9,\-]+)\}", capsys.readouterr().out).group(1).split(","))

    documented = set()
    for line in (cli.__doc__ or "").splitlines():
        m = re.match(r"\s*repro\s+([a-z][a-z0-9-]*)(?=\s)", line)
        if m and "  " in line[m.end() :]:  # the description column, not prose
            documented.add(m.group(1))

    assert documented == offered, (
        f"documented but absent: {sorted(documented - offered)}; "
        f"present but undocumented: {sorted(offered - documented)}"
    )
