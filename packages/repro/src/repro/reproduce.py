"""Run a manifest's declared commands again and ask whether the manuscript's numbers survive.

`repro verify` compares what a manuscript prints with what its files hold, and executes
nothing. This does the other half: it runs each declared regeneration in a directory holding
only its declared inputs, then puts the question `verify` asks to the file the command has just
written. Five outcomes per record, defined on `repro.models.Regeneration`.

The comparison is `repro.verify.check_evidence`, handed the fresh file's path in place of the
pinned one. There is no second comparator, so a number that verifies under `repro verify` and a
number that holds here are held to one rule, at the precision the manuscript prints.

A record whose input is another record's output runs over the *pinned* copy of that output,
whatever happened to the record producing it. Where that record did not reproduce, the
dependent one says so in `rests_on`: a cheap evaluation re-run over a week-long training run's
recorded checkpoint is worth having, and is not the same result as re-running both.

Everything the tool can observe about a run is recorded, and nothing it cannot. There is no
field for who ran it.
"""

from __future__ import annotations

import datetime
import decimal
import json
import os
import pathlib
import platform
import shutil
import subprocess

from repro.exceptions import ArtifactUnreadableError, ReproError
from repro.models import (
    ArtifactState,
    Claim,
    ClaimReading,
    Digest,
    Environment,
    Evidence,
    Manifest,
    Outcome,
    Reading,
    Regeneration,
    RegenerationRecord,
    RegenerationState,
    ReproductionReport,
)
from repro.regenerate import check, skipped
from repro.resolve import resolve
from repro.toolchain import distribution_version
from repro.verify import (
    ADAPTER_DISTRIBUTION,
    DEFAULT_BACKENDS,
    Backend,
    artifact_states,
    check_evidence,
)

#: Where each invocation's record is appended, beside the manifest. One JSON object per line.
RECORD = pathlib.Path(".repro") / "reproductions.jsonl"

#: Looked for at the top of the project, in this order. The first found is named and hashed:
#: which packages were installed is the part of an environment a later reader can rebuild.
LOCKFILES = (
    "uv.lock",
    "poetry.lock",
    "pixi.lock",
    "Pipfile.lock",
    "conda-lock.yml",
    "requirements.txt",
    "environment.yml",
    "renv.lock",
    "Manifest.toml",
)

#: Recorded where set. Each changes what a numerical program computes or the order it computes
#: it in, so a re-run that differs can be read against them.
DETERMINISM_VARIABLES = (
    "PYTHONHASHSEED",
    "OMP_NUM_THREADS",
    "MKL_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "CUBLAS_WORKSPACE_CONFIG",
    "CUDA_VISIBLE_DEVICES",
    "SOURCE_DATE_EPOCH",
)


class UnknownRegenerationError(ReproError):
    """A record was named that the manifest does not declare."""

    def __init__(self, unknown: tuple[str, ...], declared: tuple[str, ...]) -> None:
        self.unknown = unknown
        self.declared = declared
        super().__init__(
            f"the manifest declares no regeneration {', '.join(repr(u) for u in unknown)}; "
            f"declared: {', '.join(declared) or 'none'}"
        )


def _gpus() -> tuple[str, ...]:
    if shutil.which("nvidia-smi") is None:
        return ()
    try:
        listed = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,driver_version", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ()
    return tuple(line.strip() for line in listed.stdout.splitlines() if line.strip())


def environment(root: pathlib.Path) -> Environment:
    """What can be observed about where a re-run happens, with nothing that names the machine."""
    lockfile = next((root / name for name in LOCKFILES if (root / name).is_file()), None)
    return Environment(
        system=platform.system(),
        release=platform.release(),
        machine=platform.machine(),
        processor=platform.processor(),
        python=platform.python_version(),
        lockfile=lockfile.name if lockfile else "",
        lockfile_digest=Digest.of_file(lockfile).value if lockfile else "",
        gpus=_gpus(),
        variables={name: os.environ[name] for name in DETERMINISM_VARIABLES if name in os.environ},
    )


def _stored(evidence: Evidence, path: pathlib.Path) -> str | None:
    """The value an assertion addresses in one file, as stored, or None where there is none."""
    locator = getattr(evidence, "locator", None)
    if locator is None or not path.is_file():
        return None
    try:
        _, extracted, _ = resolve(locator, path)
    except (ArtifactUnreadableError, OSError, ValueError):
        return None
    return extracted.raw if extracted is not None else None


def _difference(pinned: str | None, fresh: str | None) -> str | None:
    try:
        before, after = decimal.Decimal(pinned or ""), decimal.Decimal(fresh or "")
    except decimal.InvalidOperation:
        return None
    return str(after - before) if before.is_finite() and after.is_finite() else None


def _reading(
    claim: Claim,
    evidence: Evidence,
    manifest: Manifest,
    output: str,
    produced: pathlib.Path,
    paths: dict[str, pathlib.Path],
    states: dict[str, ArtifactState],
    registry: dict[str, Backend],
) -> ClaimReading:
    before = check_evidence(claim, evidence, manifest, paths, states, registry)
    # The fresh file exists whatever is at the pinned path, so the assertion is put to it even
    # where the pinned output has since been deleted.
    fresh_states = states | {output: states[output].model_copy(update={"exists": True})}
    after = check_evidence(
        claim, evidence, manifest, paths | {output: produced}, fresh_states, registry
    )
    pinned, fresh = _stored(evidence, paths[output]), _stored(evidence, produced)

    if after.outcome is Outcome.VERIFIED:
        reading = Reading.HOLDS
    elif after.outcome is not Outcome.MISMATCH:
        reading = Reading.UNREADABLE
    elif before.outcome is Outcome.MISMATCH and pinned is not None and pinned == fresh:
        reading = Reading.ALREADY_MISMATCHED
    else:
        reading = Reading.CHANGED
    return ClaimReading(
        claim_id=claim.id,
        name=getattr(evidence, "name", "") or evidence.kind,
        printed=str(getattr(evidence, "reported", "")),
        pinned=pinned,
        fresh=fresh,
        difference=_difference(pinned, fresh),
        reading=reading,
        detail="" if reading is Reading.HOLDS else (after.detail or after.reason.value),
    )


def _rests_on(
    record: RegenerationRecord,
    producers: dict[str, RegenerationRecord],
    states: dict[str, RegenerationState],
) -> tuple[str, ...]:
    """Every record upstream of this one, at any distance, that did not reproduce."""
    seen: dict[str, RegenerationRecord] = {}
    pending = [record]
    while pending:
        for wanted in pending.pop().inputs:
            upstream = producers.get(wanted.artifact)
            if upstream is not None and upstream.id not in seen and upstream.id != record.id:
                seen[upstream.id] = upstream
                pending.append(upstream)
    return tuple(sorted(name for name in seen if states[name].state is not Regeneration.REPRODUCED))


def reproduce(
    manifest: Manifest,
    only: tuple[str, ...] = (),
    skip: tuple[str, ...] = (),
    backends: tuple[Backend, ...] = DEFAULT_BACKENDS,
) -> ReproductionReport:
    """Run the manifest's declared regenerations and report what each one found.

    Executes the commands the manifest names. `only` restricts the run to those records and
    `skip` leaves those out; a record left out is reported `not_rerun`, never omitted.

    Writes nothing to the project. `append` is what records a report.
    """
    declared = tuple(record.id for record in manifest.regenerations)
    if unknown := tuple(name for name in (*only, *skip) if name not in declared):
        raise UnknownRegenerationError(unknown, declared)

    started = datetime.datetime.now(datetime.UTC)
    registry: dict[str, Backend] = {b.kind: b for b in backends}
    artifacts, paths = artifact_states(manifest)

    def reader(record: RegenerationRecord):
        output = record.output.artifact

        def read_claims(produced: pathlib.Path) -> tuple[ClaimReading, ...]:
            return tuple(
                _reading(claim, evidence, manifest, output, produced, paths, artifacts, registry)
                for claim in manifest.claims
                for evidence in claim.evidence
                if output in evidence.artifacts
            )

        return read_claims

    states: dict[str, RegenerationState] = {}
    for record in manifest.regenerations:
        left_out = record.id in skip or (bool(only) and record.id not in only)
        states[record.id] = (
            skipped(record) if left_out else check(record, manifest, artifacts, reader(record))
        )

    producers = {record.output.artifact: record for record in manifest.regenerations}
    root = manifest.path.parent if manifest.path else pathlib.Path.cwd()
    return ReproductionReport(
        project=manifest.project,
        manifest_digest=Digest.of_text(manifest.model_dump_json()).value,
        tool_version=distribution_version(ADAPTER_DISTRIBUTION),
        started_at=started.isoformat(timespec="seconds"),
        ended_at=datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
        environment=environment(root),
        regenerations=tuple(
            states[record.id].model_copy(update={"rests_on": _rests_on(record, producers, states)})
            for record in manifest.regenerations
        ),
    )


def append(report: ReproductionReport, root: pathlib.Path) -> pathlib.Path:
    """Add one report to the project's record of re-runs, and return where it was written.

    Appended, one object per line, so an earlier re-run is never replaced by a later one and a
    second reproduction is not compared against the first.
    """
    target = root / RECORD
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(report.model_dump(mode="json"), sort_keys=True) + "\n")
    return target


__all__ = ["RECORD", "UnknownRegenerationError", "append", "environment", "reproduce"]
