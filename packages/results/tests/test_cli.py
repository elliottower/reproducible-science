"""Tests for the results CLI commands."""

from __future__ import annotations

import json
import subprocess
import sys

from provenance_core.gitref import clean_env
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


def test_run_refuses_a_duplicate_id(tmp_path):
    """A warning was not enough. Both the claim-time refusal and `verify`'s contested list
    resolve an id to a single timestamp, so two runs sharing an id let a confirmatory claim
    rest on the earlier of them -- and typing the same id twice was the whole attack."""
    run_cli("init", cwd=tmp_path)
    (tmp_path / "out.csv").write_text("a\n")
    run_cli("run", "out.csv", "--run-id", "exp1", cwd=tmp_path)
    r = run_cli("run", "out.csv", "--run-id", "exp1", cwd=tmp_path)
    assert r.returncode == 1
    assert "already exists" in r.stdout


def test_run_records_a_duplicate_id_when_told_to(tmp_path):
    run_cli("init", cwd=tmp_path)
    (tmp_path / "out.csv").write_text("a\n")
    run_cli("run", "out.csv", "--run-id", "exp1", cwd=tmp_path)
    r = run_cli("run", "out.csv", "--run-id", "exp1", "--anyway", cwd=tmp_path)
    assert r.returncode == 0


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
    sealed = next(
        e
        for e in ledger.read_ledger(tmp_path / ".results" / "ledger.jsonl")
        if e["event"] == "seal"
    )
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
            [
                *lines[:-1],
                lines[-1].replace('"after_outcomes_seen":true', '"after_outcomes_seen":false'),
            ]
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
            [
                *lines[:-1],
                lines[-1].replace('"after_outcomes_seen":true', '"after_outcomes_seen":false'),
            ]
        )
        + "\n"
    )

    v = run_cli("verify", cwd=tmp_path)
    assert v.returncode != 0
    assert "CHAIN EDITED" in v.stdout, v.stdout


# -- what `verify --files` says about a path that is no longer what was sealed ---------------


def seal_one(tmp_path, body="a,b\n1,2\n"):
    run_cli("init", cwd=tmp_path)
    path = tmp_path / "data.csv"
    path.write_text(body)
    run_cli("seal", "data.csv", "--role", "input", cwd=tmp_path)
    return path


def test_a_sealed_file_that_has_been_deleted_is_not_ok(tmp_path):
    """Only negative assertions covered this -- `"MISSING" not in stdout` on a healthy run.

    A sealed input that is gone is the ordinary shape of an unreproducible result, and it read
    as a pass.
    """
    seal_one(tmp_path).unlink()
    v = run_cli("verify", "--files", cwd=tmp_path)
    assert v.returncode == 1, v.stdout
    assert "MISSING" in v.stdout and "data.csv" in v.stdout
    assert "changed or missing" in v.stdout


def test_a_sealed_file_that_was_edited_is_reported_as_changed(tmp_path):
    path = seal_one(tmp_path)
    path.write_text("a,b\n9,9\n")
    v = run_cli("verify", "--files", cwd=tmp_path)
    assert v.returncode == 1
    assert "CHANGED" in v.stdout


def test_a_path_sealed_under_two_hashes_is_reported_even_when_it_matches_one(tmp_path):
    """Seal, edit, seal again: the file on disk matches the second seal.

    Keyed by path, the later seal replaced the earlier one and the run read as clean, so
    "seal your inputs before the run" was not what the command checked.
    """
    path = seal_one(tmp_path)
    path.write_text("a,b\n9,9\n")
    run_cli("seal", "data.csv", "--role", "input", cwd=tmp_path)
    v = run_cli("verify", "--files", cwd=tmp_path)
    assert v.returncode == 1, v.stdout
    assert "RESEALED" in v.stdout
    assert "2 different hashes" in v.stdout


def test_an_untouched_sealed_file_still_passes(tmp_path):
    # The control for the three above.
    seal_one(tmp_path)
    v = run_cli("verify", "--files", cwd=tmp_path)
    assert v.returncode == 0, v.stdout
    assert "all checks passed" in v.stdout


# -- the reanchor command's own refusals -----------------------------------------------------


def test_reanchor_refuses_a_truncated_chain(tmp_path):
    """Deleting trailing events and re-anchoring was a two-command path to a clean report.

    Truncation is the cheapest tampering there is: no line has to be forged, so the hash chain
    stays perfect and only the anchor's count disagrees.
    """
    run_cli("init", cwd=tmp_path)
    (tmp_path / "out.json").write_text('{"d": 0.1}\n')
    run_cli("run", "out.json", "--run-id", "r1", cwd=tmp_path)
    run_cli("claim", "d = 0.1", "--run-id", "r1", cwd=tmp_path)

    lp = tmp_path / ".results" / "ledger.jsonl"
    lines = lp.read_text().splitlines()
    lp.write_text("\n".join(lines[:-1]) + "\n")

    r = run_cli("reanchor", cwd=tmp_path)
    assert r.returncode == 1, r.stdout
    assert "truncated" in r.stdout
    assert ledger.verify(lp)[0] is ledger.ChainStatus.TRUNCATED, "the anchor must not have moved"


def test_reanchor_repairs_a_ledger_that_was_never_anchored(tmp_path):
    # The control: reanchor has to remain usable for what it exists to do.
    run_cli("init", cwd=tmp_path)
    lp = tmp_path / ".results" / "ledger.jsonl"
    ledger.anchor_path(lp).unlink()
    r = run_cli("reanchor", cwd=tmp_path)
    assert r.returncode == 0, r.stdout
    assert ledger.verify(lp)[0] is ledger.ChainStatus.INTACT


# -- a claim that names a run the ledger does not hold ----------------------------------------


def test_verify_reports_a_claim_whose_run_is_not_in_the_ledger(tmp_path):
    run_cli("init", cwd=tmp_path)
    (tmp_path / "out.json").write_text('{"d": 0.1}\n')
    run_cli("run", "out.json", "--run-id", "r1", cwd=tmp_path)
    run_cli("claim", "d = 0.1", "--run-id", "r1", cwd=tmp_path)

    # Drop the run event and rebuild the chain, so the ledger verifies and the only fault left
    # is that the claim rests on a run nothing recorded.
    lp = tmp_path / ".results" / "ledger.jsonl"
    events = [
        e
        for e in (json.loads(line) for line in lp.read_text().splitlines())
        if e.get("event") != "run"
    ]
    prev = ledger.ZERO
    lines = []
    for i, event in enumerate(events):
        line = ledger.canonical({**event, "seq": i, "prev_hash": prev})
        lines.append(line)
        prev = ledger.sha256_of_str(line)
    lp.write_text("\n".join(lines) + "\n")
    ledger.write_anchor(lp, len(lines), prev)
    assert ledger.verify(lp)[0] is ledger.ChainStatus.INTACT

    v = run_cli("verify", cwd=tmp_path)
    assert v.returncode == 1, v.stdout
    assert "names runs it does not contain" in v.stdout
    assert "r1" in v.stdout


def test_a_second_run_under_one_id_is_dated_by_the_later_one(tmp_path):
    """`--anyway` allows two runs under one id, and a claim rests on the most recent.

    Taking the earliest let a run performed after the outcomes were seen inherit the first
    run's timestamp, so the confirmatory guard passed on a retrospective analysis.
    """
    run_cli("init", cwd=tmp_path)
    (tmp_path / "out.json").write_text('{"d": 0.1}\n')
    run_cli("run", "out.json", "--run-id", "r1", cwd=tmp_path)
    run_cli("access", "read the outcomes", "--level", "outcomes seen", cwd=tmp_path)
    replay = run_cli("run", "out.json", "--run-id", "r1", "--anyway", cwd=tmp_path)
    assert replay.returncode == 0, replay.stdout

    refused = run_cli("claim", "d = 0.1", "--run-id", "r1", "--confirmatory", cwd=tmp_path)
    assert refused.returncode == 1, refused.stdout
    assert "after that" in refused.stdout

    run_cli("claim", "d = 0.1", "--run-id", "r1", "--confirmatory", "--anyway", cwd=tmp_path)
    v = run_cli("verify", cwd=tmp_path)
    assert "after outcomes were seen" in v.stdout


def test_a_duplicate_run_id_is_refused_without_anyway(tmp_path):
    run_cli("init", cwd=tmp_path)
    (tmp_path / "out.json").write_text('{"d": 0.1}\n')
    run_cli("run", "out.json", "--run-id", "r1", cwd=tmp_path)
    r = run_cli("run", "out.json", "--run-id", "r1", cwd=tmp_path)
    assert r.returncode == 1
    assert "already exists" in r.stdout


def a_repo_with_a_frozen_plan(tmp_path, plan="plan.md"):
    """A git repository whose first commit contains the plan, committed before anything ran."""
    for args in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"]):
        subprocess.run(["git", *args], cwd=tmp_path, capture_output=True, env=clean_env())
    (tmp_path / plan).write_text("H1. the effect is positive.\n")
    subprocess.run(["git", "add", plan], cwd=tmp_path, capture_output=True, env=clean_env())
    subprocess.run(
        ["git", "commit", "-q", "-m", "freeze the plan"],
        cwd=tmp_path,
        capture_output=True,
        env=clean_env(),
    )
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, capture_output=True, text=True, env=clean_env()
    ).stdout.strip()
    return sha


def test_a_plan_frozen_before_the_exposure_is_confirmatory(tmp_path):
    sha = a_repo_with_a_frozen_plan(tmp_path)
    run_cli("init", cwd=tmp_path)
    run_cli("access", "read the outcomes", "--level", "outcomes seen", cwd=tmp_path)
    (tmp_path / "out.json").write_text('{"d": 0.103}\n')
    run_cli("run", "out.json", "--run-id", "late", cwd=tmp_path)

    r = run_cli(
        "claim", "d = 0.103", "--run-id", "late", "--confirmatory", "--frozen-at", sha, cwd=tmp_path
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert "confirmatory, exposure logged" in r.stdout

    claim = next(
        e
        for e in ledger.read_ledger(tmp_path / ".results" / "ledger.jsonl")
        if e["event"] == "claim"
    )
    assert claim["confirmatory"] is True
    assert claim["after_outcomes_seen"] is False
    assert claim["frozen_at"] == sha

    v = run_cli("verify", cwd=tmp_path)
    assert "frozen before outcomes were seen" in v.stdout
    assert "no freeze reference" not in v.stdout


def test_a_freeze_that_does_not_resolve_is_refused(tmp_path):
    a_repo_with_a_frozen_plan(tmp_path)
    run_cli("init", cwd=tmp_path)
    run_cli("access", "read the outcomes", "--level", "outcomes seen", cwd=tmp_path)
    (tmp_path / "out.json").write_text('{"d": 0.103}\n')
    run_cli("run", "out.json", "--run-id", "late", cwd=tmp_path)

    r = run_cli(
        "claim",
        "d = 0.103",
        "--run-id",
        "late",
        "--confirmatory",
        "--frozen-at",
        "deadbeef",
        cwd=tmp_path,
    )
    assert r.returncode == 1
    assert "cannot resolve" in r.stdout
    assert not [
        e
        for e in ledger.read_ledger(tmp_path / ".results" / "ledger.jsonl")
        if e["event"] == "claim"
    ]


def test_the_refusal_names_the_freeze_route(tmp_path):
    run_cli("init", cwd=tmp_path)
    run_cli("access", "read the outcomes", "--level", "outcomes seen", cwd=tmp_path)
    (tmp_path / "out.json").write_text('{"d": 0.103}\n')
    run_cli("run", "out.json", "--run-id", "late", cwd=tmp_path)
    r = run_cli("claim", "d = 0.103", "--run-id", "late", "--confirmatory", cwd=tmp_path)
    assert r.returncode == 1
    assert "--frozen-at" in r.stdout
