"""`repro ci`: the summary a run leaves on its page, the exit codes, and the workflows.

The summaries are built from the report models, so most of this runs no command. Where a
record of re-runs is needed it is written with the models `repro reproduce` writes it with.
"""

from __future__ import annotations

import json
import pathlib
import re
import subprocess
import sys

import pytest
import repro
import yaml
from repro import ci
from repro.cli import main
from repro.models import (
    AggregateEvidence,
    AggregateMember,
    ArtifactRef,
    Claim,
    ComparisonStatus,
    Conversion,
    Decision,
    Digest,
    ExecutionStatus,
    ExtractionStatus,
    InputReading,
    Manifest,
    MetricEvidence,
    QuoteEvidence,
    Reason,
    Regeneration,
    RegenerationReason,
    RegenerationRecord,
    RegenerationState,
    ReproductionReport,
    RunOutput,
    Statistic,
    TreeLocator,
    Warning_,
)
from repro.policy import PUBLICATION, STRICT
from repro.reproduce import RECORD, append
from repro.verify import verify

ROOT = pathlib.Path(__file__).resolve().parents[3]
THEN = "2026-01-01T00:00:00+00:00"

SCRIPT = """
import json, pathlib
data = json.loads(pathlib.Path("inputs.json").read_text())
pathlib.Path("figures.json").write_text(json.dumps({"total": sum(data["xs"])}, indent=2))
"""

DRIFTING = """
import json, pathlib
data = json.loads(pathlib.Path("inputs.json").read_text())
pathlib.Path("figures.json").write_text(json.dumps({"total": sum(data["xs"]) + 1}, indent=2))
"""


def metric(artifact, reported, pointer="/total"):
    return MetricEvidence(artifact=artifact, name="total", reported=reported, pointer=pointer)


def project(root, *reported, script=None, claims=None):
    """`figures.json` holding a total of 6, with one claim per value the manuscript prints from
    it. With `script`, a command that writes the file from `inputs.json` is declared."""
    (root / "inputs.json").write_text(json.dumps({"xs": [1, 2, 3]}))
    (root / "figures.json").write_text(json.dumps({"total": 6}, indent=2))
    names = ["inputs.json", "figures.json"]
    records = ()
    if script is not None:
        (root / "make.py").write_text(script)
        names.append("make.py")
        records = (
            RegenerationRecord(
                id="sum",
                command=(sys.executable, "make.py"),
                inputs=tuple(
                    RunOutput(artifact=name, digest=Digest.of_file(root / f"{name}{suffix}"))
                    for name, suffix in (("inputs", ".json"), ("make", ".py"))
                ),
                output=RunOutput(artifact="figures", digest=Digest.of_file(root / "figures.json")),
                timeout_seconds=60,
            ),
        )
    return Manifest(
        project="study",
        path=root / "repro.yaml",
        artifacts=tuple(
            ArtifactRef(id=name.split(".")[0], path=root / name, digest=Digest.of_file(root / name))
            for name in names
        ),
        regenerations=records,
        claims=claims
        or tuple(
            Claim(id=f"c{i}", text="t", evidence=(metric("figures", value),))
            for i, value in enumerate(reported or ("6",))
        ),
    )


def on_disk(manifest):
    """The manifest as a file `repro ci` loads, beside the files it pins."""
    dumped = manifest.model_dump(mode="json", exclude={"path"}, exclude_none=True)
    manifest.path.write_text(yaml.safe_dump(dumped))
    return manifest.path


def rerun(manifest, at=THEN):
    """Record a re-run of every declared command over the files now on disk."""
    root = manifest.path.parent
    states = []
    for made in manifest.regenerations:
        written = Digest.of_file(root / "figures.json").value
        states.append(
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
        )
    append(ReproductionReport(started_at=at, regenerations=tuple(states)), root)


def decision(claim_id, execution, extraction, comparison, reason):
    return Decision(
        claim_id=claim_id,
        claim_digest="0" * 64,
        kind="metric",
        execution=execution,
        extraction=extraction,
        comparison=comparison,
        reason=reason,
    )


def row(markdown, label):
    """What one row of a summary's table says it found."""
    found = [line for line in markdown.splitlines() if line.startswith(f"| {label} |")]
    assert len(found) == 1, markdown
    return found[0].split("|")[2].strip()


def git(root, *args):
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


@pytest.fixture
def repository(tmp_path, monkeypatch):
    """A git repository holding a manifest, with a GitHub remote, as the working directory."""
    git(tmp_path, "init", "--quiet")
    git(tmp_path, "remote", "add", "origin", "https://github.com/someone/study.git")
    on_disk(project(tmp_path))
    monkeypatch.chdir(tmp_path)
    return tmp_path


# -- the claims summary ----------------------------------------------------------------------


def test_a_run_where_everything_verified_says_how_many_of_how_many(tmp_path):
    said = ci.claims_summary(ci.claims(project(tmp_path, "6", "6.0"), PUBLICATION))
    assert said.startswith("## claims: study\n")
    assert "`repro ci claims` under policy `publication`: **passed** (0 errors, 0 warnings)" in said
    assert row(said, "assertions") == "2 of 2 assertions verified"
    assert row(said, "pinned files") == "2 of 2 declared files match their pins"
    assert "###" not in said
    assert said.rstrip().endswith(ci.CLAIMS_SHOWS)


def test_a_mismatch_is_listed_with_both_values_and_the_address(tmp_path):
    run = ci.claims(project(tmp_path, "6", "7"), PUBLICATION)
    said = ci.claims_summary(run)
    assert not run.passed
    assert "**FAILED** (1 errors, 0 warnings)" in said
    assert row(said, "assertions") == "1 of 2 assertions verified, 1 mismatch"
    listed = [line for line in said.splitlines() if line.startswith("- ")]
    assert listed == [
        "- `c1` metric total: the manuscript prints `7`; "
        f"`{(tmp_path / 'figures.json').as_posix()}` at `/total` holds `6`: mismatch"
    ]


def test_outcomes_that_are_not_verified_are_counted_apart_and_never_as_verified(tmp_path):
    report = verify(project(tmp_path, "6"))
    done, absent, unavailable = (
        (ExecutionStatus.COMPLETED, ExtractionStatus.EXTRACTED, ComparisonStatus.MATCH),
        (ExecutionStatus.COMPLETED, ExtractionStatus.ABSENT, ComparisonStatus.NOT_APPLICABLE),
        (
            ExecutionStatus.UNAVAILABLE,
            ExtractionStatus.NOT_ATTEMPTED,
            ComparisonStatus.NOT_APPLICABLE,
        ),
    )
    stages = [done, absent, absent, unavailable, unavailable, unavailable]
    reasons = [Reason.VALUE_MATCH, *[Reason.POINTER_ABSENT] * 2, *[Reason.EXTRACTOR_MISSING] * 3]
    claim = report.claims[0].model_copy(
        update={
            "decisions": tuple(
                decision("c0", *stage, reason)
                for stage, reason in zip(stages, reasons, strict=True)
            )
        }
    )
    report = report.model_copy(update={"claims": (claim,)})
    run = ci.ClaimsRun(
        policy="publication", verification=report, verified=PUBLICATION.assess(report)
    )
    assert row(ci.claims_summary(run), "assertions") == (
        "1 of 6 assertions verified, 2 not found, 3 unchecked"
    )


def test_the_numbers_the_text_prints_are_counted_beside_the_assertions(tmp_path):
    manifest = project(tmp_path)
    (tmp_path / "paper.txt").write_text("The total was 6, of 57 invited in 2025.\n")
    paper = ArtifactRef(
        id="paper", path=tmp_path / "paper.txt", digest=Digest.of_file(tmp_path / "paper.txt")
    )
    evidence = (QuoteEvidence(artifact="paper", text="The total was 6"), metric("figures", "6"))
    manifest = manifest.model_copy(
        update={
            "artifacts": (*manifest.artifacts, paper),
            "claims": (Claim(id="total", text="t", evidence=evidence),),
        }
    )
    run = ci.claims(manifest, PUBLICATION)
    said = ci.claims_summary(run)
    assert run.passed
    assert row(said, "assertions") == "2 of 2 assertions verified; warnings: 1 short"
    assert row(said, "numbers in the manuscript") == (
        "3 numbers in 1 text: 1 bound, 1 set aside by rule, 0 set aside with a reason, 1 unbound"
    )
    assert sum(run.numbers.counts.values()) == 3


def test_a_manifest_that_reads_no_text_says_the_numbers_were_not_counted(tmp_path):
    said = ci.claims_summary(ci.claims(project(tmp_path), PUBLICATION))
    assert row(said, "numbers in the manuscript") == (
        "not counted: no claim reads its sentence from a text"
    )


def test_warnings_are_counted_beside_the_outcomes_and_change_none(tmp_path):
    report = verify(project(tmp_path, "6", "6.0"))
    first, second = report.claims
    warned = first.decisions[0].model_copy(update={"warnings": (Warning_.SHORT,)})
    report = report.model_copy(
        update={"claims": (first.model_copy(update={"decisions": (warned,)}), second)}
    )
    run = ci.ClaimsRun(
        policy="publication", verification=report, verified=PUBLICATION.assess(report)
    )
    assert row(ci.claims_summary(run), "assertions") == (
        "2 of 2 assertions verified; warnings: 1 short"
    )


def test_a_converted_value_that_mismatches_is_listed_as_stored_and_as_compared(tmp_path):
    manifest = project(tmp_path)
    (tmp_path / "figures.json").write_text(json.dumps({"total": 0.0424}))
    evidence = MetricEvidence(
        artifact="figures",
        name="rate",
        reported="4.3",
        pointer="/total",
        conversion=Conversion.PERCENT,
    )
    manifest = manifest.model_copy(
        update={"claims": (Claim(id="rate", text="t", evidence=(evidence,)),)}
    )
    said = ci.claims_summary(ci.claims(manifest, PUBLICATION))
    assert "at `/total` holds `0.0424`, `4.24` as a percentage: mismatch" in said


def test_an_aggregate_lists_a_few_of_the_values_it_read_and_the_statistic_of_all(tmp_path):
    manifest = project(tmp_path)
    for seed in range(5):
        (tmp_path / f"seed{seed}.json").write_text(json.dumps({"total": seed}))
    seeds = tuple(
        ArtifactRef(
            id=f"seed{seed}",
            path=tmp_path / f"seed{seed}.json",
            digest=Digest.of_file(tmp_path / f"seed{seed}.json"),
        )
        for seed in range(5)
    )
    evidence = AggregateEvidence(
        name="mean total",
        reported="3",
        statistic=Statistic.MEAN,
        count=5,
        members=tuple(
            AggregateMember(artifact=ref.id, locator=TreeLocator(pointer="/total")) for ref in seeds
        ),
    )
    manifest = manifest.model_copy(
        update={
            "artifacts": (*manifest.artifacts, *seeds),
            "claims": (Claim(id="mean", text="t", evidence=(evidence,)),),
        }
    )
    (listed,) = [
        line
        for line in ci.claims_summary(ci.claims(manifest, PUBLICATION)).splitlines()
        if line.startswith("- ")
    ]
    assert listed.startswith("- `mean` aggregate mean total: the manuscript prints `3`; ")
    assert listed.count(" at `/total` holds ") == ci.MAX_READS
    assert listed.endswith("; and 2 more; the mean of the 5 values is `2`: mismatch")


def test_a_pinned_file_that_changed_or_is_gone_is_counted_and_listed(tmp_path):
    manifest = project(tmp_path)
    (tmp_path / "figures.json").write_text(json.dumps({"total": 6}))
    (tmp_path / "inputs.json").unlink()
    said = ci.claims_summary(ci.claims(manifest, PUBLICATION))
    assert row(said, "pinned files") == (
        "0 of 2 declared files match their pins, 1 not the pinned bytes, 1 absent"
    )
    assert "- `inputs`: nothing at the declared path" in said
    assert "- `figures`: not the pinned bytes: pinned `" in said


def test_a_manifest_declaring_no_command_says_so_in_both_rows(tmp_path):
    run = ci.claims(project(tmp_path), STRICT)
    said = ci.claims_summary(run)
    assert run.passed and run.staleness is None
    assert row(said, "re-runs") == "no command is declared"
    assert row(said, "freshness").startswith("no command is declared")


def test_a_command_never_rerun_is_counted_against_the_assertions_that_read_its_file(tmp_path):
    claims = (
        Claim(id="made", text="t", evidence=(metric("figures", "6"),)),
        Claim(id="given", text="t", evidence=(metric("inputs", "1", "/xs/0"),)),
    )
    said = ci.claims_summary(
        ci.claims(project(tmp_path, script=SCRIPT, claims=claims), PUBLICATION)
    )
    assert row(said, "re-runs") == f"not re-run in this job; `{RECORD.as_posix()}` holds no re-run"
    assert row(said, "freshness") == (
        "0 current of 1 assertion that reads a file with a recorded producer, 1 never rerun; "
        "1 read files no command is recorded for"
    )
    assert "- `figures`, written by `sum`: never rerun" in said


def test_a_recorded_rerun_is_named_by_when_it_started_and_what_it_reproduced(tmp_path):
    manifest = project(tmp_path, script=SCRIPT)
    rerun(manifest)
    said = ci.claims_summary(ci.claims(manifest, PUBLICATION))
    assert row(said, "re-runs") == (
        f"not re-run in this job; the last recorded re-run, started {THEN}: "
        "1 of 1 command reproduced"
    )
    assert row(said, "freshness") == (
        "1 current of 1 assertion that reads a file with a recorded producer; "
        "0 read files no command is recorded for"
    )
    assert "###" not in said


def test_an_input_edited_after_its_rerun_is_stale_and_the_cause_is_named(tmp_path):
    manifest = project(tmp_path, script=SCRIPT)
    rerun(manifest)
    (tmp_path / "inputs.json").write_text(json.dumps({"xs": [1, 2, 4]}))
    run = ci.claims(manifest, STRICT)
    said = ci.claims_summary(run)
    assert not run.passed
    assert row(said, "freshness").startswith(
        "0 current of 1 assertion that reads a file with a recorded producer, 1 stale;"
    )
    assert "- `figures`, written by `sum`: stale: input changed" in said


def test_thousands_of_failing_assertions_are_listed_up_to_a_cap_and_the_rest_counted(tmp_path):
    manifest = project(tmp_path, *(str(n) for n in range(7, 3007)))
    said = ci.claims_summary(ci.claims(manifest, PUBLICATION))
    listed = [line for line in said.splitlines() if line.startswith("- ")]
    assert row(said, "assertions") == "0 of 3000 assertions verified, 3000 mismatch"
    assert len(listed) == ci.MAX_LISTED + 1
    assert listed[0].startswith("- `c0` metric total: the manuscript prints `7`")
    assert listed[-1] == f"- and {3000 - ci.MAX_LISTED} more"
    assert len(said.encode()) < 16 * 1024


def test_a_long_value_is_cut_and_one_holding_a_backtick_stays_code():
    assert ci._code("x" * 500) == f"`{'x' * ci.MAX_SHOWN}...`"
    assert ci._code("a`b\nc") == "`` a`b c ``"


# -- the reruns summary ----------------------------------------------------------------------


def test_the_reruns_summary_counts_commands_and_bytes_apart(tmp_path):
    manifest = project(tmp_path, script=SCRIPT)
    assert main(["ci", "reruns", str(on_disk(manifest)), "--summary", str(tmp_path / "s.md")]) == 0
    said = (tmp_path / "s.md").read_text()
    assert said.startswith("## reruns: study\n")
    assert row(said, "commands") == "1 of 1 command reproduced"
    assert row(said, "bytes") == "1 of 1 command that ran wrote the pinned bytes"
    assert f"Python {sys.version.split()[0]}" in row(said, "machine")
    assert said.rstrip().endswith(ci.RERUNS_SHOWS)
    assert len((tmp_path / RECORD).read_text().splitlines()) == 1


def test_a_rerun_that_moved_a_number_fails_and_lists_both_values(tmp_path):
    manifest = project(tmp_path, script=DRIFTING)
    assert main(["ci", "reruns", str(on_disk(manifest)), "--summary", str(tmp_path / "s.md")]) == 1
    said = (tmp_path / "s.md").read_text()
    assert "**FAILED** (1 errors, 0 warnings)" in said
    assert row(said, "commands") == "0 of 1 command reproduced, 1 changed"
    assert row(said, "bytes") == "0 of 1 command that ran wrote the pinned bytes"
    assert "- `sum`: changed: total: `6` then, `7` now, the manuscript prints `6`" in said


def test_a_skipped_command_is_counted_as_not_rerun_and_not_as_reproduced(tmp_path):
    path = on_disk(project(tmp_path, script=SCRIPT))
    code = main(["ci", "reruns", str(path), "--skip", "sum", "--summary", str(tmp_path / "s.md")])
    said = (tmp_path / "s.md").read_text()
    assert code == 0
    assert row(said, "commands") == "0 of 1 command reproduced, 1 not re-run"
    assert row(said, "bytes") == "0 of 0 commands that ran wrote the pinned bytes"


def test_reruns_with_no_command_declared_exits_2_and_runs_nothing(tmp_path, capsys):
    assert main(["ci", "reruns", str(on_disk(project(tmp_path)))]) == 2
    assert "nothing to run again" in capsys.readouterr().out
    assert not (tmp_path / RECORD).exists()


# -- the claims command ----------------------------------------------------------------------


def test_claims_exits_0_and_prints_what_verify_prints(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    path = on_disk(project(tmp_path))
    assert main(["ci", "claims", str(path)]) == 0
    ours = capsys.readouterr().out
    assert main(["verify", str(path)]) == 0
    assert ours.startswith(capsys.readouterr().out)
    assert "no command is declared" in ours
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "figures.json",
        "inputs.json",
        "repro.yaml",
    ]


def test_claims_exits_1_on_a_mismatch(tmp_path):
    assert main(["ci", "claims", str(on_disk(project(tmp_path, "7")))]) == 1


def test_claims_exits_2_with_no_manifest(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert main(["ci", "claims"]) == 2
    assert "repro manifest init" in capsys.readouterr().out


def test_claims_fails_a_never_rerun_command_only_under_the_policy_that_grades_it(tmp_path, capsys):
    path = on_disk(project(tmp_path, script=SCRIPT))
    assert main(["ci", "claims", str(path)]) == 0
    assert main(["ci", "claims", str(path), "--policy", "strict"]) == 1
    assert main(["stale", str(path), "--policy", "strict"]) == 1
    assert "1 never rerun" in capsys.readouterr().out


def test_the_step_summary_is_appended_to_and_what_was_there_is_kept(tmp_path, monkeypatch):
    summary = tmp_path / "summary.md"
    summary.write_text("an earlier step\n")
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    path = on_disk(project(tmp_path))
    assert main(["ci", "claims", str(path)]) == 0
    assert main(["ci", "claims", str(path)]) == 0
    said = summary.read_text()
    assert said.startswith("an earlier step\n## claims: study\n")
    assert said.count("## claims: study") == 2


def test_a_named_summary_file_is_written_in_place_of_the_environments(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(tmp_path / "env.md"))
    path = on_disk(project(tmp_path))
    assert main(["ci", "claims", str(path), "--summary", str(tmp_path / "named.md")]) == 0
    assert (tmp_path / "named.md").read_text().startswith("## claims: study")
    assert not (tmp_path / "env.md").exists()


def test_bare_ci_prints_its_checks_and_exits_1(capsys):
    assert main(["ci"]) == 1
    assert "{prereg,results,claims,citations,reruns,init}" in capsys.readouterr().out


# -- the workflows ---------------------------------------------------------------------------


def test_the_default_names_say_which_check_ran_and_nothing_about_the_study():
    assert ci.CHECKS == ("prereg", "results", "claims", "citations", "reruns")
    assert ci.NAMES == {check: check for check in ci.CHECKS}


def test_init_writes_only_the_claims_workflow_and_prints_its_badge(repository, capsys):
    assert main(["ci", "init"]) == 0
    out = capsys.readouterr().out
    assert [p.name for p in (repository / ci.WORKFLOWS).iterdir()] == ["claims.yml"]
    written = repository / ci.WORKFLOWS / "claims.yml"
    assert f"wrote {written.resolve()}" in out
    runs = "https://github.com/someone/study/actions/workflows/claims.yml"
    assert [line for line in out.splitlines() if "[![" in line] == [
        f"[![claims]({runs}/badge.svg)]({runs})"
    ]
    assert "skipped prereg: " in out and "skipped reruns: not asked for" in out


def test_the_claims_workflow_runs_one_pinned_command_with_read_only_permissions(repository):
    assert main(["ci", "init"]) == 0
    text = (repository / ci.WORKFLOWS / "claims.yml").read_text()
    flow = yaml.safe_load(text)
    assert text.startswith(ci.MARKER)
    assert flow["name"] == "claims"
    # PyYAML reads the key `on` as a boolean.
    assert flow[True] == {"push": {"branches": ["main"]}, "pull_request": None}
    assert flow["permissions"] == {"contents": "read"}
    (job,) = flow["jobs"].values()
    uses = [step["uses"] for step in job["steps"] if "uses" in step]
    assert all(re.fullmatch(r"[\w./-]+@[0-9a-f]{40}", used) for used in uses) and len(uses) == 2
    assert job["steps"][0]["with"] == {"persist-credentials": False}
    assert [step["run"] for step in job["steps"] if "run" in step] == [
        f"uvx --from reproducible-science=={repro.__version__} repro ci claims"
    ]


def test_the_workflow_pins_the_actions_this_repositorys_own_claims_workflow_pins():
    ours = (ROOT / ".github" / "workflows" / "claims.yml").read_text()
    for pin in (ci.CHECKOUT, ci.SETUP_UV):
        assert f"uses: {pin}\n" in ours


def test_init_with_reruns_writes_both_and_leaves_a_place_for_the_environment(
    tmp_path, monkeypatch, capsys
):
    git(tmp_path, "init", "--quiet")
    on_disk(project(tmp_path, script=SCRIPT))
    monkeypatch.chdir(tmp_path)
    assert main(["ci", "init", "--reruns"]) == 0
    out = capsys.readouterr().out
    assert sorted(p.name for p in (tmp_path / ci.WORKFLOWS).iterdir()) == [
        "claims.yml",
        "reruns.yml",
    ]
    text = (tmp_path / ci.WORKFLOWS / "reruns.yml").read_text()
    flow = yaml.safe_load(text)
    assert flow["name"] == "reruns"
    assert "# - run: uv sync\n" in text
    assert [step["run"] for step in flow["jobs"]["reruns"]["steps"] if "run" in step] == [
        f"uvx --from reproducible-science=={repro.__version__} repro ci reruns"
    ]
    badges = [line for line in out.splitlines() if line.startswith("[![")]
    assert [line.split("]")[0] for line in badges] == ["[![claims", "[![reruns"]
    assert all("github.com/OWNER/REPO/" in line for line in badges)


def test_init_with_reruns_refuses_a_manifest_that_declares_no_command(repository, capsys):
    assert main(["ci", "init", "--reruns"]) == 2
    assert "declares no command" in capsys.readouterr().out
    assert not (repository / ".github").exists()


def test_init_does_not_replace_a_workflow_it_wrote_unless_forced(repository, capsys):
    assert main(["ci", "init"]) == 0
    written = repository / ci.WORKFLOWS / "claims.yml"
    first = written.read_text()
    assert main(["ci", "init", "--name", "claims=claims checked"]) == 2
    assert "`--force` replaces" in capsys.readouterr().out
    assert written.read_text() == first
    assert main(["ci", "init", "--force", "--name", "claims=claims checked"]) == 0
    assert yaml.safe_load(written.read_text())["name"] == "claims checked"
    assert "[![claims checked](" in capsys.readouterr().out


def test_init_never_replaces_a_workflow_it_did_not_write_and_a_prefix_writes_beside_it(
    repository, capsys
):
    theirs = repository / ci.WORKFLOWS / "claims.yml"
    theirs.parent.mkdir(parents=True)
    theirs.write_text("name: something else\n")
    for flags in ([], ["--force"]):
        assert main(["ci", "init", *flags]) == 2
        assert "`--prefix repro-`" in capsys.readouterr().out
        assert theirs.read_text() == "name: something else\n"
    assert main(["ci", "init", "--prefix", "repro-"]) == 0
    assert theirs.read_text() == "name: something else\n"
    assert yaml.safe_load((theirs.parent / "repro-claims.yml").read_text())["name"] == "claims"
    assert "/actions/workflows/repro-claims.yml/badge.svg" in capsys.readouterr().out


def test_a_name_for_a_check_there_is_no_workflow_for_is_refused(repository, capsys):
    assert main(["ci", "init", "--name", "study=reproducible"]) == 2
    assert "CHECK is one of prereg, results, claims, citations, reruns" in capsys.readouterr().out
    assert not (repository / ".github").exists()


@pytest.mark.parametrize(
    "remote",
    [
        "https://github.com/someone/study.git",
        "https://github.com/someone/study",
        "https://github.com/someone/study/",
        "git@github.com:someone/study.git",
        "ssh://git@github.com/someone/study.git",
    ],
)
def test_the_owner_and_repository_are_read_from_a_github_remote(remote):
    assert ci.repository(remote) == "someone/study"


@pytest.mark.parametrize("remote", ["", "https://gitlab.com/someone/study.git", "/srv/study.git"])
def test_a_remote_that_is_not_github_names_no_repository(remote):
    assert ci.repository(remote) is None


def test_init_reads_the_badge_address_from_an_ssh_remote(repository, capsys):
    git(repository, "remote", "set-url", "origin", "git@github.com:other/paper.git")
    assert main(["ci", "init"]) == 0
    assert "https://github.com/other/paper/actions/workflows/claims.yml" in capsys.readouterr().out


def test_readme_puts_the_badge_under_the_first_heading_once(repository, capsys):
    readme = repository / "README.md"
    readme.write_text("# Study\n\nWhat it is.\n")
    assert main(["ci", "init", "--readme"]) == 0
    runs = "https://github.com/someone/study/actions/workflows/claims.yml"
    badge = f"[![claims]({runs}/badge.svg)]({runs})"
    assert readme.read_text() == f"# Study\n\n{badge}\n\nWhat it is.\n"
    assert f"  + {badge}" in capsys.readouterr().out
    assert main(["ci", "init", "--readme", "--force"]) == 0
    assert readme.read_text() == f"# Study\n\n{badge}\n\nWhat it is.\n"
    assert "nothing was added" in capsys.readouterr().out


def test_badges_go_on_one_line_at_the_head_of_the_badges_already_there():
    flows = [ci.workflow(check, f"repro ci {check}") for check in ci.CHECKS]
    text, added = ci.with_badges("# Study\n\n[![pypi](a)](b)\n\nText.\n", flows, "o/r")
    assert len(added) == 5
    assert text.splitlines()[2] == " ".join(flow.badge("o/r") for flow in flows)
    assert text.splitlines()[3:] == ["[![pypi](a)](b)", "", "Text."]
    assert ci.with_badges(text, flows, "o/r") == (text, [])


def test_readme_without_a_github_remote_writes_nothing(tmp_path, monkeypatch, capsys):
    git(tmp_path, "init", "--quiet")
    on_disk(project(tmp_path))
    (tmp_path / "README.md").write_text("# Study\n")
    monkeypatch.chdir(tmp_path)
    assert main(["ci", "init", "--readme"]) == 2
    assert "names no GitHub repository" in capsys.readouterr().out
    assert not (tmp_path / ".github").exists()
    assert (tmp_path / "README.md").read_text() == "# Study\n"


def test_init_outside_a_repository_exits_2_and_writes_nothing(tmp_path, monkeypatch, capsys):
    on_disk(project(tmp_path))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    assert main(["ci", "init"]) == 2
    assert "not inside a git repository" in capsys.readouterr().out
    assert not (tmp_path / ".github").exists()


def test_init_with_no_manifest_points_at_manifest_init(tmp_path, monkeypatch, capsys):
    git(tmp_path, "init", "--quiet")
    monkeypatch.chdir(tmp_path)
    assert main(["ci", "init"]) == 2
    assert "repro manifest init" in capsys.readouterr().out
    assert not (tmp_path / ".github").exists()


def test_a_manifest_below_the_top_is_named_in_the_command(tmp_path, monkeypatch):
    git(tmp_path, "init", "--quiet")
    (tmp_path / "paper").mkdir()
    on_disk(project(tmp_path / "paper"))
    monkeypatch.chdir(tmp_path / "paper")
    assert main(["ci", "init"]) == 0
    text = (tmp_path / ci.WORKFLOWS / "claims.yml").read_text()
    assert text.rstrip().endswith("repro ci claims paper/repro.yaml")


# -- the three tools' checks -----------------------------------------------------------------

TEXT = "The quick brown fox jumps over the lazy dog near the quiet river bank at dawn.\n"
QUOTE = "quick brown fox jumps over the lazy dog"


def pin(root, name, quote=QUOTE, there=True):
    """A claims file pinning one source by digest, with the source on disk or not."""
    (root / "sources").mkdir(exist_ok=True)
    (root / "claims").mkdir(exist_ok=True)
    if there:
        (root / "sources" / f"{name}.txt").write_text(TEXT)
    source = {
        "citation": name,
        "local": f"sources/{name}.txt",
        "sha256": Digest.of_text(TEXT).value,
    }
    document = {"source": source, "claims": {"c1": {"quotes": [{"exact": quote}]}}}
    (root / "claims" / f"{name}.yaml").write_text(yaml.safe_dump(document))


@pytest.fixture
def tools(tmp_path, monkeypatch):
    """A git repository as the working directory, with no calendar to stamp a freeze at and no
    cache or note shared with the machine the tests run on."""
    monkeypatch.setenv("PROVENANCE_CALENDARS", "")
    monkeypatch.setenv("CITATIONS_NO_CACHE", "1")
    monkeypatch.setenv("REPRO_NO_HINT", "1")
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    git(tmp_path, "init", "--quiet")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def plan(root, freeze=True):
    assert main(["prereg", "new", ".", "--title", "study"]) == 0
    git(root, "add", "PREREG.md")
    git(root, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "--quiet", "-m", "plan")
    if freeze:
        assert main(["prereg", "freeze"]) == 0


def ledger(root):
    (root / "results.json").write_text(json.dumps({"total": 6}))
    (root / "inputs.json").write_text(json.dumps({"xs": [1, 2, 3]}))
    assert main(["results", "init"]) == 0
    assert main(["results", "seal", "inputs.json"]) == 0
    assert main(["results", "run", "results.json", "--run-id", "r1"]) == 0


@pytest.fixture
def four(tools):
    """Every record a check reads: a frozen plan with one log entry, a ledger recording two
    files, a manifest, and two pinned sources of which one is on disk."""
    plan(tools)
    assert main(["prereg", "log", "tolerance from fixtures", "--access", "no results seen"]) == 0
    ledger(tools)
    on_disk(project(tools))
    pin(tools, "here")
    pin(tools, "gone", there=False)
    return tools


def summary_of(root, *argv):
    """The exit code of one check and the summary it appended."""
    target = root / "summary.md"
    target.unlink(missing_ok=True)
    code = main(["ci", *argv, "--summary", str(target)])
    return code, target.read_text()


def test_the_four_checks_of_a_project_holding_every_record(four, capsys):
    code, said = summary_of(four, "prereg")
    assert code == 0
    assert "`prereg check`: **passed** (exit 0)" in said
    assert row(said, "plans") == "1 of 1 frozen plan unchanged since the freeze"
    assert row(said, "amendments") == "0 frozen amendments, 0 drafts"
    assert row(said, "log") == "1 log entry"
    assert said.rstrip().endswith("It does not show that the study followed the plan.")

    code, said = summary_of(four, "results")
    assert code == 0
    assert "`results verify --files`: **passed** (exit 0)" in said
    assert row(said, "chain") == "intact: 3 events"
    assert row(said, "recorded files") == "2 of 2 recorded files match the hash recorded"
    assert said.rstrip().endswith("It does not show that the results are right.")

    code, said = summary_of(four, "claims")
    assert code == 0
    assert row(said, "assertions") == "1 of 1 assertion verified"

    code, said = summary_of(four, "citations")
    assert code == 0
    assert "`citations verify --claims claims`: **passed** (exit 0)" in said
    assert said.splitlines()[4] == (
        "1 of 2 quotations were not checked: 1 of 2 sources are not on this machine. "
        "An unchecked quotation is not a found one."
    )
    assert row(said, "quotations") == "1 found, 0 not found, 1 unchecked of 2 quotations"
    assert row(said, "sources") == "1 of 2 sources on this machine, 1 absent"
    assert said.rstrip().endswith(
        "It does not show that the source supports the sentence that quotes it."
    )
    assert "1 unchecked" in capsys.readouterr().out


def test_a_plan_edited_after_its_freeze_fails_and_is_named(tools):
    plan(tools)
    (tools / "PREREG.md").chmod(0o644)
    (tools / "PREREG.md").write_text((tools / "PREREG.md").read_text() + "\nAlso p < 0.10.\n")
    code, said = summary_of(tools, "prereg")
    assert code == 1
    assert "**FAILED** (exit 1)" in said
    assert row(said, "plans") == "0 of 1 frozen plan unchanged since the freeze, 1 changed"
    assert f"- `{tools.resolve() / 'PREREG.md'}`: changed" in said


def test_a_plan_never_frozen_is_called_a_draft_and_does_not_pass(tools):
    plan(tools, freeze=False)
    code, said = summary_of(tools, "prereg")
    assert code == 2
    assert "**COULD NOT CHECK** (exit 2)" in said
    assert row(said, "plans") == (
        "0 of 0 frozen plans unchanged since the freeze; 1 plan of 1 never frozen, so a draft "
        "with nothing to compare"
    )
    assert f"- `{tools.resolve() / 'PREREG.md'}`: never frozen" in said


def test_the_plans_row_adds_up_over_frozen_changed_pending_and_draft():
    def entry(frozen, check, amendments=0, drafts=0, entries=0):
        return {
            "path": "p",
            "frozen": frozen,
            "sha256": None,
            "check": check,
            "amendments": amendments,
            "amendment_drafts": drafts,
            "log_entries": entries,
        }

    plans = [
        entry(True, "unchanged", amendments=2, entries=3),
        entry(True, "unchanged", entries=1),
        entry(True, "changed", amendments=1),
        entry(True, "not frozen", drafts=1),
        entry(False, "not frozen", entries=9),
    ]
    run = ci.ToolRun(
        check="prereg", command=("prereg", "check"), exit=1, outcome="failed",
        account={"plans": plans, "commit_pinned": []},
    )  # fmt: skip
    said = ci.tool_summary(run)
    assert row(said, "plans") == (
        "2 of 4 frozen plans unchanged since the freeze, 1 changed, 1 with an amendment that "
        "is not frozen; 1 plan of 5 never frozen, so a draft with nothing to compare"
    )
    assert row(said, "amendments") == "3 frozen amendments, 1 draft"
    assert row(said, "log") == "4 log entries"
    assert len([line for line in said.splitlines() if line.startswith("- ")]) == 3


def test_a_recorded_file_that_changed_and_one_that_is_gone_fail_and_are_named(tools):
    ledger(tools)
    (tools / "results.json").write_text(json.dumps({"total": 7}))
    (tools / "inputs.json").unlink()
    code, said = summary_of(tools, "results")
    assert code == 1
    assert row(said, "chain") == "intact: 3 events"
    assert row(said, "recorded files") == (
        "0 of 2 recorded files match the hash recorded, 1 changed, 1 missing"
    )
    assert "- `results.json`: changed" in said and "- `inputs.json`: missing" in said


def test_a_ledger_whose_chain_does_not_verify_fails_and_compares_no_file(tools):
    ledger(tools)
    path = tools / ".results" / "ledger.jsonl"
    path.write_text(path.read_text().replace("r1", "r2"))
    code, said = summary_of(tools, "results")
    assert code == 1
    assert row(said, "chain").startswith("edited: ")
    assert row(said, "recorded files") == "not compared: the chain did not verify"


def test_a_citations_run_that_read_no_source_could_not_check_and_does_not_pass(tools, capsys):
    pin(tools, "gone", there=False)
    pin(tools, "lost", there=False)
    assert main(["citations", "verify", "--claims", "claims"]) == 1
    assert "nothing was measured" in capsys.readouterr().out
    code, said = summary_of(tools, "citations")
    assert code == 2
    assert "**COULD NOT CHECK** (exit 1)" in said
    assert row(said, "quotations") == "0 found, 0 not found, 2 unchecked of 2 quotations"
    assert row(said, "sources") == "0 of 2 sources on this machine, 2 absent"
    assert "could not check: `repro ci citations` exits 2." in capsys.readouterr().out


def test_a_quotation_its_source_does_not_hold_fails(tools):
    pin(tools, "here")
    pin(tools, "other", quote="a sentence the source does not contain anywhere in its text")
    code, said = summary_of(tools, "citations")
    assert code == 1
    assert row(said, "quotations") == "1 found, 1 not found, 0 unchecked of 2 quotations"
    assert "were not checked" not in said


def test_fetching_first_reports_what_was_fetched_and_leaves_the_rest_unchecked(tools):
    pin(tools, "here")
    pin(tools, "gone", there=False)
    code, said = summary_of(tools, "citations", "--fetch-sources")
    assert code == 0
    assert row(said, "fetch") == (
        "2 sources: 0 fetched and matched to the pinned digest, 1 already present, 1 no location"
    )
    assert row(said, "quotations") == "1 found, 0 not found, 1 unchecked of 2 quotations"


def test_a_check_with_no_record_to_read_exits_2_and_says_so(tools):
    for check in ci.TOOLS:
        code, said = summary_of(tools, check)
        assert code == 2
        assert f"`repro ci {check}`: **NOTHING TO READ**: {ci.NO_RECORD[check]}" in said


def badges(out):
    return [line.split("]")[0].removeprefix("[![") for line in out.splitlines() if "[![" in line]


def test_init_writes_a_workflow_for_each_record_kept_in_badge_order(four, capsys):
    assert main(["ci", "init", "--fetch-sources"]) == 0
    out = capsys.readouterr().out
    assert sorted(p.name for p in (four / ci.WORKFLOWS).iterdir()) == [
        "citations.yml",
        "claims.yml",
        "prereg.yml",
        "results.yml",
    ]
    assert badges(out) == ["prereg", "results", "claims", "citations"]
    assert "skipped reruns: not asked for" in out
    for check in ("prereg", "results"):
        flow = yaml.safe_load((four / ci.WORKFLOWS / f"{check}.yml").read_text())
        assert flow["name"] == check
        assert [step["run"] for step in flow["jobs"][check]["steps"] if "run" in step] == [
            f"uvx --from reproducible-science=={repro.__version__} repro ci {check}"
        ]
    flow = yaml.safe_load((four / ci.WORKFLOWS / "citations.yml").read_text())
    assert [step["run"] for step in flow["jobs"]["citations"]["steps"] if "run" in step] == [
        "sudo apt-get update && sudo apt-get install --yes poppler-utils",
        f"uvx --from reproducible-science=={repro.__version__} repro ci citations --fetch-sources",
    ]


def test_init_writes_only_the_workflows_whose_records_exist(tools, capsys):
    ledger(tools)
    pin(tools, "here")
    assert main(["ci", "init"]) == 0
    out = capsys.readouterr().out
    assert sorted(p.name for p in (tools / ci.WORKFLOWS).iterdir()) == [
        "citations.yml",
        "results.yml",
    ]
    assert badges(out) == ["results", "citations"]
    assert f"skipped prereg: {ci.NO_RECORD['prereg']}" in out
    assert f"skipped claims: {ci.NO_RECORD['claims']}" in out
    text = (tools / ci.WORKFLOWS / "citations.yml").read_text()
    assert text.rstrip().endswith("repro ci citations")
