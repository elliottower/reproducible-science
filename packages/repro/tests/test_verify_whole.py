"""`repro verify` checks every record a project keeps, in one report with one exit code.

Each test builds a real project -- a frozen plan, a ledger, a claims directory, a manifest --
with the tools themselves, and reads the exit code and the JSON. The case that matters most is
the one a summary could hide: a project in which one record fails while the claims verify.
"""

from __future__ import annotations

import json
import subprocess
import sys

import pytest
import yaml
from claims.cli import main as claims_main
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

    freeze(project)
    code, found = verified(capsys)
    assert code == 0
    assert found["manifest"] is None and found["verified"] == 0
    assert found["project"]["checks"]["claims"] == "not used"
    assert found["project"]["checks"]["prereg"] == "passed"


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
    assert run["properties"]["project"]["checks"]["citations"] == "failed"
    assert run["properties"]["project"]["exit_code"] == 1


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
