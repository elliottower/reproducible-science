"""`repro verify` and `repro ci` count a `corrected` quotation, and grade it under the policy.

A correction is a person's record of what the page prints, so a quotation resolved against one
is counted apart from `found`, graded as `Policy.quotation_corrected` says, and a grade of error
fails the citations check in the text line and the JSON alike.
"""

from __future__ import annotations

import json
import subprocess

import pytest
from citations import pin
from claims.policy import PROFILES, PUBLICATION, Severity
from repro import ci
from repro.cli import main

TEXT = "Table 2 reports that the coefficient of eciency was 0.81 across all twelve sites.\n"
QUOTE = "the coefficient of efficiency was 0.81 across all twelve sites"
PRINTED = "Table 2 reports that the coefficient of efficiency was 0.81 across all twelve sites."


@pytest.fixture
def project(tmp_path, monkeypatch):
    """A git repository holding one claims file whose one quotation is pinned with a correction."""
    monkeypatch.setenv("PROVENANCE_CALENDARS", "")
    monkeypatch.setenv("CITATIONS_NO_CACHE", "1")
    monkeypatch.setenv("REPRO_NO_HINT", "1")
    subprocess.run(["git", "init", "--quiet"], cwd=tmp_path, check=True)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "sources").mkdir()
    (tmp_path / "sources" / "smith.txt").write_text(TEXT)
    (tmp_path / "claims").mkdir()
    f = tmp_path / "claims" / "smith.yaml"
    f.write_text("source:\n  citation: smith\n  local: sources/smith.txt\nclaims: {}\n")
    assert (
        pin.main(
            [
                *(str(f), "--id", "eff", "--quote", QUOTE, "--page", "4"),
                *("--correct", PRINTED, "--reads", "the coefficient of eciency was 0.81"),
            ]
        )
        == 0
    )
    return tmp_path


def verified(capsys, *argv):
    capsys.readouterr()
    code = main(["verify", *argv, "--format", "json"])
    return code, json.loads(capsys.readouterr().out)


def test_a_corrected_quotation_passes_with_a_warning_under_publication(project, capsys):
    code, found = verified(capsys)
    assert code == 0
    cited = found["citations"]
    assert cited["passed"] is True and cited["outcome"] == "passed"
    assert cited["account"]["counts"]["corrected"] == 1
    assert [v["rule"] for v in cited["assessment"]["violations"]] == ["citations.corrected"]
    assert cited["assessment"]["violations"][0]["severity"] == "warning"

    assert main(["verify"]) == 0
    out = capsys.readouterr().out
    assert "  citations    passed  (" in out
    assert "warning under policy publication: 1 quotation found in a passage recorded" in out


def test_a_policy_making_corrected_an_error_fails_the_line_the_json_and_the_exit_code(
    project, capsys, monkeypatch
):
    monkeypatch.setitem(
        PROFILES,
        "publication",
        PUBLICATION.model_copy(update={"quotation_corrected": Severity.ERROR}),
    )
    code, found = verified(capsys)
    assert code == 1
    assert found["citations"]["passed"] is False
    assert found["citations"]["outcome"] == "failed"
    assert found["project"]["checks"]["citations"] == "failed"

    assert main(["verify"]) == 1
    out = capsys.readouterr().out
    assert "  citations    FAILED under policy publication  (" in out
    assert "  citations    passed" not in out


def test_ci_counts_a_corrected_quotation_as_checked_and_names_it_apart_from_found():
    run = ci.ToolRun(
        check="citations",
        command=("citations", "verify", "--claims", "claims"),
        exit=0,
        outcome="passed",
        account={"quotes": 5, "counts": {"found": 4, "corrected": 1, "not found": 0}},
    )
    assert ci.unchecked(run) == 0
    said = ci.tool_summary(run)
    assert "**passed** (exit 0)" in said
    assert "4 found, 0 not found, 0 unchecked, 1 corrected of 5 quotations" in said
