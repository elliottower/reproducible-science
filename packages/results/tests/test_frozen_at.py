"""`--frozen-at` names a freeze record, and the record, not a commit date, places the freeze.

Each attack here passed before: any commit was accepted, `HEAD` included; a commit backdated
with `GIT_COMMITTER_DATE` made a plan frozen after the outcomes were seen protect a claim; and a
confirmatory claim from a run recorded before any plan was frozen raised no flag.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys

import pytest
from provenance_core.chain import canonical, write_anchor
from provenance_core.digests import ZERO, sha256_of_text
from provenance_core.gitref import clean_env

PLAN = "# Does it hold?\n\n**H1.** The effect is positive.\n"


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


def tool(name, *args, cwd):
    return subprocess.run(
        [sys.executable, "-m", f"{name}.cli", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        env=clean_env(PROVENANCE_CALENDARS=""),
    )


def results(*args, cwd):
    return tool("results", *args, cwd=cwd)


def freeze(repo) -> str:
    """Freeze the plan as `prereg freeze` does, and return the commit its record names."""
    done = tool("prereg", "freeze", cwd=repo)
    assert done.returncode == 0, done.stdout
    named = json.loads((repo / ".prereg" / "PREREG.md.json").read_text())["commit"]
    commit(repo, "freeze")
    return named


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, "init", "-q")
    (tmp_path / "PREREG.md").write_text(PLAN)
    (tmp_path / "out.json").write_text('{"d": 0.103}\n')
    commit(tmp_path, "plan")
    assert results("init", cwd=tmp_path).returncode == 0
    return tmp_path


def rewrite(lp, rows: list[dict]) -> None:
    """Write `rows` as the ledger, chained and anchored, as `rechain.py` launders one."""
    lines, prev = [], ZERO
    for i, row in enumerate(rows):
        line = canonical(row | {"seq": i, "prev_hash": prev})
        lines.append(line)
        prev = sha256_of_text(line)
    lp.write_text("".join(f"{line}\n" for line in lines))
    write_anchor(lp, len(lines), prev)


def claims(repo) -> list[dict]:
    lines = (repo / ".results" / "ledger.jsonl").read_text().splitlines()
    return [e for e in map(json.loads, lines) if e["event"] == "claim"]


def confirm(repo, run_id, frozen_at):
    return results(
        "claim", "d = 0.103", "--run-id", run_id, "--confirmatory", "--frozen-at", frozen_at,
        cwd=repo,
    )  # fmt: skip


def test_a_plan_frozen_before_the_outcomes_were_seen_protects_the_claim(repo):
    named = freeze(repo)
    results("access", "read the outcomes", "--level", "outcomes seen", cwd=repo)
    results("run", "out.json", "--run-id", "late", cwd=repo)
    r = confirm(repo, "late", named)
    assert r.returncode == 0, r.stdout
    assert "confirmatory, exposure logged" in r.stdout
    assert "recorded before" not in r.stdout
    v = results("verify", cwd=repo)
    assert "frozen before outcomes were seen" in v.stdout


@pytest.mark.parametrize("ref", ["HEAD", "short"])
def test_frozen_at_takes_only_a_full_commit_id(repo, ref):
    named = freeze(repo)
    results("run", "out.json", "--run-id", "r1", cwd=repo)
    r = confirm(repo, "r1", "HEAD" if ref == "HEAD" else named[:12])
    assert r.returncode == 1
    assert "--frozen-at takes the full commit id a freeze record names" in r.stdout
    assert f"{named}  " in r.stdout, "the refusal lists the commits the records name"
    assert not claims(repo)


def test_a_commit_no_freeze_record_names_is_refused(repo):
    freeze(repo)
    other = git(repo, "rev-parse", "HEAD")
    results("run", "out.json", "--run-id", "r1", cwd=repo)
    r = confirm(repo, "r1", other)
    assert r.returncode == 1
    assert f"no freeze record names commit {other}" in r.stdout
    assert not claims(repo)


def test_a_backdated_commit_frozen_after_the_outcomes_were_seen_protects_nothing(repo):
    results("access", "read the outcomes", "--level", "outcomes seen", cwd=repo)
    plan = repo / "PREREG.md"
    plan.write_text(plan.read_text() + "\n**H2.** Chosen after looking.\n")
    commit(
        repo,
        "backdated",
        env={
            "GIT_COMMITTER_DATE": "2025-01-01T00:00:00Z",
            "GIT_AUTHOR_DATE": "2025-01-01T00:00:00Z",
        },
    )
    named = freeze(repo)
    results("run", "out.json", "--run-id", "late", cwd=repo)
    r = confirm(repo, "late", named)
    assert r.returncode == 1
    assert "refusing" in r.stdout
    assert "was written after the outcomes were seen" in r.stdout
    assert not claims(repo)


def test_a_ledger_rewritten_under_a_freeze_cannot_place_it(repo):
    named = freeze(repo)
    lp = repo / ".results" / "ledger.jsonl"
    rows = [json.loads(line) for line in lp.read_text().splitlines()]
    rewrite(lp, [rows[0] | {"note": "rewritten"}, *rows[1:]])
    held = json.loads((repo / ".prereg" / "PREREG.md.json").read_text())
    assert held["ledger"]["events"] == 1
    results("access", "read the outcomes", "--level", "outcomes seen", cwd=repo)
    results("run", "out.json", "--run-id", "late", cwd=repo)
    r = confirm(repo, "late", named)
    assert r.returncode == 1
    # The rewritten ledger was committed with the freeze, so the claim is refused on history
    # before the record is read; uncommitted, the record's head is what refuses it.
    assert "git history holds a ledger this one does not extend" in r.stdout
    assert not claims(repo)


def by_hand(repo, plan_commit, **fields) -> None:
    """A freeze record written by hand, as an older `prereg` or an editor would leave one."""
    held = {
        "file": "PREREG.md",
        "sha256": hashlib.sha256((repo / "PREREG.md").read_bytes()).hexdigest(),
        "commit": plan_commit,
        "frozen_at": "2025-01-01T00:00:00+00:00",
        "access": "nothing run",
        **fields,
    }
    (repo / ".prereg").mkdir(exist_ok=True)
    (repo / ".prereg" / "PREREG.md.json").write_text(json.dumps(held))


def test_prereg_freeze_writes_the_freeze_into_the_ledger(repo):
    named = freeze(repo)
    lines = (repo / ".results" / "ledger.jsonl").read_text().splitlines()
    (event,) = [e for e in map(json.loads, lines) if e["event"] == "freeze"]
    assert (event["commit"], event["file"]) == (named, "PREREG.md")


def test_a_ghost_record_with_no_plan_places_nothing(repo):
    results("access", "read the outcomes", "--level", "outcomes seen", cwd=repo)
    head = git(repo, "rev-parse", "HEAD")
    ghost = repo / "notes" / ".prereg"
    ghost.mkdir(parents=True)
    (ghost / "GHOST.md.json").write_text(
        json.dumps({"file": "GHOST.md", "sha256": "0" * 64, "commit": head,
                    "frozen_at": "2025-01-01T00:00:00+00:00", "access": "nothing run"})
    )  # fmt: skip
    results("run", "out.json", "--run-id", "late", cwd=repo)
    r = confirm(repo, "late", head)
    assert r.returncode == 1
    assert "no plan GHOST.md stands beside the record" in r.stdout
    assert not claims(repo)


def test_a_record_with_no_position_and_a_backdated_time_places_nothing(repo):
    results("access", "read the outcomes", "--level", "outcomes seen", cwd=repo)
    plan_commit = git(repo, "rev-parse", "HEAD")
    by_hand(repo, plan_commit)
    results("run", "out.json", "--run-id", "late", cwd=repo)
    r = confirm(repo, "late", plan_commit)
    assert r.returncode == 1
    assert not claims(repo)


def test_a_record_claiming_fewer_events_than_its_commit_held_places_nothing(repo):
    results("access", "read the outcomes", "--level", "outcomes seen", cwd=repo)
    plan = repo / "PREREG.md"
    plan.write_text(plan.read_text() + "\n**H2.** Chosen after looking.\n")
    plan_commit = commit(repo, "plan after looking")
    first = (repo / ".results" / "ledger.jsonl").read_text().splitlines()[0]
    by_hand(
        repo,
        plan_commit,
        ledger={"path": ".results/ledger.jsonl", "events": 1, "head": sha256_of_text(first)},
    )
    results("run", "out.json", "--run-id", "late", cwd=repo)
    r = confirm(repo, "late", plan_commit)
    assert r.returncode == 1
    assert f"the ledger as committed at {plan_commit[:12]} already held 2 events" in r.stdout
    assert not claims(repo)


def test_a_run_recorded_before_the_freeze_is_flagged_and_kept(repo):
    results("run", "out.json", "--run-id", "pilot", cwd=repo)
    named = freeze(repo)
    r = confirm(repo, "pilot", named)
    assert r.returncode == 0, r.stdout
    assert "run 'pilot' was recorded before the plan it cites was frozen" in r.stdout
    assert claims(repo)[0]["run_before_freeze"] is True

    v = results("verify", cwd=repo)
    assert v.returncode == 0
    assert "1 confirmatory claim(s) rest on runs recorded before the plan was frozen" in v.stdout


def test_a_run_recorded_after_the_freeze_is_not_flagged(repo):
    named = freeze(repo)
    results("run", "out.json", "--run-id", "main", cwd=repo)
    r = confirm(repo, "main", named)
    assert r.returncode == 0, r.stdout
    assert "recorded before" not in r.stdout
    assert "run_before_freeze" not in claims(repo)[0]
    assert "recorded before the plan was frozen" not in results("verify", cwd=repo).stdout


def test_verify_does_not_take_a_claims_commit_date_for_a_freeze(repo):
    """What an earlier version wrote for `--frozen-at <sha>`: the commit date as the freeze,
    with no record behind it. Verify placed the freeze by that date."""
    results("access", "read the outcomes", "--level", "outcomes seen", cwd=repo)
    results("run", "out.json", "--run-id", "late", cwd=repo)
    results("claim", "d = 0.103", "--run-id", "late", "--confirmatory", "--anyway", cwd=repo)
    lp = repo / ".results" / "ledger.jsonl"
    rows = [json.loads(line) for line in lp.read_text().splitlines()]
    rows[-1] |= {
        "frozen_at": git(repo, "rev-parse", "HEAD"),
        "frozen_at_time": "2025-01-01T00:00:00+00:00",
    }
    rewrite(lp, rows)

    v = results("verify", cwd=repo)
    assert v.returncode == 0, v.stdout
    assert "frozen before outcomes were seen" not in v.stdout
    assert "cite a commit no freeze record names" in v.stdout


def test_a_hand_written_position_with_no_freeze_event_places_nothing(repo):
    """The plan commit predates the ledger, so nothing committed contradicts the position the
    record states; the chain holds no freeze event for it."""
    plan_commit = git(repo, "rev-parse", "HEAD")
    results("run", "out.json", "--run-id", "early", cwd=repo)
    results("access", "read the outcomes", "--level", "outcomes seen", cwd=repo)
    first = (repo / ".results" / "ledger.jsonl").read_text().splitlines()[0]
    by_hand(
        repo,
        plan_commit,
        ledger={"path": ".results/ledger.jsonl", "events": 1, "head": sha256_of_text(first)},
    )
    results("run", "out.json", "--run-id", "late", cwd=repo)
    r = confirm(repo, "late", plan_commit)
    assert r.returncode == 1
    assert "no freeze event in the ledger stands where the record says" in r.stdout
    assert not claims(repo)


def test_a_plan_edited_after_the_outcomes_were_seen_protects_nothing(repo):
    named = freeze(repo)
    results("access", "read the outcomes", "--level", "outcomes seen", cwd=repo)
    results("run", "out.json", "--run-id", "late", cwd=repo)
    plan = repo / "PREREG.md"
    plan.chmod(0o644)
    plan.write_text(PLAN + "\n**H2.** The effect is above 0.1.\n")
    commit(repo, "edit plan")
    r = confirm(repo, "late", named)
    assert r.returncode == 1
    assert "PREREG.md has changed since it was frozen" in r.stdout


def test_verify_fails_a_confirmatory_claim_whose_plan_was_edited_after_the_claim(repo):
    named = freeze(repo)
    results("run", "out.json", "--run-id", "r1", cwd=repo)
    assert confirm(repo, "r1", named).returncode == 0
    commit(repo, "claim")
    assert results("verify", cwd=repo).returncode == 0
    assert tool("prereg", "log", "a note on the run", cwd=repo).returncode == 0
    commit(repo, "log")
    assert results("verify", cwd=repo).returncode == 0

    plan = repo / "PREREG.md"
    plan.chmod(0o644)
    plan.write_text(PLAN + "\n**H2.** The effect is above 0.1.\n")
    commit(repo, "edit plan")
    r = results("verify", cwd=repo)
    assert r.returncode == 1
    assert "confirmatory claim(s) rest on a plan that has changed since it was frozen" in r.stdout
    assert "d = 0.103" in r.stdout and "plan PREREG.md: PREREG.md has changed" in r.stdout
