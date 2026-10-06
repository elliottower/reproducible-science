"""A frozen file never changes by one byte, and anything later is a separate file."""

from __future__ import annotations

import datetime
import hashlib
import json
import re
import shutil
import stat
import subprocess
import sys

import pytest
from prereg import amendment
from provenance_core.gitref import clean_env


def git(repo, *args) -> str:
    # `clean_env` for the reason `test_freeze._run` gives: an inherited `GIT_INDEX_FILE` would
    # send these commits into the repository running the suite.
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


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def record_of(path) -> dict:
    return json.loads((path.parent / ".prereg" / f"{path.name}.json").read_text())


def fill(path, access: str) -> None:
    text = path.read_text()
    text = text.replace(amendment.HINTS[amendment.SECTIONS], "Replaces `Sample size`.")
    text = text.replace(amendment.HINTS[amendment.REASON], "The first sample was too small.")
    text = re.sub(r"^\*\*Access level:\*\*.*$", f"**Access level:** {access}", text, flags=re.M)
    path.write_text(text)


def amend(study, n: int, access: str = "nothing run", *args: str):
    """Start amendment `n`, fill it in, commit it and freeze it."""
    assert run(["amend", *args], study).returncode == 0
    path = study / f"PREREG_AMENDMENT_{n}.md"
    fill(path, access)
    commit(study, f"amendment {n}")
    return path, run(["freeze", path.name], study)


def line_of(out: str, text: str) -> str:
    """The first line of `out` holding `text`."""
    return next(ln for ln in out.splitlines() if text in ln)


@pytest.fixture
def study(tmp_path):
    git(tmp_path, "init", "-q")
    assert run(["new", "study"], tmp_path).returncode == 0
    commit(tmp_path, "plan")
    return tmp_path / "study"


@pytest.fixture
def frozen(study):
    assert run(["freeze"], study).returncode == 0
    commit(study, "freeze")
    return study / "PREREG.md"


def test_a_freeze_writes_nothing_into_the_plan_and_leaves_it_read_only(study):
    plan = study / "PREREG.md"
    before = plan.read_bytes()
    head = git(study, "rev-parse", "HEAD")

    assert run(["freeze"], study).returncode == 0

    assert plan.read_bytes() == before
    assert stat.S_IMODE(plan.stat().st_mode) & 0o222 == 0
    with pytest.raises(PermissionError):
        plan.write_bytes(before + b"\n")
    record = record_of(plan)
    assert record["sha256"] == sha256(before)
    assert record["commit"] == head
    assert record["access"] == "nothing run"
    assert record["parent"] is None
    age = datetime.datetime.now(datetime.UTC) - datetime.datetime.fromisoformat(record["frozen_at"])
    assert datetime.timedelta(0) <= age < datetime.timedelta(minutes=5)


def test_one_appended_byte_is_a_change_and_cannot_be_staged(frozen):
    study = frozen.parent
    assert run(["check"], study).returncode == 0
    (study / "notes.txt").write_text("unrelated\n")
    git(study, "add", "notes.txt")
    assert run(["check", "--staged"], study).returncode == 0

    frozen.chmod(0o644)
    with frozen.open("ab") as f:
        f.write(b"\n")

    check = run(["check"], study)
    assert check.returncode == 1
    assert line_of(check.stdout, "PREREG.md").startswith("CHANGED")
    assert run(["check", "--staged"], study).returncode == 0, "the change is not staged yet"
    git(study, "add", "PREREG.md")
    staged = run(["check", "--staged"], study)
    assert staged.returncode == 1
    assert "study/PREREG.md" in staged.stdout
    assert "notes.txt" not in staged.stdout


def test_check_staged_reads_the_index_the_commit_is_being_built_from(frozen):
    study = frozen.parent
    top = study.parent
    frozen.chmod(0o644)
    # An edit that changes the file's size: git compares size and whole seconds before it reads
    # a file, so a same-size edit made in the second of the last commit can be taken as no edit.
    frozen.write_text(
        frozen.read_text().replace("## Randomization", "## Randomization\n\nBy seed.")
    )
    assert run(["check", "--staged"], top).returncode == 0, "nothing is staged in the usual index"

    # `git commit -a` builds the commit in a temporary index and names it to the pre-commit hook
    # in `GIT_INDEX_FILE`. That index is the one holding the change.
    index = top / ".git" / "index.commit-a"
    shutil.copy(top / ".git" / "index", index)
    hook_env = clean_env(GIT_INDEX_FILE=str(index))
    subprocess.run(["git", "add", "-u"], cwd=top, env=hook_env, check=True)
    hooked = subprocess.run(
        [sys.executable, "-m", "prereg.cli", "check", "--staged"],
        cwd=top,
        env=hook_env,
        capture_output=True,
        text=True,
    )

    assert hooked.returncode == 1
    assert "STAGED       study/PREREG.md  frozen whole" in hooked.stdout


def test_a_changed_or_removed_freeze_record_cannot_be_staged(frozen):
    study = frozen.parent
    record = study / ".prereg" / "PREREG.md.json"
    record.write_text(record.read_text().replace("nothing run", "no results seen"))
    git(study, "add", "-A")
    staged = run(["check", "--staged"], study)
    assert staged.returncode == 1
    assert "study/.prereg/PREREG.md.json" in staged.stdout

    git(study, "rm", "-q", "-f", "--cached", ".prereg/PREREG.md.json", "PREREG.md")
    staged = run(["check", "--staged"], study)
    assert staged.returncode == 1
    assert "study/PREREG.md  frozen, and staged for removal" in staged.stdout


def test_a_second_freeze_is_refused_and_force_does_not_change_that(frozen):
    study = frozen.parent
    record = (study / ".prereg" / "PREREG.md.json").read_bytes()
    frozen.chmod(0o644)
    frozen.write_text(
        frozen.read_text().replace("## Randomization", "## Randomization\n\nBy seed.")
    )
    commit(study, "edit")

    for args in (["freeze"], ["freeze", "--force", "--access", "nothing run"]):
        r = run(args, study)
        assert r.returncode == 1
        assert "never changes" in r.stdout
    assert (study / ".prereg" / "PREREG.md.json").read_bytes() == record
    assert run(["check"], study).returncode == 1


def test_a_draft_carrying_the_in_file_status_and_log_is_not_frozen_whole(study):
    plan = study / "PREREG.md"
    plan.write_text(
        plan.read_text().replace("\n", "\n\n**Status:** DRAFT — not frozen.\n", 1)
        + "\n---\n\n## Log\n\n```\n2026-10-01  created  nothing run\n```\n"
    )
    commit(study, "earlier template")
    before = plan.read_bytes()

    r = run(["freeze"], study)

    assert r.returncode == 1
    assert "`**Status:** DRAFT` line" in r.stdout and "`## Log` section" in r.stdout
    assert plan.read_bytes() == before
    assert not (study / ".prereg").exists()


def test_a_log_entry_before_the_freeze_is_refused(study):
    before = (study / "PREREG.md").read_bytes()
    r = run(["log", "a note", "--access", "nothing run"], study)
    assert r.returncode == 1
    assert "not frozen" in r.stdout
    assert (study / "PREREG.md").read_bytes() == before
    assert not (study / "PREREG.log").exists()


def test_the_log_is_kept_beside_the_plan_and_rewording_an_entry_breaks_its_chain(frozen):
    study = frozen.parent
    before = frozen.read_bytes()

    first = run(["log", "tolerance now from fixtures", "--access", "no results seen"], study)
    assert (
        run(["log", "ran the primary model", "--access", "results not opened"], study).returncode
        == 0
    )

    assert "in the file" not in first.stdout, "the notice is for a plan frozen in place"
    assert frozen.read_bytes() == before
    one, two = (study / "PREREG.log").read_text().splitlines()
    assert "tolerance now from fixtures" in one and "  no results seen  " in one
    assert one.endswith(sha256(before)), "the first entry carries the plan's digest"
    assert two.endswith(sha256(one.encode())), "each later entry carries the one before it"
    assert datetime.datetime.fromisoformat(one.split("  ")[0]).tzinfo is not None
    check = run(["check"], study)
    assert check.returncode == 0
    assert "2 entries, chain intact" in line_of(check.stdout, "PREREG.log")

    log = study / "PREREG.log"
    log.write_text(log.read_text().replace("tolerance now from fixtures", "tolerance unchanged"))
    check = run(["check"], study)
    assert check.returncode == 1
    assert line_of(check.stdout, "PREREG.log").startswith("LOG ALTERED")
    assert "entry 2 does not follow the one before it" in check.stdout


def test_a_log_begun_for_another_plan_does_not_verify(frozen):
    study = frozen.parent
    run(["log", "a note", "--access", "nothing run"], study)
    log = study / "PREREG.log"
    log.write_text(log.read_text().replace(sha256(frozen.read_bytes()), sha256(b"another plan")))
    check = run(["check"], study)
    assert check.returncode == 1
    assert "does not carry this plan's digest" in check.stdout


def test_an_amendment_names_its_parent_by_digest_and_follows_the_plan_in_check(frozen):
    study = frozen.parent
    plan_digest = sha256(frozen.read_bytes())
    assert run(["amend"], study).returncode == 0
    path = study / "PREREG_AMENDMENT_1.md"
    assert f"**Amends:** `{plan_digest}` (PREREG.md)" in path.read_text()

    commit(study, "amendment as the template left it")
    unfilled = run(["freeze", path.name], study)
    assert unfilled.returncode == 1
    for field in ("Sections replaced or added", "Reason", "Access level"):
        assert field in unfilled.stdout
    assert not (study / ".prereg" / f"{path.name}.json").exists()

    fill(path, "no results seen")
    commit(study, "amendment")
    written = path.read_bytes()
    assert run(["freeze", path.name], study).returncode == 0

    assert path.read_bytes() == written
    assert stat.S_IMODE(path.stat().st_mode) & 0o222 == 0
    record = record_of(path)
    assert record["parent"] == plan_digest
    assert record["sha256"] == sha256(written)
    assert record["access"] == "no results seen"
    assert frozen.read_bytes() and sha256(frozen.read_bytes()) == plan_digest

    check = run(["check"], study)
    assert check.returncode == 0
    out = check.stdout
    assert out.index("PREREG.md  frozen") < out.index("PREREG_AMENDMENT_1.md  frozen")
    listed = line_of(
        out, f"PREREG_AMENDMENT_1.md  frozen {record['frozen_at'][:10]}  no results seen"
    )
    assert listed.startswith("unchanged")
    assert "  amends     PREREG.md" in out
    assert "after results" not in out

    path.chmod(0o644)
    path.write_text(path.read_text().replace("too small", "too large"))
    check = run(["check"], study)
    assert check.returncode == 1
    assert [ln for ln in check.stdout.splitlines() if ln.startswith("CHANGED")] == [
        f"CHANGED      {path}  frozen {record['frozen_at'][:10]}  no results seen"
    ]


def test_check_lists_amendments_by_freeze_time_not_by_number(frozen):
    study = frozen.parent
    for n in (1, 2):
        assert run(["amend"], study).returncode == 0
        fill(study / f"PREREG_AMENDMENT_{n}.md", "nothing run")
    commit(study, "two amendments")
    assert run(["freeze", "PREREG_AMENDMENT_2.md"], study).returncode == 0
    assert run(["check"], study).returncode == 2, "an amendment still in draft is not a pass"
    assert run(["freeze", "PREREG_AMENDMENT_1.md"], study).returncode == 0
    # A record's time is to the second, so the order is pinned here and not left to the clock.
    record = study / ".prereg" / "PREREG_AMENDMENT_1.md.json"
    later = json.loads(record.read_text()) | {"frozen_at": "2099-01-01T00:00:00+00:00"}
    record.write_text(json.dumps(later))

    out = run(["check"], study).stdout

    assert out.index("PREREG_AMENDMENT_2.md  frozen") < out.index("PREREG_AMENDMENT_1.md  frozen")


def test_an_amendment_whose_parent_is_gone_is_orphaned(frozen):
    study = frozen.parent
    first, done = amend(study, 1)
    assert done.returncode == 0
    second, done = amend(study, 2, "nothing run", "--parent", first.name)
    assert done.returncode == 0
    assert record_of(second)["parent"] == sha256(first.read_bytes())
    check = run(["check"], study)
    assert check.returncode == 0
    assert "  amends     PREREG_AMENDMENT_1.md" in check.stdout
    assert "orphaned" not in check.stdout

    first.unlink()
    check = run(["check"], study)
    assert check.returncode == 1
    assert line_of(
        check.stdout, first.name + f"  frozen {record_of(first)['frozen_at'][:10]}  nothing run"
    ).startswith("MISSING")
    assert [ln.split()[1] for ln in check.stdout.splitlines() if ln.startswith("orphaned")] == [
        str(second)
    ]

    (study / ".prereg" / f"{first.name}.json").unlink()
    check = run(["check"], study)
    assert check.returncode == 1
    assert "MISSING" not in check.stdout
    assert [ln.split()[1] for ln in check.stdout.splitlines() if ln.startswith("orphaned")] == [
        str(second)
    ]


def test_a_frozen_plan_that_is_deleted_is_missing_and_orphans_its_amendment(frozen):
    study = frozen.parent
    first, done = amend(study, 1)
    assert done.returncode == 0
    frozen.unlink()

    for where in (study, study.parent):
        check = run(["check"], where)
        assert check.returncode == 1
        assert f"MISSING      {frozen}" in check.stdout
        assert f"orphaned     {first}" in check.stdout


def test_an_amendment_cannot_name_a_parent_that_is_not_frozen_here(frozen):
    study = frozen.parent
    assert run(["amend"], study).returncode == 0
    path = study / "PREREG_AMENDMENT_1.md"
    fill(path, "nothing run")
    path.write_text(path.read_text().replace(sha256(frozen.read_bytes()), sha256(b"elsewhere")))
    commit(study, "amendment")

    r = run(["freeze", path.name], study)

    assert r.returncode == 1
    assert "the digest of no frozen file here" in r.stdout
    assert not (study / ".prereg" / f"{path.name}.json").exists()


def ledger(root, *levels: str, runs: int) -> None:
    """A results ledger as `results` writes one: an `init`, then runs and access events."""
    events = [{"event": "init"}]
    events += [
        {"event": "run", "run_id": f"run-{i}", "outputs": [], "note": None} for i in range(runs)
    ]
    events += [{"event": "access", "level": level, "note": "opened"} for level in levels]
    (root / ".results").mkdir()
    (root / ".results" / "ledger.jsonl").write_text(
        "".join(
            json.dumps(
                e
                | {"seq": i, "timestamp": f"2026-10-0{i + 1}T12:00:00+00:00", "prev_hash": "0" * 64}
            )
            + "\n"
            for i, e in enumerate(events)
        )
    )


def test_an_amendment_after_outcomes_were_seen_says_so_and_cannot_claim_less(frozen):
    study = frozen.parent
    ledger(study.parent, "metadata only", "outcomes seen", runs=2)

    assert run(["amend"], study).returncode == 0
    path = study / "PREREG_AMENDMENT_1.md"
    text = path.read_text()
    assert "**Access level:** results seen" in text
    assert "highest access level recorded `outcomes seen`, 2 runs recorded" in text
    assert "`../.results/ledger.jsonl`" in text

    fill(path, "results not opened")
    commit(study, "amendment claiming less than the ledger")
    refused = run(["freeze", path.name], study)
    assert refused.returncode == 1
    assert "cannot be lower than the ledger shows" in refused.stdout
    assert not (study / ".prereg" / f"{path.name}.json").exists()

    fill(path, "results seen")
    commit(study, "amendment")
    assert run(["freeze", path.name], study).returncode == 0
    assert record_of(path)["access"] == "results seen"
    check = run(["check"], study)
    assert check.returncode == 0, "an amendment after results is allowed, and labelled"
    assert line_of(check.stdout, "results seen").startswith(f"unchanged    {path}")
    assert "  written after results were seen" in check.stdout


def test_the_highest_level_in_the_ledger_is_the_floor_not_the_last(frozen):
    study = frozen.parent
    ledger(study.parent, "outcomes seen", "metadata only", runs=0)
    _, done = amend(study, 1, "no results seen")
    assert done.returncode == 1
    assert "recorded `outcomes seen`, 0 runs recorded, which is `results seen` here" in done.stdout


@pytest.mark.parametrize(
    ("level", "runs", "floor"),
    [
        ("nothing seen", 0, "nothing run"),
        ("metadata only", 0, "no results seen"),
        ("structure seen", 0, "no results seen"),
        ("outcomes seen", 0, "results seen"),
        ("nothing seen", 1, "results not opened"),
        ("structure seen", 1, "results not opened"),
        ("outcomes seen", 1, "results seen"),
    ],
)
def test_each_ledger_level_sets_the_level_an_amendment_starts_from(frozen, level, runs, floor):
    study = frozen.parent
    ledger(study.parent, level, runs=runs)
    assert run(["amend"], study).returncode == 0
    text = (study / "PREREG_AMENDMENT_1.md").read_text()
    assert f"**Access level:** {floor}\n" in text
    assert f"recorded `{level}`, {runs} run{'' if runs == 1 else 's'} recorded" in text


def test_recorded_runs_alone_put_the_floor_at_results_not_opened(frozen):
    study = frozen.parent
    ledger(study.parent, runs=3)
    assert run(["amend"], study).returncode == 0
    path = study / "PREREG_AMENDMENT_1.md"
    assert "**Access level:** results not opened\n" in path.read_text()
    assert "highest access level recorded none, 3 runs recorded" in path.read_text()

    fill(path, "no results seen")
    commit(study, "amendment claiming less than the runs show")
    refused = run(["freeze", path.name], study)
    assert refused.returncode == 1
    assert "which is `results not opened` here" in refused.stdout
    assert not (study / ".prereg" / f"{path.name}.json").exists()

    fill(path, "results seen")
    commit(study, "amendment claiming more")
    assert run(["freeze", path.name], study).returncode == 0, "a higher level may be stated"
    assert record_of(path)["access"] == "results seen"


def test_a_plan_is_frozen_at_the_ledgers_floor_and_cannot_claim_less(study):
    ledger(study.parent, "outcomes seen", runs=1)
    commit(study, "ledger")
    plan = study / "PREREG.md"

    refused = run(["freeze", "--access", "nothing run"], study)
    assert refused.returncode == 1
    assert "cannot be lower than the ledger shows" in refused.stdout
    assert not (study / ".prereg").exists()

    assert run(["freeze"], study).returncode == 0
    assert record_of(plan)["access"] == "results seen"
    assert "frozen " in line_of(run(["check"], study).stdout, "results seen")


def test_a_plan_with_no_ledger_above_it_is_frozen_as_nothing_run_or_as_stated(study):
    assert run(["freeze", "--access", "no results seen"], study).returncode == 0
    assert record_of(study / "PREREG.md")["access"] == "no results seen"


def test_an_amendment_with_no_ledger_leaves_the_level_to_the_author(frozen):
    study = frozen.parent
    assert run(["amend"], study).returncode == 0
    text = (study / "PREREG_AMENDMENT_1.md").read_text()
    assert "**Access level:**\n" in text
    assert "ledger" not in text


def logged(frozen, *notes: str):
    for note in notes:
        assert run(["log", note, "--access", "no results seen"], frozen.parent).returncode == 0
    return frozen.parent / "PREREG.log", frozen.parent / "PREREG.log.head"


def test_the_last_log_entry_removed_is_reported_and_nothing_is_appended_over_it(frozen):
    study = frozen.parent
    log, anchor = logged(frozen, "first", "second", "third")
    assert json.loads(anchor.read_text()) == {
        "count": 3,
        "head": sha256(log.read_text().splitlines()[-1].encode()),
    }
    assert run(["check"], study).returncode == 0

    log.write_text("".join(f"{ln}\n" for ln in log.read_text().splitlines()[:-1]))
    shortened = log.read_bytes()
    check = run(["check"], study)
    assert check.returncode == 1
    assert line_of(check.stdout, "PREREG.log").startswith("LOG ALTERED")
    assert "the log records 3 entries and holds 2: an entry has been removed from the end" in (
        check.stdout
    )

    again = run(["log", "written over the gap", "--access", "no results seen"], study)
    assert again.returncode == 1
    assert "nothing was appended" in again.stdout
    assert log.read_bytes() == shortened
    assert json.loads(anchor.read_text())["count"] == 3


def test_a_log_whose_anchor_is_gone_does_not_verify(frozen):
    _, anchor = logged(frozen, "first")
    anchor.unlink()
    check = run(["check"], frozen.parent)
    assert check.returncode == 1
    assert "PREREG.log.head is missing" in check.stdout


def test_an_entry_typed_into_the_log_is_reported_and_the_next_append_recounts(frozen):
    study = frozen.parent
    log, anchor = logged(frozen, "first")
    typed = f"2026-10-07T09:00:00+00:00  typed by hand  results seen  ·{sha256(log.read_text().splitlines()[0].encode())}"
    log.write_text(log.read_text() + typed + "\n")

    check = run(["check"], study)
    assert check.returncode == 1
    assert "the log records 1 entries and holds 2" in check.stdout

    assert run(["log", "third", "--access", "results seen"], study).returncode == 0
    assert json.loads(anchor.read_text())["count"] == 3
    assert run(["check"], study).returncode == 0


def test_the_last_entry_removed_with_the_anchor_edited_to_match_cannot_be_staged(frozen):
    study = frozen.parent
    log, anchor = logged(frozen, "first", "second", "third")
    commit(study, "three entries")
    assert run(["log", "fourth", "--access", "results seen"], study).returncode == 0
    git(study, "add", "-A")
    assert run(["check", "--staged"], study).returncode == 0, (
        "an appended entry is the allowed change"
    )
    commit(study, "four entries")

    kept = log.read_text().splitlines()[:-1]
    log.write_text("".join(f"{ln}\n" for ln in kept))
    anchor.write_text(json.dumps({"count": 3, "head": sha256(kept[-1].encode())}, indent=2) + "\n")

    assert run(["check"], study).returncode == 0, "the pair verifies: only history holds the fourth"
    git(study, "add", "-A")
    staged = run(["check", "--staged"], study)
    assert staged.returncode == 1
    assert "STAGED       study/PREREG.log  a log is append-only" in staged.stdout
    assert "STAGED       study/PREREG.log.head  a log's anchor, moved backwards" in staged.stdout


RULES = ["PREREG.md -text", "PREREG_AMENDMENT_*.md -text", "PREREG.log -text"]


def test_a_freeze_marks_the_frozen_files_so_no_checkout_converts_their_line_endings(study):
    r = run(["freeze"], study)
    assert ".gitattributes  3 `-text` rules added" in r.stdout
    assert (study / ".gitattributes").read_text().splitlines() == RULES

    _, done = amend(study, 1)
    assert done.returncode == 0
    assert ".gitattributes" not in done.stdout.split("Commit")[0]
    assert (study / ".gitattributes").read_text().splitlines() == RULES


def test_the_rule_is_added_to_the_nearest_gitattributes_and_its_lines_are_left_alone(study):
    top = study.parent
    existing = b"*.png binary\r\n# data\n*.csv   text eol=lf"
    (top / ".gitattributes").write_bytes(existing)
    commit(top, "attributes")

    assert run(["freeze"], study).returncode == 0
    _, done = amend(study, 1)
    assert done.returncode == 0

    assert not (study / ".gitattributes").exists()
    held = (top / ".gitattributes").read_bytes()
    assert held.startswith(existing + b"\n")
    assert held[len(existing) + 1 :].decode().splitlines() == [f"study/{rule}" for rule in RULES]


def test_a_checkout_that_converts_line_endings_leaves_a_frozen_plan_unchanged(frozen):
    study = frozen.parent
    _, done = amend(study, 1)
    assert done.returncode == 0
    commit(study, "freeze amendment")
    git(study, "config", "core.autocrlf", "true")

    for name in ("PREREG.md", "PREREG_AMENDMENT_1.md"):
        (study / name).unlink()
    git(study, "checkout", "--", ".")

    assert b"\r\n" not in frozen.read_bytes()
    assert run(["check"], study).returncode == 0
    (study / ".gitignore").unlink()
    git(study, "checkout", "--", ".gitignore")
    assert b"\r\n" in (study / ".gitignore").read_bytes(), (
        "the control: an unmarked file is converted"
    )
