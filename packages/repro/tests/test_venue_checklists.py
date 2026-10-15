"""`repro venue neurips` and `repro venue acl`: the stored questions, which record bears on
which question, and that no answer is ever chosen for the authors."""

from __future__ import annotations

import importlib.util
import json
import pathlib
import re

import pytest
import yaml
from repro.cli import main
from repro.venue import acl, neurips
from repro.venue.draft import Status, check_reads, questionnaire
from repro.venue.records import Project

_SPEC = importlib.util.spec_from_file_location(
    "venue_acm", pathlib.Path(__file__).with_name("test_venue_acm.py")
)
assert _SPEC is not None and _SPEC.loader is not None
helpers = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(helpers)
write_project = helpers.write_project

RERUNS = ".repro/reproductions.jsonl"


def said(answer):
    return [(finding.record, finding.said) for finding in answer.findings]


# -- the stored questions --------------------------------------------------------------------


def test_the_neurips_questions_are_the_sixteen_of_checklist_tex_in_order():
    stored = questionnaire(neurips.NAME)
    assert [q.title for q in stored.questions] == [
        "Claims",
        "Limitations",
        "Theory assumptions and proofs",
        "Experimental result reproducibility",
        "Open access to data and code",
        "Experimental setting/details",
        "Experiment statistical significance",
        "Experiments compute resources",
        "Code of ethics",
        "Broader impacts",
        "Safeguards",
        "Licenses for existing assets",
        "New assets",
        "Crowdsourcing and research with human subjects",
        "Institutional review board (IRB) approvals or equivalent for research with human subjects",
        "Declaration of LLM usage",
    ]
    assert stored.question("9").text == (
        "Does the research conducted in the paper conform, in every respect, with the NeurIPS "
        "Code of Ethics https://neurips.cc/public/EthicsGuidelines?"
    )
    assert all("\\" not in q.text for q in stored.questions)
    check_reads(stored, neurips.READS)


def test_the_acl_questions_are_the_forms_labels_in_order():
    stored = questionnaire(acl.NAME)
    assert [q.id for q in stored.questions] == [
        *("A1", "A2"),
        *("B", "B1", "B2", "B3", "B4", "B5", "B6"),
        *("C", "C1", "C2", "C3", "C4"),
        *("D", "D1", "D2", "D3", "D4", "D5"),
        *("E", "E1"),
    ]
    assert stored.question("D4").text == (
        "Was the data collection protocol approved (or determined exempt) by an ethics review "
        "board?"
    )
    assert stored.question("B4").section == "B. Did you use or create scientific artifacts?"
    check_reads(stored, acl.READS)


# -- which record bears on which question ----------------------------------------------------


@pytest.fixture
def project(tmp_path):
    return Project.at(write_project(tmp_path))


def test_neurips_open_access_lists_the_doi_the_command_the_lockfile_and_the_license(project):
    answer = neurips.checklist(project).answer("5")
    assert answer.status is Status.DRAFT
    assert answer.records == ("CITATION.cff", "repro.yaml", "uv.lock", "LICENSE")
    assert ("CITATION.cff", "names DOI 10.5281/zenodo.42") in said(answer)


def test_neurips_compute_lists_the_re_run_time_and_hardware(project):
    assert said(neurips.checklist(project).answer("8")) == [
        (RERUNS, "the current re-runs of 1 declared command took 12.5 s in total"),
        (
            RERUNS,
            "the re-run on 2026-10-01 ran on Linux x86_64; Python 3.12.1; GPUs: NVIDIA A100 80GB",
        ),
    ]


def test_acl_lists_the_license_compute_and_environment_and_leaves_the_rest(project):
    draft = acl.checklist(project)
    assert said(draft.answer("B2")) == [
        ("LICENSE", "is present; its first line reads `MIT License`"),
        ("CITATION.cff", "names the license MIT"),
    ]
    assert said(draft.answer("C4")) == [("uv.lock", "is present")]
    assert draft.answer("C1").records == (RERUNS,)
    drafted = {a.question.id for a in draft.answers if a.status is Status.DRAFT}
    assert drafted == {"B", "B2", "B5", "C1", "C4"}


def test_acl_b1_is_drafted_only_where_an_artifact_names_its_origin(tmp_path):
    write_project(tmp_path)
    assert acl.checklist(Project.at(tmp_path)).answer("B1").status is Status.TODO
    manifest = yaml.safe_load((tmp_path / "repro.yaml").read_text())
    manifest["artifacts"][1]["origin"] = {
        "repository": "https://github.com/someone/corpus",
        "commit": "f" * 40,
        "path": "raw.csv",
    }
    (tmp_path / "repro.yaml").write_text(yaml.safe_dump(manifest))
    ((record, text),) = said(acl.checklist(Project.at(tmp_path)).answer("B1"))
    assert record == "repro.yaml"
    assert text.startswith("`raw` was copied from https://github.com/someone/corpus at commit ")
    assert "origin check: not_checked" in text


# -- no answer is chosen ---------------------------------------------------------------------


def test_neurips_latex_answers_only_open_access_and_marks_every_justification(project):
    draft = neurips.checklist(project)
    text = neurips.latex(draft)
    answers = re.findall(r"\\item\[\] Answer: (\S+)", text)
    assert answers == [r"\answerTODO{}"] * 4 + [r"\answerYes{}"] + [r"\answerTODO{}"] * 11
    answer_line = next(line for line in text.splitlines() if "Answer: \\answerYes{}" in line)
    assert answer_line.strip() == (
        r"\item[] Answer: \answerYes{} \textbf{(DRAFT: from \texttt{CITATION.cff}; author: "
        r"confirm this repository is public)}"
    )
    assert "%" not in answer_line
    todo = sum(answer.status is Status.TODO for answer in draft.answers)
    assert text.count(r"\item[] Justification: \justificationTODO{}") == todo
    justifications = re.findall(r"\\item\[\] Justification: (.*)", text)
    assert sum("[DRAFT, generated from" in line for line in justifications) == 16 - todo
    assert "settled by" not in text
    assert text.count("author: confirm this repository is public)}") == 1


def test_markdown_puts_a_choice_line_under_every_question(project):
    for module in (neurips, acl):
        draft = module.checklist(project)
        text = module.as_markdown(draft)
        unchosen = sum(answer.choice == "" for answer in draft.answers)
        assert text.count(module.CHOICE) == unchosen
        assert text.count("(DRAFT, settled by") == len(draft.answers) - unchosen
        drafted = sum(answer.status is Status.DRAFT for answer in draft.answers)
        assert text.count("**DRAFT**, generated from") == drafted


def test_the_commands_write_json_and_acl_offers_no_latex(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(write_project(tmp_path))
    assert main(["venue", "neurips", "--format", "json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["venue"] == "neurips"
    assert len(data["answers"]) == 16
    assert main(["venue", "acl", "--format", "json"]) == 0
    assert json.loads(capsys.readouterr().out)["source"]["url"] == (
        "https://aclrollingreview.org/responsibleNLPresearch/"
    )
    with pytest.raises(SystemExit):
        main(["venue", "acl", "--format", "latex"])


# -- choices a record settles --------------------------------------------------------------


def test_acl_b_lists_the_declared_artifacts_and_leaves_the_answer_to_the_authors(project):
    answer = acl.checklist(project).answer("B")
    assert (answer.status, answer.choice) == (Status.DRAFT, "")
    assert said(answer) == [("repro.yaml", "declares 3 artifacts its claims read")]
    text = acl.as_markdown(acl.checklist(project))
    assert "settled by" not in text
    assert text.count(acl.CHOICE) == len(acl.checklist(project).answers)


def test_acl_b_stays_unchosen_with_no_manifest(tmp_path):
    answer = acl.checklist(Project.at(tmp_path)).answer("B")
    assert (answer.status, answer.choice) == (Status.TODO, "")


def test_a_re_run_does_not_settle_whether_computational_experiments_were_run(project):
    answer = acl.checklist(project).answer("C")
    assert (answer.status, answer.choice) == (Status.TODO, "")


def test_neurips_open_access_is_yes_from_a_doi_for_the_author_to_confirm(project):
    answer = neurips.checklist(project).answer("5")
    assert (answer.choice, answer.choice_from, answer.choice_note) == (
        "Yes",
        ("CITATION.cff",),
        "author: confirm this repository is public",
    )


def test_neurips_open_access_is_yes_from_a_github_repository_alone(tmp_path):
    (tmp_path / "codemeta.json").write_text(
        json.dumps({"codeRepository": "https://github.com/a/b"})
    )
    answer = neurips.checklist(Project.at(tmp_path)).answer("5")
    assert (answer.choice, answer.choice_from) == ("Yes", ("codemeta.json",))


def test_neurips_compute_stays_unchosen_though_re_runs_are_recorded(project):
    draft = neurips.checklist(project)
    assert draft.answer("8").status is Status.DRAFT
    assert {answer.question.id for answer in draft.answers if answer.choice} == {"5"}


def test_no_acl_answer_is_settled_by_a_public_repository(tmp_path):
    (tmp_path / "CITATION.cff").write_text(
        yaml.safe_dump({"doi": "10.5281/zenodo.9", "repository-code": "https://github.com/a/b"})
    )
    assert {a.question.id for a in acl.checklist(Project.at(tmp_path)).answers if a.choice} == set()


def test_an_origin_alone_does_not_settle_neurips_open_access(tmp_path):
    write_project(tmp_path)
    (tmp_path / "CITATION.cff").unlink()
    manifest = yaml.safe_load((tmp_path / "repro.yaml").read_text())
    manifest["artifacts"][1]["origin"] = {
        "repository": "https://github.com/someone-else/data",
        "commit": "f" * 40,
        "path": "raw.csv",
    }
    (tmp_path / "repro.yaml").write_text(yaml.safe_dump(manifest))
    assert neurips.checklist(Project.at(tmp_path)).answer("5").choice == ""


def test_the_help_of_each_command_says_what_it_answers(capsys):
    with pytest.raises(SystemExit):
        main(["venue", "neurips", "--help"])
    neurips_help = " ".join(capsys.readouterr().out.split())
    assert "Open access (5) is \\answerYes{}" in neurips_help
    assert "Every answer stays" not in neurips_help
    with pytest.raises(SystemExit):
        main(["venue", "acl", "--help"])
    assert "No question is answered yes or no" in " ".join(capsys.readouterr().out.split())


def test_a_doi_that_is_not_a_doi_does_not_answer_neurips_open_access(tmp_path):
    (tmp_path / "CITATION.cff").write_text(yaml.safe_dump({"doi": "TBD"}))
    assert neurips.checklist(Project.at(tmp_path)).answer("5").choice == ""
