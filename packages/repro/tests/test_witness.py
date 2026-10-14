"""Where a re-run happened, as its environment said.

An entry in the record of re-runs says a command was run again. It did not say where, so a
re-run on the author's machine and one a CI service ran read alike. The entry now copies the
variables a GitHub Actions runner sets, and nothing else: no request is made and nothing is
checked. Nothing here executes a command; the entries are written with the models
`repro reproduce` writes them with.
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError
from repro.cli import main
from repro.models import (
    ArtifactRef,
    Claim,
    Digest,
    Freshness,
    InputReading,
    Manifest,
    MetricEvidence,
    Regeneration,
    RegenerationReason,
    RegenerationRecord,
    RegenerationState,
    ReproductionReport,
    RunOutput,
    StaleCause,
    Witness,
)
from repro.reproduce import GITHUB_ACTIONS_VARIABLES, RECORD, append, witness
from repro.stale import reruns, stale
from repro.why import why

THEN = "2026-01-01T00:00:00+00:00"

RUNNER = {
    "GITHUB_ACTIONS": "true",
    "GITHUB_REPOSITORY": "owner/repo",
    "GITHUB_WORKFLOW": "reproduce",
    "GITHUB_RUN_ID": "123456",
    "GITHUB_RUN_ATTEMPT": "2",
    "GITHUB_SHA": "0f" * 20,
    "GITHUB_REF": "refs/heads/main",
    "RUNNER_OS": "Linux",
}

WITNESSED = Witness(
    kind="github_actions",
    repository="owner/repo",
    workflow="reproduce",
    run_id="123456",
    run_attempt="2",
    sha="0f" * 20,
    ref="refs/heads/main",
    runner_os="Linux",
)


# -- reading the environment -----------------------------------------------------------------


def test_every_variable_a_runner_sets_is_recorded():
    assert witness(RUNNER) == WITNESSED
    assert witness(RUNNER).model_dump(mode="json") == {
        "kind": "github_actions",
        "repository": "owner/repo",
        "workflow": "reproduce",
        "run_id": "123456",
        "run_attempt": "2",
        "sha": "0f" * 20,
        "ref": "refs/heads/main",
        "runner_os": "Linux",
    }


def test_the_fields_are_the_ones_agreed_and_no_other():
    assert list(Witness.model_fields) == [
        "kind",
        "repository",
        "workflow",
        "run_id",
        "run_attempt",
        "sha",
        "ref",
        "runner_os",
    ]
    assert list(GITHUB_ACTIONS_VARIABLES) == list(Witness.model_fields)[1:]
    with pytest.raises(ValidationError):
        Witness(kind="github_actions", url="https://github.com/owner/repo/actions/runs/1")
    with pytest.raises(ValidationError):
        Witness(kind="local")


@pytest.mark.parametrize(
    "variables",
    [
        {},
        {name: value for name, value in RUNNER.items() if name != "GITHUB_ACTIONS"},
        {**RUNNER, "GITHUB_ACTIONS": "false"},
        {**RUNNER, "GITHUB_ACTIONS": "True"},
        {**RUNNER, "GITHUB_ACTIONS": "1"},
        {**RUNNER, "GITHUB_ACTIONS": ""},
        {"CI": "true", "GITLAB_CI": "true"},
    ],
)
def test_there_is_no_witness_unless_github_actions_is_the_string_true(variables):
    assert witness(variables) is None


@pytest.mark.parametrize("missing", sorted(GITHUB_ACTIONS_VARIABLES.values()))
def test_a_variable_that_is_missing_or_empty_is_left_out_and_the_rest_are_kept(missing):
    field = next(f for f, name in GITHUB_ACTIONS_VARIABLES.items() if name == missing)
    for partial in (
        {name: value for name, value in RUNNER.items() if name != missing},
        {**RUNNER, missing: ""},
    ):
        found = witness(partial)
        assert getattr(found, field) is None
        dumped = found.model_dump(mode="json")
        assert field not in dumped
        assert dumped == {k: v for k, v in WITNESSED.model_dump(mode="json").items() if k != field}


def test_a_runner_that_set_nothing_else_is_still_a_witness_of_its_kind():
    found = witness({"GITHUB_ACTIONS": "true"})
    assert found.model_dump(mode="json") == {"kind": "github_actions"}
    assert found.said == "in GitHub Actions"
    assert witness({"GITHUB_ACTIONS": "true", "GITHUB_RUN_ID": "7"}).said == (
        "in GitHub Actions run 7"
    )
    assert WITNESSED.said == "in GitHub Actions run 123456 of owner/repo"


# -- the entry in the record -----------------------------------------------------------------


def file(root, name):
    return root / f"{name}.json"


def project(root):
    """`data -> totals`, one command, and a claim on what it writes."""
    file(root, "data").write_text(json.dumps({"xs": [1, 2, 3]}))
    file(root, "totals").write_text(json.dumps({"total": 6}))
    made = RegenerationRecord(
        id="sum",
        command=("make", "totals"),
        inputs=(RunOutput(artifact="data", digest=Digest.of_file(file(root, "data"))),),
        output=RunOutput(artifact="totals", digest=Digest.of_file(file(root, "totals"))),
    )
    manifest = Manifest(
        project="p",
        path=root / "repro.yaml",
        artifacts=tuple(
            ArtifactRef(id=name, path=file(root, name), digest=Digest.of_file(file(root, name)))
            for name in ("data", "totals")
        ),
        regenerations=(made,),
        claims=(
            Claim(
                id="total",
                text="The total is 6.",
                evidence=(
                    MetricEvidence(artifact="totals", name="total", reported="6", pointer="/total"),
                ),
            ),
        ),
    )
    manifest.path.write_text(manifest.model_dump_json())
    return manifest, made


def entry(root, made, **report):
    written = Digest.of_file(file(root, made.output.artifact)).value
    state = RegenerationState(
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
                observed=Digest.of_file(file(root, wanted.artifact)).value,
            )
            for wanted in made.inputs
        ),
    )
    return ReproductionReport(started_at=THEN, regenerations=(state,), **report)


def test_an_entry_with_no_witness_has_no_such_key_and_is_the_entry_it_was(tmp_path):
    _, made = project(tmp_path)
    local = entry(tmp_path, made)
    assert local.witness is None
    dumped = local.model_dump(mode="json")
    assert "witness" not in dumped
    assert list(dumped) == [
        "schema_version",
        "project",
        "manifest_digest",
        "tool_version",
        "started_at",
        "ended_at",
        "environment",
        "regenerations",
    ]
    append(local, tmp_path)
    (line,) = (tmp_path / RECORD).read_text().splitlines()
    assert "witness" not in json.loads(line)
    assert "witness" not in json.loads(local.model_dump_json())


def test_an_entry_with_a_witness_round_trips_through_the_record(tmp_path):
    _, made = project(tmp_path)
    append(entry(tmp_path, made, witness=witness(RUNNER)), tmp_path)
    (line,) = (tmp_path / RECORD).read_text().splitlines()
    assert json.loads(line)["witness"] == WITNESSED.model_dump(mode="json")
    (read,) = reruns(tmp_path)
    assert read.witness == WITNESSED
    assert ReproductionReport.model_validate_json(read.model_dump_json()) == read

    partial = witness({"GITHUB_ACTIONS": "true", "GITHUB_RUN_ID": "7"})
    again = ReproductionReport.model_validate_json(
        entry(tmp_path, made, witness=partial).model_dump_json()
    )
    assert again.witness == partial
    assert json.loads(again.model_dump_json())["witness"] == {
        "kind": "github_actions",
        "run_id": "7",
    }


def old_log(root, made):
    """A line as the tool wrote it before the field existed."""
    line = json.dumps(entry(root, made).model_dump(mode="json"), sort_keys=True)
    assert "witness" not in line
    (root / RECORD).parent.mkdir(parents=True, exist_ok=True)
    (root / RECORD).write_text(line + "\n")


# -- `repro stale` and `repro why` -----------------------------------------------------------


def test_an_old_log_loads_and_stale_and_why_print_as_before(tmp_path, capsys):
    manifest, made = project(tmp_path)
    old_log(tmp_path, made)
    (read,) = reruns(tmp_path)
    assert read.witness is None

    report = stale(manifest)
    assert [(node.state, node.witness) for node in report.regenerations] == [
        (Freshness.CURRENT, None)
    ]
    account = why(manifest, "total")
    assert account.chain[0].regeneration.witness is None

    assert main(["why", "total", str(manifest.path)]) == 0
    shown = capsys.readouterr().out
    assert f"      re-run of {THEN} reproduced, and its output is the bytes now on disk\n" in shown
    assert "GitHub" not in shown

    file(tmp_path, "data").write_text(json.dumps({"xs": [1, 2, 4]}))
    main(["stale", str(manifest.path)])
    shown = capsys.readouterr().out
    (line,) = [line for line in shown.splitlines() if "input changed" in line]
    assert line.endswith(f"on disk {Digest.of_file(file(tmp_path, 'data')).value[:12]}")
    assert "GitHub" not in shown


def test_stale_and_why_say_where_a_witnessed_rerun_ran(tmp_path, capsys):
    manifest, made = project(tmp_path)
    append(entry(tmp_path, made, witness=WITNESSED), tmp_path)

    report = stale(manifest)
    assert [(node.rerun_at, node.witness) for node in report.regenerations] == [(THEN, WITNESSED)]
    account = why(manifest, "total")
    assert account.chain[0].regeneration.witness == WITNESSED

    assert main(["why", "total", str(manifest.path)]) == 0
    shown = capsys.readouterr().out
    assert (
        f"      re-run of {THEN} reproduced in GitHub Actions run 123456 of owner/repo, "
        "and its output is the bytes now on disk\n"
    ) in shown

    assert main(["why", "total", str(manifest.path), "--format", "json"]) == 0
    chain = json.loads(capsys.readouterr().out)["chain"]
    assert chain[0]["regeneration"]["witness"] == WITNESSED.model_dump(mode="json")

    # An input edited after the re-run: the finding names the re-run, and so where it ran.
    file(tmp_path, "data").write_text(json.dumps({"xs": [1, 2, 4]}))
    report = stale(manifest)
    (found,) = report.findings
    assert (found.cause, found.witness) == (StaleCause.INPUT_CHANGED, WITNESSED)
    main(["stale", str(manifest.path)])
    (line,) = [line for line in capsys.readouterr().out.splitlines() if "input changed" in line]
    assert line.endswith("; that re-run was in GitHub Actions run 123456 of owner/repo")
    assert f"the re-run of {THEN} read " in line

    main(["stale", str(manifest.path), "--format", "json"])
    staleness = json.loads(capsys.readouterr().out)["staleness"]
    assert staleness["findings"][0]["witness"] == WITNESSED.model_dump(mode="json")
    assert staleness["regenerations"][0]["witness"] == WITNESSED.model_dump(mode="json")

    main(["why", "total", str(manifest.path)])
    shown = capsys.readouterr().out
    assert "; that re-run was in GitHub Actions run 123456 of owner/repo\n" in shown


def test_each_rerun_is_named_with_its_own_witness(tmp_path):
    manifest, made = project(tmp_path)
    append(entry(tmp_path, made), tmp_path)
    later = entry(tmp_path, made, witness=WITNESSED).model_copy(
        update={"started_at": "2026-02-01T00:00:00+00:00"}
    )
    append(later, tmp_path)
    (node,) = stale(manifest).regenerations
    assert (node.rerun_at, node.witness) == ("2026-02-01T00:00:00+00:00", WITNESSED)
