"""A plan frozen in place, with its freeze record and its log inside the file, keeps the rules it
was frozen under: nothing converts it, and every command reads it as the version that froze it did.

The plan is the captured one in `data/frozen_in_place.md`: frozen, then logged to twice.
"""

from __future__ import annotations

import subprocess
import sys

import pytest
from prereg import log
from provenance_core.gitref import clean_env

DIGEST = "35abc8ae2767bee40600e37a5032b1536a8799fea672bdc323f6c317176dd966"


def git(repo, *args) -> str:
    done = subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
        cwd=repo,
        env=clean_env(),
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout.strip()


def commit(repo, message="commit") -> None:
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)


def run(args, cwd):
    return subprocess.run(
        [sys.executable, "-m", "prereg.cli", *args],
        cwd=cwd,
        env=clean_env(),
        capture_output=True,
        text=True,
    )


@pytest.fixture
def study(tmp_path, frozen_in_place):
    git(tmp_path, "init", "-q")
    (tmp_path / "study").mkdir()
    (tmp_path / "study" / "PREREG.md").write_bytes(frozen_in_place)
    commit(tmp_path, "a plan frozen in place")
    return tmp_path / "study"


def test_check_reports_it_exactly_as_before(study):
    r = run(["check"], study)
    assert r.returncode == 0
    assert r.stdout == (
        f"unchanged    {study / 'PREREG.md'}\n  timestamp  none. `prereg timestamp` makes one.\n"
    )


def test_an_edit_above_the_line_is_changed_with_the_message_it_always_had(study):
    plan = study / "PREREG.md"
    plan.write_text(plan.read_text().replace("## Randomization", "## Randomisation"))
    r = run(["check"], study)
    assert r.returncode == 1
    assert r.stdout.startswith(f"CHANGED      {plan}\n  frozen  {DIGEST[:16]}…\n")
    assert "the plan was edited after freezing: restore it and record the change in the log" in (
        r.stdout
    )


def test_trailing_whitespace_stays_exempt_for_it_alone(study):
    plan = study / "PREREG.md"
    plan.write_text(plan.read_text() + "\n\n")
    assert run(["check"], study).returncode == 0


def test_log_appends_in_the_file_and_says_where_new_logs_are_kept(study, frozen_in_place):
    plan = study / "PREREG.md"
    before = log.log_lines(frozen_in_place.decode())

    r = run(["log", "C5 failed at k=15", "--access", "results seen"], study)

    assert r.returncode == 0
    assert "logged: C5 failed at k=15  (results seen)" in r.stdout
    assert "keep their log beside them, in PREREG.log" in r.stdout
    assert "deviation" in r.stdout
    after = log.log_lines(plan.read_text())
    assert after[:-1] == before
    entry, _, value = after[-1].rpartition(log.LOG_MARK)
    assert "C5 failed at k=15" in entry and entry.rstrip().endswith("results seen")
    assert value == log.chain_value(before[-1].rpartition(log.LOG_MARK)[2], entry)
    assert f"**Log:** {len(after)} entries, head `{value}`" in plan.read_text()
    assert f"**Plan sha256:** `{DIGEST}`" in plan.read_text()
    assert not (study / "PREREG.log").exists()
    assert not (study / ".prereg").exists()
    assert run(["check"], study).returncode == 0


def test_a_removed_log_entry_is_reported_as_before(study):
    plan = study / "PREREG.md"
    kept = [ln for ln in plan.read_text().splitlines() if "ran the primary model" not in ln]
    plan.write_text("\n".join(kept) + "\n")
    r = run(["check"], study)
    assert r.returncode == 1
    assert r.stdout.startswith(f"LOG ALTERED  {plan}\n")
    assert "the log records 4 entries and holds 3" in r.stdout


def test_a_freeze_without_force_is_refused_as_before(study):
    before = (study / "PREREG.md").read_bytes()
    r = run(["freeze"], study)
    assert r.returncode == 1
    assert "is already frozen. Use `prereg log` to append, or --force." in r.stdout
    assert (study / "PREREG.md").read_bytes() == before


def test_a_forced_refreeze_stays_in_the_file(study):
    plan = study / "PREREG.md"
    plan.write_text(plan.read_text().replace("## Randomization", "## Randomization\n\nBy seed."))
    commit(study, "edit")

    r = run(["freeze", "--force", "--access", "no results seen"], study)

    assert r.returncode == 0
    assert "(of everything above the log)" in r.stdout
    assert DIGEST not in plan.read_text()
    assert "**Status:** FROZEN at `" + git(study, "rev-parse", "HEAD")[:12] in plan.read_text()
    assert not (study / ".prereg").exists()
    assert plan.stat().st_mode & 0o200, "a plan frozen in place is still written to by its log"
    assert run(["check"], study).returncode == 0


def test_the_index_may_hold_a_log_entry_and_not_an_edit_above_the_line(study):
    plan = study / "PREREG.md"
    assert run(["log", "ran", "--access", "results not opened"], study).returncode == 0
    git(study, "add", "-A")
    assert run(["check", "--staged"], study).returncode == 0

    plan.write_text(plan.read_text().replace("## Randomization", "## Randomization\n\nBy seed."))
    git(study, "add", "-A")
    r = run(["check", "--staged"], study)
    assert r.returncode == 1
    assert "STAGED       study/PREREG.md  frozen above its log line" in r.stdout


def test_an_amendment_to_it_names_the_digest_in_the_file_and_is_frozen_whole(
    study, frozen_in_place
):
    assert run(["amend"], study).returncode == 0
    path = study / "PREREG_AMENDMENT_1.md"
    text = path.read_text()
    assert f"**Amends:** `{DIGEST}` (PREREG.md)" in text
    path.write_text(
        text.replace("_Name each section", "Adds `Sample size`. _")
        .replace("_Why the plan changes._", "A second cohort.")
        .replace("**Access level:**", "**Access level:** results not opened")
    )
    commit(study, "amendment")
    assert run(["freeze", path.name], study).returncode == 0

    r = run(["check"], study)
    assert r.returncode == 0
    lines = r.stdout.splitlines()
    assert lines[:2] == [
        f"unchanged    {study / 'PREREG.md'}",
        "  timestamp  none. `prereg timestamp` makes one.",
    ]
    assert lines[2].startswith(f"unchanged    {path}  frozen ")
    assert lines[2].endswith("  results not opened")
    assert lines[3:] == [
        "  amends     PREREG.md",
        "  timestamp  owed. `prereg timestamp` completes it.",
    ]
    assert (study / "PREREG.md").read_bytes() == frozen_in_place


def test_each_format_in_one_project_is_checked_under_its_own_rule(study):
    top = study.parent
    assert run(["new", "later"], top).returncode == 0
    document = top / "PREREGISTRATION.md"
    document.write_text("# Does the rule hold?\n\n**Commit SHA:** _pending_\n\n**H1.** It does.\n")
    commit(top, "a new plan and a registration by commit line")
    sha = git(top, "rev-parse", "HEAD")
    document.write_text(document.read_text().replace("_pending_", sha[:7]))
    commit(top, "record the commit")
    assert run(["freeze"], top / "later").returncode == 0

    r = run(["check"], top)

    assert r.returncode == 0
    lines = r.stdout.splitlines()
    whole = next(i for i, ln in enumerate(lines) if "later/PREREG.md" in ln)
    assert lines[whole].startswith("unchanged") and lines[whole].endswith("  nothing run")
    assert "  frozen 20" in lines[whole]
    assert lines[whole + 1] == "  timestamp  owed. `prereg timestamp` completes it."
    in_place = lines.index(f"unchanged    {study / 'PREREG.md'}")
    assert lines[in_place + 1] == "  timestamp  none. `prereg timestamp` makes one."
    assert "2 plans: 2 unchanged, 0 changed, 0 not frozen" in lines
    assert f"unchanged    PREREGISTRATION.md  at {sha[:7]}" in lines

    for plan in (study / "PREREG.md", top / "later" / "PREREG.md"):
        plan.chmod(0o644)
        plan.write_text(plan.read_text() + "\n")
    document.write_text(document.read_text() + "\nA note added after the freeze.\n")
    r = run(["check"], top)
    assert r.returncode == 1
    lines = r.stdout.splitlines()
    assert f"unchanged    {study / 'PREREG.md'}" in lines, (
        "frozen in place, a trailing line is exempt"
    )
    assert any(ln.startswith(f"CHANGED      {top / 'later' / 'PREREG.md'}") for ln in lines)
    assert f"appended     PREREGISTRATION.md  at {sha[:7]}" in lines
    assert "2 plans: 1 unchanged, 1 changed, 0 not frozen" in lines

    git(top, "add", "-A")
    staged = run(["check", "--staged"], top)
    assert staged.returncode == 1
    assert [ln for ln in staged.stdout.splitlines() if ln.startswith("STAGED")] == [
        "STAGED       later/PREREG.md  frozen whole"
    ]


def test_the_index_may_not_hold_an_edit_to_a_document_frozen_by_a_commit_line(tmp_path):
    git(tmp_path, "init", "-q")
    document = tmp_path / "PREREGISTRATION.md"
    document.write_text(
        "# Does the rule hold?\n\n**Commit SHA:** _pending_\n\n**H1.** Above 0.10.\n"
    )
    commit(tmp_path, "register")
    document.write_text(
        document.read_text().replace("_pending_", git(tmp_path, "rev-parse", "HEAD"))
    )
    commit(tmp_path, "record the commit")

    document.write_text(document.read_text() + "\nA note added after the freeze.\n")
    git(tmp_path, "add", "-A")
    assert run(["check", "--staged"], tmp_path).returncode == 0, (
        "lines added at the end are allowed"
    )

    document.write_text(document.read_text().replace("Above 0.10", "Above 0.050"))
    git(tmp_path, "add", "-A")
    r = run(["check", "--staged"], tmp_path)
    assert r.returncode == 1
    assert "STAGED       PREREGISTRATION.md  frozen by a commit line" in r.stdout
