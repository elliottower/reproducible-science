"""A CORE-Bench capsule and its task, read into a draft manifest and its open items.

The capsule and the task are written in the test, in the shape the benchmark's task files
have (`capsule_id`, `capsule_title`, `capsule_doi`, and `results`, one mapping of question to
value per run), and are of no real capsule. Nothing in a capsule is run.
"""

from __future__ import annotations

import hashlib
import json

import pytest
import yaml
from claims.cli import main
from claims.manifest import load
from claims.models import Basis
from claims.open_items import DRAFT_NAME, ITEMS_NAME, ClaimState, Need, read, tally
from claims.sources import corebench
from claims.sources.corebench import CorebenchError, from_corebench

METRICS = (
    '{"auc": {"had": 0.9375660604380387, "l1": 0.91}, "layers": 3, "epochs": 7, "fitted": true}\n'
)
TABLE = "model,acc\nlasso,0.813\nridge,3.2\n"

AUC = "Report the average AUC score of Had."
ACCURACY = "Report the accuracy of lasso."
RIDGE = "Report the accuracy of ridge."
LAYERS = "How many layers does the model have?"
EPOCHS = "How many epochs was the model trained for?"
LABEL = "Report the x-axis label of the power plot."

# Written as text, so the task states `0.8130` with its trailing zero, as a task file can. The
# ridge question is given lasso's value: one match, under a label the question does not name.
TASKS = (
    "["
    '{"capsule_id": "capsule-0000002", "results": [{"q": 1}]},'
    '{"capsule_id": "capsule-0000001", "capsule_title": "An invented capsule",'
    ' "capsule_doi": "https://doi.org/10.5555/invented",'
    f' "results": [{{"{AUC}": 0.9375660604380387, "{ACCURACY}": 0.8130, "{RIDGE}": 0.8130,'
    f' "{LAYERS}": 3, "{EPOCHS}": 7, "{LABEL}": "Power"}}]}}'
    "]"
)


def capsule(root, metrics: str = METRICS):
    (root / "results").mkdir(parents=True)
    (root / "code").mkdir()
    (root / "results" / "metrics.json").write_text(metrics)
    (root / "results" / "table.csv").write_text(TABLE)
    (root / "results" / "log.txt").write_text("AUC 0.94\n")
    (root / "results" / "plot.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (root / "code" / "run.py").write_text("raise SystemExit('never run')\n")
    return root


def read_capsule(tmp_path, tasks: str = TASKS, metrics: str = METRICS):
    folder = capsule(tmp_path / "capsule-0000001", metrics)
    (tmp_path / "tasks.json").write_text(tasks)
    written = from_corebench(folder, tmp_path / "tasks.json", tmp_path / "out")
    return written, {item.claim: item for item in read(tmp_path / "out" / ITEMS_NAME).items}


def evidence_of(tmp_path) -> dict:
    manifest = load(tmp_path / "out" / DRAFT_NAME)
    return {claim.text: claim.evidence for claim in manifest.claims}


def test_result_files_are_pinned_and_each_question_is_a_claim_with_its_text(tmp_path):
    written, _ = read_capsule(tmp_path)

    manifest = load(tmp_path / "out" / DRAFT_NAME)
    assert {a.id: a.digest.value for a in manifest.artifacts} == {
        "results/log.txt": hashlib.sha256(b"AUC 0.94\n").hexdigest(),
        "results/metrics.json": hashlib.sha256(METRICS.encode()).hexdigest(),
        "results/table.csv": hashlib.sha256(TABLE.encode()).hexdigest(),
    }
    assert [(p.file, p.reason) for p in written.passed_over] == [
        ("results/plot.png", "a format no backend reads")
    ]
    assert [claim.text for claim in manifest.claims] == [
        AUC,
        ACCURACY,
        RIDGE,
        LAYERS,
        EPOCHS,
        LABEL,
    ]
    assert manifest.project == "An invented capsule"
    assert manifest.provenance.repository == "https://doi.org/10.5555/invented"


def test_a_specific_value_at_one_address_is_a_unique_candidate_and_is_never_written(tmp_path):
    _, items = read_capsule(tmp_path)

    assert all(evidence == () for evidence in evidence_of(tmp_path).values())
    auc = items["report-the-average-auc-score-of-had"]
    assert (auc.unique, auc.reason) == (True, "")
    assert [
        (c["artifact"], c["locator"]["pointer"], c["reported"], c["basis"]) for c in auc.candidates
    ] == [("results/metrics.json", "/auc/had", "0.9375660604380387", "inferred")]
    accuracy = items["report-the-accuracy-of-lasso"]
    assert accuracy.unique
    first = accuracy.candidates[0]
    assert (first["locator"]["column"], first["locator"]["row"], first["reported"]) == (
        "acc",
        0,
        "0.8130",
    )


def test_the_same_value_at_two_addresses_is_not_unique(tmp_path):
    folder = capsule(tmp_path / "capsule-0000001")
    (folder / "results" / "other.json").write_text('{"auc": {"had": 0.9375660604380387}}\n')
    (tmp_path / "tasks.json").write_text(TASKS)
    from_corebench(folder, tmp_path / "tasks.json", tmp_path / "out")
    items = {item.claim: item for item in read(tmp_path / "out" / ITEMS_NAME).items}

    assert evidence_of(tmp_path)[AUC] == ()
    auc = items["report-the-average-auc-score-of-had"]
    assert not auc.unique
    assert auc.reason == "2 addresses pass the guards, not one"
    assert {c["artifact"] for c in auc.candidates} == {"results/metrics.json", "results/other.json"}


def test_a_small_integer_at_one_address_is_not_unique(tmp_path):
    _, items = read_capsule(tmp_path)

    assert evidence_of(tmp_path)[EPOCHS] == ()
    epochs = items["how-many-epochs-was-the-model-trained-for"]
    assert [c["locator"]["pointer"] for c in epochs.candidates] == ["/epochs"]
    assert not epochs.unique
    assert "fewer than 3 significant digits" in epochs.reason


def test_an_integer_answer_matches_every_stored_value_that_rounds_to_it(tmp_path):
    _, items = read_capsule(tmp_path)

    layers = items["how-many-layers-does-the-model-have"]
    found = {(c["artifact"], json.dumps(c["locator"], sort_keys=True)) for c in layers.candidates}
    assert found == {
        ("results/metrics.json", json.dumps({"contract": 1, "kind": "tree", "pointer": "/layers"})),
        (
            "results/table.csv",
            json.dumps(
                {
                    "column": "acc",
                    "contract": 1,
                    "delimiter": "",
                    "kind": "table_position",
                    "row": 1,
                }
            ),
        ),
    }


def test_a_label_the_address_does_not_carry_is_not_unique(tmp_path):
    _, items = read_capsule(tmp_path)

    assert evidence_of(tmp_path)[RIDGE] == ()
    ridge = items["report-the-accuracy-of-ridge"]
    # One match, specific enough, and in lasso's row of a question about ridge.
    assert [(c["locator"]["column"], c["locator"]["row"]) for c in ridge.candidates] == [("acc", 0)]
    assert not ridge.unique
    assert ridge.reason == "the question names a label or a split no matching address carries"


def test_a_key_label_the_question_names_otherwise_is_not_unique(tmp_path):
    tasks = json.dumps(
        [{"capsule_id": "capsule-0000001", "results": [{"Report the L1 AUC score.": 0.9376}]}]
    )
    metrics = '{"auc": {"had": 0.93756, "l1": 0.5}}\n'
    _, items = read_capsule(tmp_path, tasks, metrics)

    item = items["report-the-l1-auc-score"]
    assert [c["locator"]["pointer"] for c in item.candidates] == ["/auc/had"]
    assert not item.unique
    assert item.reason == "the question names a label or a split no matching address carries"


def test_an_answer_that_is_not_a_number_asks_for_a_passage(tmp_path):
    _, items = read_capsule(tmp_path)

    label = items["report-the-x-axis-label-of-the-power-plot"]
    assert label.need is Need.PASSAGE
    assert label.candidates == ()
    assert label.context["values"] == ["Power"]


def test_runs_that_disagree_give_no_candidate(tmp_path):
    tasks = json.dumps(
        [{"capsule_id": "capsule-0000001", "results": [{AUC: 0.9375660604380387}, {AUC: 0.91}]}]
    )
    _, items = read_capsule(tmp_path, tasks)

    auc = items["report-the-average-auc-score-of-had"]
    assert auc.candidates == ()
    assert (auc.unique, auc.reason) == (False, "the runs disagree, so no one value is the task's")
    assert auc.context["values"] == ["0.9375660604380387", "0.91"]


def test_the_tally_counts_candidates_and_then_an_agents_fill(tmp_path):
    _, items = read_capsule(tmp_path)
    found = tally(tmp_path / "out" / ITEMS_NAME)
    assert found.claims[ClaimState.READER] == 0
    assert found.claims[ClaimState.OPEN] == 6
    assert {key: found.items[key] for key in (
        "with_unique_candidate", "with_several_candidates", "with_one_not_unique",
        "with_no_candidate",
    )} == {
        "with_unique_candidate": 2,  # AUC, accuracy of lasso
        "with_several_candidates": 1,  # layers: 3 matches /layers and 3.2
        "with_one_not_unique": 2,  # epochs: a small integer; ridge: lasso's row
        "with_no_candidate": 1,  # the axis label, which is not a number
    }  # fmt: skip

    # An agent fills the AUC item with its unique candidate, marked inferred as it must be.
    path = tmp_path / "out" / DRAFT_NAME
    document = yaml.safe_load(path.read_text())
    auc = items["report-the-average-auc-score-of-had"]
    claim = next(c for c in document["claims"] if c["id"] == auc.claim)
    claim["evidence"] = [auc.candidates[0]]
    path.write_text(yaml.safe_dump(document, sort_keys=False))

    found = tally(tmp_path / "out" / ITEMS_NAME)
    assert found.claims[ClaimState.BOUND] == 1
    assert (found.items["filled"], found.items["filled_and_passing"]) == (1, 1)
    assert found.assertions[Basis.INFERRED] == {"matched": 1}


def test_a_link_out_of_the_capsule_and_an_lfs_pointer_are_not_read(tmp_path):
    folder = capsule(tmp_path / "capsule-0000001")
    (tmp_path / "elsewhere.json").write_text('{"auc": 0.9375660604380387}\n')
    (folder / "results" / "linked.json").symlink_to(tmp_path / "elsewhere.json")
    (folder / "results" / "big.csv").write_text(
        "version https://git-lfs.github.com/spec/v1\noid sha256:" + "0" * 64 + "\nsize 9\n"
    )
    (tmp_path / "tasks.json").write_text(TASKS)
    written = from_corebench(folder, tmp_path / "tasks.json", tmp_path / "out")

    unread = {n.file: n.reason for n in written.not_checked}
    assert unread["results/linked.json"].startswith("a link to a file outside the capsule")
    assert unread["results/big.csv"].startswith("a Git LFS pointer")
    manifest = load(tmp_path / "out" / DRAFT_NAME)
    assert manifest.artifact("results/linked.json") is None
    assert manifest.artifact("results/big.csv").digest is None
    # The value outside the capsule was not found, so the AUC's candidate is still unique.
    auc = {item.claim: item for item in read(tmp_path / "out" / ITEMS_NAME).items}[
        "report-the-average-auc-score-of-had"
    ]
    assert auc.unique and auc.candidates[0]["locator"]["pointer"] == "/auc/had"


def test_a_yaml_result_with_a_key_twice_is_not_searched(tmp_path):
    folder = capsule(tmp_path / "capsule-0000001")
    (folder / "results" / "more.yaml").write_text("auc: 0.9375660604380387\nauc: 0.1\n")
    (tmp_path / "tasks.json").write_text(TASKS)
    written = from_corebench(folder, tmp_path / "tasks.json", tmp_path / "out")

    assert [n.file for n in written.not_checked] == ["results/more.yaml"]
    assert "'auc' is given twice" in written.not_checked[0].reason
    auc = {item.claim: item for item in read(tmp_path / "out" / ITEMS_NAME).items}[
        "report-the-average-auc-score-of-had"
    ]
    assert [c["artifact"] for c in auc.candidates] == ["results/metrics.json"]


def test_a_task_file_with_a_key_twice_is_refused(tmp_path):
    tasks = '[{"capsule_id": "capsule-0000001", "results": [{"q": 1, "q": 2}]}]'
    with pytest.raises(CorebenchError, match="'q' is given twice"):
        read_capsule(tmp_path, tasks)
    assert not (tmp_path / "out").exists()


def test_a_task_file_without_the_capsule_is_refused_and_nothing_is_written(tmp_path):
    with pytest.raises(CorebenchError, match="capsule-0000001"):
        read_capsule(tmp_path, '[{"capsule_id": "capsule-0000002", "results": [{"q": 1}]}]')
    assert not (tmp_path / "out").exists()


def test_from_corebench_prints_what_it_wrote_as_json(tmp_path, capsys):
    folder = capsule(tmp_path / "capsule-0000001")
    (tmp_path / "tasks.json").write_text(TASKS)
    out = tmp_path / "out"
    args = ["from-corebench", str(folder), str(tmp_path / "tasks.json"), "-o", str(out)]

    assert main([*args, "--format", "json"]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert (printed["artifacts"], printed["claims"], printed["items"]) == (3, 6, 6)


def items_for(tmp_path, folder, tasks: str):
    (tmp_path / "tasks.json").write_text(tasks)
    written = from_corebench(folder, tmp_path / "tasks.json", tmp_path / "out")
    return written, {item.claim: item for item in read(tmp_path / "out" / ITEMS_NAME).items}


def one_question(question: str, value: str) -> str:
    return f'[{{"capsule_id": "capsule-0000001", "results": [{{"{question}": {value}}}]}}]'


def test_the_console_log_code_ocean_writes_is_pinned_and_searched(tmp_path):
    folder = capsule(tmp_path / "capsule-0000001")
    (folder / "results" / "output").write_text(
        "Loading model...\nExact Match: 0.27338983050847454\nF1: 0.41\n"
    )
    _, items = items_for(
        tmp_path, folder, one_question("Report the Exact Match score.", "0.27338983050847454")
    )

    manifest = load(tmp_path / "out" / DRAFT_NAME)
    assert manifest.artifact("results/output").media_type == "text/plain"
    item = items["report-the-exact-match-score"]
    assert item.unique
    assert item.candidates[0]["locator"]["kind"] == "prose"
    assert item.candidates[0]["locator"]["before"].endswith("exact match:")
    assert evidence_of(tmp_path)["Report the Exact Match score."] == ()

    # The candidate is one the prose backend resolves: filled, it matches.
    path = tmp_path / "out" / DRAFT_NAME
    document = yaml.safe_load(path.read_text())
    document["claims"][0]["evidence"] = [item.candidates[0]]
    path.write_text(yaml.safe_dump(document, sort_keys=False))
    assert tally(tmp_path / "out" / ITEMS_NAME).claims[ClaimState.BOUND] == 1


def test_a_split_the_question_names_must_be_the_addresss(tmp_path):
    folder = capsule(tmp_path / "capsule-0000001")
    (folder / "results" / "splits.csv").write_text("model,train_acc,val_acc\nlasso,0.9271,0.8814\n")
    _, items = items_for(tmp_path, folder, one_question("Report the test accuracy.", "0.9271"))

    item = items["report-the-test-accuracy"]
    assert [c["locator"]["column"] for c in item.candidates] == ["train_acc"]
    assert not item.unique
    assert item.reason == "the question names a label or a split no matching address carries"


def test_a_split_the_address_carries_leaves_its_candidate_unique(tmp_path):
    folder = capsule(tmp_path / "capsule-0000001")
    (folder / "results" / "splits.csv").write_text(
        "model,train_acc,test_acc\nlasso,0.9271,0.8814\n"
    )
    _, items = items_for(tmp_path, folder, one_question("Report the test accuracy.", "0.8814"))

    item = items["report-the-test-accuracy"]
    assert item.unique
    assert item.candidates[0]["locator"]["column"] == "test_acc"


@pytest.mark.parametrize(
    ("name", "content", "said"),
    [
        ("huge.json", '{"a": 1e999999999}', "a number out of range"),
        ("nan.json", '{"a": NaN}', "NaN, which is not a number"),
        ("deep.json", "[" * 5000 + "]" * 5000, "nested deeper than 64"),
        (
            "bomb.yaml",
            "a: &a [x, x, x, x, x, x, x, x, x, x]\n"
            + "".join(
                f"{chr(98 + i)}: &{chr(98 + i)} [{', '.join([f'*{chr(97 + i)}'] * 10)}]\n"
                for i in range(7)
            ),
            "an alias, which is refused here",
        ),
        ("deep.yaml", "x: " + "[" * 5000 + "]" * 5000 + "\n", "nested deeper than 64"),
        ("big.yaml", "a: " + "9" * 5000 + "\n", "a number out of range"),
    ],
    ids=["huge-json", "nan-json", "deep-json", "alias-bomb", "deep-yaml", "big-yaml"],
)
def test_a_hostile_result_file_is_not_checked_with_a_reason(tmp_path, name, content, said):
    folder = capsule(tmp_path / "capsule-0000001")
    (folder / "results" / name).write_text(content)
    written, items = items_for(tmp_path, folder, TASKS)

    unread = {n.file: n.reason for n in written.not_checked}
    assert said in unread[f"results/{name}"]
    # The other files were searched as before.
    assert items["report-the-average-auc-score-of-had"].unique


def test_a_task_file_with_a_number_out_of_range_is_refused(tmp_path):
    with pytest.raises(CorebenchError, match="out of range"):
        read_capsule(tmp_path, one_question(AUC, "1e999999999"))
    assert not (tmp_path / "out").exists()


def test_a_csv_cell_out_of_range_is_skipped_not_compared(tmp_path):
    folder = capsule(tmp_path / "capsule-0000001")
    (folder / "results" / "huge.csv").write_text(
        "model,auc\nhuge,1e999999999\nlong," + "9" * 5000 + "\n"
    )
    _, items = items_for(tmp_path, folder, TASKS)

    auc = items["report-the-average-auc-score-of-had"]
    assert auc.unique and auc.candidates[0]["artifact"] == "results/metrics.json"


def test_a_log_with_many_matches_is_read_once_and_capped(tmp_path, monkeypatch):
    folder = capsule(tmp_path / "capsule-0000001")
    (folder / "results" / "output").write_text(
        "".join(f"step {n}: loss 0.8130\n" for n in range(40_000))
    )
    reads = []
    real = corebench.stored_value

    def counted(evidence, path):
        reads.append(path)
        return real(evidence, path)

    monkeypatch.setattr(corebench, "stored_value", counted)
    _, items = items_for(tmp_path, folder, one_question("Report the loss.", "0.8130"))

    item = items["report-the-loss"]
    assert len(item.candidates) == corebench.MAX_CANDIDATES
    assert item.context["candidates_not_examined"] == 40_000 - corebench.MAX_CANDIDATES
    assert not item.unique
    assert "not examined" in item.reason
    assert len(reads) <= corebench.MAX_CANDIDATES


def test_a_question_some_runs_do_not_ask_is_kept_and_said(tmp_path):
    tasks = json.dumps(
        [{"capsule_id": "capsule-0000001", "results": [{AUC: 0.9375660604380387}, {"r": 0.5}]}]
    )
    _, items = read_capsule(tmp_path, tasks)

    assert set(items) == {"report-the-average-auc-score-of-had", "r"}
    assert items["r"].context["absent_from_runs"] == [0]
    assert items["report-the-average-auc-score-of-had"].context["absent_from_runs"] == [1]
