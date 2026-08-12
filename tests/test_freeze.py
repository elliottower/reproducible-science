"""A freeze is only worth anything if editing the plan afterwards is detectable."""
from __future__ import annotations

import subprocess
import sys

import pytest

from prereg import cli


def run(args, cwd):
    return subprocess.run([sys.executable, "-m", "prereg.cli", *args],
                          cwd=cwd, capture_output=True, text=True)


@pytest.fixture
def repo(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path)
    run(["new", "study"], tmp_path)
    subprocess.run(["git", "add", "-A"], cwd=tmp_path)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-q", "-m", "init"], cwd=tmp_path)
    return tmp_path / "study"


def test_new_uses_the_osf_headings(tmp_path):
    run(["new", "study"], tmp_path)
    text = (tmp_path / "study" / "PREREG.md").read_text()
    for q, _ in cli.template.QUESTIONS:
        assert f"## {q}" in text


def test_the_two_headings_that_do_the_work_are_present(tmp_path):
    run(["new", "study"], tmp_path)
    text = (tmp_path / "study" / "PREREG.md").read_text()
    assert "## Foreknowledge of data or evidence" in text
    assert "## Inference criteria" in text


def test_check_passes_immediately_after_freeze(repo):
    run(["freeze"], repo)
    assert run(["check"], repo).returncode == 0


def test_editing_the_plan_is_detected(repo):
    run(["freeze"], repo)
    p = repo / "PREREG.md"
    p.write_text(p.read_text().replace("## Randomization", "## Randomisation"))
    r = run(["check"], repo)
    assert r.returncode == 1
    assert "CHANGED" in r.stdout


def test_appending_to_the_log_is_not_a_change(repo):
    run(["freeze"], repo)
    run(["log", "tolerance from fixtures", "--access", "no results seen"], repo)
    assert run(["check"], repo).returncode == 0, "appending below the line is the allowed edit"


def test_freezing_twice_is_refused(repo):
    run(["freeze"], repo)
    assert run(["freeze"], repo).returncode == 1


def test_freeze_refuses_uncommitted_changes(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path)
    run(["new", "study"], tmp_path)
    r = run(["freeze"], tmp_path / "study")
    assert r.returncode == 1
    assert "Commit first" in r.stdout


def test_an_unknown_access_value_is_refused(repo):
    run(["freeze"], repo)
    r = run(["log", "something", "--access", "probably fine"], repo)
    assert r.returncode == 1


def test_results_seen_is_called_a_deviation(repo):
    run(["freeze"], repo)
    r = run(["log", "criterion failed", "--access", "results seen"], repo)
    assert "deviation" in r.stdout


def test_check_on_an_unfrozen_plan_does_not_report_success(tmp_path):
    run(["new", "study"], tmp_path)
    assert run(["check"], tmp_path / "study").returncode != 0


def test_commands_find_the_plan_from_a_subdirectory(repo):
    run(["freeze"], repo)
    (repo / "results").mkdir(exist_ok=True)
    assert run(["check"], repo / "results").returncode == 0


def test_force_refreeze_rewrites_the_header_it_prints(repo):
    run(["freeze"], repo)
    p = repo / "PREREG.md"
    p.write_text(p.read_text().replace("## Randomization", "## Randomization\n\nBy seed."))
    subprocess.run(["git", "add", "-A"], cwd=repo)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-q", "-m", "edit"], cwd=repo)
    r = run(["freeze", "--force"], repo)
    printed = [w for w in r.stdout.split() if len(w.rstrip("…")) == 16][-1].rstrip("…")
    assert printed in p.read_text(), "freeze printed a digest it did not write"
    assert run(["check"], repo).returncode == 0


def test_status_note_survives_the_freeze_intact(repo):
    p = repo / "PREREG.md"
    p.write_text(p.read_text().replace(
        "**Status:** DRAFT — not frozen.",
        "**Status:** DRAFT — not frozen. Third version; see Log."))
    subprocess.run(["git", "add", "-A"], cwd=repo)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-q", "-m", "note"], cwd=repo)
    run(["freeze"], repo)
    text = p.read_text()
    frozen_line = next(ln for ln in text.splitlines() if ln.startswith("**Frozen:**"))
    assert frozen_line.strip().endswith(cli.today()), \
        f"note was glued onto the freeze date: {frozen_line!r}"
    assert "Third version; see Log." in text
    assert run(["check"], repo).returncode == 0


def test_refreezing_an_unedited_plan_is_idempotent(repo):
    run(["freeze"], repo)
    first = (repo / "PREREG.md").read_text()
    digest = cli.re.search(r"`([0-9a-f]{64})`", first).group(1)
    run(["freeze", "--force"], repo)
    second = (repo / "PREREG.md").read_text()
    assert cli.re.search(r"`([0-9a-f]{64})`", second).group(1) == digest
    assert run(["check"], repo).returncode == 0
