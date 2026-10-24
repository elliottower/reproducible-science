"""`repro verify` checks every record a project keeps, in one report with one exit code.

Each test builds a real project -- a frozen plan, a ledger, a claims directory, a manifest --
with the tools themselves, and reads the exit code and the JSON. The case that matters most is
the one a summary could hide: a project in which one record fails while the claims verify.
"""

from __future__ import annotations

import json
import subprocess
import sys
from types import SimpleNamespace

import pytest
import yaml
from claims.cli import main as claims_main
from repro import ci, whole
from repro.cli import main
from repro.models import (
    ArtifactRef,
    Claim,
    Digest,
    InputReading,
    Manifest,
    MetricEvidence,
    Regeneration,
    RegenerationReason,
    RegenerationRecord,
    RegenerationState,
    ReproductionReport,
    RunOutput,
)
from repro.reproduce import append

SCRIPT = """
import json, pathlib
data = json.loads(pathlib.Path("inputs.json").read_text())
pathlib.Path("figures.json").write_text(json.dumps({"total": sum(data["xs"])}, indent=2))
"""

TEXT = "The quick brown fox jumps over the lazy dog near the quiet river bank at dawn.\n"
QUOTE = "quick brown fox jumps over the lazy dog"


def git(root, *args):
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def pin_manifest(root, script=False, reported="6"):
    """`repro.yaml` pinning the files as they are on disk now, with one claim reading the total
    from `figures.json`. With `script`, the command that writes it is declared."""
    names = ["inputs.json", "figures.json", *(["make.py"] if script else [])]

    def digest(name):
        return Digest.of_file(root / name)

    records = ()
    if script:
        records = (
            RegenerationRecord(
                id="sum",
                command=(sys.executable, "make.py"),
                inputs=(
                    RunOutput(artifact="inputs", digest=digest("inputs.json")),
                    RunOutput(artifact="make", digest=digest("make.py")),
                ),
                output=RunOutput(artifact="figures", digest=digest("figures.json")),
                timeout_seconds=60,
            ),
        )
    manifest = Manifest(
        project="study",
        path=root / "repro.yaml",
        artifacts=tuple(
            ArtifactRef(id=name.split(".")[0], path=root / name, digest=digest(name))
            for name in names
        ),
        regenerations=records,
        claims=(
            Claim(
                id="total",
                text="t",
                evidence=(
                    MetricEvidence(
                        artifact="figures", name="total", reported=reported, pointer="/total"
                    ),
                ),
            ),
        ),
    )
    dumped = manifest.model_dump(mode="json", exclude={"path"}, exclude_none=True)
    manifest.path.write_text(yaml.safe_dump(dumped))
    return manifest


def files(root, xs=(1, 2, 3)):
    (root / "inputs.json").write_text(json.dumps({"xs": list(xs)}))
    (root / "figures.json").write_text(json.dumps({"total": 6}, indent=2))
    (root / "make.py").write_text(SCRIPT)


def rerun(manifest):
    """Record a re-run of every declared command that reproduced over the pinned files."""
    root = manifest.path.parent
    written = Digest.of_file(root / "figures.json").value
    states = tuple(
        RegenerationState(
            regeneration_id=made.id,
            artifact_id=made.output.artifact,
            state=Regeneration.REPRODUCED,
            reason=RegenerationReason.OUTPUT_MATCHES,
            expected=written,
            actual=written,
            executed=True,
            bytes_identical=True,
            command=made.command,
            inputs=tuple(
                InputReading(
                    artifact_id=wanted.artifact,
                    path=wanted.artifact,
                    pinned=wanted.digest.value,
                    observed=wanted.digest.value,
                )
                for wanted in made.inputs
            ),
        )
        for made in manifest.regenerations
    )
    append(ReproductionReport(started_at="2026-01-01T00:00:00+00:00", regenerations=states), root)


def cite(root, name, quote=QUOTE):
    """A claims file pinning one source, on disk, by digest."""
    (root / "sources").mkdir(exist_ok=True)
    (root / "claims").mkdir(exist_ok=True)
    (root / "sources" / f"{name}.txt").write_text(TEXT)
    source = {
        "citation": name,
        "local": f"sources/{name}.txt",
        "sha256": Digest.of_text(TEXT).value,
    }
    document = {"source": source, "claims": {"c1": {"quotes": [{"exact": quote}]}}}
    (root / "claims" / f"{name}.yaml").write_text(yaml.safe_dump(document))


def freeze(root):
    assert main(["prereg", "new", ".", "--title", "study"]) == 0
    git(root, "add", "PREREG.md")
    git(root, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "--quiet", "-m", "plan")
    assert main(["prereg", "freeze"]) == 0


def ledger():
    assert main(["results", "init"]) == 0
    assert main(["results", "seal", "inputs.json"]) == 0
    assert main(["results", "run", "figures.json", "--run-id", "r1"]) == 0


@pytest.fixture
def project(tmp_path, monkeypatch):
    """An empty git repository as the working directory, sharing nothing with this machine."""
    monkeypatch.setenv("PROVENANCE_CALENDARS", "")
    monkeypatch.setenv("CITATIONS_NO_CACHE", "1")
    monkeypatch.setenv("REPRO_NO_HINT", "1")
    git(tmp_path, "init", "--quiet")
    monkeypatch.chdir(tmp_path)
    files(tmp_path)
    return tmp_path


@pytest.fixture
def every(project):
    """Every record: a frozen plan, a ledger, a pinned quotation, and a manifest whose one
    declared command has a recorded re-run over the files now on disk."""
    freeze(project)
    ledger()
    cite(project, "smith")
    rerun(pin_manifest(project, script=True))
    return project


def verified(capsys, *argv):
    """The exit code of `repro verify --format json`, and the document it printed."""
    capsys.readouterr()
    code = main(["verify", *argv, "--format", "json"])
    return code, json.loads(capsys.readouterr().out)


def test_every_record_is_checked_and_a_project_holding_all_of_them_passes(every, capsys):
    code, found = verified(capsys)
    assert code == 0
    assert found["project"]["checks"] == {
        "claims": "passed",
        "staleness": "passed",
        "prereg": "passed",
        "results": "passed",
        "citations": "passed",
        "cross_tool": "not used",
    }
    assert found["project"]["exit_code"] == 0
    assert found["prereg"]["command"] == ["prereg", "check"]
    assert found["results"]["command"] == ["results", "verify", "--files"]
    assert found["citations"]["account"]["counts"]["found"] == 1
    assert found["staleness"]["report"]["regenerations"][0]["state"] == "current"


def test_the_claims_report_is_where_and_what_it_was_and_the_tools_sit_beside_it(every, capsys):
    """Readers of `--format json` take `report` at the top level; it is `claims verify`'s."""
    _, found = verified(capsys)
    claims_main(["verify", "--format", "json"])
    alone = json.loads(capsys.readouterr().out)
    assert set(alone) == {"report", "assessment"}
    for key in ("report", "assessment"):
        assert found[key] == alone[key]
    claim = found["report"]["claims"][0]
    assert claim["claim_id"] == "total"
    decision = claim["decisions"][0]
    for key in ("kind", "artifact_id", "execution", "comparison", "reason", "detail", "warnings"):
        assert key in decision
    assert found["report"]["project"] == "study"
    assert found["report"]["manifest_digest"]
    assert set(found) == {
        "report",
        "assessment",
        "staleness",
        "prereg",
        "results",
        "citations",
        "cross_tool",
        "coverage",
        "project",
    }


def test_a_project_with_only_claims_names_every_other_record_as_unused(project, capsys):
    pin_manifest(project)
    code, found = verified(capsys)
    assert code == 0
    assert found["project"]["checks"] == {
        "claims": "passed",
        "staleness": "not used",
        "prereg": "not used",
        "results": "not used",
        "citations": "not used",
        "cross_tool": "not used",
    }
    for name in ("prereg", "results", "citations"):
        assert found[name]["used"] is False and found[name]["exit"] is None
    assert "regenerations" in found["staleness"]["reason"]

    assert main(["verify"]) == 0
    out = capsys.readouterr().out
    assert "1 of 1 checks passed" in out
    assert "not used here: staleness, prereg, results, citations" in out


def test_a_quotation_its_source_does_not_hold_fails_the_project_whose_claims_verify(
    project, capsys
):
    pin_manifest(project)
    cite(project, "smith", quote="a sentence the source never prints")
    code, found = verified(capsys)
    assert code == 1
    assert found["assessment"]["passed"] is True
    assert found["citations"]["outcome"] == "failed"
    assert found["project"]["checks"]["citations"] == "failed"

    assert main(["verify"]) == 1
    assert "1 of 2 checks passed; failed: citations" in capsys.readouterr().out


def test_a_frozen_plan_edited_after_its_freeze_fails_the_project(project, capsys):
    pin_manifest(project)
    freeze(project)
    plan = project / "PREREG.md"
    plan.chmod(0o644)
    plan.write_text(plan.read_text() + "\nAlso p < 0.10.\n")
    code, found = verified(capsys)
    assert code == 1
    assert found["prereg"]["outcome"] == "failed"
    assert found["project"]["checks"]["claims"] == "passed"
    assert found["project"]["checks"]["prereg"] == "failed"


def test_a_stale_claim_is_reported_and_fails_only_where_the_policy_says_stale_is_an_error(
    project, capsys
):
    rerun(pin_manifest(project, script=True))
    # The input changes after the re-run and is pinned again, so every pin is clean and the
    # number still verifies: only the record of re-runs can say the file is stale.
    files(project, xs=(1, 2, 4))
    pin_manifest(project, script=True)

    code, found = verified(capsys)
    assert code == 0
    assert found["staleness"]["report"]["claims"][0]["state"] == "stale"
    assert found["staleness"]["passed"] is True
    assert [v["rule"] for v in found["staleness"]["assessment"]["violations"]] == [
        "staleness.stale"
    ]

    code, found = verified(capsys, "--policy", "strict")
    assert code == 1
    assert found["assessment"]["passed"] is True
    assert found["project"]["checks"]["staleness"] == "failed"


def test_nothing_to_check_exits_2_and_a_project_without_a_manifest_is_still_checked(
    project, capsys
):
    for name in ("inputs.json", "figures.json", "make.py"):
        (project / name).unlink()
    code, found = verified(capsys)
    assert code == 2
    assert found["manifest"] is None
    assert set(found["project"]["checks"].values()) == {"not used"}
    assert main(["verify"]) == 2
    out = capsys.readouterr().out
    assert out.endswith(
        "    repro manifest init\n\nnot used here: claims, staleness, prereg, results, citations\n"
    )

    freeze(project)
    code, found = verified(capsys)
    assert code == 0
    assert found["manifest"] is None and found["verified"] == 0
    assert found["project"]["checks"]["claims"] == "not used"
    assert found["project"]["checks"]["prereg"] == "passed"

    # The claims are one section among the others, not a block saying nothing was checked.
    assert main(["verify"]) == 0
    out = capsys.readouterr().out
    assert "nothing was checked" not in out and "verified: 0" not in out
    assert "  claims       not used here: no repro.yaml here or above" in out
    assert "1 of 1 checks passed\nnot used here: claims, staleness, results, citations" in out


def test_a_check_that_could_not_be_made_is_said_so_and_fails_the_project(project, capsys):
    pin_manifest(project)
    assert main(["prereg", "new", ".", "--title", "study"]) == 0
    code, found = verified(capsys)
    assert code == 1
    assert found["prereg"]["outcome"] == "could not check"
    assert found["project"]["checks"]["prereg"] == "could not check"
    assert main(["verify"]) == 1
    assert "1 of 2 checks passed; could not check: prereg" in capsys.readouterr().out


def test_a_directory_names_the_project_checked(every, tmp_path, monkeypatch, capsys):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    code, found = verified(capsys, str(every))
    assert code == 0
    assert found["project"]["root"] == every.resolve().as_posix()
    assert found["prereg"]["used"] is True


def test_sarif_carries_each_checks_verdict_and_exits_as_the_project_does(project, capsys):
    pin_manifest(project)
    cite(project, "smith", quote="a sentence the source never prints")
    capsys.readouterr()
    assert main(["verify", "--format", "sarif"]) == 1
    run = json.loads(capsys.readouterr().out)["runs"][0]
    assert run["properties"]["passed"] is True
    assert run["properties"]["project"] == "study"
    assert run["properties"]["checks"]["sections"]["citations"] == "failed"
    assert run["properties"]["checks"]["exit_code"] == 1


def test_claims_verify_is_the_claims_alone(project, capsys):
    pin_manifest(project)
    cite(project, "smith", quote="a sentence the source never prints")
    assert claims_main(["verify"]) == 0
    assert "citations" not in capsys.readouterr().out


def test_check_is_no_longer_a_command(capsys):
    with pytest.raises(SystemExit) as raised:
        main(["check"])
    assert raised.value.code == 2
    assert "invalid choice: 'check'" in capsys.readouterr().err


def test_repro_claims_runs_claims_where_only_repro_is_on_path(project, capsys):
    pin_manifest(project, reported="7")
    capsys.readouterr()
    assert main(["claims", "verify", "--format", "json"]) == 1
    through_repro = capsys.readouterr().out
    assert claims_main(["verify", "--format", "json"]) == 1
    assert json.loads(through_repro) == json.loads(capsys.readouterr().out)
    assert main(["claims", "--version"]) == 0


def test_a_resealed_output_is_named_in_the_report_though_it_passes(project, capsys):
    ledger()
    (project / "figures.json").write_text(json.dumps({"total": 7}, indent=2))
    assert main(["results", "seal", "make.py"]) == 0
    assert main(["results", "run", "figures.json", "--run-id", "r2"]) == 0
    pin_manifest(project, reported="7")
    capsys.readouterr()

    assert main(["verify"]) == 0
    assert "RESEALED   figures.json" in capsys.readouterr().out


def test_an_output_recorded_again_with_nothing_sealed_fails_only_under_strict(project, capsys):
    ledger()
    (project / "figures.json").write_text(json.dumps({"total": 7}, indent=2))
    assert main(["results", "run", "figures.json", "--run-id", "r2", "--strict"]) == 1
    assert main(["results", "run", "figures.json", "--run-id", "r2"]) == 0
    pin_manifest(project, reported="7")

    code, found = verified(capsys)
    assert code == 0
    assert [v["rule"] for v in found["project"]["strict_failures"]] == ["results.rerecorded"]
    code, found = verified(capsys, "--policy", "strict")
    assert code == 1
    assert found["project"]["checks"]["results"] == "failed"


# -- the manuscript's coverage ----------------------------------------------------------------

PAPER = (
    "We report a total of 6.\n"
    f"As \\citet{{smith}} put it, ``{QUOTE}''.\n"
    "They also wrote that ``the treatment cured every patient in the trial''.\n"
)


def with_paper(root, text=PAPER, name="paper.tex"):
    """The manifest, with the manuscript declared as one of its artifacts."""
    (root / name).write_text(text)
    manifest = pin_manifest(root)
    document = yaml.safe_load(manifest.path.read_text())
    document["artifacts"].append(
        {"id": "paper", "path": name, "digest": Digest.of_file(root / name).model_dump()}
    )
    manifest.path.write_text(yaml.safe_dump(document))


def test_a_quotation_nothing_pins_warns_by_default_and_fails_under_strict(project, capsys):
    """The red-team attack: a fabricated quotation in the manuscript, which no claims file
    pins, passed `repro verify` under every policy."""
    cite(project, "smith")
    with_paper(project)
    code, found = verified(capsys)
    assert code == 0
    assert found["project"]["checks"]["coverage"] == "passed"
    statuses = [(q["line"], q["status"]) for q in found["coverage"]["quotations"]]
    assert statuses == [(2, "covered"), (3, "uncovered")]
    (warned,) = found["coverage"]["violations"]
    assert (warned["severity"], warned["rule"], warned["subject"]) == (
        "warning",
        "coverage.quotation_uncovered",
        "paper.tex:3",
    )
    assert [v["rule"] for v in found["project"]["strict_failures"]] == [
        "coverage.quotation_uncovered"
    ]

    code, found = verified(capsys, "--policy", "strict")
    assert code == 1
    assert found["project"]["checks"]["coverage"] == "failed"
    assert found["project"]["strict_failures"] == []


def test_a_number_no_run_binds_warns_by_default_and_fails_under_strict(project, capsys):
    ledger()
    with_paper(project, "We enrolled 57 participants and the ICC was 0.4213.\n", "paper.md")
    code, found = verified(capsys)
    assert code == 0
    (numbers,) = found["coverage"]["numbers"]
    assert numbers["manuscript"] == "paper.md" and numbers["unbound"] == 2
    assert [v["rule"] for v in found["coverage"]["violations"]] == ["coverage.numbers_unbound"]
    code, found = verified(capsys, "--policy", "strict")
    assert code == 1
    assert found["project"]["checks"]["coverage"] == "failed"


def test_the_summary_says_how_many_findings_strict_would_fail(project, capsys):
    cite(project, "smith")
    with_paper(project)
    capsys.readouterr()
    assert main(["verify"]) == 0
    out = capsys.readouterr().out
    (summary,) = [line for line in out.splitlines() if "checks passed" in line]
    assert summary == "3 of 3 checks passed (default policy; strict: 1 failure)"
    assert "  strict: coverage.quotation_uncovered" not in out

    assert main(["verify", "--explain"]) == 0
    out = capsys.readouterr().out
    assert "  strict: coverage.quotation_uncovered  paper.tex:3  " in out

    # Under strict the line is as it was, and so it is where strict would fail nothing.
    assert main(["verify", "--policy", "strict"]) == 1
    assert "2 of 3 checks passed; failed: coverage\n" in capsys.readouterr().out
    with_paper(project, PAPER.splitlines(keepends=True)[1])
    assert main(["verify"]) == 0
    assert "\n3 of 3 checks passed\n" in capsys.readouterr().out


def test_a_stale_claim_is_counted_among_what_strict_would_fail(project, capsys):
    rerun(pin_manifest(project, script=True))
    files(project, xs=(1, 2, 4))
    pin_manifest(project, script=True)
    capsys.readouterr()
    assert main(["verify"]) == 0
    assert "2 of 2 checks passed (default policy; strict: 1 failure)" in capsys.readouterr().out


def test_a_claim_number_its_run_does_not_hold_is_counted_among_what_strict_would_fail(
    project, capsys
):
    ledger()
    assert main(["results", "claim", "The total was 9.913.", "--run-id", "r1"]) == 0
    pin_manifest(project)
    code, found = verified(capsys)
    assert code == 0
    assert found["project"]["checks"]["results"] == "passed"
    (failure,) = found["project"]["strict_failures"]
    assert (failure["rule"], failure["subject"]) == ("results.claim_numbers_not_in_outputs", "r1")

    assert main(["verify"]) == 0
    out = capsys.readouterr().out
    assert "2 of 2 checks passed (default policy; strict: 1 failure)" in out


def test_a_coarse_reported_value_is_counted_among_what_strict_would_fail(project, capsys):
    (project / "figures.json").write_text(json.dumps({"total": 6.4}, indent=2))
    pin_manifest(project, reported="6")
    code, found = verified(capsys)
    assert code == 0
    assert [v["rule"] for v in found["project"]["strict_failures"]] == ["evidence.coarse_precision"]


def test_a_quotation_found_after_a_negation_is_counted_among_what_strict_would_fail(
    project, capsys
):
    cite(project, "smith", quote="the treatment reduced mortality in every subgroup")
    (project / "sources" / "smith.txt").write_text(
        "We found no evidence that the treatment reduced mortality in every subgroup we "
        "examined across the three sites.\n"
    )
    document = yaml.safe_load((project / "claims" / "smith.yaml").read_text())
    document["source"]["sha256"] = Digest.of_file(project / "sources" / "smith.txt").value
    (project / "claims" / "smith.yaml").write_text(yaml.safe_dump(document))
    pin_manifest(project)
    code, found = verified(capsys)
    assert code == 0
    assert found["project"]["checks"]["citations"] == "passed"
    assert [v["rule"] for v in found["project"]["strict_failures"]] == ["citations.after_negation"]


def test_what_the_default_run_says_strict_would_fail_is_what_strict_fails(project, capsys):
    ledger()
    assert main(["results", "claim", "The total was 9.913.", "--run-id", "r1"]) == 0
    cite(project, "smith", quote="the treatment reduced mortality in every subgroup")
    (project / "sources" / "smith.txt").write_text(
        "We found no evidence that the treatment reduced mortality in every subgroup we "
        "examined across the three sites.\n"
    )
    document = yaml.safe_load((project / "claims" / "smith.yaml").read_text())
    document["source"]["sha256"] = Digest.of_file(project / "sources" / "smith.txt").value
    (project / "claims" / "smith.yaml").write_text(yaml.safe_dump(document))
    pin_manifest(project)

    code, default = verified(capsys)
    assert code == 0
    named = sorted(v["rule"] for v in default["project"]["strict_failures"])
    assert named == ["citations.after_negation", "results.claim_numbers_not_in_outputs"]

    code, strict = verified(capsys, "--policy", "strict")
    assert code == 1
    failed = sorted(name for name, word in strict["project"]["checks"].items() if word == "failed")
    assert failed == sorted({rule.split(".")[0] for rule in named})
    assert "--strict" in strict["results"]["command"]
    assert "--strict" in strict["citations"]["command"]
    held = strict["results"]["account"]["claims_numbers_not_in_outputs"]
    negated = strict["citations"]["account"]["warnings"]["after negation"]
    assert len(held) + len(negated) == len(named)


def claimed_paper(root, text):
    """A manuscript the claim reads its sentence from, so `numbers` and coverage both count it."""
    with_paper(root, text, "paper.md")
    path = root / "repro.yaml"
    document = yaml.safe_load(path.read_text())
    document["claims"][0]["evidence"].append(
        {"kind": "quote", "artifact": "paper", "text": "We report a total of 6"}
    )
    path.write_text(yaml.safe_dump(document))


def test_unbound_numbers_are_reported_once_and_max_unbound_acts_on_that_report(project, capsys):
    ledger()
    claimed_paper(project, "We report a total of 6. We enrolled 57 people; the ICC was 0.4213.\n")
    code, found = verified(capsys)
    assert code == 0
    assert "numbers.unbound" not in [v["rule"] for v in found["assessment"]["violations"]]
    (unbound,) = [v for v in found["coverage"]["violations"] if "numbers" in v["rule"]]
    assert (unbound["rule"], unbound["severity"]) == ("coverage.numbers_unbound", "warning")

    code, found = verified(capsys, "--max-unbound", "0")
    assert code == 1
    assert found["project"]["checks"]["coverage"] == "failed"
    assert "numbers.unbound" not in [v["rule"] for v in found["assessment"]["violations"]]


def test_without_a_ledger_the_claims_section_keeps_the_unbound_numbers(project, capsys):
    claimed_paper(project, "We report a total of 6. We enrolled 57 people; the ICC was 0.4213.\n")
    code, found = verified(capsys)
    assert code == 0
    assert "numbers.unbound" in [v["rule"] for v in found["assessment"]["violations"]]


def test_a_markdown_manuscript_is_read_as_markdown(project, capsys):
    cite(project, "smith")
    text = (
        "We report a total of 6.\n\n"
        "> the treatment cured every patient in the trial and then some\n\n"
        'About 50% agreed, and one wrote "the second fabricated passage nobody pinned" later.\n'
    )
    with_paper(project, text, "paper.md")
    code, found = verified(capsys)
    assert code == 0
    quoted = [q["text"] for q in found["coverage"]["quotations"]]
    assert any("cured every patient" in q for q in quoted)
    assert any("second fabricated passage" in q for q in quoted)


def test_a_preregistration_a_claim_quotes_is_not_read_as_the_manuscript(project, capsys):
    cite(project, "smith")
    (project / "PREREG.md").write_text('H1 holds. "An unpinned quotation in the plan itself."\n')
    manifest = pin_manifest(project)
    document = yaml.safe_load(manifest.path.read_text())
    document["artifacts"].append(
        {
            "id": "plan",
            "path": "PREREG.md",
            "digest": Digest.of_file(project / "PREREG.md").model_dump(),
        }
    )
    document["claims"][0]["evidence"].append(
        {"kind": "quote", "artifact": "plan", "text": "H1 holds"}
    )
    manifest.path.write_text(yaml.safe_dump(document))
    _, found = verified(capsys)
    assert "PREREG.md" not in found["coverage"].get("manuscripts", ())


def test_a_quotation_with_two_strict_warnings_counts_once():
    quote = {"claim": "smith:c1", "quote": "the treatment reduced mortality", "state": "found"}
    account = {
        "strict_warnings": ["after negation", "references"],
        "warnings": {"after negation": [quote], "references": [quote], "after hedge": [quote]},
    }
    run = ci.ToolRun(check="citations", command=("citations",), outcome="passed", account=account)
    found = whole._tool_strict(SimpleNamespace(tools={"citations": run}))
    assert [(v.rule, v.subject) for v in found] == [
        ("citations.after_negation+references", "smith:c1")
    ]


def test_a_derived_claim_is_counted_on_the_results_line_and_listed_with_explain(project, capsys):
    ledger()
    how = "the mean of the per-family values"
    assert (
        main(["results", "claim", "The mean was 0.872.", "--run-id", "r1", "--derived", how]) == 0
    )
    pin_manifest(project)
    capsys.readouterr()
    assert main(["verify"]) == 0
    out = capsys.readouterr().out
    assert "1 claim(s) marked derived, their numbers not compared with outputs" in out
    assert how not in out
    assert main(["verify", "--explain"]) == 0
    assert f"derived: {how}" in capsys.readouterr().out
    _, found = verified(capsys)
    assert found["project"]["strict_failures"] == []


def test_a_declared_manuscript_missing_is_said_and_no_other_file_is_read(project, capsys):
    ledger()
    claimed_paper(project, "We report a total of 6. We enrolled 57 people; the ICC was 0.4213.\n")
    (project / "paper.md").rename(project / "elsewhere.txt")
    (project / "NOTES.md").write_text("A result file printing 0.123 and 0.456.\n")
    manifest = project / "repro.yaml"
    document = yaml.safe_load(manifest.read_text())
    document["artifacts"].append(
        {
            "id": "notes",
            "path": "NOTES.md",
            "digest": Digest.of_file(project / "NOTES.md").model_dump(),
        }
    )
    manifest.write_text(yaml.safe_dump(document))
    _, found = verified(capsys)
    rules = [(v["rule"], v["subject"]) for v in found["coverage"]["violations"]]
    assert ("coverage.manuscript_missing", "paper.md") in rules
    assert found["coverage"]["manuscripts"] == []


def test_an_invisible_character_in_a_listed_claim_is_shown_as_its_escape():
    assert whole._escaped("0.71​57") == "0.71\\u200b57"


def test_a_missing_text_a_claim_names_is_reported_whatever_its_suffix(project, capsys):
    ledger()
    claimed_paper(project, "We report a total of 6.\n")
    manifest = project / "repro.yaml"
    document = yaml.safe_load(manifest.read_text())
    (project / "paper.md").rename(project / "paper.txt")
    for artifact in document["artifacts"]:
        if artifact["id"] == "paper":
            artifact["path"] = "paper.txt"
    manifest.write_text(yaml.safe_dump(document))
    (project / "paper.txt").rename(project / "gone.txt")
    _, found = verified(capsys)
    rules = [(v["rule"], v["subject"]) for v in found["coverage"]["violations"]]
    assert ("coverage.manuscript_missing", "paper.txt") in rules
