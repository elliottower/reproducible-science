"""graph.json, built from a real project with the real `repro`."""

from __future__ import annotations

import json
import pathlib
import urllib.request

import pytest
from repro_ui import graph


def built(project: pathlib.Path, out: pathlib.Path, check: bool = True) -> dict:
    graph.build(project, out / "graph.json", check=check, fetch=False)
    return json.loads((out / "graph.json").read_text())


def test_a_verified_claim_is_counted_on_the_file_it_reads_and_the_section_it_is_in(
    project, tmp_path
):
    g = built(project, tmp_path / "out")
    results = next(n for n in g["nodes"] if n["id"] == "results")
    section = next(n for n in g["nodes"] if n["type"] == "section")
    assert (results["ok"], results["fail"]) == (1, 0)
    assert (section["label"], section["ok"], section["fail"]) == ("Section 1", 1, 0)
    assert g["totals"]["claims"] == 1
    assert {
        "source": "results",
        "target": "sec:Section 1",
        "kind": "supports",
        "count": 1,
    } in g["edges"]


def test_a_claim_fails_and_its_file_reads_changed_once_the_file_no_longer_holds_the_number(
    project, tmp_path
):
    (project / "results.json").write_text(json.dumps({"total": 7}))
    g = built(project, tmp_path / "out")
    results = next(n for n in g["nodes"] if n["id"] == "results")
    assert results["state"] == "changed"
    assert (results["ok"], results["fail"]) == (0, 1)
    assert g["totals"]["failing"] == 1


def test_a_project_that_declares_no_rebuild_step_builds_with_an_empty_reproduce_tab(
    project_without_steps, tmp_path
):
    # `repro stale` prints a sentence, not JSON, when nothing is declared; the build crashed on it.
    g = built(project_without_steps, tmp_path / "out")
    assert g["tabs"]["reproduce"]["steps"] == []
    assert g["totals"]["claims"] == 1


def test_a_rebuild_step_is_listed_with_the_files_it_reads_and_writes(project, tmp_path):
    g = built(project, tmp_path / "out")
    (step,) = g["tabs"]["reproduce"]["steps"]
    assert step["id"] == "results"
    assert step["output_path"] == "results.json"
    assert {i["path"] for i in step["inputs"]} == {"data.json", "make.py"}
    assert step["state"] == "never_rerun"
    assert step["history"] == []


def test_a_run_knows_whether_its_files_still_hold_what_it_wrote_and_which_outside_records_name_them(
    project, tmp_path
):
    recorded = graph.sha256(project / "results.json")
    ledger = project / ".results" / "ledger.jsonl"
    ledger.parent.mkdir()
    events = [
        {
            "event": "run",
            "run_id": "count",
            "timestamp": "2026-01-01T00:00:00+00:00",
            "note": "make.py",
            "outputs": [{"path": "results.json", "sha256": recorded}],
        },
        {
            "event": "annotation",
            "timestamp": "2026-01-02T00:00:00+00:00",
            "status": "linked, not checked",
            "subjects": [{"path": "results.json", "sha256": recorded, "kind": "file"}],
            "target": {
                "kind": "wandb:run",
                "ref": "https://wandb.ai/team/project/runs/abc",
            },
            "note": "",
        },
    ]
    ledger.write_text("".join(json.dumps(e) + "\n" for e in events))

    (run,) = built(project, tmp_path / "out")["tabs"]["results"]["runs"]
    assert run["files"] == [{"path": "results.json", "sha256": recorded, "on_disk": True}]
    (link,) = run["links"]
    assert (link["kind"], link["url"], link["same_bytes"]) == (
        "wandb:run",
        "https://wandb.ai/team/project/runs/abc",
        True,
    )

    (project / "results.json").write_text(json.dumps({"total": 7}))
    (run,) = built(project, tmp_path / "out", check=False)["tabs"]["results"]["runs"]
    assert run["files"][0]["on_disk"] is False


def test_without_fetch_a_doi_is_never_looked_up_and_a_cached_landing_page_is_still_used(
    monkeypatch,
):
    def refuse(*args, **kwargs):
        raise AssertionError("reached the network")

    monkeypatch.setattr(urllib.request, "urlopen", refuse)
    assert graph.landing_url("", "10.1/x", {}, fetch=False) == "https://doi.org/10.1/x"
    cache = {"https://doi.org/10.1/x": "https://publisher.example/article"}
    assert (
        graph.landing_url("", "10.1/x", cache, fetch=False) == "https://publisher.example/article"
    )
    assert (
        graph.landing_url("https://example.org/paper.pdf", "", {}, fetch=False)
        == "https://example.org/paper.pdf"
    )


@pytest.mark.parametrize(
    ("tex", "text"),
    [
        ('N\\"ust', "Nüst"),
        ("Vicentt\\'{\\i}n", "Vicenttín"),
        ("{\\o}stergaard", "østergaard"),
        ("\\c{c}a", "ça"),
        (
            "\\code{x}",
            "\\code{x}",
        ),  # a command that starts like an accent is left alone
        ("50\\% \\& more", "50% & more"),
    ],
)
def test_latex_accents_and_escapes_read_as_the_characters_they_print(tex, text):
    assert graph.latex_text(tex) == text
