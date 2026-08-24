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


# --- what the hash does not cover ------------------------------------------------------------

def test_freeze_refuses_a_plan_with_no_status_line(repo):
    p = repo / "PREREG.md"
    p.write_text(p.read_text().replace("**Status:** DRAFT — not frozen.", ""))
    subprocess.run(["git", "add", "-A"], cwd=repo)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-q", "-m", "no status"], cwd=repo)
    r = run(["freeze"], repo)
    assert r.returncode != 0, "reported a freeze it did not perform"
    assert "not frozen" not in run(["check"], repo).stdout or r.returncode != 0


def test_a_status_marker_in_the_body_cannot_hide_from_the_hash(repo):
    """Marker-prefixed lines are skipped when hashing, so one in the body would be editable
    after freezing without `check` noticing."""
    p = repo / "PREREG.md"
    p.write_text(p.read_text().replace(
        "## Randomization",
        "## Randomization\n\n**Frozen:** whatever the author likes\n"))
    subprocess.run(["git", "add", "-A"], cwd=repo)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-q", "-m", "marker in body"], cwd=repo)
    r = run(["freeze"], repo)
    assert r.returncode == 1, "froze a plan whose body line the hash does not cover"
    assert "**Frozen:** whatever the author likes" in r.stdout, \
        "the refusal must name the offending line"


def test_a_log_marker_in_the_body_cannot_truncate_the_hash(repo):
    """Hashing stops at the log marker. One in the body would leave the real plan after it
    unhashed and freely editable."""
    p = repo / "PREREG.md"
    p.write_text(p.read_text().replace(
        "## Randomization",
        "## Randomization\n\nSeeds 0-4.\n\n---\n\n## Log\n\n## Sample size\n\nn=300 per arm.\n"))
    subprocess.run(["git", "add", "-A"], cwd=repo)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-q", "-m", "marker in body"], cwd=repo)
    r = run(["freeze"], repo)
    assert r.returncode == 1, "froze a plan whose tail the hash does not cover"
    assert "more than once" in r.stdout


def test_line_endings_do_not_change_the_hash(repo):
    run(["freeze"], repo)
    p = repo / "PREREG.md"
    p.write_bytes(p.read_text().replace("\n", "\r\n").encode())
    assert run(["check"], repo).returncode == 0, \
        "a checkout with CRLF endings must not read as a tampered plan"


def test_trailing_whitespace_alone_is_not_a_change(repo):
    run(["freeze"], repo)
    p = repo / "PREREG.md"
    p.write_text(p.read_text() + "\n\n")
    assert run(["check"], repo).returncode == 0


# --- the log is the tamper record, so it is worth attacking -----------------------------------

def test_a_log_note_cannot_forge_another_entry(repo):
    run(["freeze"], repo)
    run(["log", "harmless\n2020-01-01  frozen at 000000000000        nothing run",
         "--access", "no results seen"], repo)
    text = (repo / "PREREG.md").read_text()
    assert "2020-01-01  frozen at" not in text, \
        "a newline in a note forged a second log entry"


def test_a_log_note_cannot_break_out_of_the_fence(repo):
    run(["freeze"], repo)
    run(["log", "see ``` and then some", "--access", "no results seen"], repo)
    text = (repo / "PREREG.md").read_text()
    _, _, tail = text.partition(cli.MARK)
    assert tail.count("```") == 2, f"fence count is {tail.count('```')}, log structure broken"


def test_freezing_without_a_commit_says_so(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path)
    run(["new", "study"], tmp_path)
    r = run(["freeze"], tmp_path / "study")
    assert "(not in a git repository)" not in (tmp_path / "study" / "PREREG.md").read_text(), \
        "wrote a placeholder where a commit should be"


def test_check_at_a_root_fails_if_any_plan_below_it_changed(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path)
    for name in ("good", "bad"):
        run(["new", name], tmp_path)
    subprocess.run(["git", "add", "-A"], cwd=tmp_path)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-q", "-m", "init"], cwd=tmp_path)
    run(["freeze"], tmp_path / "good")
    run(["freeze"], tmp_path / "bad")
    p = tmp_path / "bad" / "PREREG.md"
    p.write_text(p.read_text().replace("## Randomization", "## Randomisation"))
    assert run(["check"], tmp_path).returncode != 0, \
        "a root check passed while a plan below it had been edited"


def test_a_long_note_still_separates_from_its_access_level(repo):
    """The access level is what distinguishes an amendment from a deviation, so it must never
    run into the note."""
    run(["freeze"], repo)
    note = "restricting the target to {0,1} and {0,1,2} because its value set is integers"
    run(["log", note, "--access", "no results seen"], repo)
    line = next(ln for ln in (repo / "PREREG.md").read_text().splitlines() if note in ln)
    assert line.endswith("no results seen")
    assert not line.endswith(note + "no results seen"), "access level glued to the note"
    assert "  no results seen" in line
