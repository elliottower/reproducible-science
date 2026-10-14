"""`repro venue acm`: which record answers which field of the Artifact Appendix, and the
markers that keep a generated answer from reading as the authors'.

Each project is written by hand, record by record, so every finding the draft carries can be
traced to one line written here.
"""

from __future__ import annotations

import hashlib
import json
import subprocess

import pytest
import yaml
from provenance_core.chain import append_event
from repro.cli import main
from repro.exceptions import ReproError
from repro.models import (
    Environment,
    InputReading,
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
from repro.venue.records import Finding, Project, spans, without_userinfo

SHA = "a" * 64
COMMIT = "0123456789abcdef0123456789abcdef01234567"


RAW = b"x,y\n1,2\n"
TABLE = b'{"accuracy": 0.91}\n'
COMMAND = ["python", "make_table.py", "--seed", "7"]
RERUNS = ".repro/reproductions.jsonl"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def rerun(started_at, *, command=COMMAND, raw=RAW, duration=12.5, regeneration="table-2"):
    """One invocation of `repro reproduce` that reproduced `table-2` over `raw`."""
    return ReproductionReport(
        started_at=started_at,
        environment=Environment(
            system="Linux", machine="x86_64", python="3.12.1", gpus=("NVIDIA A100 80GB",)
        ),
        regenerations=(
            RegenerationState(
                regeneration_id=regeneration,
                artifact_id="table2",
                state=Regeneration.REPRODUCED,
                reason=RegenerationReason.OUTPUT_MATCHES,
                executed=True,
                duration_seconds=duration,
                command=tuple(command),
                inputs=(InputReading(artifact_id="raw", observed=sha(raw)),),
                expected=sha(TABLE),
                actual=sha(TABLE),
            ),
        ),
    )


def write_reruns(root, *reports):
    (root / ".repro").mkdir(exist_ok=True)
    (root / RERUNS).write_text("".join(r.model_dump_json() + "\n" for r in reports))


def write_project(root):
    """A project holding one record of every kind the appendix reads, each as the tool that
    keeps it writes it: a re-run that is current, a ledger whose chain verifies, a plan frozen
    whole."""
    (root / "data").mkdir()
    (root / "results").mkdir()
    (root / "data" / "raw.csv").write_bytes(RAW)
    (root / "results" / "table_2.json").write_bytes(TABLE)
    manifest = {
        "schema_version": "repro/1",
        "project": "demo",
        "artifacts": [
            {"id": "table2", "path": "results/table_2.json", "digest": {"value": sha(TABLE)}},
            {"id": "raw", "path": "data/raw.csv", "digest": {"value": sha(RAW)}},
            {"id": "notes", "path": "notes.md"},
        ],
        "claims": [
            {"id": "c1", "text": "Accuracy is 91%."},
            {"id": "c2", "text": "Recall is 80%."},
        ],
        "regenerations": [
            {
                "id": "table-2",
                "command": COMMAND,
                "inputs": ["raw"],
                "output": {"artifact": "table2", "digest": {"value": sha(TABLE)}},
            }
        ],
    }
    (root / "repro.yaml").write_text(yaml.safe_dump(manifest))
    write_reruns(root, rerun("2026-10-01T10:00:00+00:00"))
    (root / ".results").mkdir()
    for event in (
        {"event": "init"},
        {"event": "run", "run_id": "smoke_first", "outputs": []},
        {"event": "seal", "role": "inputs", "files": []},
        {"event": "run", "run_id": "main", "outputs": []},
        {"event": "claim", "claim": "Accuracy is 91%.", "run_id": "main", "confirmatory": True},
    ):
        append_event(root / ".results" / "ledger.jsonl", event)
    freeze(root)
    (root / "CITATION.cff").write_text(
        yaml.safe_dump({"cff-version": "1.2.0", "doi": "10.5281/zenodo.42", "license": "MIT"})
    )
    (root / "LICENSE").write_text("\nMIT License\n\nCopyright (c) 2026\n")
    (root / "uv.lock").write_text("version = 1\n")
    return root


def freeze(directory, commit=COMMIT):
    """A `PREREG.md` in `directory`, frozen whole: the record `prereg freeze` writes beside it."""
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "PREREG.md").write_text("# Plan\n")
    (directory / ".prereg").mkdir()
    record = {
        "file": "PREREG.md",
        "sha256": SHA,
        "commit": commit,
        "frozen_at": "2026-09-01T00:00:00+00:00",
        "access": "no data",
    }
    (directory / ".prereg" / "PREREG.md.json").write_text(json.dumps(record))


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
    record = RERUNS
    assert said(full.answer("time-to-complete")) == [
        (record, "the current re-runs of 1 declared command took 12.5 s in total")
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
        (".results/ledger.jsonl", "binds 1 claim to runs it records, 1 of them confirmatory"),
        (RERUNS, "`table-2`: current; reproduced by the re-run on 2026-10-01, 12.5 s"),
    ]


def test_the_license_field_reads_the_first_line_that_is_not_blank(full):
    assert said(full.answer("code-licenses")) == [
        ("LICENSE", "is present; its first line reads `MIT License`"),
        ("CITATION.cff", "names the license MIT"),
    ]


def test_every_field_no_reader_is_named_for_is_left_to_do(full):
    for answer in full.answers:
        if answer.question.id not in {*acm.READS, *acm.SETTLES}:
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


# -- plans ---------------------------------------------------------------------------------


def test_a_plan_under_tests_fixtures_or_examples_is_not_the_projects(tmp_path):
    for folder in ("tests/data", "packages/x/fixtures", "examples/demo"):
        freeze(tmp_path / folder, commit="b" * 40)
    draft = acm.appendix(Project.at(tmp_path))
    assert draft.answer("experiment-workflow").findings == ()
    freeze(tmp_path / "study")
    assert said(acm.appendix(Project.at(tmp_path)).answer("experiment-workflow")) == [
        ("study/PREREG.md", f"frozen at commit {COMMIT[:12]}")
    ]


def test_a_plan_never_frozen_is_not_listed(tmp_path):
    (tmp_path / "PREREG.md").write_text("# Plan\n")
    assert acm.appendix(Project.at(tmp_path)).answer("experiment-workflow").findings == ()


def test_a_plan_named_explicitly_is_read_wherever_it_is(tmp_path):
    freeze(tmp_path / "tests" / "kept", commit="c" * 40)
    project = Project.at(tmp_path, plan=tmp_path / "tests" / "kept" / "PREREG.md")
    assert said(acm.appendix(project).answer("experiment-workflow")) == [
        ("tests/kept/PREREG.md", f"frozen at commit {'c' * 12}")
    ]


# -- choices a record settles --------------------------------------------------------------


def test_a_doi_settles_archived_and_publicly_available_as_yes(full):
    for field in ("archived", "publicly-available"):
        answer = full.answer(field)
        assert answer.status is Status.DRAFT
        assert (answer.choice, answer.choice_from) == ("Yes", ("CITATION.cff",))
        assert said(answer) == [("CITATION.cff", "names DOI 10.5281/zenodo.42")]


def test_a_declared_command_settles_the_workflow_framework_as_yes(full):
    answer = full.answer("workflow-framework")
    assert (answer.choice, answer.choice_from) == ("Yes", ("repro.yaml",))


def test_with_no_doi_nothing_is_chosen_and_the_fields_stay_to_do(tmp_path):
    write_project(tmp_path)
    (tmp_path / "CITATION.cff").write_text(yaml.safe_dump({"license": "MIT"}))
    draft = acm.appendix(Project.at(tmp_path))
    for field in ("archived", "publicly-available"):
        assert (draft.answer(field).choice, draft.answer(field).status) == ("", Status.TODO)


def test_a_license_on_disk_settles_no_choice(full):
    assert full.answer("code-licenses").status is Status.DRAFT
    assert all(
        answer.choice == "" for answer in full.answers if answer.question.id not in acm.SETTLES
    )


def test_a_settled_choice_is_marked_draft_in_every_format(full):
    assert "Answer: **Yes** (DRAFT, settled by `CITATION.cff`" in markdown(full)
    assert r"Yes \textbf{[DRAFT, settled by \texttt{CITATION.cff}]}" in acm.latex(full)
    assert r"Yes \textbf{[DRAFT, settled by \texttt{CITATION.cff}; author: confirm" in acm.latex(
        full
    )


# -- archived and publicly available, offline ------------------------------------------------

SWH = "swh:1:dir:" + "d" * 40


def archive_and_public(root):
    draft = acm.appendix(Project.at(root))
    return draft.answer("archived"), draft.answer("publicly-available")


def test_a_doi_in_codemeta_settles_archived(tmp_path):
    (tmp_path / "codemeta.json").write_text(
        json.dumps({"identifier": "https://doi.org/10.5281/zenodo.7"})
    )
    archived, public = archive_and_public(tmp_path)
    assert (archived.choice, said(archived)) == (
        "Yes",
        [("codemeta.json", "names DOI 10.5281/zenodo.7")],
    )
    assert (public.choice, public.choice_from) == ("Yes", ("codemeta.json",))


@pytest.mark.parametrize(
    ("name", "text"),
    [
        ("CITATION.cff", yaml.safe_dump({"identifiers": [{"type": "swh", "value": SWH}]})),
        ("codemeta.json", json.dumps({"identifier": [SWH]})),
    ],
)
def test_a_software_heritage_id_among_the_projects_identifiers_settles_archived(
    tmp_path, name, text
):
    (tmp_path / name).write_text(text)
    archived, _ = archive_and_public(tmp_path)
    assert (archived.choice, said(archived)) == (
        "Yes",
        [(name, f"names Software Heritage ID {SWH}")],
    )


@pytest.mark.parametrize(
    ("name", "text", "said_as"),
    [
        (
            "CITATION.cff",
            yaml.safe_dump({"repository-code": "https://gitlab.com/a/b"}),
            "names repository-code https://gitlab.com/a/b",
        ),
        (
            "codemeta.json",
            json.dumps({"codeRepository": "https://github.com/a/b"}),
            "names codeRepository https://github.com/a/b",
        ),
    ],
)
def test_a_repository_settles_publicly_available_for_the_author_to_confirm(
    tmp_path, name, text, said_as
):
    (tmp_path / name).write_text(text)
    archived, public = archive_and_public(tmp_path)
    assert (public.choice, public.choice_note) == (
        "Yes",
        "author: confirm this repository is public",
    )
    assert said(public) == [(name, f"{said_as}; author: confirm this repository is public")]
    assert archived.status is Status.TODO


def test_identifiers_of_other_works_settle_nothing(tmp_path):
    write_project(tmp_path)
    (tmp_path / "CITATION.cff").write_text(
        yaml.safe_dump(
            {
                "references": [
                    {
                        "title": "numpy",
                        "doi": "10.1038/s41586-020-2649-2",
                        "repository-code": "https://github.com/numpy/numpy",
                        "identifiers": [{"type": "swh", "value": "swh:1:rel:" + "f" * 40}],
                    }
                ]
            }
        )
    )
    (tmp_path / "codemeta.json").write_text(
        json.dumps(
            {
                "softwareRequirements": [
                    {"identifier": "10.5281/zenodo.1", "codeRepository": "https://github.com/x/y"}
                ]
            }
        )
    )
    (tmp_path / "README.md").write_text(f"# Demo\n\nBuilds on {SWH}, doi 10.1234/x.\n")
    manifest = yaml.safe_load((tmp_path / "repro.yaml").read_text())
    manifest["artifacts"][1]["origin"] = {
        "repository": "https://github.com/someone-else/data",
        "commit": "e" * 40,
        "path": "raw.csv",
    }
    (tmp_path / "repro.yaml").write_text(yaml.safe_dump(manifest))
    archived, public = archive_and_public(tmp_path)
    assert (archived.status, archived.choice) == (Status.TODO, "")
    assert (public.status, public.choice) == (Status.TODO, "")


def test_a_github_url_alone_is_publicly_available_and_not_archived(tmp_path):
    (tmp_path / "CITATION.cff").write_text(
        yaml.safe_dump({"repository-code": "https://github.com/a/b"})
    )
    (tmp_path / "README.md").write_text("# Demo\n\nCode: https://github.com/a/b\n")
    archived, public = archive_and_public(tmp_path)
    assert public.choice == "Yes"
    assert (archived.status, archived.choice, archived.findings) == (Status.TODO, "", ())
    assert "A GitHub or GitLab URL alone is not an archive." in archived.todo_note
    text = markdown(acm.appendix(Project.at(tmp_path)))
    assert "**TODO** (authors): no record here names an archived copy" in text
    assert "(DRAFT, settled by `CITATION.cff`; author: confirm this repository is public)" in text


# -- staleness, the ledger's chain, and malformed records ----------------------------------


def test_a_re_run_that_is_no_longer_current_is_not_reported_as_current(tmp_path):
    write_project(tmp_path)
    (tmp_path / "data" / "raw.csv").write_bytes(b"x,y\n1,3\n")
    manifest = yaml.safe_load((tmp_path / "repro.yaml").read_text())
    manifest["artifacts"][1]["digest"]["value"] = sha(b"x,y\n1,3\n")
    (tmp_path / "repro.yaml").write_text(yaml.safe_dump(manifest))
    draft = acm.appendix(Project.at(tmp_path))
    assert (RERUNS, "`table-2`: stale; the re-run compared was on 2026-10-01") in said(
        draft.answer("evaluation")
    )
    assert draft.answer("time-to-complete").status is Status.TODO
    assert draft.answer("hardware").status is Status.TODO


def test_a_re_run_of_a_command_no_longer_declared_is_not_listed(tmp_path):
    write_project(tmp_path)
    write_reruns(
        tmp_path,
        rerun("2025-01-01T00:00:00+00:00", regeneration="old-gone"),
        rerun("2026-10-01T10:00:00+00:00", duration=0.0),
    )
    draft = acm.appendix(Project.at(tmp_path))
    lines = [text for record, text in said(draft.answer("evaluation")) if record == RERUNS]
    assert lines == ["`table-2`: current; reproduced by the re-run on 2026-10-01, 0.0 s"]
    assert said(draft.answer("time-to-complete")) == [
        (RERUNS, "the current re-runs of 1 declared command took 0.0 s in total")
    ]


def test_a_claim_naming_no_recorded_run_is_not_counted_as_bound(tmp_path):
    write_project(tmp_path)
    append_event(
        tmp_path / ".results" / "ledger.jsonl",
        {"event": "claim", "claim": "Recall is 80%.", "run_id": "never", "confirmatory": False},
    )
    assert (
        ".results/ledger.jsonl",
        "binds 1 claim to runs it records, 1 of them confirmatory; 1 more names a run it does "
        "not record",
    ) in said(acm.appendix(Project.at(tmp_path)).answer("evaluation"))


def test_a_ledger_whose_chain_does_not_verify_says_so(tmp_path):
    write_project(tmp_path)
    path = tmp_path / ".results" / "ledger.jsonl"
    path.write_text(path.read_text().replace('"main"', '"other"', 1))
    workflow = said(acm.appendix(Project.at(tmp_path)).answer("experiment-workflow"))
    assert (
        ".results/ledger.jsonl",
        "does not verify as a chain: `results verify` would report edited",
    ) in workflow


@pytest.mark.parametrize(
    ("name", "content"),
    [
        ("CITATION.cff", b"identifiers: 5\ndoi: [1, 2]\n"),
        (".results/ledger.jsonl", b"[1, 2]\n"),
        ("PREREG.md", b"\xff\xfe not text **Plan sha256:** `" + b"a" * 64 + b"`\n"),
    ],
)
def test_malformed_records_do_not_crash_the_draft(tmp_path, name, content):
    (tmp_path / ".results").mkdir()
    (tmp_path / name).write_bytes(content)
    draft = acm.appendix(Project.at(tmp_path))
    assert draft.answer("abstract").status is Status.TODO


def test_a_plan_named_that_is_not_there_is_refused(tmp_path):
    with pytest.raises(ReproError, match="no such file"):
        Project.at(tmp_path, plan=tmp_path / "nothere.md")


def test_the_help_says_which_fields_are_answered(capsys):
    with pytest.raises(SystemExit):
        main(["venue", "acm", "--help"])
    out = " ".join(capsys.readouterr().out.split())
    assert "Three fields are answered Yes where a record settles them" in out
    with pytest.raises(SystemExit):
        main(["venue", "--help"])
    assert "No question is answered yes or no" not in " ".join(capsys.readouterr().out.split())


# -- second review ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "citation",
    [{"doi": "TBD"}, {"identifiers": [{"type": "doi", "value": "to be assigned"}]}],
)
def test_a_citation_doi_that_is_not_a_doi_settles_nothing(tmp_path, citation):
    (tmp_path / "CITATION.cff").write_text(yaml.safe_dump(citation))
    archived, public = archive_and_public(tmp_path)
    assert (archived.status, archived.choice) == (Status.TODO, "")
    assert (public.status, public.choice) == (Status.TODO, "")


def test_the_remote_is_shown_without_credentials_and_for_the_author_to_confirm(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(tmp_path),
            "remote",
            "add",
            "origin",
            "https://alice:ghp_secret123@github.com/a/b.git",
        ],
        check=True,
    )
    answer = acm.appendix(Project.at(tmp_path)).answer("how-to-access")
    assert said(answer) == [
        (
            "git config",
            "remote `origin` is https://github.com/a/b.git; author: confirm this repository is "
            "public",
        )
    ]
    assert "ghp_secret123" not in markdown(acm.appendix(Project.at(tmp_path)))


@pytest.mark.parametrize(
    ("url", "shown"),
    [
        ("ssh://git:pw@example.org/a.git", "ssh://example.org/a.git"),
        ("git@github.com:a/b.git", "github.com:a/b.git"),
        ("https://github.com/a/b", "https://github.com/a/b"),
    ],
)
def test_userinfo_is_taken_out_of_every_kind_of_address(url, shown):
    assert without_userinfo(url) == shown


def test_a_plan_outside_the_project_is_shown_by_its_name(tmp_path):
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    freeze(tmp_path / "elsewhere")
    project = Project.at(project_dir, plan=tmp_path / "elsewhere" / "PREREG.md")
    assert said(acm.appendix(project).answer("experiment-workflow")) == [
        ("PREREG.md", f"frozen at commit {COMMIT[:12]}")
    ]


def test_a_backtick_in_a_command_keeps_the_code_span_whole(tmp_path):
    write_project(tmp_path)
    manifest = yaml.safe_load((tmp_path / "repro.yaml").read_text())
    manifest["regenerations"][0]["command"] = ["sh", "-c", "echo `date`"]
    (tmp_path / "repro.yaml").write_text(yaml.safe_dump(manifest))
    draft = acm.appendix(Project.at(tmp_path))
    first = draft.answer("experiments").findings[0].said
    assert first == "`table-2` runs ``sh -c 'echo `date`'`` and writes results/table_2.json"
    assert spans(first)[2] == (True, "sh -c 'echo `date`'")
    assert r"\texttt{sh -c 'echo `date`'}" in acm.latex(draft)


def test_one_claim_naming_no_recorded_run_reads_names(tmp_path):
    write_project(tmp_path)
    append_event(
        tmp_path / ".results" / "ledger.jsonl",
        {"event": "claim", "claim": "x", "run_id": "never", "confirmatory": False},
    )
    evaluation = [text for _, text in said(acm.appendix(Project.at(tmp_path)).answer("evaluation"))]
    assert any(text.endswith("; 1 more names a run it does not record") for text in evaluation)
