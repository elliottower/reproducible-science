"""Does the pinned code, over the pinned inputs, still produce the numbers the manuscript prints?

The command runs in a sandbox holding only the declared inputs, so nothing in the working tree
is written to and a command needing an undeclared file fails rather than quietly succeeding.
The verdict is read off the claims, not the bytes: a re-run that writes a different file holding
the same numbers has reproduced them.
"""

from __future__ import annotations

import json
import pathlib
import sys

import pytest
from repro.cli import main
from repro.models import (
    ArtifactRef,
    Claim,
    Digest,
    Manifest,
    MetricEvidence,
    Reading,
    Regeneration,
    RegenerationReason,
    RegenerationRecord,
    RunOutput,
)
from repro.policy import PUBLICATION, STRICT, Severity
from repro.reproduce import RECORD, UnknownRegenerationError, append, reproduce
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

    inputs = (
        (
            RunOutput(artifact="inputs", digest=Digest.of_file(tmp_path / "inputs.json")),
            RunOutput(artifact="make", digest=Digest.of_file(tmp_path / "make.py")),
        )
        if declare_input
        else (RunOutput(artifact="make", digest=Digest.of_file(tmp_path / "make.py")),)
    )
    return Manifest(
        project="p",
        path=manifest_path,
        artifacts=(ref("inputs.json"), ref("make.py"), ref("figures.json")),
        regenerations=(
            RegenerationRecord(
                id="figures",
                command=(sys.executable, "make.py"),
                inputs=inputs,
                output=RunOutput(artifact="figures", digest=Digest.of_file(figures)),
                volatile=volatile,
                timeout_seconds=60,
            ),
        ),
        claims=(
            Claim(
                id="c",
                text="t",
                evidence=(
                    MetricEvidence(
                        artifact="figures", name="total", reported=str(sum(xs)), pointer="/total"
                    ),
                ),
            ),
        ),
    )


def state(manifest, **kwargs):
    return reproduce(manifest, **kwargs).regenerations[0]


# -- the verdicts ----------------------------------------------------------------------------


def test_the_declared_command_reproduces_the_artifact(tmp_path):
    result = state(project(tmp_path))
    assert result.state is Regeneration.REPRODUCED
    assert result.reason is RegenerationReason.OUTPUT_MATCHES
    assert result.bytes_identical is True
    assert result.executed is True and result.exit_code == 0


def test_a_changed_script_is_reported_before_it_runs(tmp_path):
    manifest = project(tmp_path)
    (tmp_path / "make.py").write_text(SCRIPT.replace("sum(data", "1 + sum(data"))
    # The script is itself a pinned input, so a changed script is reported before it runs.
    assert state(manifest).reason is RegenerationReason.INPUT_CHANGED


NONDETERMINISTIC = """
import json, pathlib, random
data = json.loads(pathlib.Path("inputs.json").read_text())
pathlib.Path("figures.json").write_text(
    json.dumps({"total": sum(data["xs"]), "nonce": random.random()}, indent=2))
"""

DRIFTING = """
import json, pathlib, random
data = json.loads(pathlib.Path("inputs.json").read_text())
pathlib.Path("figures.json").write_text(
    json.dumps({"total": sum(data["xs"]) + random.randint(1, 9)}, indent=2))
"""

WRITES_NOTHING = "pass\n"

WRITES_ANOTHER_SHAPE = """
import json, pathlib, random
pathlib.Path("figures.json").write_text(json.dumps({"sum": 6, "nonce": random.random()}))
"""

LEAVES_A_FILE_BEHIND = """
import json, pathlib
data = json.loads(pathlib.Path("inputs.json").read_text())
pathlib.Path("cache").mkdir()
pathlib.Path("cache/scratch.bin").write_text("x")
pathlib.Path("figures.json").write_text(json.dumps({"total": sum(data["xs"])}, indent=2))
"""


def test_different_bytes_holding_the_same_numbers_have_reproduced(tmp_path):
    """The case the verdict was changed for. A re-run that orders a listing differently, or
    carries a field no claim reads, writes another file with every number the manuscript
    prints. Calling that a divergence reports a difference nobody can find in the paper."""
    result = state(project(tmp_path, script=NONDETERMINISTIC))
    assert result.state is Regeneration.REPRODUCED
    assert result.reason is RegenerationReason.CLAIMS_HOLD
    assert result.bytes_identical is False
    assert [c.reading for c in result.claims] == [Reading.HOLDS]


def test_a_number_the_manuscript_prints_that_moved_has_changed(tmp_path):
    result = state(project(tmp_path, script=DRIFTING))
    assert result.state is Regeneration.CHANGED
    assert result.reason is RegenerationReason.CLAIM_CHANGED
    (claim,) = result.claims
    assert claim.reading is Reading.CHANGED
    assert (claim.printed, claim.pinned) == ("6", "6")
    assert claim.fresh is not None and 7 <= int(claim.fresh) <= 15
    assert claim.difference == str(int(claim.fresh) - 6)


def test_a_command_that_exits_cleanly_and_writes_nothing_has_failed(tmp_path):
    """Exit 0 is not evidence that the work was done."""
    result = state(project(tmp_path, script=WRITES_NOTHING))
    assert result.state is Regeneration.FAILED
    assert result.reason is RegenerationReason.OUTPUT_NOT_PRODUCED
    assert result.exit_code == 0


def test_an_output_the_number_cannot_be_read_from_is_unchecked(tmp_path):
    """The command ran and wrote a file. That the pointer resolves to nothing in it is neither
    a number that held nor a number that changed."""
    result = state(project(tmp_path, script=WRITES_ANOTHER_SHAPE))
    assert result.state is Regeneration.UNCHECKED
    assert result.reason is RegenerationReason.CLAIM_UNREADABLE
    assert [c.reading for c in result.claims] == [Reading.UNREADABLE]
    assert result.claims[0].fresh is None


def test_different_bytes_that_no_claim_reads_have_changed(tmp_path):
    """With nothing bound to the file, its bytes are all there is to compare, and they differ."""
    manifest = project(tmp_path, script=NONDETERMINISTIC).model_copy(update={"claims": ()})
    result = state(manifest)
    assert result.state is Regeneration.CHANGED
    assert result.reason is RegenerationReason.NO_CLAIM_READS_OUTPUT


def test_a_number_the_paper_already_misprinted_is_not_blamed_on_the_rerun(tmp_path):
    """The manuscript prints 7 and the pinned file holds 6. The re-run writes 6 again. Nothing
    changed, and the disagreement is `repro verify`'s to report."""
    manifest = project(tmp_path, script=NONDETERMINISTIC)
    wrong = Claim(
        id="c",
        text="t",
        evidence=(
            MetricEvidence(artifact="figures", name="total", reported="7", pointer="/total"),
        ),
    )
    result = state(manifest.model_copy(update={"claims": (wrong,)}))
    assert result.state is Regeneration.REPRODUCED
    assert [c.reading for c in result.claims] == [Reading.ALREADY_MISMATCHED]
    assert (result.claims[0].pinned, result.claims[0].fresh) == ("6", "6")


def test_files_the_command_wrote_and_did_not_declare_are_recorded(tmp_path):
    result = state(project(tmp_path, script=LEAVES_A_FILE_BEHIND))
    assert result.undeclared_outputs == ("cache/scratch.bin",)


def test_a_record_expecting_something_other_than_the_artifact_is_refused(tmp_path):
    """A record could otherwise declare its own answer: the command writes a number, the
    record expects that number, and the artifact the claims were read from says another."""
    manifest = project(tmp_path)
    stale = manifest.model_copy(
        update={
            "regenerations": (
                manifest.regenerations[0].model_copy(
                    update={
                        "output": RunOutput(
                            artifact="figures", digest=Digest(algorithm="sha256", value="0" * 64)
                        )
                    }
                ),
            )
        }
    )
    result = state(stale)
    assert result.state is Regeneration.NOT_RERUN
    assert result.reason is RegenerationReason.OUTPUT_NOT_THE_ARTIFACT
    assert result.executed is False


def test_an_output_copied_in_as_its_own_input_is_refused(tmp_path):
    """Otherwise `true` reproduces it: the file is already at the expected path."""
    manifest = project(tmp_path)
    record = manifest.regenerations[0]
    circular = manifest.model_copy(
        update={
            "regenerations": (
                record.model_copy(
                    update={"command": ("true",), "inputs": (*record.inputs, record.output)}
                ),
            )
        }
    )
    result = state(circular)
    assert result.state is Regeneration.NOT_RERUN
    assert result.reason is RegenerationReason.OUTPUT_IS_ALSO_AN_INPUT


# -- the sandbox is the point ----------------------------------------------------------------


def test_a_command_needing_an_undeclared_file_fails(tmp_path):
    """Only declared inputs are placed in the working directory, so the declaration is
    checked for sufficiency and not merely recorded."""
    manifest = project(tmp_path, script=NEEDS_UNDECLARED)
    result = state(manifest)
    assert result.state is Regeneration.FAILED
    assert result.reason is RegenerationReason.COMMAND_FAILED


def test_the_working_tree_is_never_written_to(tmp_path):
    manifest = project(tmp_path)
    before = Digest.of_file(tmp_path / "figures.json").value
    mtime = (tmp_path / "figures.json").stat().st_mtime_ns
    state(manifest)
    assert Digest.of_file(tmp_path / "figures.json").value == before
    assert (tmp_path / "figures.json").stat().st_mtime_ns == mtime


# -- opt-in ----------------------------------------------------------------------------------


def leaves_a_mark(tmp_path):
    """A manifest whose command writes a file at an absolute path outside the sandbox, so
    whether it was executed can be read off the disk."""
    mark = tmp_path / "the-command-ran"
    script = SCRIPT + f"\npathlib.Path({str(mark)!r}).write_text('ran')\n"
    return project(tmp_path, script=script), mark


def test_verifying_executes_nothing(tmp_path):
    manifest, mark = leaves_a_mark(tmp_path)
    verify(manifest)
    assert not mark.exists()
    reproduce(manifest)
    assert mark.exists(), "the control: the same manifest does run when asked to"


def test_a_skipped_record_is_reported_and_not_run(tmp_path):
    manifest, mark = leaves_a_mark(tmp_path)
    result = state(manifest, skip=("figures",))
    assert result.state is Regeneration.NOT_RERUN
    assert result.reason is RegenerationReason.SKIPPED
    assert not mark.exists()


def test_only_runs_the_records_it_names(tmp_path):
    manifest = project(tmp_path)
    other = manifest.regenerations[0].model_copy(update={"id": "other"})
    both = manifest.model_copy(update={"regenerations": (manifest.regenerations[0], other)})
    report = reproduce(both, only=("other",))
    assert [s.state for s in report.regenerations] == [
        Regeneration.NOT_RERUN,
        Regeneration.REPRODUCED,
    ]


def test_naming_a_record_the_manifest_does_not_declare_is_an_error(tmp_path):
    with pytest.raises(UnknownRegenerationError, match="no-such-record"):
        reproduce(project(tmp_path), only=("no-such-record",))


def test_skipping_a_record_is_not_a_finding(tmp_path):
    report = reproduce(project(tmp_path), skip=("figures",))
    assert PUBLICATION.assess_reproduction(report).passed is True


def test_a_project_can_require_every_record_to_run(tmp_path):
    report = reproduce(project(tmp_path), skip=("figures",))
    demanding = PUBLICATION.model_copy(update={"regeneration_not_rerun": Severity.ERROR})
    assert demanding.assess_reproduction(report).passed is False


def test_a_changed_number_fails_the_policy(tmp_path):
    assessment = PUBLICATION.assess_reproduction(reproduce(project(tmp_path, script=DRIFTING)))
    assert assessment.passed is False
    assert [v.rule for v in assessment.errors] == ["reproduction.changed.claim_changed"]


def test_an_unreadable_output_warns_a_draft_and_fails_a_strict_check(tmp_path):
    report = reproduce(project(tmp_path, script=WRITES_ANOTHER_SHAPE))
    assert PUBLICATION.assess_reproduction(report).passed is True
    assert len(PUBLICATION.assess_reproduction(report).warnings) == 1
    assert STRICT.assess_reproduction(report).passed is False


def test_reproducing_with_different_bytes_passes_the_strictest_policy(tmp_path):
    report = reproduce(project(tmp_path, script=NONDETERMINISTIC))
    assert STRICT.assess_reproduction(report).violations == ()


# -- a changed input is not a changed number --------------------------------------------------


def test_an_input_that_moved_since_the_record_was_written_is_not_rerun(tmp_path):
    manifest, mark = leaves_a_mark(tmp_path)
    (tmp_path / "inputs.json").write_text(json.dumps({"xs": [9, 9]}))
    result = state(manifest)
    assert result.state is Regeneration.NOT_RERUN, (
        "different inputs producing a different output is not a failure to reproduce"
    )
    assert result.reason is RegenerationReason.INPUT_CHANGED
    assert not mark.exists(), "a record refused for its inputs must not have executed anything"
    moved = next(i for i in result.inputs if i.artifact_id == "inputs")
    assert moved.pinned != moved.observed and moved.path == "inputs.json"


# -- a record that rests on one that did not reproduce ----------------------------------------


def test_a_record_downstream_of_one_that_was_not_rerun_says_so(tmp_path):
    """`table` reads what `figures` writes, and `summary` reads what `table` writes. Skipping
    `figures` still lets the other two run, over its pinned output, and both carry the
    condition -- including the one two steps away."""
    manifest = project(tmp_path)
    (tmp_path / "table.py").write_text(
        "import json, pathlib\n"
        "total = json.loads(pathlib.Path('figures.json').read_text())['total']\n"
        "pathlib.Path('table.json').write_text(json.dumps({'double': 2 * total}))\n"
    )
    (tmp_path / "summary.py").write_text(
        "import json, pathlib\n"
        "double = json.loads(pathlib.Path('table.json').read_text())['double']\n"
        "pathlib.Path('summary.json').write_text(json.dumps({'half': double // 2}))\n"
    )
    (tmp_path / "table.json").write_text(json.dumps({"double": 12}))
    (tmp_path / "summary.json").write_text(json.dumps({"half": 6}))

    def ref(name):
        path = tmp_path / name
        return ArtifactRef(id=name.replace(".", "_"), path=path, digest=Digest.of_file(path))

    def pin(artifact_id, name):
        return RunOutput(artifact=artifact_id, digest=Digest.of_file(tmp_path / name))

    chained = manifest.model_copy(
        update={
            "artifacts": (
                *manifest.artifacts,
                ref("table.py"),
                ref("summary.py"),
                ref("table.json"),
                ref("summary.json"),
            ),
            "regenerations": (
                *manifest.regenerations,
                RegenerationRecord(
                    id="table",
                    command=(sys.executable, "table.py"),
                    inputs=(pin("figures", "figures.json"), pin("table_py", "table.py")),
                    output=pin("table_json", "table.json"),
                ),
                RegenerationRecord(
                    id="summary",
                    command=(sys.executable, "summary.py"),
                    inputs=(pin("table_json", "table.json"), pin("summary_py", "summary.py")),
                    output=pin("summary_json", "summary.json"),
                ),
            ),
        }
    )
    by_id = {s.regeneration_id: s for s in reproduce(chained, skip=("figures",)).regenerations}
    assert by_id["table"].state is Regeneration.REPRODUCED
    assert by_id["table"].rests_on == ("figures",)
    assert by_id["summary"].rests_on == ("figures",)

    everything = {s.regeneration_id: s for s in reproduce(chained).regenerations}
    assert [s.rests_on for s in everything.values()] == [(), (), ()]


# -- what a record carries, and what it must not ----------------------------------------------

SAYS_WHERE_IT_IS = """
import os, sys
print(os.getcwd(), file=sys.stderr)
print(os.path.expanduser("~") + "/x: no such file", file=sys.stderr)
raise SystemExit(3)
"""


def test_a_record_names_no_directory_on_the_machine_that_made_it(tmp_path):
    """Records are committed to repositories that become public. The command is the manifest's
    own text and is left out of the search; everything the tool wrote is in it."""
    project_dir = tmp_path / "a-directory-name-that-must-not-leak"
    project_dir.mkdir()
    report = reproduce(project(project_dir, script=SAYS_WHERE_IT_IS))
    (failed,) = report.regenerations
    assert failed.state is Regeneration.FAILED and failed.exit_code == 3

    written = report.model_dump(mode="json")
    for regeneration in written["regenerations"]:
        del regeneration["command"]
    text = json.dumps(written)
    assert "a-directory-name-that-must-not-leak" not in text
    assert str(pathlib.Path.home()) not in text
    assert "repro-regen-" not in text, "the sandbox's own path is a path on this machine"


def test_the_environment_is_recorded(tmp_path):
    (tmp_path / "uv.lock").write_text("version = 1\n")
    environment = reproduce(project(tmp_path)).environment
    assert environment.python.count(".") == 2
    assert environment.system and environment.machine
    assert environment.lockfile == "uv.lock"
    assert environment.lockfile_digest == Digest.of_file(tmp_path / "uv.lock").value


def test_each_invocation_is_appended_and_the_manifest_is_left_alone(tmp_path):
    manifest = project(tmp_path)
    before = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    first = append(reproduce(manifest), tmp_path)
    second = append(reproduce(manifest, skip=("figures",)), tmp_path)
    assert first == second == tmp_path / RECORD
    lines = [json.loads(line) for line in first.read_text().splitlines()]
    assert [line["regenerations"][0]["state"] for line in lines] == ["reproduced", "not_rerun"]
    assert {path: path.read_bytes() for path in before} == before


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
        project="p",
        path=manifest_path,
        artifacts=(ref("inputs.json"), ref("make.py"), ref("figures.json")),
        regenerations=(
            RegenerationRecord(
                id="figures",
                command=(sys.executable, "make.py"),
                inputs=(
                    RunOutput(artifact="inputs", digest=Digest.of_file(tmp_path / "inputs.json")),
                    RunOutput(artifact="make", digest=Digest.of_file(tmp_path / "make.py")),
                ),
                output=RunOutput(artifact="figures", digest=expected),
                volatile=("/generated_at",),
                timeout_seconds=60,
            ),
        ),
        claims=(
            Claim(
                id="c",
                text="t",
                evidence=(
                    MetricEvidence(
                        artifact="figures", name="total", reported="6", pointer="/total"
                    ),
                ),
            ),
        ),
    )
    assert state(manifest).state is Regeneration.REPRODUCED


def test_without_naming_the_volatile_field_the_bytes_differ(tmp_path):
    """Which is why the field is named rather than the comparison loosened."""
    from repro.regenerate import canonical_digest

    path = tmp_path / "f.json"
    path.write_text(json.dumps({"total": 6, "generated_at": "then"}))
    assert canonical_digest(path, ()) != canonical_digest(path, ("/generated_at",))


# -- a command that cannot run has failed ------------------------------------------------------


def test_a_missing_runner_has_failed_without_running(tmp_path):
    manifest = project(tmp_path)
    broken = manifest.model_copy(
        update={
            "regenerations": (
                manifest.regenerations[0].model_copy(
                    update={"command": ("definitely-not-a-real-program-9x8y7z",)}
                ),
            )
        }
    )
    result = state(broken)
    assert result.state is Regeneration.FAILED
    assert result.reason is RegenerationReason.RUNNER_UNAVAILABLE
    assert result.executed is False


def test_an_empty_command_is_refused():
    with pytest.raises(ValueError, match="command is empty"):
        RegenerationRecord(id="r", command=(), output=RunOutput(artifact="a"))


# -- the sandbox has to actually contain things ---------------------------------------------


@pytest.mark.parametrize(
    "relative",
    [
        "figures.json",
        "../victim/planted.txt",
        "../../../etc/passwd",
    ],
)
def test_every_declared_path_lands_inside_the_sandbox(tmp_path, relative):
    """`Path.relative_to` is lexical, so an absolute artifact path containing `..` produced a
    relative path that climbed back out, and `sandbox / that` was not inside the sandbox at
    all -- on the write side before the command even ran, and on the read side by resolving
    the output to the real pre-existing artifact."""
    from repro.regenerate import _inside

    root = tmp_path / "project"
    root.mkdir()
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    target = _inside(sandbox, root / relative, root)
    assert target is not None
    assert str(target).startswith(str(sandbox.resolve()) + "/"), (
        f"{relative} escaped the sandbox to {target}"
    )


def test_two_inputs_sharing_a_basename_do_not_overwrite_each_other(tmp_path):
    """The second silently replaced the first, and the command then read a file that was never
    digest-matched to the input it stood for."""
    import sys

    root = tmp_path / "project"
    root.mkdir()
    (root / "make.py").write_text("import pathlib; pathlib.Path('out.json').write_text('{}')\n")
    (root / "out.json").write_text("{}")
    manifest_path = root / "repro.yaml"
    manifest_path.write_text("")

    one = tmp_path / "a" / "shared.txt"
    two = tmp_path / "b" / "shared.txt"
    for path, body in ((one, "first"), (two, "second")):
        path.parent.mkdir(parents=True)
        path.write_text(body)

    manifest = Manifest(
        project="p",
        path=manifest_path,
        artifacts=(
            ArtifactRef(id="make", path=root / "make.py", digest=Digest.of_file(root / "make.py")),
            ArtifactRef(id="out", path=root / "out.json", digest=Digest.of_file(root / "out.json")),
            ArtifactRef(id="one", path=one, digest=Digest.of_file(one)),
            ArtifactRef(id="two", path=two, digest=Digest.of_file(two)),
        ),
        regenerations=(
            RegenerationRecord(
                id="r",
                command=(sys.executable, "make.py"),
                inputs=(
                    RunOutput(artifact="make", digest=Digest.of_file(root / "make.py")),
                    RunOutput(artifact="one", digest=Digest.of_file(one)),
                    RunOutput(artifact="two", digest=Digest.of_file(two)),
                ),
                output=RunOutput(artifact="out", digest=Digest.of_file(root / "out.json")),
                timeout_seconds=30,
            ),
        ),
        claims=(
            Claim(
                id="c",
                text="t",
                evidence=(MetricEvidence(artifact="out", name="m", reported="1", pointer="/x"),),
            ),
        ),
    )
    result = reproduce(manifest).regenerations[0]
    assert result.state is Regeneration.NOT_RERUN
    assert "collide" in result.detail


# -- the command ------------------------------------------------------------------------------

MANIFEST = """\
project: p
artifacts:
  - {{id: inputs, path: inputs.json, digest: {{algorithm: sha256, value: "{inputs}"}}}}
  - {{id: make, path: make.py, digest: {{algorithm: sha256, value: "{make}"}}}}
  - {{id: figures, path: figures.json, digest: {{algorithm: sha256, value: "{figures}"}}}}
claims:
  - id: c
    text: t
    evidence:
      - {{kind: metric, artifact: figures, name: total, reported: "6", pointer: /total}}
regenerations:
  - id: figures
    command: ["{python}", make.py]
    inputs:
      - {{artifact: inputs, digest: {{algorithm: sha256, value: "{inputs}"}}}}
      - {{artifact: make, digest: {{algorithm: sha256, value: "{make}"}}}}
    output: {{artifact: figures, digest: {{algorithm: sha256, value: "{figures}"}}}}
"""


def on_disk(tmp_path, script):
    project(tmp_path, script=script)
    (tmp_path / "repro.yaml").write_text(
        MANIFEST.format(
            python=sys.executable,
            **{
                name: Digest.of_file(tmp_path / file).value
                for name, file in (
                    ("inputs", "inputs.json"),
                    ("make", "make.py"),
                    ("figures", "figures.json"),
                )
            },
        )
    )
    return tmp_path / "repro.yaml"


def test_the_command_prints_both_values_of_a_number_that_changed(tmp_path, capsys):
    code = main(["reproduce", str(on_disk(tmp_path, DRIFTING))])
    out = capsys.readouterr().out
    assert code == 1
    assert "re-ran 1 of 1" in out
    assert "changed" in out and "6 then, " in out and "paper prints 6" in out
    assert len((tmp_path / RECORD).read_text().splitlines()) == 1


def test_the_command_passes_a_rerun_whose_numbers_hold(tmp_path, capsys):
    code = main(["reproduce", str(on_disk(tmp_path, NONDETERMINISTIC))])
    out = capsys.readouterr().out
    assert code == 0
    assert "bytes differ, 1 of 1 numbers hold" in out


def test_verify_no_longer_takes_a_flag_that_executes(tmp_path):
    with pytest.raises(SystemExit):
        main(["verify", str(on_disk(tmp_path, SCRIPT)), "--regenerate"])


def test_a_manifest_declaring_no_command_has_nothing_to_run(tmp_path, capsys):
    path = on_disk(tmp_path, SCRIPT)
    path.write_text(path.read_text().split("regenerations:")[0])
    assert main(["reproduce", str(path)]) == 2
    assert "nothing to run again" in capsys.readouterr().out
    assert not (tmp_path / RECORD).exists()
