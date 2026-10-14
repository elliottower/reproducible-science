from __future__ import annotations

import json
import os
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
        "tree": ("results/metrics.json",),
        "delimited": ("results/table.csv",),
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
    assert "candidate bindings, guessed: 4 of the 5 numbers compared agree with one of" in out
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
    assert "2 of the 2 numbers compared" in out
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
    assert any("results/metrics.json was read no further than 2 values" in n for n in found.notes)
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


def test_an_unreadable_manuscript_is_a_note_and_verify_still_exits_2(project, capsys):
    if os.geteuid() == 0:
        pytest.skip("root reads a mode-000 file")
    (project / "paper.md").chmod(0)
    try:
        assert main(["verify"]) == 2
        out = capsys.readouterr().out
    finally:
        (project / "paper.md").chmod(0o644)
    assert "note: paper.md could not be read:" in out
    assert "verified: 0." in out


def test_json_nested_deeper_than_the_interpreter_recurses_is_read(project):
    (project / "results" / "metrics.json").write_text('{"a":' * 3000 + "0.931" + "}" * 3000)
    (project / "results" / "table.csv").unlink()
    found = survey(project)
    (candidate,) = found.candidates
    assert candidate.locator == {"kind": "tree", "pointer": "/a" * 3000}
    assert main(["verify"]) == 2


def test_numbers_in_json_lists_are_read_at_their_index(project):
    (project / "results" / "metrics.json").write_text(
        json.dumps({"runs": [{"acc": 0.9}, {"acc": 0.931}]})
    )
    found = survey(project)
    tree = [c.locator for c in found.candidates if c.locator["kind"] == "tree"]
    assert tree == [{"kind": "tree", "pointer": "/runs/1/acc"}]


def write_table(project, text):
    (project / "results" / "table.csv").write_text(text)
    (project / "results" / "metrics.json").unlink()


def test_an_index_column_and_an_unnamed_one_are_compared_with_nothing_and_named(project):
    rows = "".join(f"{i},{i * 2},{1 / (i + 1):.4f}\n" for i in range(2000))
    write_table(project, ",step,loss\n" + rows)
    (project / "paper.md").write_text("A 12-layer model, 768 units, batch 512; loss 0.0213.\n")
    found = survey(project)
    assert [(c.printed, c.locator["column"]) for c in found.candidates] == [("0.0213", "loss")]
    assert found.skipped_columns == (
        "results/table.csv: a column with no name was compared with nothing",
        "results/table.csv: column step was compared with nothing, as an index: its values "
        "are whole numbers that only increase",
    )
    assert set(found.skipped_columns) <= set(found.notes)


def test_a_column_that_only_decreases_or_repeats_is_still_compared(project):
    write_table(project, "epochs\n100\n100\n100\n")
    (project / "paper.md").write_text("We trained for 100 epochs.\n")
    (candidate,) = survey(project).candidates
    assert (candidate.locator["row"], candidate.more_rows) == (0, 2)


def test_one_number_matching_many_rows_of_a_column_is_one_guess(project, capsys):
    write_table(project, "epochs,f1\n100,0.5\n100,0.6\n100,0.7\n12,0.8\n")
    (project / "paper.md").write_text("We trained for 100 epochs.\n")
    assert main(["verify"]) == 2
    out = capsys.readouterr().out
    assert "results/table.csv column epochs, row 0 holds 100, and 2 more rows" in out
    assert out.count("    guess  ") == 1


def test_guesses_in_json_and_yaml_come_before_guesses_in_tables(project):
    (project / "paper.md").write_text("The AUC was 0.71 and accuracy 0.931.\n")
    kinds = [c.locator["kind"] for c in survey(project).candidates]
    assert kinds == ["tree", "table_position"]


def test_with_the_comparison_cap_reached_the_headline_counts_what_was_compared(
    project, monkeypatch, capsys
):
    monkeypatch.setattr(claims.starter, "MAX_COMPARISONS", 20)
    (project / "paper.md").write_text(" ".join(f"{i}.5" for i in range(10, 60)) + "\n")
    assert main(["verify"]) == 2
    out = capsys.readouterr().out
    # Four values are held, so the cap allows five numbers.
    assert "guessed: 0 of the 5 numbers compared" in out
    assert "45 of the 50 numbers paper.md prints were not compared" in out


def test_json_names_its_schema_keys_formats_by_a_stable_key_and_holds_no_absolute_path(
    project, capsys
):
    assert main(["verify", "--format", "json"]) == 2
    text = capsys.readouterr().out
    document = json.loads(text)
    assert document["schema_version"] == "reproducible.science/survey/0.1-experimental"
    assert set(document["survey"]["results"]) == {"tree", "delimited"}
    assert "root" not in document["survey"]
    assert str(project) not in text


def test_a_delimited_file_is_read_no_further_than_the_value_cap(project, monkeypatch):
    # Bytes that are not UTF-8 far past the first rows: a reader that reads the whole file
    # refuses it, and one that stops at the cap never reaches them.
    rows = "".join(f"run{i},0.{i:05d}\n" for i in range(20_000)).encode()
    (project / "results" / "table.csv").write_bytes(b"model,auc\n" + rows + b"\xff\xfe\n")
    monkeypatch.setattr(claims.starter, "MAX_VALUES_PER_FILE", 10**6)
    whole = survey(project)
    assert any(n.startswith("results/table.csv could not be read") for n in whole.notes)
    monkeypatch.setattr(claims.starter, "MAX_VALUES_PER_FILE", 10)
    cut = survey(project)
    assert cut.cut == ("results/table.csv",)
    assert not any("could not be read" in n for n in cut.notes)
    assert "results/table.csv was read no further than 10 values" in " ".join(cut.notes)
