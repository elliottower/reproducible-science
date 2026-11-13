"""A freeze is checked against history as well as the disk: the file at the commit its record
names, the record's own history, the companions frozen with it, and the ledger it was frozen
beside."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys

import pytest
from provenance_core import sha256_of_text
from provenance_core.gitref import clean_env


def git(repo, *args, env=None) -> str:
    done = subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
        cwd=repo,
        env=clean_env(**(env or {})),
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout.strip()


def commit(repo, message="commit", env=None) -> str:
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message, env=env)
    return git(repo, "rev-parse", "HEAD")


def run(args, cwd):
    return subprocess.run(
        [sys.executable, "-m", "prereg.cli", *args],
        cwd=cwd,
        env=clean_env(),
        capture_output=True,
        text=True,
    )


def record_path(plan):
    return plan.parent / ".prereg" / f"{plan.name}.json"


def rewrite_record(plan, **fields) -> None:
    where = record_path(plan)
    held = json.loads(where.read_text()) | fields
    where.write_text(json.dumps(held, indent=2) + "\n")


def edit(plan, old: str, new: str) -> None:
    plan.chmod(0o644)
    plan.write_text(plan.read_text().replace(old, new))


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


def test_an_unchanged_freeze_passes_against_its_history(frozen):
    r = run(["check"], frozen.parent)
    assert r.returncode == 0, r.stdout
    assert r.stdout.startswith("unchanged")


def test_a_plan_edited_with_its_record_and_committed_is_found_in_history(frozen):
    edit(frozen, "# ", "# Edited: ")
    rewrite_record(frozen, sha256=hashlib.sha256(frozen.read_bytes()).hexdigest())
    commit(frozen.parent, "edit the plan and its digest together")

    r = run(["check"], frozen.parent)
    assert r.returncode == 1
    assert r.stdout.startswith(f"REWRITTEN    {frozen}")
    assert "PREREG.md.json was rewritten in commit" in r.stdout
    assert "the commit the freeze record names, is not the file the record says was frozen" in (
        r.stdout
    )


def test_a_record_repointed_at_the_edit_is_still_a_record_rewritten(frozen):
    edit(frozen, "# ", "# Edited: ")
    edited = commit(frozen.parent, "edit")
    rewrite_record(frozen, sha256=hashlib.sha256(frozen.read_bytes()).hexdigest(), commit=edited)
    commit(frozen.parent, "repoint the record")

    r = run(["check"], frozen.parent)
    assert r.returncode == 1
    assert "PREREG.md.json was rewritten in commit" in r.stdout
    assert "is not the file the record says" not in r.stdout


def test_a_record_deleted_and_made_again_over_a_backdated_edit_is_found(frozen):
    study = frozen.parent
    aside = study.parent / "record.json"
    record_path(frozen).rename(aside)
    edit(frozen, "# ", "# Edited: ")
    commit(study, "edit", env={"GIT_COMMITTER_DATE": "2026-01-01T00:00:00Z"})
    assert run(["freeze"], study).returncode == 0
    commit(study, "freeze again")

    r = run(["check"], study)
    assert r.returncode == 1
    assert "was deleted in commit" in r.stdout
    assert "and written again in commit" in r.stdout


def test_a_record_deleted_and_restored_byte_for_byte_is_the_same_freeze(frozen):
    study = frozen.parent
    held = record_path(frozen).read_bytes()
    record_path(frozen).unlink()
    commit(study, "removed by mistake")
    record_path(frozen).write_bytes(held)
    commit(study, "restored")
    r = run(["check"], study)
    assert r.returncode == 0, r.stdout


def test_a_committed_record_that_is_gone_is_a_finding_not_a_draft(frozen):
    study = frozen.parent
    record_path(frozen).unlink()
    r = run(["check"], study)
    assert r.returncode == 1
    assert f"RECORD GONE  {frozen}" in r.stdout
    assert "is gone from disk" in r.stdout

    commit(study, "delete the record")
    r = run(["check"], study)
    assert r.returncode == 1
    assert "deleted since" in r.stdout


def test_an_uncommitted_edit_to_a_committed_record_is_found(frozen):
    rewrite_record(frozen, access="results seen")
    r = run(["check"], frozen.parent)
    assert r.returncode == 1
    assert "PREREG.md.json on disk is not the version last committed" in r.stdout


def test_an_earlier_freezes_timestamp_beside_the_plan_is_a_refreeze(frozen):
    (frozen.parent / f"{frozen.name}.0123456789abcdef.ots").write_bytes(b"proof")
    r = run(["check"], frozen.parent)
    assert r.returncode == 1
    assert "is the timestamp of an earlier freeze, of 0123456789abcdef" in r.stdout


def test_a_forced_freeze_of_uncommitted_bytes_is_noted_and_passes(study):
    plan = study / "PREREG.md"
    plan.write_text(plan.read_text() + "\nA last line.\n")
    assert run(["freeze", "--force"], study).returncode == 0
    held = json.loads(record_path(plan).read_text())
    assert held["uncommitted"] is True
    commit(study, "freeze")

    r = run(["check"], study)
    assert r.returncode == 0, r.stdout
    assert "note       frozen with --force from bytes that are not those of commit" in r.stdout


def test_a_record_written_by_an_earlier_version_reads_as_before(frozen):
    held = json.loads(record_path(frozen).read_text())
    assert set(held) == {"file", "sha256", "commit", "frozen_at", "access", "parent"}


def test_a_companion_is_frozen_with_the_plan_and_any_change_to_it_fails(study):
    config = study / "analysis_plan.yaml"
    config.write_text("alpha: 0.05\n")
    commit(study, "config")
    r = run(["freeze", "--companion", "analysis_plan.yaml"], study)
    assert r.returncode == 0, r.stdout
    plan = study / "PREREG.md"
    held = json.loads(record_path(plan).read_text())
    assert held["companions"] == {
        "analysis_plan.yaml": hashlib.sha256(b"alpha: 0.05\n").hexdigest()
    }
    commit(study, "freeze")
    r = run(["check"], study)
    assert r.returncode == 0, r.stdout
    assert "with       analysis_plan.yaml, unchanged" in r.stdout

    config.write_text("alpha: 0.10\n")
    r = run(["check"], study)
    assert r.returncode == 1
    assert r.stdout.startswith(f"CHANGED      {plan}")
    assert "analysis_plan.yaml was frozen with it as" in r.stdout

    git(study, "add", "-A")
    staged = run(["check", "--staged"], study)
    assert staged.returncode == 1
    assert "STAGED       study/analysis_plan.yaml  frozen with a plan as its companion" in (
        staged.stdout
    )

    config.unlink()
    r = run(["check"], study)
    assert r.returncode == 1
    assert "analysis_plan.yaml was frozen with it and is gone" in r.stdout


def test_a_companion_with_uncommitted_changes_is_refused_before_anything_is_written(study):
    (study / "analysis_plan.yaml").write_text("alpha: 0.05\n")
    r = run(["freeze", "--companion", "analysis_plan.yaml"], study)
    assert r.returncode == 1
    assert "has uncommitted changes" in r.stdout
    assert not record_path(study / "PREREG.md").exists()


def test_a_companion_edited_together_with_its_digest_is_found_at_the_commit(study):
    config = study / "analysis_plan.yaml"
    config.write_text("alpha: 0.05\n")
    commit(study, "config")
    assert run(["freeze", "--companion", "analysis_plan.yaml"], study).returncode == 0
    commit(study, "freeze")
    config.write_text("alpha: 0.10\n")
    plan = study / "PREREG.md"
    rewrite_record(
        plan,
        companions={"analysis_plan.yaml": hashlib.sha256(b"alpha: 0.10\n").hexdigest()},
    )
    commit(study, "edit the companion and its digest")
    r = run(["check"], study)
    assert r.returncode == 1
    assert "analysis_plan.yaml at commit" in r.stdout


def ledger(root, events: list[dict]) -> list[str]:
    (root / ".results").mkdir()
    lines = [json.dumps(e | {"seq": i}) for i, e in enumerate(events)]
    (root / ".results" / "ledger.jsonl").write_text("".join(f"{line}\n" for line in lines))
    return lines


def test_a_freeze_records_where_it_sits_in_the_ledger(study):
    lines = ledger(study.parent, [{"event": "init"}, {"event": "access", "level": "nothing seen"}])
    commit(study, "ledger")
    assert run(["freeze"], study).returncode == 0
    held = json.loads(record_path(study / "PREREG.md").read_text())
    assert held["ledger"] == {
        "path": "../.results/ledger.jsonl",
        "events": 2,
        "head": sha256_of_text(lines[-1]),
    }


def test_a_run_declared_late_is_kept_in_the_record_and_shown_by_check(study):
    ledger(
        study.parent,
        [
            {"event": "init"},
            {"event": "run", "run_id": "r1", "outputs": []},
            {"event": "label", "run_id": "r1", "holds": "metadata only", "note": "forgot"},
        ],
    )
    commit(study, "ledger")
    assert run(["freeze"], study).returncode == 0
    plan = study / "PREREG.md"
    assert json.loads(record_path(plan).read_text())["ledger"]["declared_late"] == ["r1"]
    commit(study, "freeze")

    out = study.parent / "check.json"
    r = run(["check", "--json", str(out)], study)
    assert r.returncode == 0, r.stdout
    assert (
        "ledger     frozen at an access floor that `results label` lowered after the fact: r1"
        in (r.stdout)
    )
    account = json.loads(out.read_text())
    assert account["plans"][0]["declared_late"] == ["r1"]
    assert account["notes"] == [
        f"{plan}: frozen at an access floor that `results label` lowered after the fact: r1"
    ]
