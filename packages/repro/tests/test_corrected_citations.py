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
READS = "the coefficient of eciency was 0.81 across all twelve sites"


def corrected_project(root, monkeypatch, text=TEXT, quote=QUOTE, printed=PRINTED, reads=READS):
    """A git repository holding one claims file whose one quotation is pinned with a correction."""
    monkeypatch.setenv("PROVENANCE_CALENDARS", "")
    monkeypatch.setenv("CITATIONS_NO_CACHE", "1")
    monkeypatch.setenv("REPRO_NO_HINT", "1")
    subprocess.run(["git", "init", "--quiet"], cwd=root, check=True)
    monkeypatch.chdir(root)
    (root / "sources").mkdir()
    (root / "sources" / "smith.txt").write_text(text)
    (root / "claims").mkdir()
    f = root / "claims" / "smith.yaml"
    f.write_text("source:\n  citation: smith\n  local: sources/smith.txt\nclaims: {}\n")
    assert (
        pin.main(
            [
                *(str(f), "--id", "eff", "--quote", quote, "--page", "4"),
                *("--correct", printed, "--reads", reads),
            ]
        )
        == 0
    )
    return root


@pytest.fixture
def project(tmp_path, monkeypatch):
    return corrected_project(tmp_path, monkeypatch)


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


def test_a_correction_that_adds_a_not_is_named_with_its_warning_under_every_policy(
    tmp_path, monkeypatch, capsys
):
    corrected_project(
        tmp_path,
        monkeypatch,
        text="Studies find that reproducibility increases impact, visibility, and trust.\n",
        quote="reproducibility does not increase impact",
        printed="reproducibility does not increase impact, visibility, and",
        reads="reproducibility increases impact, visibility, and",
    )
    code, found = verified(capsys)
    assert code == 0
    assert found["citations"]["account"]["corrected"][0]["flags"] == ["correction adds a negation"]
    for policy in ("publication", "exploratory"):
        capsys.readouterr()
        assert main(["verify", "--policy", policy]) == 0
        out = capsys.readouterr().out
        assert (
            "      1 corrected by hand; `citations verify --claims claims` shows what each "
            "correction changes\n"
            f"        smith:eff{' ' * 31}correction adds a negation\n"
        ) in out


def test_a_claims_file_citations_refuses_fails_the_check_under_every_policy_naming_it(
    project, capsys
):
    f = project / "claims" / "smith.yaml"
    lines = f.read_text().splitlines(keepends=True)
    at = next(i for i, line in enumerate(lines) if line.strip() == "correction:")
    indent = lines[at + 1][: len(lines[at + 1]) - len(lines[at + 1].lstrip())]
    lines.insert(at + 1, f"{indent}passage: Table 2 reports that the coefficient was 0.18.\n")
    f.write_text("".join(lines))
    (project / "sources" / "jones.txt").write_text("Plain text quoted exactly as written here.\n")
    (project / "claims" / "jones.yaml").write_text(
        "source:\n  citation: jones\n  local: sources/jones.txt\n"
        "claims:\n  a:\n    quotes:\n    - exact: Plain text quoted exactly as written here\n"
    )
    why = "smith.yaml: not valid YAML: a correction carries `passage` twice"
    for policy in ("exploratory", "publication", "strict"):
        code, found = verified(capsys, "--policy", policy)
        assert code == 1
        cited = found["citations"]
        assert cited["passed"] is False and cited["outcome"] == "failed"
        assert cited["account"]["counts"]["found"] == 1
        assert cited["account"]["skipped_files"] == 1
        assert found["project"]["checks"]["citations"] == "failed"

        assert main(["verify", "--policy", policy]) == 1
        out = capsys.readouterr().out
        assert "  citations    FAILED (exit 1)  (citations verify --claims claims)" in out
        assert f"refused  {why}" in out
        assert "citations    passed" not in out
        assert "0 of 1 checks passed; failed: citations" in out


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
