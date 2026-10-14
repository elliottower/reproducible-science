"""`repro venue acm`: which record answers which field of the Artifact Appendix, and the
markers that keep a generated answer from reading as the authors'.

Each project is written by hand, record by record, so every finding the draft carries can be
traced to one line written here.
"""

from __future__ import annotations

import json

import pytest
import yaml
from repro.cli import main
from repro.models import (
    Environment,
    Regeneration,
    RegenerationReason,
    RegenerationState,
    ReproductionReport,
)
from repro.venue import acm
from repro.venue.draft import (
    Questionnaire,
    Status,
    UnknownQuestionError,
    UnknownReaderError,
    check_reads,
    markdown,
    questionnaire,
)
from repro.venue.records import Finding, Project

SHA = "a" * 64
COMMIT = "0123456789abcdef0123456789abcdef01234567"


def write_project(root):
    """A project holding one record of every kind the appendix reads."""
    (root / "data").mkdir()
    manifest = {
        "schema_version": "repro/1",
        "project": "demo",
        "artifacts": [
            {"id": "table2", "path": "results/table_2.json", "digest": {"value": SHA}},
            {"id": "raw", "path": "data/raw.csv", "digest": {"value": SHA}},
            {"id": "notes", "path": "notes.md"},
        ],
        "claims": [
            {"id": "c1", "text": "Accuracy is 91%."},
            {"id": "c2", "text": "Recall is 80%."},
        ],
        "regenerations": [
            {
                "id": "table-2",
                "command": ["python", "make_table.py", "--seed", "7"],
                "inputs": ["raw"],
                "output": {"artifact": "table2", "digest": {"value": SHA}},
            }
        ],
    }
    (root / "repro.yaml").write_text(yaml.safe_dump(manifest))
    report = ReproductionReport(
        started_at="2026-10-01T10:00:00+00:00",
        environment=Environment(
            system="Linux", machine="x86_64", python="3.12.1", gpus=("NVIDIA A100 80GB",)
        ),
        regenerations=(
            RegenerationState(
                regeneration_id="table-2",
                artifact_id="table2",
                state=Regeneration.REPRODUCED,
                reason=RegenerationReason.OUTPUT_MATCHES,
                executed=True,
                duration_seconds=12.5,
            ),
        ),
    )
    (root / ".repro").mkdir()
    (root / ".repro" / "reproductions.jsonl").write_text(report.model_dump_json() + "\n")
    (root / ".results").mkdir()
    events = [
        {"event": "init"},
        {"event": "run", "run_id": "smoke_first", "outputs": []},
        {"event": "seal", "role": "inputs", "files": []},
        {"event": "run", "run_id": "main", "outputs": []},
        {"event": "claim", "claim": "Accuracy is 91%.", "run_id": "main", "confirmatory": True},
    ]
    (root / ".results" / "ledger.jsonl").write_text(
        "".join(json.dumps(event) + "\n" for event in events)
    )
    (root / "PREREG.md").write_text("# Plan\n")
    (root / ".prereg").mkdir()
    (root / ".prereg" / "PREREG.md.json").write_text(json.dumps({"commit": COMMIT}))
    (root / "CITATION.cff").write_text(
        yaml.safe_dump({"cff-version": "1.2.0", "doi": "10.5281/zenodo.42", "license": "MIT"})
    )
    (root / "LICENSE").write_text("\nMIT License\n\nCopyright (c) 2026\n")
    (root / "uv.lock").write_text("version = 1\n")
    return root


@pytest.fixture
def full(tmp_path):
    return acm.appendix(Project.at(write_project(tmp_path)))


def said(answer):
    return [(finding.record, finding.said) for finding in answer.findings]


def test_the_archive_field_is_the_doi_citation_cff_names(full):
    archived = full.answer("archived")
    assert archived.status is Status.DRAFT
    assert said(archived) == [("CITATION.cff", "names DOI 10.5281/zenodo.42")]


def test_a_doi_among_the_identifiers_is_read_too(tmp_path):
    (tmp_path / "CITATION.cff").write_text(
        yaml.safe_dump(
            {
                "identifiers": [
                    {"type": "url", "value": "https://example.org"},
                    {"type": "doi", "value": "10.1234/abc"},
                ]
            }
        )
    )
    draft = acm.appendix(Project.at(tmp_path))
    assert said(draft.answer("archived")) == [("CITATION.cff", "names DOI 10.1234/abc")]


def test_the_experiments_field_quotes_the_declared_command_and_its_output(full):
    assert said(full.answer("experiments")) == [
        (
            "repro.yaml",
            "`table-2` runs `python make_table.py --seed 7` and writes results/table_2.json",
        ),
        ("repro.yaml", "`repro reproduce` runs each declared command again"),
    ]


def test_time_and_hardware_come_from_the_record_of_re_runs(full):
    record = ".repro/reproductions.jsonl"
    assert said(full.answer("time-to-complete")) == [
        (record, "the last re-run of 1 declared command took 12.5 s in total")
    ]
    assert said(full.answer("hardware")) == [
        (
            record,
            "the re-run on 2026-10-01 ran on Linux x86_64; Python 3.12.1; GPUs: NVIDIA A100 80GB",
        )
    ]


def test_the_ledger_count_leaves_out_test_runs_and_counts_a_run_after_a_seal(full):
    workflow = said(full.answer("experiment-workflow"))
    assert ("PREREG.md", f"frozen at commit {COMMIT[:12]}") in workflow
    assert (
        ".results/ledger.jsonl",
        "records 1 seal of inputs and 1 run, 1 of them recorded after a seal",
    ) in workflow


def test_the_evaluation_field_counts_claims_pins_and_re_run_outcomes(full):
    assert said(full.answer("evaluation")) == [
        ("repro.yaml", "declares 2 claims and 3 artifacts, 2 of them pinned by sha256"),
        (".results/ledger.jsonl", "binds 1 claim to recorded runs, 1 of them confirmatory"),
        (".repro/reproductions.jsonl", "`table-2` last re-run on 2026-10-01: reproduced, 12.5 s"),
    ]


def test_the_license_field_reads_the_first_line_that_is_not_blank(full):
    assert said(full.answer("code-licenses")) == [
        ("LICENSE", "is present; its first line reads `MIT License`"),
        ("CITATION.cff", "names the license MIT"),
    ]


def test_every_field_no_reader_is_named_for_is_left_to_do(full):
    for answer in full.answers:
        if answer.question.id not in acm.READS:
            assert answer.status is Status.TODO
            assert answer.findings == ()


def test_a_project_with_no_records_is_all_todo_and_no_field_is_marked_draft(tmp_path):
    draft = acm.appendix(Project.at(tmp_path))
    assert {answer.status for answer in draft.answers} == {Status.TODO}
    text = markdown(draft)
    assert "**DRAFT**" not in text
    assert text.count("**TODO**") == len(draft.answers)


def test_every_drafted_field_is_marked_and_names_each_record_it_came_from(full):
    text = markdown(full)
    drafted = [answer for answer in full.answers if answer.status is Status.DRAFT]
    assert text.count("**DRAFT**") == len(drafted)
    assert text.count("**TODO**") == len(full.answers) - len(drafted)
    for answer in drafted:
        named = ", ".join(f"`{record}`" for record in answer.records)
        assert f"**DRAFT**, generated from {named}; not written by the authors." in text


def test_latex_marks_every_field_and_escapes_what_latex_reads_as_markup(tmp_path):
    write_project(tmp_path)
    manifest = yaml.safe_load((tmp_path / "repro.yaml").read_text())
    manifest["regenerations"][0]["command"] = ["python", "make_table.py", "--rate", "5%"]
    (tmp_path / "repro.yaml").write_text(yaml.safe_dump(manifest))
    draft = acm.appendix(Project.at(tmp_path))
    text = acm.latex(draft)
    assert r"\texttt{python make\_table.py --rate 5\%}" in text
    drafted = sum(answer.status is Status.DRAFT for answer in draft.answers)
    assert text.count(r"\textbf{[DRAFT, generated from") == drafted
    assert text.count(r"\textbf{[TODO (authors)") == len(draft.answers) - drafted
    assert text.count(r"\begin{itemize}") == text.count(r"\end{itemize}")


def test_the_stored_appendix_holds_the_template_fields_in_order():
    stored = questionnaire(acm.NAME)
    assert stored.source.url.endswith("/docs/template/ae.tex")
    checklist = [q.title for q in stored.questions if q.section == acm.CHECKLIST]
    assert checklist[0] == "Algorithm" and checklist[-1] == "Archived (provide DOI)?"
    assert len(checklist) == 22
    check_reads(stored, acm.READS)


def test_a_mapping_naming_a_missing_question_or_reader_is_refused():
    stored = questionnaire(acm.NAME)
    with pytest.raises(UnknownQuestionError):
        check_reads(stored, {"no-such-field": ("claims",)})
    with pytest.raises(UnknownReaderError):
        check_reads(stored, {"archived": ("no_such_reader",)})
    assert isinstance(stored, Questionnaire)


def test_output_is_never_written_over_without_force(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(write_project(tmp_path))
    target = tmp_path / "appendix.md"
    target.write_text("edited by the authors\n")
    assert main(["venue", "acm", "--output", str(target)]) == 2
    assert target.read_text() == "edited by the authors\n"
    assert main(["venue", "acm", "--output", str(target), "--force"]) == 0
    assert target.read_text().startswith("# Artifact Appendix (DRAFT)")
    assert "drafted from records" in capsys.readouterr().out


def test_json_carries_the_status_and_records_of_each_answer(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(write_project(tmp_path))
    assert main(["venue", "acm", "--format", "json"]) == 0
    data = json.loads(capsys.readouterr().out)
    archived = next(a for a in data["answers"] if a["question"]["id"] == "archived")
    assert archived["status"] == "draft"
    assert archived["records"] == ["CITATION.cff"]
    assert data["notice"].startswith("DRAFT.")
    assert Finding.model_validate(archived["findings"][0]).said == "names DOI 10.5281/zenodo.42"
