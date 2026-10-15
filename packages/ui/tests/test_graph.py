"""graph.json, built from a real project with the real `repro`."""

from __future__ import annotations

import hashlib
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


def test_a_project_keeping_no_plan_ledger_or_quotations_says_so_on_each_line_and_has_no_issues(
    project, tmp_path
):
    for check in (True, False):
        g = built(project, tmp_path / "out", check=check)
        s = g["status"]
        assert [s[k]["state"] for k in ("prereg", "results", "citations")] == ["none"] * 3
        assert s["claims"] == {"state": "read", "total": 1, "verified": 1, "ok": True}
        assert g["issues"] == []
        assert g["tabs"]["prereg"] == {
            "plans": [],
            "used": False,
            "output": g["tabs"]["prereg"]["output"],
        }


def test_each_record_verify_reads_gives_its_count_and_each_kind_of_problem_one_row(kept, tmp_path):
    g = built(kept, tmp_path / "out")
    s = g["status"]
    assert (s["prereg"]["plans"], s["prereg"]["frozen"], s["prereg"]["changed"]) == (1, 0, 1)
    assert (s["results"]["runs"], s["results"]["sealed"], s["results"]["changed"]) == (1, 1, 3)
    assert (s["citations"]["quotes"], s["citations"]["found"], s["citations"]["not_found"]) == (
        2,
        1,
        1,
    )
    assert (s["claims"]["verified"], s["claims"]["total"]) == (1, 1)

    rows = {r["id"]: r for r in g["issues"]}
    assert set(rows) == {"prereg-changed", "results-changed", "citations-not-found"}
    assert rows["prereg-changed"]["title"] == "PREREG.md changed after it was frozen"
    freeze = json.loads((kept / ".prereg" / "PREREG.md.json").read_text())
    (plan,) = rows["prereg-changed"]["items"]
    assert plan["diff"] == {"commit": freeze["commit"], "sha256": freeze["sha256"]}

    sealed = {i["label"]: i for i in rows["results-changed"]["items"]}
    assert set(sealed) == {"data.json", "blob.bin", "scratch.txt"}
    assert sealed["data.json"]["open"]["run"]["run_id"] == "count"
    # A commit holds the sealed bytes of the two committed files, and none holds scratch.txt's.
    assert sealed["data.json"]["diff"]["commit"] and sealed["blob.bin"]["diff"]["commit"]
    assert sealed["scratch.txt"]["diff"]["commit"] is None

    (quote,) = rows["citations-not-found"]["items"]
    assert rows["citations-not-found"]["title"] == "1 quotation not found in its source (fox2020)"
    assert quote["open"]["quote"] == {"file": "claims/fox.yaml", "statement": "sleeps", "index": 0}


def test_a_refresh_rereads_the_plans_and_the_ledger_without_running_verify(kept, tmp_path):
    out = tmp_path / "out"
    built(kept, out)
    checks = len(graph.read_checks(kept))
    (kept / "data.json").write_text(json.dumps({"values": [1, 2, 3]}))
    (kept / "blob.bin").unlink()
    g = built(kept, out, check=False)
    assert len(graph.read_checks(kept)) == checks
    rows = {r["id"]: r for r in g["issues"]}
    assert {i["label"] for i in rows["results-changed"]["items"]} == {"scratch.txt"}
    assert [i["label"] for i in rows["results-missing"]["items"]] == ["blob.bin"]
    # The quotations keep what the last check found: a refresh does not read every source.
    assert "citations-not-found" in rows


def test_a_diff_shows_the_frozen_or_sealed_bytes_against_the_file_now(kept, sealed_blob, tmp_path):
    g = built(kept, tmp_path / "out")
    plan = graph.issue_diff(kept, g, "prereg-changed", "PREREG.md")
    assert "+A line added after the freeze." in plan["diff"].splitlines()
    assert (
        plan["old"]["sha256"]
        == json.loads((kept / ".prereg" / "PREREG.md.json").read_text())["sha256"]
    )

    data = graph.issue_diff(kept, g, "results-changed", "data.json")
    assert data["diff"].splitlines()[-4:] == [
        '-{"values": [1, 2, 3]}',
        "\\ No newline at end of file",
        '+{"values": [1, 2, 3, 4]}',
        "\\ No newline at end of file",
    ]

    blob = graph.issue_diff(kept, g, "results-changed", "blob.bin")
    assert (blob["binary"], blob["diff"]) == (True, "")
    assert blob["old"] == {
        "sha256": hashlib.sha256(sealed_blob).hexdigest(),
        "size": len(sealed_blob),
    }
    assert blob["new"]["sha256"] == hashlib.sha256(sealed_blob[::-1]).hexdigest()

    scratch = graph.issue_diff(kept, g, "results-changed", "scratch.txt")
    assert scratch["old"] is None
    assert scratch["note"] == "No copy of the sealed bytes was kept: no commit holds them."


def test_a_diff_is_refused_for_anything_the_issues_do_not_name(kept, tmp_path):
    g = built(kept, tmp_path / "out")
    (kept.parent / "secret.txt").write_text("not the page's to show")
    for issue, path in [
        ("results-changed", "repro.yaml"),
        ("prereg-changed", "data.json"),
        ("results-changed", "../secret.txt"),
        ("results-changed", "/etc/hosts"),
        ("results-changed", "./data.json"),
        ("not-an-issue", "data.json"),
        ("citations-not-found", "claims/fox.yaml"),
    ]:
        with pytest.raises(graph.NotNamed):
            graph.issue_diff(kept, g, issue, path)


def test_a_path_an_issue_names_that_leads_out_of_the_project_is_refused(kept, tmp_path):
    g = built(kept, tmp_path / "out")
    item = g["issues"][1]["items"][0]
    item["open"]["path"] = "../secret.txt"
    (kept.parent / "secret.txt").write_text("not the page's to show")
    with pytest.raises(graph.NotNamed):
        graph.issue_diff(kept, g, g["issues"][1]["id"], "../secret.txt")


def test_the_prereg_and_results_lines_are_ok_once_the_plan_and_the_sealed_files_are_restored(
    kept, tmp_path, tools
):
    s = built(kept, tmp_path / "out")["status"]
    assert (s["prereg"]["ok"], s["results"]["ok"]) == (False, False)
    tools.git(kept, "checkout", "--", "PREREG.md", "data.json", "blob.bin")
    (kept / "scratch.txt").write_text("never committed\n")
    g = built(kept, tmp_path / "out")
    s = g["status"]
    assert s["prereg"] == {
        "state": "read",
        "plans": 1,
        "frozen": 1,
        "changed": 0,
        "drafts": 0,
        "amendments": 0,
        "unknown": 0,
        "ok": True,
    }
    assert (s["results"]["sealed"], s["results"]["runs"], s["results"]["ok"]) == (1, 1, True)
    assert [r["id"] for r in g["issues"]] == ["citations-not-found"]


def test_runs_with_nothing_sealed_before_them_are_one_row_with_a_note_and_nothing_to_click(
    project, tmp_path, tools
):
    tools.cli(project, "results", "init")
    tools.cli(project, "results", "run", "--run-id", "count", "results.json")
    g = built(project, tmp_path / "out")
    assert (g["status"]["results"]["sealed"], g["status"]["results"]["runs"]) == (0, 1)
    assert g["status"]["results"]["ok"] is False
    (row,) = g["issues"]
    assert (row["id"], row["fix"], row["items"]) == ("results-unsealed", False, [])
    assert row["title"] == "1 run with nothing sealed before it"


def test_a_refresh_and_a_check_agree_on_whether_the_project_keeps_plans_or_a_ledger(
    project, tmp_path
):
    (project / ".prereg").mkdir()
    (project / ".results").mkdir()
    checked = built(project, tmp_path / "out")
    refreshed = built(project, tmp_path / "out", check=False)
    for key in ("prereg", "results"):
        assert refreshed["status"][key] == checked["status"][key], key
    assert [r["id"] for r in refreshed["issues"]] == [r["id"] for r in checked["issues"]]


def test_a_commit_that_reads_as_an_option_never_reaches_git(kept, tmp_path):
    g = built(kept, tmp_path / "out")
    written = tmp_path / "written"
    (row,) = [r for r in g["issues"] if r["id"] == "prereg-changed"]
    row["items"][0]["diff"]["commit"] = f"--output={written}"
    d = graph.issue_diff(kept, g, "prereg-changed", "PREREG.md")
    assert d["old"] is None
    assert not written.exists()


def test_a_project_in_a_subfolder_finds_the_commit_of_each_sealed_file_despite_spaces_deletions_and_paths_outside(
    tmp_path, tools
):
    outer = tmp_path / "repo"
    sub = outer / "paper"
    sub.mkdir(parents=True)
    tools.write_project(sub, with_step=False)
    tools.git(outer, "init", "-q")
    spaced = sub / "c d.txt"
    spaced.write_text("first\n")
    tools.git(outer, "add", "-A")
    tools.git(outer, "commit", "-q", "-m", "first")
    first = tools.git(outer, "rev-parse", "HEAD")
    tools.git(outer, "rm", "-q", "paper/c d.txt")
    tools.git(outer, "commit", "-q", "-m", "deleted")
    spaced.write_text("second\n")
    (tmp_path / "secret.txt").write_text("outside the repository\n")
    (sub / "link.txt").symlink_to(tmp_path / "secret.txt")
    tools.cli(sub, "results", "init")
    tools.cli(sub, "results", "seal", "data.json", "c d.txt", "link.txt")
    tools.git(outer, "add", "-A")
    tools.git(outer, "commit", "-q", "-m", "sealed")
    sealed_at = tools.git(outer, "rev-parse", "HEAD")
    (sub / "data.json").write_text(json.dumps({"values": [1, 2, 3, 4]}))
    spaced.write_text("third\n")
    (tmp_path / "secret.txt").write_text("changed outside\n")

    g = built(sub, tmp_path / "out")
    items = {i["label"]: i for r in g["issues"] if r["tool"] == "results" for i in r["items"]}
    # The oldest commit holding the sealed bytes: data.json is unchanged since the first.
    assert items["data.json"]["diff"]["commit"] == first
    assert items["c d.txt"]["diff"]["commit"] == sealed_at
    d = graph.issue_diff(sub, g, "results-changed", "c d.txt")
    assert [x for x in d["diff"].splitlines() if x[:1] in "+-" and x[:3] not in ("+++", "---")] == [
        "-second",
        "+third",
    ]
