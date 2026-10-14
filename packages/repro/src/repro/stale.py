"""Is what each claim reads still what a recorded re-run produced?

`repro verify` compares a manuscript with its files. It passes a number that sits in its file
unchanged while the data or the script that file was computed from has since been edited:
the output is still the pinned one, and nothing in a pin says what it was made from.
`repro reproduce` would find out, by running every command. This reads what `reproduce` has
already recorded, executes nothing and writes nothing.

**The reference is the record of re-runs, not the manifest.** A regeneration record carries a
digest for each input and for its output, and a project that rebuilds its manifest from the
files on disk rewrites all of them at once, so they agree after a rebuild whether or not the
command ran. What a rebuild cannot write is `.repro/reproductions.jsonl`, where each
`repro reproduce` appends the command it started, the digest of every input it copied into
the sandbox and the digest of the output the command wrote.

A regeneration is `current` where one of those re-runs, among the ones that executed and
reproduced, ran today's command over the inputs now on disk and its output is the output now
on disk: the file the re-run was compared against, or the one it wrote. An artifact takes the
state of the record that writes it, joined with every record upstream.

`current` is a statement about the record. It says the files are the ones a re-run that
reproduced was made over, and not that the command would reproduce now. An input the
manifest does not declare is not compared at all.
"""

from __future__ import annotations

import collections
import pathlib
from collections.abc import Iterable

from pydantic import ValidationError

from repro.exceptions import ReproError
from repro.models import (
    ArtifactNode,
    AssertionNode,
    ClaimNode,
    Digest,
    Edge,
    Freshness,
    Manifest,
    PinDisagreement,
    Regeneration,
    RegenerationNode,
    RegenerationRecord,
    RegenerationState,
    ReproductionReport,
    StaleCause,
    StaleFinding,
    StalenessReport,
)
from repro.regenerate import canonical_digest, upstream
from repro.reproduce import RECORD
from repro.verify import artifact_states

#: One regeneration's entry in the record, with when its invocation started.
Rerun = tuple[str, RegenerationState]


class RecordUnreadableError(ReproError):
    """A line of the record of re-runs is not a report `repro reproduce` wrote."""

    def __init__(self, path: pathlib.Path, line: int, detail: str) -> None:
        self.path = path
        self.line = line
        super().__init__(f"{path}:{line}: {detail}")


def reruns(root: pathlib.Path) -> tuple[ReproductionReport, ...]:
    """Every invocation in the project's record of re-runs, oldest first. Empty where the
    project has no record."""
    path = root / RECORD
    if not path.is_file():
        return ()
    reports = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            reports.append(ReproductionReport.model_validate_json(line))
        except ValidationError as e:
            first = e.errors()[0]
            where = ".".join(str(x) for x in first["loc"]) or "(top level)"
            raise RecordUnreadableError(path, number, f"{where}: {first['msg']}") from e
    return tuple(reports)


def worst(states: Iterable[Freshness]) -> Freshness:
    """The state of a thing that rests on several.

    A file with no producer says nothing either way, so it never outranks a finding. Beside
    something current it leaves the whole `partly_outside_the_record`.
    """
    found = set(states)
    for state in (Freshness.STALE, Freshness.UNDETERMINED, Freshness.NEVER_RERUN):
        if state in found:
            return state
    if found <= {Freshness.NO_PRODUCER}:
        return Freshness.NO_PRODUCER
    return Freshness.CURRENT if found == {Freshness.CURRENT} else Freshness.PARTLY_OUTSIDE


def _read(entry: RegenerationState) -> dict[str, str | None]:
    return {reading.artifact_id: reading.observed for reading in entry.inputs}


def _compare(
    record: RegenerationRecord,
    recorded: list[Rerun],
    attempted: list[Rerun],
    disk: dict[str, str | None],
    written: str | None,
    loops: bool,
) -> tuple[Freshness, Rerun | None, list[StaleFinding]]:
    """One record against its own re-runs, saying nothing of the records upstream: its state,
    the re-run it was compared with, and each difference from that re-run."""
    output = record.output.artifact

    def finding(cause: StaleCause, artifact: str, **digests: str | None) -> StaleFinding:
        return StaleFinding(cause=cause, regeneration=record.id, artifact=artifact, **digests)

    if loops:
        return Freshness.UNDETERMINED, None, [finding(StaleCause.CYCLE, output)]
    if not recorded:
        return Freshness.NEVER_RERUN, None, []

    missing = [
        finding(StaleCause.INPUT_MISSING, wanted.artifact)
        for wanted in record.inputs
        if disk.get(wanted.artifact) is None
    ]
    if written is None:
        missing.append(finding(StaleCause.OUTPUT_MISSING, output))
    if missing:
        return Freshness.UNDETERMINED, recorded[-1], missing

    declared = {wanted.artifact: disk[wanted.artifact] for wanted in record.inputs}
    for rerun in reversed(recorded):
        entry = rerun[1]
        if (
            entry.command == record.command
            and _read(entry) == declared
            # A re-run that wrote other bytes holding the same numbers reproduced the file it
            # was compared against, so that file is as much its output as the one it wrote.
            and written in (entry.expected, entry.actual)
        ):
            # A later re-run of the same command over the same inputs that did not reproduce
            # leaves two witnessed runs that disagree, and the record does not say which the
            # file on disk is the output of.
            later = attempted[attempted.index(rerun) + 1 :]
            disagreeing = [
                finding(
                    StaleCause.LATER_RERUN_DID_NOT_REPRODUCE,
                    output,
                    observed=other.actual,
                    on_disk=written,
                    rerun_at=when,
                )
                for when, other in later
                if other.state is not Regeneration.REPRODUCED
                and other.command == record.command
                and _read(other) == declared
            ]
            if disagreeing:
                return Freshness.UNDETERMINED, rerun, disagreeing[-1:]
            return Freshness.CURRENT, rerun, []

    when, last = recorded[-1]
    found = []
    if last.command != record.command:
        found.append(finding(StaleCause.COMMAND_CHANGED, output, rerun_at=when))
    read = _read(last)
    found += [
        finding(
            StaleCause.INPUT_CHANGED,
            name,
            observed=read.get(name),
            on_disk=declared.get(name),
            rerun_at=when,
        )
        for name in sorted(read.keys() | declared.keys())
        if read.get(name) != declared.get(name)
    ]
    if written not in (last.expected, last.actual):
        found.append(
            finding(
                StaleCause.OUTPUT_CHANGED,
                output,
                observed=last.actual,
                on_disk=written,
                rerun_at=when,
            )
        )
    return Freshness.STALE, recorded[-1], found


def stale(manifest: Manifest) -> StalenessReport:
    """Compare every regeneration with the project's record of re-runs, and say for each
    artifact and each claim whether what it rests on is still what a re-run produced.

    Executes nothing and writes nothing.
    """
    root = manifest.path.parent if manifest.path else pathlib.Path.cwd()
    log = reruns(root)
    recorded: dict[str, list[Rerun]] = collections.defaultdict(list)
    attempted: dict[str, list[Rerun]] = collections.defaultdict(list)
    # Where each invocation ran, by when it started, which is how a re-run is named.
    ran_in = {report.started_at: report.witness for report in log}
    for report in log:
        for entry in report.regenerations:
            if not entry.executed:
                continue
            attempted[entry.regeneration_id].append((report.started_at, entry))
            if entry.state is Regeneration.REPRODUCED:
                recorded[entry.regeneration_id].append((report.started_at, entry))

    states, paths = artifact_states(manifest)
    disk = {name: state.actual for name, state in states.items()}
    producers = {record.output.artifact: record for record in manifest.regenerations}
    above = {record.id: upstream(record, producers) for record in manifest.regenerations}

    local: dict[str, Freshness] = {}
    compared: dict[str, Rerun | None] = {}
    written: dict[str, str | None] = {}
    differences: dict[str, list[StaleFinding]] = {}
    for record in manifest.regenerations:
        output = record.output.artifact
        # The digest `reproduce` compares: the file's own, or the canonical one where the
        # record names volatile fields.
        written[record.id] = (
            canonical_digest(paths[output], record.volatile).value
            if disk.get(output) is not None
            else None
        )
        local[record.id], compared[record.id], differences[record.id] = _compare(
            record,
            recorded[record.id],
            attempted[record.id],
            disk,
            written[record.id],
            loops=record.id in above[record.id],
        )

    nodes: dict[str, RegenerationNode] = {}
    for record in manifest.regenerations:
        own = local[record.id]
        others = above[record.id]
        # A record on a cycle has no upstream to take a state from: it is its own.
        state = own if record.id in others else worst([own, *(local[name] for name in others)])
        nearest = (
            min((distance, name) for name, distance in others.items() if local[name] is state)
            if state is not own
            else None
        )
        rerun = compared[record.id]
        nodes[record.id] = RegenerationNode(
            id=record.id,
            artifact=record.output.artifact,
            state=state,
            causes=(
                tuple(dict.fromkeys(found.cause for found in differences[record.id]))
                if nearest is None
                else ((StaleCause.UPSTREAM_STALE,) if state is Freshness.STALE else ())
            ),
            upstream=nearest[1] if nearest else None,
            distance=nearest[0] if nearest else None,
            rerun_at=rerun[0] if rerun else None,
            witness=ran_in.get(rerun[0]) if rerun else None,
        )

    def of(artifact_id: str) -> Freshness:
        producer = producers.get(artifact_id)
        return nodes[producer.id].state if producer else Freshness.NO_PRODUCER

    claims = []
    edges = []
    for claim in manifest.claims:
        assertions = tuple(
            AssertionNode(
                kind=evidence.kind,
                artifacts=evidence.artifacts,
                state=worst(of(name) for name in evidence.artifacts),
            )
            for evidence in claim.evidence
        )
        claims.append(
            ClaimNode(id=claim.id, state=worst(a.state for a in assertions), assertions=assertions)
        )
        edges += [
            Edge(kind="reads", source=claim.id, target=name, on_disk=disk.get(name))
            for name in dict.fromkeys(name for a in assertions for name in a.artifacts)
        ]

    disagreements = []
    for record in manifest.regenerations:
        rerun = compared[record.id]
        edges.append(
            Edge(
                kind="produced_by",
                source=record.output.artifact,
                target=record.id,
                recorded=record.output.digest.value if record.output.digest else None,
                observed=rerun[1].actual if rerun else None,
                on_disk=written[record.id],
            )
        )
        read = _read(rerun[1]) if rerun else {}
        for wanted in record.inputs:
            edges.append(
                Edge(
                    kind="consumes",
                    source=record.id,
                    target=wanted.artifact,
                    recorded=wanted.digest.value if wanted.digest else None,
                    observed=read.get(wanted.artifact),
                    on_disk=disk.get(wanted.artifact),
                )
            )
            pinned = manifest.artifact(wanted.artifact)
            if (
                wanted.digest is not None
                and pinned is not None
                and pinned.digest is not None
                and wanted.digest != pinned.digest
            ):
                disagreements.append(
                    PinDisagreement(
                        regeneration=record.id,
                        artifact=wanted.artifact,
                        recorded=wanted.digest.value,
                        pinned=pinned.digest.value,
                    )
                )

    return StalenessReport(
        project=manifest.project,
        manifest_digest=Digest.of_text(manifest.model_dump_json()).value,
        reruns=len(log),
        claims=tuple(claims),
        artifacts=tuple(
            ArtifactNode(
                id=artifact.id,
                path=artifact.path.as_posix(),
                state=of(artifact.id),
                producer=producers[artifact.id].id if artifact.id in producers else None,
                on_disk=disk.get(artifact.id),
            )
            for artifact in manifest.artifacts
        ),
        regenerations=tuple(nodes.values()),
        edges=tuple(edges),
        findings=tuple(
            found.model_copy(update={"witness": ran_in.get(found.rerun_at)})
            if found.rerun_at is not None
            else found
            for each in differences.values()
            for found in each
        ),
        record_disagrees_with_pin=tuple(disagreements),
    )


__all__ = ["RecordUnreadableError", "reruns", "stale", "worst"]
