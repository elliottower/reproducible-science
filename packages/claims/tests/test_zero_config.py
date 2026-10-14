from __future__ import annotations

import json
import os
import subprocess

import claims.starter
import pytest
from claims.adapters.tree import Written
from claims.cli import main
from claims.models import Conversion, Manifest, Outcome
from claims.starter import _numbers, _pins, survey
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
    assert (
        "results/metrics.json holds more than 2 numbers; the first 2 were compared" in found.notes
    )
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


def test_the_walk_over_a_tree_reaches_a_number_deeper_than_python_recurses():
    tree: object = Written("0.931")
    for _ in range(5000):
        tree = {"a": tree}
    assert list(_numbers(tree)) == [("/a" * 5000, "0.931")]


def test_json_nested_3000_deep_is_read_or_is_a_note_and_verify_exits_2(project, capsys):
    (project / "results" / "metrics.json").write_text('{"a":' * 3000 + "0.931" + "}" * 3000)
    (project / "results" / "table.csv").unlink()
    found = survey(project)
    # Python 3.11 decodes JSON recursively and refuses this depth; 3.12 and later read it.
    read = [c.locator for c in found.candidates] == [{"kind": "tree", "pointer": "/a" * 3000}]
    noted = any(n.startswith("results/metrics.json could not be read") for n in found.notes)
    assert read != noted
    assert main(["verify"]) == 2
    assert "verified: 0." in capsys.readouterr().out


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
    assert "results/table.csv holds more than 10 numbers; the first 10 were compared" in cut.notes


COHORT = (
    "wave,followup_years,n_enrolled,cumulative_events,dose_mg,hazard\n"
    "1,1,1204,37,10,0.91\n2,2,1388,81,20,0.87\n3,5,1502,143,40,0.81\n4,10,1650,212,80,0.74\n"
)


def test_columns_that_only_increase_are_compared_like_any_other(project, capsys):
    write_table(project, COHORT)
    (project / "paper.md").write_text(
        "By ten years of follow-up, 212 events had accrued among 1,650 participants; at 80 mg "
        "the hazard ratio was 0.74, and 143 events by year 5.\n"
    )
    found = survey(project)
    assert found.index_like == ()
    assert [(c.printed, c.locator["column"]) for c in found.candidates] == [
        ("212", "cumulative_events"),
        ("1,650", "n_enrolled"),
        ("80", "dose_mg"),
        ("0.74", "hazard"),
        ("143", "cumulative_events"),
    ]
    assert main(["verify"]) == 2
    assert "guessed: 5 of the 5 numbers compared" in capsys.readouterr().out


def test_a_column_named_for_an_index_is_listed_last_tagged_and_counted_apart(project, capsys):
    rows = "".join(f"{i},{seed},{1 / (i + 1):.4f}\n" for i, seed in enumerate((3, 12, 5, 9, 1)))
    write_table(project, ",seed,loss\n" + rows)
    (project / "paper.md").write_text("Over 12 runs; loss 0.3333 at seed 4.\n")
    found = survey(project)
    assert found.index_like == (
        "results/table.csv column (no name)",
        "results/table.csv column seed",
    )
    assert [(c.printed, c.index_like) for c in found.candidates] == [
        ("0.3333", False),
        ("12", True),
    ]
    assert main(["verify"]) == 2
    out = capsys.readouterr().out
    assert "guessed: 1 of the 2 numbers compared" in out
    assert "and 1 more number agrees only with index-like columns or keys, listed last." in out
    assert "results/table.csv column seed, row 1 holds 12  [index-like column]" in out
    assert out.count("[index-like column]") == 1


def test_a_column_stepping_by_a_constant_over_ten_rows_is_index_like_and_not_hidden(project):
    rows = "".join(f"{5 * i},{0.5 + i * i / 1000:.3f}\n" for i in range(12))
    write_table(project, "minute,acc\n" + rows)
    (project / "paper.md").write_text("At minute 45 accuracy was 0.581.\n")
    found = survey(project)
    assert found.index_like == ("results/table.csv column minute",)
    kinds = [(c.locator["column"], c.index_like) for c in found.candidates]
    assert kinds == [("acc", False), ("minute", True)]


def test_a_constant_step_over_fewer_than_ten_rows_is_not_index_like(project):
    write_table(project, "minute,acc\n" + "".join(f"{5 * i},0.5\n" for i in range(9)))
    assert survey(project).index_like == ()


def test_one_number_in_many_rows_is_one_guess_whose_place_holds_it_exactly(project, capsys):
    write_table(project, "model,auc\nlasso,0.708\nridge,0.71\nrf,0.712\n")
    (project / "paper.md").write_text("The AUC was 0.71.\n")
    (candidate,) = survey(project).candidates
    assert (candidate.locator["row"], candidate.stored) == (1, "0.71")
    assert [(a.locator["row"], a.stored) for a in candidate.also] == [(0, "0.708"), (2, "0.712")]
    assert main(["verify"]) == 2
    out = capsys.readouterr().out
    assert "column auc, row 1 holds 0.71; rows 0, 2 hold 0.708 and 0.712" in out
    assert out.count("    guess  ") == 1


def test_rows_holding_the_same_value_are_said_to(project, capsys):
    write_table(project, "epochs,f1\n100,0.5\n100,0.6\n100,0.7\n12,0.8\n")
    (project / "paper.md").write_text("We trained for 100 epochs.\n")
    assert main(["verify"]) == 2
    assert "column epochs, row 0 holds 100; rows 1, 2 hold the same" in capsys.readouterr().out


def test_a_key_repeated_across_list_elements_is_grouped_and_an_index_name_demoted(project):
    history = [{"step": i, "loss": round(1 / (i + 1), 4)} for i in range(800)]
    history[3]["loss"] = 0.25
    history[9]["loss"] = 0.25
    (project / "results" / "metrics.json").write_text(json.dumps({"history": history}))
    (project / "results" / "table.csv").unlink()
    (project / "paper.md").write_text("A model at 512 steps; loss 0.25.\n")
    found = survey(project)
    assert found.index_like == ("results/metrics.json /history/*/step",)
    assert [(c.locator["pointer"], c.index_like) for c in found.candidates] == [
        ("/history/3/loss", False),
        ("/history/512/step", True),
    ]
    (loss, _) = found.candidates
    assert [a.locator["pointer"] for a in loss.also] == ["/history/9/loss"]


def test_list_values_stepping_by_a_constant_are_index_like(project):
    (project / "results" / "metrics.json").write_text(
        json.dumps({"epochs": list(range(10, 130, 10)), "acc": 0.931})
    )
    found = survey(project)
    assert found.index_like == ("results/metrics.json /epochs/*",)
    assert not next(c for c in found.candidates if c.stored == "0.931").index_like


def test_a_long_pointer_is_shortened_in_text_and_whole_in_json(project, capsys):
    key = "k" * 100
    (project / "results" / "metrics.json").write_text(json.dumps({key: {"accuracy": 0.9312}}))
    assert main(["verify"]) == 2
    text = capsys.readouterr().out
    assert f"/{key}/accuracy" not in text
    assert "..." in next(line for line in text.splitlines() if "holds 0.9312" in line)
    assert main(["verify", "--format", "json"]) == 2
    document = json.loads(capsys.readouterr().out)
    pointers = [c["locator"].get("pointer") for c in document["survey"]["candidates"]]
    assert f"/{key}/accuracy" in pointers


def test_an_unreadable_directory_under_results_is_a_note(project):
    if os.geteuid() == 0:
        pytest.skip("root lists a mode-000 directory")
    locked = project / "results" / "locked"
    locked.mkdir()
    (locked / "z.json").write_text('{"x": 0.71}')
    locked.chmod(0)
    try:
        found = survey(project)
    finally:
        locked.chmod(0o755)
    assert "results/locked/ could not be listed" in found.notes


def test_no_note_holds_an_absolute_path(project):
    (project / "results" / "metrics.json").write_bytes(b"\xff\xfe")
    found = survey(project)
    assert any(n.startswith("results/metrics.json could not be read") for n in found.notes)
    assert not any(str(project) in n or str(project.resolve()) in n for n in found.notes)


def test_a_mapping_key_named_for_an_index_is_demoted_at_any_depth(project, capsys):
    (project / "results" / "metrics.json").write_text(
        json.dumps({"seed": 42, "run": {"epoch": 12, "accuracy": 0.9312, "epochs": 100}})
    )
    (project / "results" / "table.csv").unlink()
    (project / "paper.md").write_text("Seed 42, 12 epochs of 100; accuracy 0.931.\n")
    found = survey(project)
    assert found.index_like == ("results/metrics.json /seed", "results/metrics.json /run/epoch")
    assert [(c.locator["pointer"], c.index_like) for c in found.candidates] == [
        ("/run/epochs", False),
        ("/run/accuracy", False),
        ("/seed", True),
        ("/run/epoch", True),
    ]
    assert main(["verify"]) == 2
    out = capsys.readouterr().out
    assert "guessed: 2 of the 4 numbers compared" in out
    assert "and 2 more numbers agree only with index-like columns or keys" in out
    assert "results/metrics.json /seed holds 42  [index-like key]" in out


def test_a_name_is_index_like_only_as_a_whole_word(project):
    (project / "results" / "metrics.json").write_text(
        json.dumps(
            {
                "id_acc": 0.912,
                "step_size": 0.003,
                "gini_index": 0.412,
                "row_count": 1234,
                "Global-Step": 4000,
                "ID": 77,
            }
        )
    )
    (project / "results" / "table.csv").unlink()
    (project / "paper.md").write_text("0.912, 0.003, 0.412, 1,234 rows, 4,000 steps, run 77.\n")
    found = survey(project)
    demoted = {c.locator["pointer"] for c in found.candidates if c.index_like}
    assert demoted == {"/Global-Step", "/ID"}
    assert len(found.candidates) == 6


def test_a_counter_that_starts_again_for_each_run_is_index_like(project):
    rows = "".join(
        f"r{run},{5 * i},{0.5 + i * i / 997:.4f}\n" for run in range(3) for i in range(30)
    )
    write_table(project, "run,minute,acc\n" + rows)
    history = [{"history": [{"minute": 5 * i, "acc": i * i / 997} for i in range(30)]}] * 3
    (project / "results" / "metrics.json").write_text(json.dumps({"runs": history}))
    found = survey(project)
    assert found.index_like == (
        "results/metrics.json /runs/*/history/*/minute",
        "results/table.csv column minute",
    )


def test_a_metric_that_rises_by_a_constant_amount_is_not_index_like(project):
    write_table(project, "acc\n" + "".join(f"{0.5 + i / 100:.2f}\n" for i in range(20)))
    assert survey(project).index_like == ()


def test_one_other_place_is_said_in_the_singular(project, capsys):
    write_table(project, "model,auc,seed\nlasso,0.71,3\nridge,0.71,12\n")
    (project / "paper.md").write_text("The AUC was 0.71 over 12 runs.\n")
    assert main(["verify"]) == 2
    out = capsys.readouterr().out
    assert "column auc, row 0 holds 0.71; row 1 holds the same" in out
    assert "and 1 more number agrees only with index-like columns or keys" in out
    (project / "results" / "table.csv").unlink()
    history = [{"acc": 0.52}, {"acc": 0.523}]
    (project / "results" / "metrics.json").write_text(json.dumps({"history": history}))
    (project / "paper.md").write_text("Accuracy was 0.52.\n")
    assert main(["verify"]) == 2
    assert "/history/0/acc holds 0.52; 1 more list element holds 0.523" in capsys.readouterr().out


def test_a_printed_unit_suffix_is_not_scaled(project):
    (project / "results" / "metrics.json").write_text(json.dumps({"params": 25557032}))
    (project / "results" / "table.csv").unlink()
    (project / "paper.md").write_text("ResNet-50 has 25.6M parameters.\n")
    assert survey(project).candidates == ()
