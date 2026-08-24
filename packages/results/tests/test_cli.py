"""Tests for the results CLI commands."""

from __future__ import annotations

import subprocess
import sys

from results import ledger


def run_cli(*args, cwd=None):
    return subprocess.run(
        [sys.executable, "-m", "results.cli", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
    )


def test_init_creates_results_dir(tmp_path):
    r = run_cli("init", cwd=tmp_path)
    assert r.returncode == 0
    assert (tmp_path / ".results" / "ledger.jsonl").exists()
    events = ledger.read_ledger(tmp_path / ".results" / "ledger.jsonl")
    assert len(events) == 1
    assert events[0]["event"] == "init"


def test_init_twice_fails(tmp_path):
    run_cli("init", cwd=tmp_path)
    r = run_cli("init", cwd=tmp_path)
    assert r.returncode == 1


def test_seal_records_file_hashes(tmp_path):
    run_cli("init", cwd=tmp_path)
    (tmp_path / "script.py").write_text("print('hello')\n")
    (tmp_path / "data.csv").write_text("a,b\n1,2\n")
    r = run_cli("seal", "script.py", "data.csv", "--role", "input", cwd=tmp_path)
    assert r.returncode == 0
    events = ledger.read_ledger(tmp_path / ".results" / "ledger.jsonl")
    seal = [e for e in events if e["event"] == "seal"]
    assert len(seal) == 1
    assert len(seal[0]["files"]) == 2


def test_access_records_event(tmp_path):
    run_cli("init", cwd=tmp_path)
    r = run_cli("access", "read zenodo metadata", "--level", "metadata only", cwd=tmp_path)
    assert r.returncode == 0
    events = ledger.read_ledger(tmp_path / ".results" / "ledger.jsonl")
    access = [e for e in events if e["event"] == "access"]
    assert len(access) == 1
    assert access[0]["level"] == "metadata only"


def test_access_rejects_invalid_level(tmp_path):
    run_cli("init", cwd=tmp_path)
    r = run_cli("access", "whatever", "--level", "banana", cwd=tmp_path)
    assert r.returncode == 1
    assert "level must be" in r.stdout


def test_run_records_outputs(tmp_path):
    run_cli("init", cwd=tmp_path)
    (tmp_path / "results.json").write_text('{"icc": 0.42}\n')
    r = run_cli("run", "results.json", "--run-id", "run_001", cwd=tmp_path)
    assert r.returncode == 0
    events = ledger.read_ledger(tmp_path / ".results" / "ledger.jsonl")
    runs = [e for e in events if e["event"] == "run"]
    assert len(runs) == 1
    assert runs[0]["run_id"] == "run_001"


def test_run_warns_on_duplicate_id(tmp_path):
    run_cli("init", cwd=tmp_path)
    (tmp_path / "out1.json").write_text('{"a": 1}\n')
    (tmp_path / "out2.json").write_text('{"a": 2}\n')
    run_cli("run", "out1.json", "--run-id", "exp_001", cwd=tmp_path)
    r = run_cli("run", "out2.json", "--run-id", "exp_001", cwd=tmp_path)
    assert r.returncode == 0
    assert "already exists" in r.stdout


def test_claim_requires_existing_run(tmp_path):
    run_cli("init", cwd=tmp_path)
    r = run_cli("claim", "ICC = 0.42", "--run-id", "run_001", cwd=tmp_path)
    assert r.returncode == 1
    assert "no run" in r.stdout


def test_claim_succeeds_after_run(tmp_path):
    run_cli("init", cwd=tmp_path)
    (tmp_path / "results.json").write_text('{"icc": 0.42}\n')
    run_cli("run", "results.json", "--run-id", "run_001", cwd=tmp_path)
    r = run_cli(
        "claim",
        "ICC = 0.42",
        "--run-id",
        "run_001",
        "--confirmatory",
        "--location",
        "Table 2",
        cwd=tmp_path,
    )
    assert r.returncode == 0
    events = ledger.read_ledger(tmp_path / ".results" / "ledger.jsonl")
    claims = [e for e in events if e["event"] == "claim"]
    assert len(claims) == 1
    assert claims[0]["confirmatory"] is True
    assert claims[0]["location"] == "Table 2"


def test_verify_passes_on_clean_ledger(tmp_path):
    run_cli("init", cwd=tmp_path)
    r = run_cli("verify", cwd=tmp_path)
    assert r.returncode == 0
    assert "chain intact" in r.stdout


def test_verify_files_catches_drift(tmp_path):
    run_cli("init", cwd=tmp_path)
    (tmp_path / "data.csv").write_text("a,b\n1,2\n")
    run_cli("seal", "data.csv", cwd=tmp_path)
    (tmp_path / "data.csv").write_text("a,b\n1,2\n3,4\n")
    r = run_cli("verify", "--files", cwd=tmp_path)
    assert r.returncode == 1
    assert "CHANGED" in r.stdout


def test_full_workflow(tmp_path):
    run_cli("init", cwd=tmp_path)
    (tmp_path / "prereg.md").write_text("# My prereg\n")
    (tmp_path / "script.py").write_text("import json\n")
    run_cli("seal", "prereg.md", "script.py", "--role", "prereg", cwd=tmp_path)
    run_cli("access", "downloaded zenodo metadata", "--level", "metadata only", cwd=tmp_path)
    (tmp_path / "out.json").write_text('{"result": 42}\n')
    run_cli("run", "out.json", "--run-id", "exp_001", "--note", "first analysis", cwd=tmp_path)
    run_cli(
        "claim",
        "the answer is 42",
        "--run-id",
        "exp_001",
        "--confirmatory",
        "--location",
        "Section 3",
        cwd=tmp_path,
    )
    r = run_cli("verify", "--files", cwd=tmp_path)
    assert r.returncode == 0
    assert "chain intact" in r.stdout
    assert "all checks passed" in r.stdout


def test_confirmatory_claim_refused_after_outcomes_seen(tmp_path):
    run_cli("init", cwd=tmp_path)
    run_cli("access", "read the reviewer report", "--level", "outcomes seen", cwd=tmp_path)
    (tmp_path / "out.json").write_text('{"d": 0.103}\n')
    run_cli("run", "out.json", "--run-id", "late", cwd=tmp_path)
    r = run_cli("claim", "d = 0.103", "--run-id", "late", "--confirmatory", cwd=tmp_path)
    assert r.returncode == 1
    assert "retrospective" in r.stdout
    events = ledger.read_ledger(tmp_path / ".results" / "ledger.jsonl")
    assert [e for e in events if e["event"] == "claim"] == []


def test_exploratory_claim_allowed_after_outcomes_seen(tmp_path):
    run_cli("init", cwd=tmp_path)
    run_cli("access", "read the reviewer report", "--level", "outcomes seen", cwd=tmp_path)
    (tmp_path / "out.json").write_text('{"d": 0.103}\n')
    run_cli("run", "out.json", "--run-id", "late", cwd=tmp_path)
    r = run_cli("claim", "d = 0.103", "--run-id", "late", cwd=tmp_path)
    assert r.returncode == 0
    claims = [
        e
        for e in ledger.read_ledger(tmp_path / ".results" / "ledger.jsonl")
        if e["event"] == "claim"
    ]
    assert claims[0]["confirmatory"] is False
    assert claims[0]["after_outcomes_seen"] is False


def test_confirmatory_claim_allowed_when_run_predates_outcomes(tmp_path):
    run_cli("init", cwd=tmp_path)
    (tmp_path / "out.json").write_text('{"d": 0.103}\n')
    run_cli("run", "out.json", "--run-id", "early", cwd=tmp_path)
    run_cli("access", "read the reviewer report", "--level", "outcomes seen", cwd=tmp_path)
    r = run_cli("claim", "d = 0.103", "--run-id", "early", "--confirmatory", cwd=tmp_path)
    assert r.returncode == 0
    claims = [
        e
        for e in ledger.read_ledger(tmp_path / ".results" / "ledger.jsonl")
        if e["event"] == "claim"
    ]
    assert claims[0]["after_outcomes_seen"] is False


def test_anyway_records_the_ordering_and_verify_reports_it(tmp_path):
    run_cli("init", cwd=tmp_path)
    run_cli("access", "read the reviewer report", "--level", "outcomes seen", cwd=tmp_path)
    (tmp_path / "out.json").write_text('{"d": 0.103}\n')
    run_cli("run", "out.json", "--run-id", "late", cwd=tmp_path)
    r = run_cli(
        "claim", "d = 0.103", "--run-id", "late", "--confirmatory", "--anyway", cwd=tmp_path
    )
    assert r.returncode == 0
    claims = [
        e
        for e in ledger.read_ledger(tmp_path / ".results" / "ledger.jsonl")
        if e["event"] == "claim"
    ]
    assert claims[0]["confirmatory"] is True
    assert claims[0]["after_outcomes_seen"] is True
    v = run_cli("verify", "--files", cwd=tmp_path)
    assert v.returncode == 0
    assert "after outcomes were seen" in v.stdout
    assert "all checks passed" not in v.stdout


def test_verify_without_files_does_not_claim_hashes_were_checked(tmp_path):
    run_cli("init", cwd=tmp_path)
    (tmp_path / "data.csv").write_text("a,b\n1,2\n")
    run_cli("seal", "data.csv", cwd=tmp_path)
    (tmp_path / "data.csv").write_text("a,b\n1,2\n3,4\n")
    r = run_cli("verify", cwd=tmp_path)
    assert r.returncode == 0
    assert "all checks passed" not in r.stdout
    assert "not checked" in r.stdout


def test_paths_recorded_relative_to_root_not_cwd(tmp_path):
    run_cli("init", cwd=tmp_path)
    sub = tmp_path / "paper"
    sub.mkdir()
    (sub / "draft.tex").write_text("\\documentclass{article}\n")
    r = run_cli("seal", "draft.tex", cwd=sub)
    assert r.returncode == 0
    sealed = [
        e
        for e in ledger.read_ledger(tmp_path / ".results" / "ledger.jsonl")
        if e["event"] == "seal"
    ][0]
    assert sealed["files"][0]["path"] == "paper/draft.tex"
    v = run_cli("verify", "--files", cwd=tmp_path)
    assert v.returncode == 0
    assert "MISSING" not in v.stdout


def test_verify_files_resolves_paths_from_a_subdirectory(tmp_path):
    run_cli("init", cwd=tmp_path)
    sub = tmp_path / "paper"
    sub.mkdir()
    (sub / "draft.tex").write_text("\\documentclass{article}\n")
    run_cli("seal", "draft.tex", cwd=sub)
    v = run_cli("verify", "--files", cwd=sub)
    assert v.returncode == 0
    assert "MISSING" not in v.stdout


def test_verify_recomputes_ordering_rather_than_trusting_the_claim_event(tmp_path):
    """A ledger whose claim event lacks the flag is still caught by verify."""
    run_cli("init", cwd=tmp_path)
    run_cli("access", "read the outcomes", "--level", "outcomes seen", cwd=tmp_path)
    (tmp_path / "out.json").write_text('{"d": 0.103}\n')
    run_cli("run", "out.json", "--run-id", "late", cwd=tmp_path)
    run_cli("claim", "d = 0.103", "--run-id", "late", "--confirmatory", "--anyway", cwd=tmp_path)

    lp = tmp_path / ".results" / "ledger.jsonl"
    lines = lp.read_text().splitlines()
    assert '"after_outcomes_seen":true' in lines[-1]
    lp.write_text(
        "\n".join(
            lines[:-1]
            + [lines[-1].replace('"after_outcomes_seen":true', '"after_outcomes_seen":false')]
        )
        + "\n"
    )

    # The chain catches the edit on its own, which is a stronger result than this test was
    # written for. Re-anchor so the ledger looks untouched, and check that ordering is still
    # recomputed from the events rather than read off the flag the claim event carries.
    from results import ledger as L

    L.reanchor(lp)
    assert L.verify(lp)[0] is L.ChainStatus.INTACT

    v = run_cli("verify", cwd=tmp_path)
    assert "after outcomes were seen" in v.stdout


def test_verify_catches_the_same_edit_before_recomputing_anything(tmp_path):
    """The edit above, without re-anchoring: the chain reports it and stops."""
    run_cli("init", cwd=tmp_path)
    run_cli("access", "read the outcomes", "--level", "outcomes seen", cwd=tmp_path)
    (tmp_path / "out.json").write_text('{"d": 0.103}\n')
    run_cli("run", "out.json", "--run-id", "late", cwd=tmp_path)
    run_cli("claim", "d = 0.103", "--run-id", "late", "--confirmatory", "--anyway", cwd=tmp_path)

    lp = tmp_path / ".results" / "ledger.jsonl"
    lines = lp.read_text().splitlines()
    lp.write_text(
        "\n".join(
            lines[:-1]
            + [lines[-1].replace('"after_outcomes_seen":true', '"after_outcomes_seen":false')]
        )
        + "\n"
    )

    v = run_cli("verify", cwd=tmp_path)
    assert v.returncode != 0
    assert "CHAIN EDITED" in v.stdout, v.stdout
