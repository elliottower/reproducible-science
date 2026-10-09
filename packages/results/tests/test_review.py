"""`results review`: a record that someone examined named bytes, and what `verify` says of it."""

from __future__ import annotations

import os
import subprocess
import sys

from results import ledger

REVIEW = (
    "--scope",
    "each mismatch against the paper's table",
    "--procedure",
    "read the rendered page beside the file",
    "--reviewer",
    "A. Reader",
)


def run_cli(*args, cwd, env=None):
    base = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE", "ANTHROPIC"))}
    return subprocess.run(
        [sys.executable, "-m", "results.cli", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        env={**base, **(env or {})},
    )


def project(tmp_path):
    run_cli("init", cwd=tmp_path)
    (tmp_path / "table.csv").write_text("a,b\n1,2\n")
    return tmp_path


def last_event(tmp_path):
    return ledger.read_ledger(tmp_path / ".results" / "ledger.jsonl")[-1]


def test_a_review_records_the_digest_of_what_was_examined(tmp_path):
    project(tmp_path)
    r = run_cli("review", "table.csv", *REVIEW, "--verdict", "partial", cwd=tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    event = last_event(tmp_path)
    assert event["event"] == "review"
    assert event["verdict"] == "partial"
    assert event["reviewer"] == "A. Reader"
    assert event["subjects"] == [
        {
            "path": "table.csv",
            "sha256": ledger.sha256_of_file(tmp_path / "table.csv"),
            "kind": "file",
        }
    ]
    assert "self-reported and unsigned" in r.stdout


def test_a_verdict_outside_the_four_writes_nothing(tmp_path):
    project(tmp_path)
    before = (tmp_path / ".results" / "ledger.jsonl").read_bytes()
    r = run_cli("review", "table.csv", *REVIEW, "--verdict", "verified", cwd=tmp_path)
    assert r.returncode == 1
    assert (tmp_path / ".results" / "ledger.jsonl").read_bytes() == before


def test_scope_procedure_and_reviewer_are_required(tmp_path):
    project(tmp_path)
    for dropped in ("--scope", "--procedure", "--reviewer"):
        at = REVIEW.index(dropped)
        args = REVIEW[:at] + REVIEW[at + 2 :]
        r = run_cli("review", "table.csv", *args, "--verdict", "pass", cwd=tmp_path)
        assert r.returncode == 2, dropped
        assert dropped in r.stderr


def test_the_session_is_recorded_as_the_environment_and_the_flag_give_it(tmp_path):
    project(tmp_path)
    env = {
        "CLAUDECODE": "1",
        "CLAUDE_CODE_EXECPATH": "/somewhere/claude/versions/2.1.295",
        "CLAUDE_CODE_SESSION_ID": "0f0f0f0f-aaaa-bbbb-cccc-121212121212",
    }
    r = run_cli(
        "review",
        "table.csv",
        *REVIEW,
        "--verdict",
        "pass",
        "--model",
        "claude-opus-5-5",
        cwd=tmp_path,
        env=env,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert last_event(tmp_path)["session"] == {
        "model": "claude-opus-5-5",
        "harness": "Claude Code",
        "harness_version": "2.1.295",
        "session_id": "0f0f0f0f-aaaa-bbbb-cccc-121212121212",
    }


def test_outside_a_session_and_with_no_model_the_session_is_empty(tmp_path):
    project(tmp_path)
    run_cli("review", "table.csv", *REVIEW, "--verdict", "pass", cwd=tmp_path)
    assert last_event(tmp_path)["session"] == {}


def test_a_session_with_no_model_named_says_so(tmp_path):
    project(tmp_path)
    r = run_cli(
        "review", "table.csv", *REVIEW, "--verdict", "pass", cwd=tmp_path, env={"CLAUDECODE": "1"}
    )
    assert "no --model" in r.stdout
    assert "model" not in last_event(tmp_path)["session"]


def test_verify_reports_a_reviewed_file_that_changed_as_stale_and_does_not_fail(tmp_path):
    project(tmp_path)
    run_cli("review", "table.csv", *REVIEW, "--verdict", "pass", cwd=tmp_path)

    current = run_cli("verify", "--files", cwd=tmp_path)
    assert current.returncode == 0, current.stdout
    assert "current      table.csv" in current.stdout
    assert "STALE" not in current.stdout

    (tmp_path / "table.csv").write_text("a,b\n1,3\n")
    stale = run_cli("verify", "--files", cwd=tmp_path)
    assert stale.returncode == 0, stale.stdout
    assert "STALE        table.csv" in stale.stdout
    assert "1 reviewed file(s) are no longer the bytes that were reviewed" in stale.stdout


def test_a_review_is_not_a_seal(tmp_path):
    project(tmp_path)
    run_cli("review", "table.csv", *REVIEW, "--verdict", "pass", cwd=tmp_path)
    (tmp_path / "table.csv").write_text("a,b\n1,3\n")
    run_cli("review", "table.csv", *REVIEW, "--verdict", "pass", cwd=tmp_path)
    r = run_cli("verify", "--files", cwd=tmp_path)
    assert "RESEALED" not in r.stdout
    assert "CHANGED" not in r.stdout


def test_without_files_verify_lists_the_review_and_says_the_subject_was_not_checked(tmp_path):
    project(tmp_path)
    run_cli("review", "table.csv", *REVIEW, "--verdict", "fail", cwd=tmp_path)
    r = run_cli("verify", cwd=tmp_path)
    assert "reviews (self-reported, unsigned):" in r.stdout
    assert "fail" in r.stdout and "A. Reader" in r.stdout
    assert "not checked  table.csv" in r.stdout
