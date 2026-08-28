from __future__ import annotations

import decimal
import hashlib
import json
import shutil
import subprocess
import sys

import pytest
from repro.demo import (
    OWNED,
    PAPER_MD,
    REPORTED_NUMBER,
    UNREAD_WORD,
    _run,
    scaffold,
)
from repro.exceptions import ReproError


def run_repro(*args: str, cwd=None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "repro", *args], cwd=cwd, capture_output=True, text=True
    )


def run_script(name: str, cwd) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, name], cwd=cwd, capture_output=True, text=True)


def verify(cwd) -> tuple[int, dict]:
    """The report as data, so a test asserts on the three stages rather than on a rendering."""
    result = run_repro("verify", "--format", "json", cwd=cwd)
    return result.returncode, json.loads(result.stdout)


def decisions(payload: dict) -> list[dict]:
    return [d for claim in payload["report"]["claims"] for d in claim["decisions"]]


def problems(payload: dict) -> list[str]:
    """The rules a policy graded above `ignore`.

    A policy records every violation it considered, `ignore` included, so an unrequested
    regeneration appears in the list of a run that passed with nothing wrong with it.
    """
    return [v["rule"] for v in payload["assessment"]["violations"] if v["severity"] != "ignore"]


def validity(payload: dict, artifact_id: str) -> str:
    return next(
        a["validity"] for a in payload["report"]["artifacts"] if a["artifact_id"] == artifact_id
    )


def edit(path, old: str, new: str) -> None:
    text = path.read_text()
    assert old in text
    path.write_text(text.replace(old, new, 1))


def project(tmp_path):
    """A scaffolded demo with the analysis run and the manifest pinned."""
    target = tmp_path / "demo"
    scaffold(target)
    assert run_script("analysis.py", target).returncode == 0
    assert run_script("pin.py", target).returncode == 0
    return target


def test_scaffold_refuses_a_directory_that_already_holds_files(tmp_path):
    target = tmp_path / "demo"
    target.mkdir()
    (target / "notes.md").write_text("mine")

    with pytest.raises(ReproError):
        scaffold(target)
    assert (target / "notes.md").read_text() == "mine"
    assert not (target / "analysis.py").exists()


def test_scaffold_refuses_a_path_that_is_not_a_directory(tmp_path):
    target = tmp_path / "demo"
    target.write_text("a file someone already has here")

    with pytest.raises(ReproError):
        scaffold(target, force=True)
    assert target.read_text() == "a file someone already has here"


def test_force_replaces_the_demo_files_and_leaves_the_rest_alone(tmp_path):
    target = tmp_path / "demo"
    scaffold(target)
    (target / "notes.md").write_text("mine")
    (target / "analysis.py").write_text("raise SystemExit(1)")

    scaffold(target, force=True)

    assert (target / "notes.md").read_text() == "mine"
    assert "bootstrap_interval" in (target / "analysis.py").read_text()


def test_force_clears_the_ledger_so_a_second_walkthrough_records_a_fresh_run(tmp_path):
    target = tmp_path / "demo"
    scaffold(target)
    (target / ".results").mkdir()
    (target / ".results" / "ledger.jsonl").write_text("{}\n")

    scaffold(target, force=True)

    assert not (target / ".results").exists()
    assert {name for name in OWNED if (target / name).exists()} == {
        "README.md",
        "analysis.py",
        "data.csv",
        "paper.md",
        "pin.py",
    }


def test_the_scaffolded_project_verifies_clean(tmp_path):
    target = project(tmp_path)

    code, payload = verify(target)

    assert code == 0, payload
    assert payload["assessment"]["passed"] is True
    assert problems(payload) == []
    assert {a["validity"] for a in payload["report"]["artifacts"]} == {"authoritative"}
    assert [d["comparison"] for d in decisions(payload)] == ["match", "match", "match"]
    assert sorted(d["kind"] for d in decisions(payload)) == ["correspondence", "metric", "quote"]


def test_the_manuscript_reports_the_number_the_analysis_computes(tmp_path):
    target = project(tmp_path)

    delta = decimal.Decimal(
        str(json.loads((target / "results.json").read_text())["effect"]["delta"])
    )
    printed = decimal.Decimal(REPORTED_NUMBER[0].split()[1])

    # The manuscript states the effect as a literal, so a template edited without re-running the
    # analysis would ship a demo whose first `repro verify` fails. Rounded to the precision the
    # manuscript prints, which is the comparison the correspondence performs.
    assert delta.quantize(printed, rounding=decimal.ROUND_HALF_EVEN) == printed
    assert REPORTED_NUMBER[0] in (target / "paper.md").read_text()
    assert UNREAD_WORD[0] in (target / "paper.md").read_text()


def test_the_analysis_produces_the_same_bytes_twice(tmp_path):
    target = project(tmp_path)
    first = hashlib.sha256((target / "results.json").read_bytes()).hexdigest()

    assert run_script("analysis.py", target).returncode == 0

    assert hashlib.sha256((target / "results.json").read_bytes()).hexdigest() == first


def test_a_broken_pin_and_a_mismatch_are_different_failures(tmp_path):
    target = project(tmp_path)

    # A word no assertion reads. Every comparison still matches and the run fails anyway, on
    # the pin alone.
    edit(target / "paper.md", *UNREAD_WORD)
    code, pinned = verify(target)
    assert code == 1
    assert validity(pinned, "paper") == "broken_pin"
    assert {d["comparison"] for d in decisions(pinned)} == {"match"}
    assert problems(pinned) == ["artifact.pin"]

    # Re-pinning accepts the edit, which is what isolates the second failure from the first.
    assert run_script("pin.py", target).returncode == 0
    assert verify(target)[0] == 0

    edit(target / "paper.md", *REPORTED_NUMBER)
    assert run_script("pin.py", target).returncode == 0
    code, mismatched = verify(target)

    assert code == 1
    assert {a["validity"] for a in mismatched["report"]["artifacts"]} == {"authoritative"}
    correspondence = next(d for d in decisions(mismatched) if d["kind"] == "correspondence")
    # The three stages, not the flattened word: the check ran, both sides extracted, and the
    # comparison is what failed. A missing extractor or an unresolvable pointer would reach the
    # same `not_found`/`unchecked` line in a report that collapsed them.
    assert correspondence["execution"] == "completed"
    assert correspondence["extraction"] == "extracted"
    assert correspondence["comparison"] == "mismatch"
    assert correspondence["reason"] == "value_mismatch"
    assert [side["extracted"] for side in correspondence["sides"]] == ["0.055", "0.0453"]
    assert problems(mismatched) == ["evidence.mismatch"]


def test_the_walkthrough_runs_both_failures_and_leaves_the_project_verifying(tmp_path):
    result = run_repro("demo", str(tmp_path / "demo"))

    assert result.returncode == 0, result.stdout + result.stderr
    # Both strings come from `repro verify`, not from the walkthrough's own prose: a demo that
    # narrated its failures without producing them would print neither.
    assert "BROKEN PIN  paper: pinned" in result.stdout
    assert "MISS  effect-size  correspondence" in result.stdout
    assert result.stdout.count("[exit 1]") == 2

    assert verify(tmp_path / "demo")[0] == 0
    # Byte-identical to what was scaffolded: the README tells a reader to edit two literals in
    # this file, and a walkthrough that left one of its own edits behind would leave one of
    # those instructions naming text that is no longer there.
    assert (tmp_path / "demo" / "paper.md").read_text() == PAPER_MD


def test_the_walkthrough_refuses_a_directory_it_did_not_write(tmp_path):
    target = tmp_path / "demo"
    target.mkdir()
    (target / "notes.md").write_text("mine")

    result = run_repro("demo", str(target))

    assert result.returncode == 2
    assert "--force" in result.stdout
    assert not (target / "repro.yaml").exists()


def test_a_tool_that_is_not_installed_is_reported_rather_than_raised(tmp_path, capsys):
    # The one branch no installation of this package can reach, since every tool the
    # walkthrough drives is a declared dependency. Asserting it here is the only way it is
    # asserted at all.
    code = _run(["repro-demo-no-such-command"], tmp_path, "results init")

    assert code == 127
    assert "is not installed" in capsys.readouterr().out


@pytest.mark.skipif(shutil.which("python3") is None, reason="the declared command names python3")
def test_the_declared_regeneration_reproduces_the_pinned_results(tmp_path):
    target = project(tmp_path)

    result = run_repro("verify", "--regenerate", "--format", "json", cwd=target)
    payload = json.loads(result.stdout)

    assert result.returncode == 0
    assert [r["state"] for r in payload["report"]["regenerations"]] == ["reproduced"]
