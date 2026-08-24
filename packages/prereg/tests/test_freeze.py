"""A freeze is only worth anything if editing the plan afterwards is detectable."""

from __future__ import annotations

import subprocess
import sys

import pytest
from prereg import cli


def run(args, cwd):
    return subprocess.run(
        [sys.executable, "-m", "prereg.cli", *args], cwd=cwd, capture_output=True, text=True
    )


@pytest.fixture
def repo(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path)
    run(["new", "study"], tmp_path)
    subprocess.run(["git", "add", "-A"], cwd=tmp_path)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "init"],
        cwd=tmp_path,
    )
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
    result = run(["freeze"], tmp_path / "study")
    assert result.returncode == 1
    assert "Commit first" in result.stdout


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
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "edit"], cwd=repo
    )
    r = run(["freeze", "--force", "--access", "nothing run"], repo)
    printed = [w for w in r.stdout.split() if len(w.rstrip("…")) == 16][-1].rstrip("…")
    assert printed in p.read_text(), "freeze printed a digest it did not write"
    assert run(["check"], repo).returncode == 0


def test_status_note_survives_the_freeze_intact(repo):
    p = repo / "PREREG.md"
    p.write_text(
        p.read_text().replace(
            "**Status:** DRAFT — not frozen.",
            "**Status:** DRAFT — not frozen. Third version; see Log.",
        )
    )
    subprocess.run(["git", "add", "-A"], cwd=repo)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "note"], cwd=repo
    )
    run(["freeze"], repo)
    text = p.read_text()
    frozen_line = next(ln for ln in text.splitlines() if ln.startswith("**Frozen:**"))
    assert frozen_line.strip().endswith(cli.today()), (
        f"note was glued onto the freeze date: {frozen_line!r}"
    )
    assert "Third version; see Log." in text
    assert run(["check"], repo).returncode == 0


def test_refreezing_an_unedited_plan_is_idempotent(repo):
    run(["freeze"], repo)
    first = (repo / "PREREG.md").read_text()
    digest = cli.re.search(r"`([0-9a-f]{64})`", first).group(1)
    run(["freeze", "--force", "--access", "nothing run"], repo)
    second = (repo / "PREREG.md").read_text()
    assert cli.re.search(r"`([0-9a-f]{64})`", second).group(1) == digest
    assert run(["check"], repo).returncode == 0


# --- what the hash does not cover ------------------------------------------------------------


def test_freeze_refuses_a_plan_with_no_status_line(repo):
    p = repo / "PREREG.md"
    p.write_text(p.read_text().replace("**Status:** DRAFT — not frozen.", ""))
    subprocess.run(["git", "add", "-A"], cwd=repo)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "no status"],
        cwd=repo,
    )
    r = run(["freeze"], repo)
    assert r.returncode != 0, "reported a freeze it did not perform"
    # A refusal has to leave the plan unfrozen. The earlier form of this assertion was
    # `"not frozen" not in ... or r.returncode != 0`, whose right operand the line above had
    # already proven true, so it could not fail whatever `check` printed.
    check = run(["check"], repo)
    assert "not frozen" in check.stdout
    assert check.returncode == 2


def test_a_status_marker_in_the_body_cannot_hide_from_the_hash(repo):
    """Marker-prefixed lines are skipped when hashing, so one in the body would be editable
    after freezing without `check` noticing."""
    p = repo / "PREREG.md"
    p.write_text(
        p.read_text().replace(
            "## Randomization", "## Randomization\n\n**Frozen:** whatever the author likes\n"
        )
    )
    subprocess.run(["git", "add", "-A"], cwd=repo)
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=t@t",
            "-c",
            "user.name=t",
            "commit",
            "-q",
            "-m",
            "marker in body",
        ],
        cwd=repo,
    )
    r = run(["freeze"], repo)
    assert r.returncode == 1, "froze a plan whose body line the hash does not cover"
    assert "**Frozen:** whatever the author likes" in r.stdout, (
        "the refusal must name the offending line"
    )


def test_a_log_marker_in_the_body_cannot_truncate_the_hash(repo):
    """Hashing stops at the log marker. One in the body would leave the real plan after it
    unhashed and freely editable."""
    p = repo / "PREREG.md"
    p.write_text(
        p.read_text().replace(
            "## Randomization",
            "## Randomization\n\nSeeds 0-4.\n\n---\n\n## Log\n\n## Sample size\n\nn=300 per arm.\n",
        )
    )
    subprocess.run(["git", "add", "-A"], cwd=repo)
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=t@t",
            "-c",
            "user.name=t",
            "commit",
            "-q",
            "-m",
            "marker in body",
        ],
        cwd=repo,
    )
    r = run(["freeze"], repo)
    assert r.returncode == 1, "froze a plan whose tail the hash does not cover"
    assert "more than once" in r.stdout


def test_line_endings_do_not_change_the_hash(repo):
    run(["freeze"], repo)
    p = repo / "PREREG.md"
    p.write_bytes(p.read_text().replace("\n", "\r\n").encode())
    assert run(["check"], repo).returncode == 0, (
        "a checkout with CRLF endings must not read as a tampered plan"
    )


def test_trailing_whitespace_alone_is_not_a_change(repo):
    run(["freeze"], repo)
    p = repo / "PREREG.md"
    p.write_text(p.read_text() + "\n\n")
    assert run(["check"], repo).returncode == 0


# --- the log is the tamper record, so it is worth attacking -----------------------------------


def test_a_log_note_cannot_forge_another_entry(repo):
    run(["freeze"], repo)
    run(
        [
            "log",
            "harmless\n2020-01-01  frozen at 000000000000        nothing run",
            "--access",
            "no results seen",
        ],
        repo,
    )
    text = (repo / "PREREG.md").read_text()
    assert "2020-01-01  frozen at" not in text, "a newline in a note forged a second log entry"


def test_a_log_note_cannot_break_out_of_the_fence(repo):
    run(["freeze"], repo)
    run(["log", "see ``` and then some", "--access", "no results seen"], repo)
    text = (repo / "PREREG.md").read_text()
    _, _, tail = text.partition(cli.MARK)
    assert tail.count("```") == 2, f"fence count is {tail.count('```')}, log structure broken"


def test_freezing_without_a_commit_says_so(tmp_path):
    """`git()` returns "" on any non-zero exit, so a repository with no commit read as clean.

    Reaching the guard needs `--force`: an uncommitted plan is always dirty, and the dirty
    check returns first. The earlier version of this test asserted a literal the source never
    emits, on a run that stopped one guard earlier.
    """
    subprocess.run(["git", "init", "-q"], cwd=tmp_path)
    run(["new", "study"], tmp_path)
    plan = tmp_path / "study"
    r = run(["freeze", "--force", "--access", "nothing run"], plan)
    assert r.returncode == 1, r.stdout
    assert "not in a git repository with a commit" in r.stdout
    text = (plan / "PREREG.md").read_text()
    assert "**Plan sha256:**" not in text, "a refused freeze must not write a digest"
    assert "DRAFT" in text


def test_check_at_a_root_fails_if_any_plan_below_it_changed(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path)
    for name in ("good", "bad"):
        run(["new", name], tmp_path)
    subprocess.run(["git", "add", "-A"], cwd=tmp_path)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "init"],
        cwd=tmp_path,
    )
    run(["freeze"], tmp_path / "good")
    run(["freeze"], tmp_path / "bad")
    p = tmp_path / "bad" / "PREREG.md"
    p.write_text(p.read_text().replace("## Randomization", "## Randomisation"))
    assert run(["check"], tmp_path).returncode != 0, (
        "a root check passed while a plan below it had been edited"
    )


def test_a_long_note_still_separates_from_its_access_level(repo):
    """The access level is what distinguishes an amendment from a deviation, so it must never
    run into the note."""
    run(["freeze"], repo)
    note = "restricting the target to {0,1} and {0,1,2} because its value set is integers"
    run(["log", note, "--access", "no results seen"], repo)
    line = next(ln for ln in (repo / "PREREG.md").read_text().splitlines() if note in ln)
    entry = line.rpartition(cli.LOG_MARK)[0] or line
    assert entry.rstrip().endswith("no results seen")
    assert not line.endswith(note + "no results seen"), "access level glued to the note"
    assert "  no results seen" in line


# --- the log is append-only, and now says so ------------------------------------------------


def test_deleting_a_log_entry_is_visible(repo):
    """The plan's hash stops at the log, since the log is written after freezing. That left
    the record of deviations -- the only account of what changed after the plan was fixed --
    freely deletable while `check` still reported the plan unchanged."""
    run(["freeze"], repo)
    run(["log", "saw the outcome table", "--access", "results seen"], repo)
    run(["log", "adjusted the threshold", "--access", "results seen"], repo)
    path = repo / "PREREG.md"
    assert cli.log_problems(path.read_text()) == []

    kept = [ln for ln in path.read_text().splitlines() if "saw the outcome table" not in ln]
    path.write_text("\n".join(kept) + "\n")
    problems = cli.log_problems(path.read_text())
    assert problems, "an entry was removed and nothing reported it"
    assert "removed" in problems[0]


def test_editing_a_log_entry_is_visible(repo):
    run(["freeze"], repo)
    run(["log", "results seen on the held-out split", "--access", "results seen"], repo)
    path = repo / "PREREG.md"
    path.write_text(
        path.read_text().replace("results seen on the held-out split", "nothing was examined")
    )
    assert cli.log_problems(path.read_text())


def test_check_reports_a_tampered_log(repo):
    run(["freeze"], repo)
    run(["log", "saw the outcomes", "--access", "results seen"], repo)
    path = repo / "PREREG.md"
    kept = [ln for ln in path.read_text().splitlines() if "saw the outcomes" not in ln]
    path.write_text("\n".join(kept) + "\n")
    result = run(["check"], repo)
    assert result.returncode != 0
    assert "log" in result.stdout.lower()


def test_content_hidden_behind_a_marker_after_freezing_is_reported(repo):
    """`freeze` refuses a plan that hides content behind a marker line; `check` did not.

    `plan_of` skips marker-prefixed lines so the hash cannot cover itself, which means a line
    inserted *after* the freeze sits in the plan uncovered. `**Frozen:** we will also accept
    p<0.10` is a commitment the reader sees and the digest does not.
    """
    run(["freeze"], repo)
    assert run(["check"], repo).returncode == 0

    path = repo / "PREREG.md"
    before = cli.sha256_of(cli.plan_of(path.read_text()))
    # Exactly one line, and no blank line around it: `plan_of` drops the marker line but joins
    # what remains, so an inserted blank would move the digest and the hash would catch it
    # instead. The point is the case the hash cannot see.
    path.write_text(
        path.read_text().replace(
            "## Randomization", "**Frozen:** we will also accept p<0.10\n## Randomization", 1
        )
    )
    assert cli.sha256_of(cli.plan_of(path.read_text())) == before, (
        "the digest must be blind to this, or the test is not exercising the hidden-content check"
    )

    r = run(["check"], repo)
    assert r.returncode != 0, "a commitment added after the freeze reported as unchanged"
    assert "UNCOVERED" in r.stdout
    assert "p<0.10" in r.stdout


def test_check_at_a_root_fails_if_any_plan_below_it_was_never_frozen(tmp_path):
    """The single-plan branch returns 2 for an unfrozen plan; the root branch returned 0.

    Whether an unfrozen registration passed CI therefore depended on which directory the
    command ran from.
    """
    subprocess.run(["git", "init", "-q"], cwd=tmp_path)
    for name in ("frozen", "never"):
        run(["new", name], tmp_path)
    subprocess.run(["git", "add", "-A"], cwd=tmp_path)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "init"],
        cwd=tmp_path,
    )
    run(["freeze"], tmp_path / "frozen")

    r = run(["check"], tmp_path)
    assert r.returncode != 0, "a root check passed with an unfrozen plan below it"
    assert "1 not frozen" in r.stdout
    assert run(["check"], tmp_path / "never").returncode == 2, "the two branches must agree"


def test_a_root_check_passes_when_every_plan_below_it_is_frozen(tmp_path):
    # The control: the root branch has to stay usable, not merely strict.
    subprocess.run(["git", "init", "-q"], cwd=tmp_path)
    for name in ("a", "b"):
        run(["new", name], tmp_path)
    subprocess.run(["git", "add", "-A"], cwd=tmp_path)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "init"],
        cwd=tmp_path,
    )
    for name in ("a", "b"):
        run(["freeze"], tmp_path / name)
    assert run(["check"], tmp_path).returncode == 0


def test_replacing_the_last_log_entry_is_caught_by_the_anchor(repo):
    """Chaining cannot see the end of the log rewritten, because the chain is rebuilt with it.

    Only the anchor's head witnesses which entry is last. Deleting one changes the count and
    is caught there; substituting one keeps the count, so the head is the only thing that
    disagrees.
    """
    run(["freeze"], repo)
    run(["log", "saw the outcome table", "--access", "results seen"], repo)
    run(["log", "adjusted the threshold", "--access", "results seen"], repo)
    path = repo / "PREREG.md"
    assert cli.log_problems(path.read_text()) == []

    lines = path.read_text().splitlines()
    entries = cli.log_lines(path.read_text())
    previous = ""
    for entry in entries[:-1]:
        body, _, recorded = entry.rpartition(cli.LOG_MARK)
        previous = recorded.strip() if body else cli.chain_value(previous, entry)

    original = entries[-1]
    body = original.rpartition(cli.LOG_MARK)[0].replace("adjusted the threshold", "no change made")
    forged = f"{body}{cli.LOG_MARK} {cli.chain_value(previous, body)}"
    path.write_text("\n".join(ln.replace(original, forged) for ln in lines) + "\n")

    problems = cli.log_problems(path.read_text())
    assert problems, "a rewritten last entry chained cleanly and nothing else looked at it"
    assert any("not the one recorded" in p for p in problems), problems
    assert run(["check"], repo).returncode != 0


def test_a_forced_refreeze_after_results_were_seen_must_say_what_was_seen(repo):
    """`nothing run` was written unconditionally, so a rewrite forced after a `results seen`
    entry logged itself as an amendment directly beneath the line saying otherwise."""
    run(["freeze"], repo)
    run(["log", "saw the outcome table", "--access", "results seen"], repo)

    before = cli.log_lines((repo / "PREREG.md").read_text())
    assert before[-1].endswith("results seen") or "results seen" in before[-1]

    r = run(["freeze", "--force"], repo)
    assert r.returncode == 1, r.stdout
    assert "cannot describe itself" in r.stdout
    # The refusal has to leave the log alone. Writing `nothing run` blind put an amendment
    # claiming nothing had been run directly beneath the entry recording that the outcomes
    # had been examined.
    assert cli.log_lines((repo / "PREREG.md").read_text()) == before

    ok = run(["freeze", "--force", "--access", "results seen"], repo)
    assert ok.returncode == 0, ok.stdout
    after = cli.log_lines((repo / "PREREG.md").read_text())
    assert len(after) == len(before) + 1
    assert "results seen" in after[-1] and "nothing run" not in after[-1]
