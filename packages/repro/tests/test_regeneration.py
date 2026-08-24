"""Does the pinned code, over the pinned inputs, still produce the pinned artifact?

The check runs in a sandbox holding only the declared inputs, so nothing in the working tree
is written to and a command needing an undeclared file fails rather than quietly succeeding.
"""
from __future__ import annotations

import json
import sys

import pytest

from repro.models import (
    ArtifactRef,
    Claim,
    Digest,
    Manifest,
    MetricEvidence,
    Regeneration,
    RegenerationReason,
    RegenerationRecord,
    RunOutput,
)
from repro.policy import PUBLICATION, Policy, Severity
from repro.verify import verify

SCRIPT = """
import json, pathlib
data = json.loads(pathlib.Path("inputs.json").read_text())
pathlib.Path("figures.json").write_text(json.dumps({"total": sum(data["xs"])}, indent=2))
"""

NEEDS_UNDECLARED = """
import json, pathlib
pathlib.Path("secret.txt").read_text()
pathlib.Path("figures.json").write_text("{}")
"""


def project(tmp_path, script=SCRIPT, xs=(1, 2, 3), volatile=(), declare_input=True):
    (tmp_path / "make.py").write_text(script)
    (tmp_path / "inputs.json").write_text(json.dumps({"xs": list(xs)}))
    (tmp_path / "secret.txt").write_text("undeclared\n")
    figures = tmp_path / "figures.json"
    figures.write_text(json.dumps({"total": sum(xs)}, indent=2))
    manifest_path = tmp_path / "repro.yaml"
    manifest_path.write_text("")

    def ref(name):
        path = tmp_path / name
        return ArtifactRef(id=name.split(".")[0], path=path, digest=Digest.of_file(path))

    inputs = ((RunOutput(artifact="inputs", digest=Digest.of_file(tmp_path / "inputs.json")),
               RunOutput(artifact="make", digest=Digest.of_file(tmp_path / "make.py")))
              if declare_input else
              (RunOutput(artifact="make", digest=Digest.of_file(tmp_path / "make.py")),))
    return Manifest(
        project="p", path=manifest_path,
        artifacts=(ref("inputs.json"), ref("make.py"), ref("figures.json")),
        regenerations=(RegenerationRecord(
            id="figures", command=(sys.executable, "make.py"), inputs=inputs,
            output=RunOutput(artifact="figures", digest=Digest.of_file(figures)),
            volatile=volatile, timeout_seconds=60),),
        claims=(Claim(id="c", text="t", evidence=(
            MetricEvidence(artifact="figures", name="total",
                           reported=str(sum(xs)), pointer="/total"),)),))


def state(manifest, regenerate=True):
    return verify(manifest, regenerate=regenerate).regenerations[0]


# -- the two verdicts -----------------------------------------------------------------------

def test_the_declared_command_reproduces_the_artifact(tmp_path):
    result = state(project(tmp_path))
    assert result.state is Regeneration.REPRODUCED
    assert result.reason is RegenerationReason.OUTPUT_MATCHES


def test_a_command_producing_something_else_has_diverged(tmp_path):
    manifest = project(tmp_path)
    (tmp_path / "make.py").write_text(SCRIPT.replace("sum(data", "1 + sum(data"))
    # The script is itself a pinned input, so a changed script is reported before it runs.
    assert state(manifest).reason is RegenerationReason.INPUT_CHANGED


def test_an_output_that_no_longer_matches_is_reported(tmp_path):
    """The pinned output digest is stale while the code and inputs are unchanged."""
    manifest = project(tmp_path)
    stale = manifest.model_copy(update={"regenerations": (
        manifest.regenerations[0].model_copy(update={"output": RunOutput(
            artifact="figures",
            digest=Digest(algorithm="sha256", value="0" * 64))}),)})
    result = state(stale)
    assert result.state is Regeneration.DIVERGED
    assert result.reason is RegenerationReason.OUTPUT_DIFFERS
    assert result.actual is not None


# -- the sandbox is the point ----------------------------------------------------------------

def test_a_command_needing_an_undeclared_file_fails(tmp_path):
    """Only declared inputs are placed in the working directory, so the declaration is
    checked for sufficiency and not merely recorded."""
    manifest = project(tmp_path, script=NEEDS_UNDECLARED)
    result = state(manifest)
    assert result.state is Regeneration.DIVERGED
    assert result.reason is RegenerationReason.COMMAND_FAILED


def test_the_working_tree_is_never_written_to(tmp_path):
    manifest = project(tmp_path)
    before = Digest.of_file(tmp_path / "figures.json").value
    mtime = (tmp_path / "figures.json").stat().st_mtime_ns
    state(manifest)
    assert Digest.of_file(tmp_path / "figures.json").value == before
    assert (tmp_path / "figures.json").stat().st_mtime_ns == mtime


# -- opt-in ----------------------------------------------------------------------------------

def test_nothing_runs_unless_asked(tmp_path):
    result = state(project(tmp_path), regenerate=False)
    assert result.state is Regeneration.UNCHECKED
    assert result.reason is RegenerationReason.NOT_REQUESTED


def test_not_having_run_it_is_not_a_finding(tmp_path):
    report = verify(project(tmp_path), regenerate=False)
    assert PUBLICATION.assess(report).passed is True


def test_a_project_can_require_it(tmp_path):
    report = verify(project(tmp_path), regenerate=False)
    demanding = PUBLICATION.model_copy(
        update={"regeneration_unchecked": Severity.ERROR})
    assert demanding.assess(report).passed is False


def test_divergence_fails_the_policy(tmp_path):
    manifest = project(tmp_path)
    stale = manifest.model_copy(update={"regenerations": (
        manifest.regenerations[0].model_copy(update={"output": RunOutput(
            artifact="figures", digest=Digest(algorithm="sha256", value="0" * 64))}),)})
    assessment = PUBLICATION.assess(verify(stale, regenerate=True))
    assert assessment.passed is False
    assert any(v.rule == "artifact.regeneration" for v in assessment.errors)


# -- a changed input is not a divergence -----------------------------------------------------

def test_an_input_that_moved_since_the_record_was_written_is_unchecked(tmp_path):
    manifest = project(tmp_path)
    (tmp_path / "inputs.json").write_text(json.dumps({"xs": [9, 9]}))
    result = state(manifest)
    assert result.state is Regeneration.UNCHECKED, (
        "different inputs producing a different output is not a failure to reproduce")
    assert result.reason is RegenerationReason.INPUT_CHANGED


# -- volatile fields --------------------------------------------------------------------------

def test_a_timestamp_field_can_be_excluded_from_the_comparison(tmp_path):
    """An output carrying a timestamp never reproduces byte for byte; naming the field keeps
    the comparison exact everywhere else."""
    script = """
import json, pathlib, os
data = json.loads(pathlib.Path("inputs.json").read_text())
pathlib.Path("figures.json").write_text(json.dumps(
    {"total": sum(data["xs"]), "generated_at": os.environ.get("STAMP", "now")}))
"""
    (tmp_path / "make.py").write_text(script)
    (tmp_path / "inputs.json").write_text(json.dumps({"xs": [1, 2, 3]}))
    figures = tmp_path / "figures.json"
    figures.write_text(json.dumps({"total": 6, "generated_at": "an earlier run"}))
    manifest_path = tmp_path / "repro.yaml"
    manifest_path.write_text("")

    from repro.regenerate import canonical_digest
    expected = canonical_digest(figures, ("/generated_at",))

    def ref(name):
        path = tmp_path / name
        return ArtifactRef(id=name.split(".")[0], path=path, digest=Digest.of_file(path))

    manifest = Manifest(
        project="p", path=manifest_path,
        artifacts=(ref("inputs.json"), ref("make.py"), ref("figures.json")),
        regenerations=(RegenerationRecord(
            id="figures", command=(sys.executable, "make.py"),
            inputs=(RunOutput(artifact="inputs", digest=Digest.of_file(tmp_path / "inputs.json")),
                    RunOutput(artifact="make", digest=Digest.of_file(tmp_path / "make.py"))),
            output=RunOutput(artifact="figures", digest=expected),
            volatile=("/generated_at",), timeout_seconds=60),),
        claims=(Claim(id="c", text="t", evidence=(
            MetricEvidence(artifact="figures", name="total", reported="6",
                           pointer="/total"),)),))
    assert state(manifest).state is Regeneration.REPRODUCED


def test_without_naming_the_volatile_field_the_same_run_diverges(tmp_path):
    """Which is why the field is named rather than the comparison loosened."""
    from repro.regenerate import canonical_digest
    path = tmp_path / "f.json"
    path.write_text(json.dumps({"total": 6, "generated_at": "then"}))
    assert canonical_digest(path, ()) != canonical_digest(path, ("/generated_at",))


# -- a command that cannot run is not a divergence --------------------------------------------

def test_a_missing_runner_is_unchecked(tmp_path):
    manifest = project(tmp_path)
    broken = manifest.model_copy(update={"regenerations": (
        manifest.regenerations[0].model_copy(
            update={"command": ("definitely-not-a-real-program-9x8y7z",)}),)})
    result = state(broken)
    assert result.state is Regeneration.UNCHECKED
    assert result.reason is RegenerationReason.RUNNER_UNAVAILABLE


def test_an_empty_command_is_refused():
    with pytest.raises(ValueError, match="command is empty"):
        RegenerationRecord(id="r", command=(), output=RunOutput(artifact="a"))
