from __future__ import annotations

import json
import subprocess

import claims.starter
import pytest
from claims.cli import main
from claims.models import Conversion, Manifest, Outcome
from claims.starter import _pins, survey
from claims.verify import verify

PAPER = (
    "# Results\n\n"
    "In 2024 we fit the lasso to 480 participants.\n"
    "Held-out accuracy was 0.931, and the error rate was 4.3% (Table 2).\n"
    "We ran 3 seeds; the AUC was 0.71, not 0.55.\n"
)


@pytest.fixture
def project(tmp_path, monkeypatch):
    # A hook sets `GIT_DIR`, which outranks the directory a git command is run in.
    for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
        monkeypatch.delenv(name, raising=False)
    root = tmp_path / "study"
    (root / "results").mkdir(parents=True)
    (root / "results" / "metrics.json").write_text(
        json.dumps({"model": "lasso", "scores": {"accuracy": 0.9312, "n": 480, "rate": 0.0426}})
    )
    (root / "results" / "table.csv").write_text("model,auc\nlasso,0.71\n")
    (root / "paper.md").write_text(PAPER)
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    monkeypatch.chdir(root)
    return root


def snapshot(root):
    return {
        path.relative_to(root).as_posix(): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_a_printed_number_that_a_result_file_holds_is_a_candidate_and_no_other_is(project):
    found = survey(project)
    assert found.results == {
        "JSON and YAML": ("results/metrics.json",),
        "CSV, TSV and PSV": ("results/table.csv",),
    }
    assert found.manuscript == "paper.md"
    bound = {
        (c.printed, c.path, tuple(c.locator.values()), c.stored, c.conversion)
        for c in found.candidates
    }
    assert bound == {
        ("480", "results/metrics.json", ("tree", "/scores/n"), "480", None),
        ("0.931", "results/metrics.json", ("tree", "/scores/accuracy"), "0.9312", None),
        ("4.3%", "results/metrics.json", ("tree", "/scores/rate"), "0.0426", Conversion.PERCENT),
        ("0.71", "results/table.csv", ("table_position", "auc", 0), "0.71", None),
    }
    # 0.55 agrees with nothing stored; 2024 is a year, 2 a table's label, 3 a single digit.
    assert found.compared == 5
    assert found.read_from == ("results/metrics.json", "results/table.csv")
    assert [c.line for c in found.candidates] == [3, 4, 4, 5]


def test_every_candidate_is_one_the_engine_verifies_when_declared(project):
    found = survey(project)
    assert found.candidates
    for c in found.candidates:
        pins = _pins([project / c.path], project)
        evidence = {
            "kind": "value",
            "artifact": pins[0]["id"],
            "name": "n",
            "reported": c.printed.rstrip("%"),
            "locator": c.locator,
            **({"conversion": c.conversion.value} if c.conversion else {}),
        }
        claim = {"id": "c", "text": c.context, "evidence": [evidence]}
        trial = Manifest.model_validate(
            {"artifacts": pins, "claims": [claim], "path": project / "repro.yaml"}
        )
        assert [d.outcome for d in verify(trial).decisions] == [Outcome.VERIFIED]


def test_a_number_that_disagrees_at_the_printed_precision_is_not_a_candidate(project):
    (project / "paper.md").write_text("Held-out accuracy was 0.932 over 481 people.\n")
    found = survey(project)
    assert found.compared == 2
    assert found.candidates == ()


def test_verify_with_no_manifest_reports_guesses_verifies_nothing_and_exits_2(project, capsys):
    assert main(["verify"]) == 2
    out = capsys.readouterr().out
    assert out.startswith("no repro.yaml here or above.\n")
    assert out.rstrip().endswith("    claims manifest init")
    assert "candidate bindings, guessed: 4 of the 5 numbers paper.md prints agree" in out
    assert "results/metrics.json /scores/accuracy holds 0.9312" in out
    assert "results/table.csv column auc, row 0 holds 0.71" in out
    assert "verified: 0." in out
    guesses = [line for line in out.splitlines() if "holds" in line]
    assert len(guesses) == 4
    assert all(line.lstrip().startswith("guess") for line in guesses)
    assert "passed" not in out
    assert "ok  " not in out


def test_verify_with_no_manifest_writes_nothing(project, capsys):
    before = snapshot(project)
    assert main(["verify"]) == 2
    assert "candidate bindings, guessed" in capsys.readouterr().out
    assert snapshot(project) == before


def test_with_every_printed_number_matching_verify_still_does_not_pass(project, capsys):
    (project / "paper.md").write_text("Held-out accuracy was 0.931 over 480 people.\n")
    assert main(["verify"]) == 2
    out = capsys.readouterr().out
    assert "2 of the 2 numbers" in out
    assert "passed" not in out


def test_with_nothing_to_find_verify_says_so_and_exits_2(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert main(["verify"]) == 2
    out = capsys.readouterr().out
    assert "  result files: 0\n  manuscript: none found\n" in out
    assert "candidate bindings: none, because there is no manuscript to compare" in out


def test_json_with_no_manifest_is_one_document_that_verifies_nothing(project, capsys):
    before = snapshot(project)
    assert main(["verify", "--format", "json"]) == 2
    document = json.loads(capsys.readouterr().out)
    assert document["manifest"] is None
    assert document["verified"] == 0
    assert {c["stored"] for c in document["survey"]["candidates"]} == {
        "480",
        "0.9312",
        "0.0426",
        "0.71",
    }
    assert snapshot(project) == before


def test_sarif_with_no_manifest_holds_no_result_and_no_pass(project, capsys):
    assert main(["verify", "--format", "sarif"]) == 2
    (run,) = json.loads(capsys.readouterr().out)["runs"]
    assert run["results"] == []
    assert len(run["properties"]["survey"]["candidates"]) == 4
    (notification,) = run["invocations"][0]["toolExecutionNotifications"]
    assert notification["level"] == "warning"
    assert "nothing was verified" in notification["message"]["text"]


def test_a_file_over_the_value_cap_is_cut_and_said_to_be(project, monkeypatch):
    monkeypatch.setattr(claims.starter, "MAX_VALUES_PER_FILE", 2)
    found = survey(project)
    assert found.cut == ("results/metrics.json",)
    assert found.values == 2 + 1
    assert any("results/metrics.json holds more than 2 numbers" in n for n in found.notes)
    # /scores/rate is the third number, so the percentage is no longer found.
    assert "0.0426" not in {c.stored for c in found.candidates}


def test_comparisons_stop_at_the_cap_and_say_how_many_were_not_made(project, monkeypatch):
    # Four values are held, so each number printed without a percent sign costs four.
    monkeypatch.setattr(claims.starter, "MAX_COMPARISONS", 4)
    found = survey(project)
    assert (found.compared, found.not_compared) == (1, 4)
    assert [c.printed for c in found.candidates] == ["480"]
    assert any(
        "4 of the 5 numbers the manuscript prints were not compared" in n for n in found.notes
    )
