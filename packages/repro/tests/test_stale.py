"""Is what a claim reads still what a recorded re-run produced?

Nothing here executes a command. The record of re-runs is written with the models
`repro reproduce` writes it with, as the entry a re-run over the files then on disk would have
left, and the files are edited afterwards.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import re

import pytest
from repro.cli import main
from repro.models import (
    ArtifactRef,
    Claim,
    Digest,
    Freshness,
    InputReading,
    Manifest,
    MetricEvidence,
    Outcome,
    Regeneration,
    RegenerationReason,
    RegenerationRecord,
    RegenerationState,
    ReproductionReport,
    RunOutput,
    StaleCause,
    StalenessReport,
    Validity,
)
from repro.policy import EXPLORATORY, PUBLICATION, STRICT
from repro.regenerate import canonical_digest
from repro.reproduce import RECORD, append
from repro.stale import RecordUnreadableError, stale
from repro.verify import verify

THEN = "2026-01-01T00:00:00+00:00"

#: The line the mod and `repro audit` take for `repro verify`'s summary: counts and one word
#: each, and nothing else on the line.
VERIFY_SUMMARY = re.compile(r"^\s*\d+ \w+(?:, \d+ \w+)*$")


def file(root, name):
    return root / f"{name}.json"


def put(root, name, **fields):
    file(root, name).write_text(json.dumps({"total": 6, **fields}))


def record(root, name, inputs, output, volatile=()):
    return RegenerationRecord(
        id=name,
        command=("make", name),
        inputs=tuple(RunOutput(artifact=i, digest=Digest.of_file(file(root, i))) for i in inputs),
        output=RunOutput(artifact=output, digest=canonical_digest(file(root, output), volatile)),
        volatile=volatile,
    )


def claim(artifact):
    return Claim(
        id=f"on-{artifact}",
        text="t",
        evidence=(MetricEvidence(artifact=artifact, name="total", reported="6", pointer="/total"),),
    )


def manifest(root, records, claims):
    """Every file under root pinned as it is now: what a manifest rebuilt from disk holds."""
    return Manifest(
        project="p",
        path=root / "repro.yaml",
        artifacts=tuple(
            ArtifactRef(id=p.stem, path=p, digest=Digest.of_file(p))
            for p in sorted(root.glob("*.json"))
        ),
        regenerations=tuple(records),
        claims=tuple(claims),
    )


def rerun(root, made, **changes):
    """The entry `repro reproduce` leaves for a record that ran over the files now on disk
    and wrote the output now on disk."""
    written = canonical_digest(file(root, made.output.artifact), made.volatile).value
    entry = RegenerationState(
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
    return entry.model_copy(update=changes)


def log(root, *entries, at=THEN):
    append(ReproductionReport(started_at=at, regenerations=entries), root)


def chain(root, prefix, length):
    """`{prefix}0 -> r{prefix}1 -> {prefix}1 -> ...`, each record re-run over the files as
    written."""
    for i in range(length + 1):
        put(root, f"{prefix}{i}", step=f"{prefix}{i}")
    records = [
        record(root, f"r{prefix}{i}", (f"{prefix}{i - 1}",), f"{prefix}{i}")
        for i in range(1, length + 1)
    ]
    log(root, *(rerun(root, made) for made in records))
    return records


def by_id(nodes):
    return {node.id: node for node in nodes}


def snapshot(root: pathlib.Path) -> dict[str, str]:
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


# -- the gap ----------------------------------------------------------------------------------


def test_an_edited_input_leaves_verify_passing_and_is_named_by_stale(tmp_path):
    records = chain(tmp_path, "a", 1)
    project = manifest(tmp_path, records, [claim("a1")])
    assert stale(project).claims[0].state is Freshness.CURRENT
    before = Digest.of_file(file(tmp_path, "a0")).value

    put(tmp_path, "a0", step="edited")
    (decision,) = verify(project).claims[0].decisions
    assert decision.outcome is Outcome.VERIFIED
    assert decision.validity is Validity.AUTHORITATIVE

    report = stale(project)
    assert report.claims[0].state is Freshness.STALE
    (found,) = report.findings
    assert (found.cause, found.regeneration, found.artifact) == (
        StaleCause.INPUT_CHANGED,
        "ra1",
        "a0",
    )
    assert (found.observed, found.on_disk) == (before, Digest.of_file(file(tmp_path, "a0")).value)
    assert found.rerun_at == THEN


def test_the_stored_result_of_a_claim_is_not_rewritten_by_an_upstream_edit(tmp_path):
    project = manifest(tmp_path, chain(tmp_path, "a", 2), [claim("a2")])
    before = verify(project).claims[0].model_dump(mode="json")
    put(tmp_path, "a0", step="edited")
    assert stale(project).claims[0].state is Freshness.STALE
    assert verify(project).claims[0].model_dump(mode="json") == before


def test_a_manifest_rebuilt_from_disk_does_not_erase_the_signal(tmp_path):
    records = chain(tmp_path, "a", 1)
    put(tmp_path, "a0", step="edited")
    rebuilt = manifest(tmp_path, [record(tmp_path, "ra1", ("a0",), "a1")], [claim("a1")])

    checked = verify(rebuilt)
    assert {a.validity for a in checked.artifacts} == {Validity.AUTHORITATIVE}
    assert PUBLICATION.assess(checked).violations == ()
    assert rebuilt.regenerations[0] != records[0]

    report = stale(rebuilt)
    assert report.record_disagrees_with_pin == ()
    assert report.claims[0].state is Freshness.STALE
    assert [f.cause for f in report.findings] == [StaleCause.INPUT_CHANGED]

    log(tmp_path, rerun(tmp_path, rebuilt.regenerations[0]), at="2026-02-01T00:00:00+00:00")
    assert stale(rebuilt).claims[0].state is Freshness.CURRENT


# -- depth ------------------------------------------------------------------------------------


def test_an_edit_three_records_upstream_is_one_finding_and_a_distance(tmp_path):
    records = [*chain(tmp_path, "a", 3), *chain(tmp_path, "b", 3)]
    project = manifest(tmp_path, records, [claim("a3"), claim("b3")])
    put(tmp_path, "a0", step="edited")

    report = stale(project)
    assert [(c.id, c.state) for c in report.claims] == [
        ("on-a3", Freshness.STALE),
        ("on-b3", Freshness.CURRENT),
    ]
    assert [(f.regeneration, f.artifact) for f in report.findings] == [("ra1", "a0")]

    nodes = by_id(report.regenerations)
    assert (nodes["ra1"].causes, nodes["ra1"].upstream) == ((StaleCause.INPUT_CHANGED,), None)
    for name, distance in (("ra2", 1), ("ra3", 2)):
        assert nodes[name].state is Freshness.STALE
        assert nodes[name].causes == (StaleCause.UPSTREAM_STALE,)
        assert (nodes[name].upstream, nodes[name].distance) == ("ra1", distance)
    assert {nodes[f"rb{i}"].state for i in (1, 2, 3)} == {Freshness.CURRENT}

    states = {a.id: a.state for a in report.artifacts}
    assert states["a0"] is Freshness.NO_PRODUCER and states["b3"] is Freshness.CURRENT
    assert {states[f"a{i}"] for i in (1, 2, 3)} == {Freshness.STALE}


def test_a_ladder_of_diamonds_reports_each_changed_input_once(tmp_path):
    rungs = 40
    put(tmp_path, "base0", step="base0")
    records = []
    for i in range(1, rungs + 1):
        for side in ("left", "right"):
            put(tmp_path, f"{side}{i}", step=f"{side}{i}")
            records.append(record(tmp_path, f"r{side}{i}", (f"base{i - 1}",), f"{side}{i}"))
        put(tmp_path, f"base{i}", step=f"base{i}")
        records.append(record(tmp_path, f"rbase{i}", (f"left{i}", f"right{i}"), f"base{i}"))
    log(tmp_path, *(rerun(tmp_path, made) for made in records))
    project = manifest(tmp_path, records, [claim(f"base{rungs}")])
    assert stale(project).claims[0].state is Freshness.CURRENT

    put(tmp_path, "base0", step="edited")
    report = stale(project)
    # Two to the fortieth routes lead from the last file to the first.
    assert sorted((f.regeneration, f.artifact) for f in report.findings) == [
        ("rleft1", "base0"),
        ("rright1", "base0"),
    ]
    assert report.claims[0].state is Freshness.STALE
    top = by_id(report.regenerations)[f"rbase{rungs}"]
    assert top.upstream in ("rleft1", "rright1")
    assert top.distance == 2 * (rungs - 1) + 1
    assert {node.state for node in report.regenerations} == {Freshness.STALE}


# -- what cannot be compared ------------------------------------------------------------------


def test_records_on_a_cycle_are_undetermined_and_the_walk_ends(tmp_path):
    for name in ("x", "y", "z", "own"):
        put(tmp_path, name, step=name)
    records = [
        record(tmp_path, "rx", ("y",), "x"),
        record(tmp_path, "ry", ("x",), "y"),
        record(tmp_path, "rz", ("y",), "z"),
        record(tmp_path, "rown", ("own",), "own"),
    ]
    log(tmp_path, *(rerun(tmp_path, made) for made in records))
    report = stale(manifest(tmp_path, records, [claim("y"), claim("z"), claim("own")]))

    nodes = by_id(report.regenerations)
    for name in ("rx", "ry", "rown"):
        assert nodes[name].state is Freshness.UNDETERMINED
        assert nodes[name].causes == (StaleCause.CYCLE,)
    assert nodes["rz"].state is Freshness.UNDETERMINED
    assert (nodes["rz"].upstream, nodes["rz"].distance) == ("ry", 1)
    assert {c.state for c in report.claims} == {Freshness.UNDETERMINED}
    assert sorted(f.regeneration for f in report.findings) == ["rown", "rx", "ry"]


def test_a_missing_input_or_output_is_undetermined(tmp_path):
    records = chain(tmp_path, "a", 1) + chain(tmp_path, "b", 1)
    project = manifest(tmp_path, records, [claim("a1"), claim("b1")])
    file(tmp_path, "a0").unlink()
    file(tmp_path, "b1").unlink()

    report = stale(project)
    assert [c.state for c in report.claims] == [Freshness.UNDETERMINED, Freshness.UNDETERMINED]
    assert [(f.cause, f.regeneration, f.artifact) for f in report.findings] == [
        (StaleCause.INPUT_MISSING, "ra1", "a0"),
        (StaleCause.OUTPUT_MISSING, "rb1", "b1"),
    ]


def test_a_producer_with_no_reproduced_rerun_was_never_rerun(tmp_path):
    for name in ("in", "unlogged", "changed", "refused", "after"):
        put(tmp_path, name, step=name)
    records = [
        record(tmp_path, "runlogged", ("in",), "unlogged"),
        record(tmp_path, "rchanged", ("in",), "changed"),
        record(tmp_path, "rrefused", ("in",), "refused"),
        record(tmp_path, "rafter", ("unlogged",), "after"),
    ]
    log(
        tmp_path,
        rerun(tmp_path, records[1], state=Regeneration.CHANGED),
        rerun(tmp_path, records[2], state=Regeneration.NOT_RERUN, executed=False),
        rerun(tmp_path, records[3]),
    )
    project = manifest(tmp_path, records, [claim(r.output.artifact) for r in records])

    report = stale(project)
    assert {c.state for c in report.claims} == {Freshness.NEVER_RERUN}
    assert report.findings == ()
    after = by_id(report.regenerations)["rafter"]
    assert (after.upstream, after.distance) == ("runlogged", 1)

    log(tmp_path, *(rerun(tmp_path, made) for made in records[:3]))
    assert {c.state for c in stale(project).claims} == {Freshness.CURRENT}


# -- the other causes -------------------------------------------------------------------------


def test_a_command_that_is_no_longer_the_one_that_ran_is_stale(tmp_path):
    (made,) = chain(tmp_path, "a", 1)
    edited = made.model_copy(update={"command": ("make", "ra1", "--fast")})
    report = stale(manifest(tmp_path, [edited], [claim("a1")]))
    assert report.claims[0].state is Freshness.STALE
    assert [(f.cause, f.regeneration) for f in report.findings] == [
        (StaleCause.COMMAND_CHANGED, "ra1")
    ]


def test_an_output_edited_after_its_rerun_is_stale(tmp_path):
    project = manifest(tmp_path, chain(tmp_path, "a", 1), [claim("a1")])
    before = Digest.of_file(file(tmp_path, "a1")).value
    put(tmp_path, "a1", step="edited by hand")
    (found,) = stale(project).findings
    assert (found.cause, found.artifact) == (StaleCause.OUTPUT_CHANGED, "a1")
    assert (found.observed, found.on_disk) == (before, Digest.of_file(file(tmp_path, "a1")).value)


def test_an_output_differing_only_in_a_volatile_field_has_not_changed(tmp_path):
    put(tmp_path, "in")
    put(tmp_path, "out", generated_at="then")
    made = record(tmp_path, "r", ("in",), "out", volatile=("/generated_at",))
    log(tmp_path, rerun(tmp_path, made))
    project = manifest(tmp_path, [made], [claim("out")])
    raw = Digest.of_file(file(tmp_path, "out"))

    put(tmp_path, "out", generated_at="now")
    assert Digest.of_file(file(tmp_path, "out")) != raw
    assert stale(project).regenerations[0].state is Freshness.CURRENT

    put(tmp_path, "out", generated_at="now", extra=1)
    assert stale(project).regenerations[0].causes == (StaleCause.OUTPUT_CHANGED,)


def test_the_file_a_rerun_reproduced_with_other_bytes_is_its_output(tmp_path):
    (made,) = chain(tmp_path, "a", 1)
    (tmp_path / RECORD).unlink()
    log(
        tmp_path,
        rerun(
            tmp_path,
            made,
            reason=RegenerationReason.CLAIMS_HOLD,
            actual="0" * 64,
            bytes_identical=False,
        ),
    )
    assert stale(manifest(tmp_path, [made], [])).regenerations[0].state is Freshness.CURRENT


def test_a_record_whose_input_digest_is_not_the_pin_is_noted_and_changes_no_state(tmp_path):
    (made,) = chain(tmp_path, "a", 1)
    elsewhere = Digest(value="1" * 64)
    moved = made.model_copy(update={"inputs": (RunOutput(artifact="a0", digest=elsewhere),)})
    report = stale(manifest(tmp_path, [moved], [claim("a1")]))
    (note,) = report.record_disagrees_with_pin
    assert (note.regeneration, note.artifact) == ("ra1", "a0")
    assert (note.recorded, note.pinned) == ("1" * 64, Digest.of_file(file(tmp_path, "a0")).value)
    assert report.claims[0].state is Freshness.CURRENT and report.findings == ()


def test_a_line_of_the_record_that_is_not_a_report_is_an_error(tmp_path):
    project = manifest(tmp_path, chain(tmp_path, "a", 1), [])
    with (tmp_path / RECORD).open("a") as handle:
        handle.write('{"regenerations": [{"state": "reproduced"}]}\n')
    with pytest.raises(RecordUnreadableError, match=r"reproductions\.jsonl:2"):
        stale(project)


# -- the policy -------------------------------------------------------------------------------


def findings_under(policy, report):
    assessment = policy.assess_staleness(report)
    return assessment.passed, len(assessment.errors), len(assessment.warnings)


def test_a_stale_record_warns_a_submission_and_fails_a_strict_check(tmp_path):
    project = manifest(tmp_path, chain(tmp_path, "a", 2), [claim("a2")])
    assert STRICT.assess_staleness(stale(project)).violations == ()
    put(tmp_path, "a0", step="edited")
    report = stale(project)
    assert findings_under(EXPLORATORY, report) == (True, 0, 2)
    assert findings_under(PUBLICATION, report) == (True, 0, 2)
    assert findings_under(STRICT, report) == (False, 2, 0)
    assert [v.rule for v in STRICT.assess_staleness(report).errors] == ["staleness.stale"] * 2


def test_what_was_never_rerun_or_cannot_be_compared_is_ignored_in_a_draft(tmp_path):
    put(tmp_path, "in")
    put(tmp_path, "out")
    never = manifest(tmp_path, [record(tmp_path, "r", ("in",), "out")], [claim("out")])
    missing = manifest(tmp_path, chain(tmp_path, "a", 1), [claim("a1")])
    file(tmp_path, "a0").unlink()
    for project, state in ((never, Freshness.NEVER_RERUN), (missing, Freshness.UNDETERMINED)):
        report = stale(project)
        assert [node.state for node in report.regenerations] == [state]
        assert findings_under(EXPLORATORY, report) == (True, 0, 0)
        assert findings_under(PUBLICATION, report) == (True, 0, 1)
        assert findings_under(STRICT, report) == (False, 1, 0)


def test_a_file_with_no_producer_is_counted_and_never_a_violation(tmp_path):
    project = manifest(tmp_path, chain(tmp_path, "a", 1), [claim("a0")])
    put(tmp_path, "a0", step="edited")
    report = stale(project)
    assert report.claims[0].state is Freshness.NO_PRODUCER
    stale_records = [node.id for node in report.regenerations if node.state is Freshness.STALE]
    assert [v.subject for v in STRICT.assess_staleness(report).violations] == stale_records


# -- the command ------------------------------------------------------------------------------


def on_disk(project):
    project.path.write_text(project.model_dump_json())
    return str(project.path)


def test_every_summary_carries_what_it_is_a_count_of(tmp_path, capsys):
    records = chain(tmp_path, "a", 2)
    project = manifest(tmp_path, records, [claim("a2"), claim("a1"), claim("a0")])
    path = on_disk(project)

    def summary():
        code = main(["stale", path])
        out = capsys.readouterr().out
        assert not [line for line in out.splitlines() if VERIFY_SUMMARY.match(line)]
        for line in out.splitlines():
            if re.search(r"\d+ stale\b", line):
                assert re.search(r" of \d+ assertions | \d+ claims: ", f" {line.strip()}")
        return code, out

    code, out = summary()
    assert code == 0
    assert "0 stale, 0 never rerun, 0 undetermined, 2 current of 2 assertions that read" in out
    assert "1 assertions read 1 files no command is recorded for" in out
    assert "3 claims: 0 stale, 0 never rerun, 2 current, 0 partly outside the record, " in out
    assert "1 outside the record, 0 undetermined" in out
    assert "STALE" not in out

    put(tmp_path, "a0", step="edited")
    code, out = summary()
    assert code == 0
    assert re.search(r"STALE +a1: input changed: a0 .*the re-run of 2026-01-01", out)
    assert re.search(r"STALE +a2: upstream stale: ra1, 1 step up", out)
    assert re.search(r"stale +on-a2 +reads a2", out)
    assert "2 stale, 0 never rerun, 0 undetermined, 0 current of 2 assertions that read" in out
    assert "1 assertions read 1 files no command is recorded for" in out
    assert "policy publication: passed  (0 errors, 2 warnings)" in out
    assert main(["stale", path, "--policy", "strict"]) == 1
    capsys.readouterr()

    (tmp_path / RECORD).unlink()
    code, out = summary()
    assert "holds no re-run" in out
    assert "0 stale, 2 never rerun, 0 undetermined, 0 current of 2 assertions that read" in out
    assert "1 assertions read 1 files no command is recorded for" in out


def test_the_json_document_is_the_report_as_a_graph(tmp_path, capsys):
    project = manifest(tmp_path, chain(tmp_path, "a", 2), [claim("a2"), claim("a0")])
    put(tmp_path, "a0", step="edited")
    assert main(["stale", on_disk(project), "--format", "json"]) == 0
    document = json.loads(capsys.readouterr().out)
    assert StalenessReport.model_validate(document["staleness"]) == stale(project)
    assert document["assessment"]["policy"] == "publication"

    edges = document["staleness"]["edges"]
    assert sorted((e["kind"], e["source"], e["target"]) for e in edges) == [
        ("consumes", "ra1", "a0"),
        ("consumes", "ra2", "a1"),
        ("produced_by", "a1", "ra1"),
        ("produced_by", "a2", "ra2"),
        ("reads", "on-a0", "a0"),
        ("reads", "on-a2", "a2"),
    ]
    consumed = next(e for e in edges if (e["kind"], e["target"]) == ("consumes", "a0"))
    assert consumed["observed"] != consumed["on_disk"] == Digest.of_file(file(tmp_path, "a0")).value
    (found,) = document["staleness"]["findings"]
    assert set(found) == {
        "cause",
        "regeneration",
        "artifact",
        "observed",
        "on_disk",
        "rerun_at",
        "witness",
    }
    assert found["witness"] is None
    for table in ("claims", "artifacts", "regenerations"):
        assert all("state" in node for node in document["staleness"][table])
    assert all("state" in a for c in document["staleness"]["claims"] for a in c["assertions"])


def test_the_command_writes_nothing(tmp_path, capsys):
    project = manifest(tmp_path, chain(tmp_path, "a", 2), [claim("a2")])
    path = on_disk(project)
    put(tmp_path, "a0", step="edited")
    before = snapshot(tmp_path)
    stale(project)
    assert main(["stale", path]) == 0
    assert main(["stale", path, "--format", "json", "--policy", "strict"]) == 1
    assert snapshot(tmp_path) == before

    (tmp_path / RECORD).unlink()
    (tmp_path / RECORD).parent.rmdir()
    before = snapshot(tmp_path)
    assert main(["stale", path]) == 0
    assert snapshot(tmp_path) == before
    assert "holds no re-run" in capsys.readouterr().out


def test_the_command_exits_2_where_there_is_nothing_to_compare(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main(["stale"]) == 2
    assert "no repro.yaml here or above" in capsys.readouterr().out

    put(tmp_path, "a0")
    assert main(["stale", on_disk(manifest(tmp_path, [], [claim("a0")]))]) == 2
    assert "no command is declared" in capsys.readouterr().out

    (made,) = chain(tmp_path, "a", 1)
    project = manifest(tmp_path, [made], [claim("a1")])
    document = json.loads(project.model_dump_json())
    document["regenerations"].append({**document["regenerations"][0], "id": "again"})
    project.path.write_text(json.dumps(document))
    assert main(["stale", str(project.path)]) == 2
    assert "both write artifact 'a1'" in capsys.readouterr().out

    on_disk(project)
    with (tmp_path / RECORD).open("a") as handle:
        handle.write("not a report\n")
    assert main(["stale", str(project.path)]) == 2
    assert "reproductions.jsonl:2" in capsys.readouterr().out


LATER = "2026-02-01T00:00:00+00:00"


def test_a_later_rerun_over_the_same_inputs_that_did_not_reproduce_is_undetermined(
    tmp_path, capsys
):
    records = chain(tmp_path, "a", 2) + chain(tmp_path, "b", 1) + chain(tmp_path, "c", 1)
    ra1, _, rb1, _ = records
    other = "0" * 64
    log(
        tmp_path,
        rerun(tmp_path, ra1, state=Regeneration.CHANGED, actual=other, bytes_identical=False),
        rerun(tmp_path, rb1, state=Regeneration.FAILED, actual=None, bytes_identical=False),
        at=LATER,
    )
    project = manifest(tmp_path, records, [claim("a1"), claim("a2"), claim("b1"), claim("c1")])

    report = stale(project)
    nodes = by_id(report.regenerations)
    written = Digest.of_file(file(tmp_path, "a1")).value
    for name in ("ra1", "rb1"):
        assert nodes[name].state is Freshness.UNDETERMINED
        assert nodes[name].causes == (StaleCause.LATER_RERUN_DID_NOT_REPRODUCE,)
        # The re-run it is compared with is still the one that reproduced.
        assert nodes[name].rerun_at == THEN
    assert (nodes["ra2"].state, nodes["ra2"].upstream) == (Freshness.UNDETERMINED, "ra1")
    assert nodes["rc1"].state is Freshness.CURRENT
    assert [c.state for c in report.claims] == [
        Freshness.UNDETERMINED,
        Freshness.UNDETERMINED,
        Freshness.UNDETERMINED,
        Freshness.CURRENT,
    ]
    assert [
        (f.regeneration, f.artifact, f.observed, f.on_disk, f.rerun_at) for f in report.findings
    ] == [
        ("ra1", "a1", other, written, LATER),
        ("rb1", "b1", None, Digest.of_file(file(tmp_path, "b1")).value, LATER),
    ]

    main(["stale", on_disk(project)])
    out = capsys.readouterr().out
    assert (
        f"later rerun did not reproduce: the re-run of {LATER} read the same inputs and "
        f"wrote {other[:12]}, on disk {written[:12]}"
    ) in out
    assert f"the re-run of {LATER} read the same inputs and wrote no output" in out
    assert "0 stale, 0 never rerun, 3 undetermined, 1 current of 4 assertions that read" in out


def test_a_rerun_that_did_not_reproduce_says_nothing_of_other_inputs_or_an_earlier_time(tmp_path):
    for name in ("early", "edited"):
        put(tmp_path, f"{name}0", step=0)
        put(tmp_path, f"{name}1", step=1)
    early = record(tmp_path, "rearly", ("early0",), "early1")
    edited = record(tmp_path, "redited", ("edited0",), "edited1")

    # One failed before it reproduced. The other reproduced, failed over an edited input, and
    # the input was put back.
    log(tmp_path, rerun(tmp_path, early, state=Regeneration.FAILED, actual=None), at=THEN)
    log(tmp_path, rerun(tmp_path, early), rerun(tmp_path, edited), at=LATER)
    put(tmp_path, "edited0", step="edited")
    log(
        tmp_path,
        rerun(tmp_path, edited, state=Regeneration.CHANGED, actual="0" * 64),
        at="2026-03-01T00:00:00+00:00",
    )
    put(tmp_path, "edited0", step=0)
    project = manifest(tmp_path, [early, edited], [claim("early1"), claim("edited1")])

    report = stale(project)
    assert {node.id: node.state for node in report.regenerations} == {
        "rearly": Freshness.CURRENT,
        "redited": Freshness.CURRENT,
    }
    assert report.findings == ()
