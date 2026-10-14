"""`repro venue acm-evidence`: which records are listed under which criterion, and an output
that never reads as a badge."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import pathlib
import re

import pytest
import yaml
from repro.cli import main
from repro.venue import acm_evidence
from repro.venue.acm_evidence import LABEL, Standing, as_html, evidence_map
from repro.venue.records import Project

_SPEC = importlib.util.spec_from_file_location(
    "venue_acm", pathlib.Path(__file__).with_name("test_venue_acm.py")
)
assert _SPEC is not None and _SPEC.loader is not None
helpers = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(helpers)
write_project = helpers.write_project

#: The names of ACM's badges. None may label anything or stand as a status in the output.
BADGE_NAMES = (
    "Artifacts Available",
    "Artifacts Evaluated",
    "Functional",
    "Reusable",
    "Results Validated",
    "Results Reproduced",
    "Results Replicated",
)

ORIGIN = "0123456789abcdef0123456789abcdef01234567"


def by_id(made):
    return {mapped.criterion.id: mapped for mapped in made.criteria}


def said(mapped):
    return [(finding.record, finding.said) for finding in mapped.findings]


def test_the_archival_criterion_lists_the_doi_and_no_third_party_origin(tmp_path):
    write_project(tmp_path)
    manifest = yaml.safe_load((tmp_path / "repro.yaml").read_text())
    manifest["artifacts"][1]["origin"] = {
        "repository": "https://github.com/someone-else/data",
        "commit": ORIGIN,
        "path": "raw.csv",
    }
    (tmp_path / "repro.yaml").write_text(yaml.safe_dump(manifest))
    archival = by_id(evidence_map(Project.at(tmp_path)))["archival"]
    assert archival.standing is Standing.LISTED
    assert said(archival) == [("CITATION.cff", "names DOI 10.5281/zenodo.42")]


def test_an_origin_alone_lists_nothing_under_the_archival_criterion(tmp_path):
    write_project(tmp_path)
    (tmp_path / "CITATION.cff").unlink()
    manifest = yaml.safe_load((tmp_path / "repro.yaml").read_text())
    manifest["artifacts"][1]["origin"] = {
        "repository": "https://github.com/someone-else/data",
        "commit": ORIGIN,
        "path": "raw.csv",
    }
    (tmp_path / "repro.yaml").write_text(yaml.safe_dump(manifest))
    assert by_id(evidence_map(Project.at(tmp_path)))["archival"].standing is Standing.NONE


def test_the_two_criteria_about_results_obtained_by_others_are_never_determined(tmp_path):
    made = by_id(evidence_map(Project.at(write_project(tmp_path))))
    for criterion in ("by-others-with-artifacts", "by-others-independently"):
        assert made[criterion].standing is Standing.NOT_DETERMINABLE
        assert made[criterion].findings == ()


def test_the_exercisable_criterion_lists_commands_re_runs_claims_and_documentation(tmp_path):
    write_project(tmp_path)
    (tmp_path / "README.md").write_text("# Demo\n\nRun make.\n")
    exercisable = by_id(evidence_map(Project.at(tmp_path)))["exercisable"]
    assert exercisable.records == (
        "repro.yaml",
        ".repro/reproductions.jsonl",
        ".results/ledger.jsonl",
        "README.md",
        "CITATION.cff",
    )
    assert ("README.md", "is present, 3 lines") in said(exercisable)


def test_reuse_adds_the_license_and_the_environment_to_what_exercisable_lists(tmp_path):
    made = by_id(evidence_map(Project.at(write_project(tmp_path))))
    extra = set(said(made["reuse"])) - set(said(made["exercisable"]))
    assert extra == {
        ("LICENSE", "is present; its first line reads `MIT License`"),
        ("CITATION.cff", "names the license MIT"),
        ("uv.lock", "is present"),
    }


def test_a_project_with_no_records_lists_none_under_any_criterion(tmp_path):
    made = by_id(evidence_map(Project.at(tmp_path)))
    assert {criterion: mapped.standing for criterion, mapped in made.items()} == {
        "archival": Standing.NONE,
        "exercisable": Standing.NONE,
        "reuse": Standing.NONE,
        "by-others-with-artifacts": Standing.NOT_DETERMINABLE,
        "by-others-independently": Standing.NOT_DETERMINABLE,
    }


#: The criteria's words as they stand in the saved v1.1 page, typed here from that copy rather
#: than read back from the package, with the sha256 of each.
POLICY_V1_1 = {
    "archival": (
        "Author-created artifacts relevant to this paper have been placed on a publically "
        "accessible archival repository. A DOI or link to this repository along with a unique "
        "identifier for the object is provided."
    ),
    "by-others-with-artifacts": (
        "The main results of the paper have been obtained in a subsequent study by a person or "
        "team other than the authors, using, in part, artifacts provided by the author."
    ),
}


def test_the_policy_text_is_the_saved_v1_1_text_and_each_quotation_is_pinned():
    policy = acm_evidence.policy()
    assert policy.version == "1.1"
    assert policy.source.retrieved.isoformat() == "2026-10-11"
    assert "saved from a browser" in policy.source.via.lower()
    criteria = {criterion.id: criterion for criterion in policy.criteria}
    for criterion_id, words in POLICY_V1_1.items():
        assert criteria[criterion_id].policy_text == words
    for criterion in criteria.values():
        digest = hashlib.sha256(criterion.policy_text.encode("utf-8")).hexdigest()
        assert criterion.quoted_sha256 == digest
        assert criterion.source_line > 0
    assert set(acm_evidence.READS) == {c.id for c in criteria.values() if c.determinable}


def test_acm_evidence_takes_no_plan(capsys):
    with pytest.raises(SystemExit):
        main(["venue", "acm-evidence", "--plan", "PREREG.md"])


def test_the_page_carries_the_label_and_no_badge_name_outside_the_quoted_policy(tmp_path):
    page = as_html(evidence_map(Project.at(write_project(tmp_path))))
    assert f"<h1>{LABEL}</h1>" in page
    assert f"<title>{LABEL}</title>" in page
    assert "<img" not in page and "<svg" not in page
    outside = re.sub(r"<blockquote>.*?</blockquote>", "", page, flags=re.S)
    for name in BADGE_NAMES:
        assert name not in outside
    standings = re.findall(r'<p class="standing">(.*?)</p>', page)
    assert standings == [
        "DRAFT: records listed",
        "DRAFT: records listed",
        "DRAFT: records listed",
        "TODO: not determinable by this tool",
        "TODO: not determinable by this tool",
    ]
    header = page[page.index("<header>") : page.index("</header>")]
    assert '<p class="draft"><strong>DRAFT. Generated by a program' in header


def test_markup_in_a_finding_is_escaped(tmp_path):
    write_project(tmp_path)
    manifest = yaml.safe_load((tmp_path / "repro.yaml").read_text())
    manifest["regenerations"][0]["command"] = ["sh", "-c", "make <table>"]
    (tmp_path / "repro.yaml").write_text(yaml.safe_dump(manifest))
    page = as_html(evidence_map(Project.at(tmp_path)))
    assert "&lt;table&gt;" in page
    assert "<table>" not in page


def test_json_carries_the_label_and_each_standing(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(write_project(tmp_path))
    assert main(["venue", "acm-evidence", "--format", "json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["label"] == LABEL
    assert [c["standing"] for c in data["criteria"]] == [
        "records listed",
        "records listed",
        "records listed",
        "not determinable by this tool",
        "not determinable by this tool",
    ]
    assert data["criteria"][0]["records"] == ["CITATION.cff"]
    assert data["status"] == "draft"
    assert data["draft_notice"].startswith("DRAFT.")
    assert [c["status"] for c in data["criteria"]] == ["draft", "draft", "draft", "todo", "todo"]
    assert (
        data["criteria"][0]["criterion"]["quoted_sha256"]
        == hashlib.sha256(POLICY_V1_1["archival"].encode()).hexdigest()
    )


def test_a_criterion_with_no_record_is_marked_todo(tmp_path):
    page = as_html(evidence_map(Project.at(tmp_path)))
    assert re.findall(r'<p class="standing">(.*?)</p>', page)[:3] == ["TODO: no record found"] * 3


def test_a_doi_that_is_not_a_doi_lists_nothing_under_archival(tmp_path):
    (tmp_path / "CITATION.cff").write_text(yaml.safe_dump({"doi": "TBD"}))
    assert by_id(evidence_map(Project.at(tmp_path)))["archival"].standing is Standing.NONE


def test_a_backtick_in_a_command_is_one_code_element_in_the_page(tmp_path):
    write_project(tmp_path)
    manifest = yaml.safe_load((tmp_path / "repro.yaml").read_text())
    manifest["regenerations"][0]["command"] = ["sh", "-c", "echo `date`"]
    (tmp_path / "repro.yaml").write_text(yaml.safe_dump(manifest))
    page = as_html(evidence_map(Project.at(tmp_path)))
    assert "<code>sh -c &#x27;echo `date`&#x27;</code>" in page
