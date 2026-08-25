"""What a project declares: its artifacts, its runs, and how they were produced.

The `Manifest` model lives here; reading one off disk is `repro.manifest`."""

from __future__ import annotations

import enum
import pathlib

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator
from repro.core.artifacts import ArtifactRef, Digest
from repro.core.claims import Claim
from repro.core.outcomes import RegistrationAuthority

SCHEMA_VERSION = "repro/1"

_SHA256_HEX = r"^[a-f0-9]{64}$"


# ---------------------------------------------------------------------------------- manifest


class Provenance(BaseModel):
    """Where a manifest's artifacts came from.

    Recorded, never verified. The pin is the artifact's digest: a commit identifies a tree,
    and a tree does not establish that the file on disk today is the file that was in it.
    A reader who wants these exact bytes uses the commit to fetch them and the digest to
    confirm they arrived.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    repository: str = ""
    """Remote URL, or a local path where there is no remote."""

    commit: str = ""
    """Full SHA of the revision the artifacts were read from."""

    dirty: bool = False
    """Whether the working tree had uncommitted changes when the manifest was written. A
    manifest built from a dirty tree names a commit that does not contain what was read."""

    generated_by: str = ""
    """The script that wrote this manifest, so the figures can be regenerated."""


class RunOutput(BaseModel):
    """An artifact a run produced, bound by digest rather than by name.

    Naming the artifact alone is not a binding: a later file written to the same path can be
    presented as the output of an earlier run, which is the manoeuvre the ordering check
    exists to detect. A run that records no digest is reported `run_output_unlinked`.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    artifact: str
    digest: Digest | None = None

    @model_validator(mode="before")
    @classmethod
    def _accept_a_bare_id(cls, data):
        """`outputs: [results]` parses, and is reported as unlinked rather than rejected."""
        return {"artifact": data} if isinstance(data, str) else data


class RunRecord(BaseModel):
    """A computation that produced artifacts, and the plan it was registered under."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    registered_plan: str = ""
    """The plan this run was registered under. Where it names a declared artifact, that
    document is pinned, so it cannot be edited after the fact without breaking the pin."""

    registration_authority: RegistrationAuthority = RegistrationAuthority.SELF_RECORDED
    """Who attests to `registered_at`. Defaults to the weakest, which is what an unqualified
    timestamp in a file actually is."""

    registered_at: AwareDatetime | None = None
    started_at: AwareDatetime | None = None
    """Both must carry an offset. A naive timestamp compared against an aware one is either a
    crash or a silently wrong ordering, and an ordering that is wrong by a timezone is the
    failure this check exists to catch."""

    outputs: tuple[RunOutput, ...] = ()

    def output(self, artifact_id: str) -> RunOutput | None:
        return next((o for o in self.outputs if o.artifact == artifact_id), None)


class Regeneration(enum.StrEnum):
    """Whether the declared command reproduced the artifact it claims to have produced."""

    REPRODUCED = "reproduced"
    DIVERGED = "diverged"
    UNCHECKED = "unchecked"
    """Not attempted, or the inputs are not the ones declared. Regeneration is opt-in, so
    this is the ordinary state, not a finding."""


class RegenerationReason(enum.StrEnum):
    OUTPUT_MATCHES = "output_matches"
    OUTPUT_DIFFERS = "output_differs"
    NOT_REQUESTED = "not_requested"
    INPUT_UNPINNED = "input_unpinned"
    INPUT_CHANGED = "input_changed"
    INPUT_MISSING = "input_missing"
    COMMAND_FAILED = "command_failed"
    """The command exited non-zero. Where the inputs were copied into an empty directory,
    this also catches a script that needs a file the manifest never declared."""
    COMMAND_TIMED_OUT = "command_timed_out"
    OUTPUT_NOT_PRODUCED = "output_not_produced"
    OUTPUT_UNPINNED = "output_unpinned"
    """The record names no expected digest for its output."""
    OUTPUT_NOT_THE_ARTIFACT = "output_not_the_artifact"
    """The record's expected output is not the artifact the claims were checked against, so
    reproducing it would say nothing about the manuscript's numbers."""
    OUTPUT_IS_ALSO_AN_INPUT = "output_is_also_an_input"
    """The output was copied into the sandbox as one of its own inputs, so a command that does
    nothing reproduces it."""
    RUNNER_UNAVAILABLE = "runner_unavailable"


class RegenerationRecord(BaseModel):
    """A command that produces an artifact from declared inputs.

    The honest analogue of the ordering check for a measurement no plan could have
    registered: not "did this follow its plan" but "does the pinned code, over the pinned
    inputs, still produce this". Opt-in, because it executes a command.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    command: tuple[str, ...]
    """argv, never a shell string. A shell string needs quoting rules, brings a shell's
    expansion with it, and turns a manifest into something that can run anything."""

    inputs: tuple[RunOutput, ...] = ()
    """Every artifact the command reads. Only these are placed in the working directory, so
    a command needing an undeclared file fails and says so."""

    output: RunOutput
    """The artifact the command writes, and the digest it is expected to have."""

    volatile: tuple[str, ...] = ()
    """JSON Pointers to fields removed before comparing. Literal byte identity is the right
    test only after timestamps, paths and environment metadata are controlled; naming them
    keeps the comparison honest instead of loosening it everywhere."""

    timeout_seconds: float = 300.0

    @model_validator(mode="after")
    def _command_is_not_empty(self):
        if not self.command:
            raise ValueError(f"regeneration {self.id!r}: command is empty")
        return self


class RegenerationState(BaseModel):
    """What happened when a regeneration record was checked."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    regeneration_id: str
    artifact_id: str
    state: Regeneration
    reason: RegenerationReason
    expected: str | None = None
    actual: str | None = None
    detail: str = ""


class Manifest(BaseModel):
    """One project: its artifacts and its claims."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = SCHEMA_VERSION
    project: str = ""
    provenance: Provenance | None = None
    artifacts: tuple[ArtifactRef, ...] = ()
    claims: tuple[Claim, ...] = ()
    runs: tuple[RunRecord, ...] = ()
    regenerations: tuple[RegenerationRecord, ...] = ()

    path: pathlib.Path | None = Field(default=None, exclude=True)

    @model_validator(mode="after")
    def _ids_are_unique(self):
        """Two artifacts with one id is not a manifest with a duplicate; it is a manifest that
        says two different things about the same name.

        The engine keys its state by id, so a duplicate silently kept the last declaration and
        dropped the rest -- including, in the case that matters, a broken pin, which then
        disappeared from the report entirely and left `strict` passing with no violations.
        Claims are checked the same way for the same reason.
        """
        for label, items in (("artifact", self.artifacts), ("claim", self.claims)):
            seen: set[str] = set()
            for item in items:
                if item.id in seen:
                    raise ValueError(
                        f"duplicate {label} id {item.id!r}: one id must name one thing"
                    )
                seen.add(item.id)
        return self

    def artifact(self, artifact_id: str) -> ArtifactRef | None:
        return next((a for a in self.artifacts if a.id == artifact_id), None)

    def resolve(self, artifact: ArtifactRef) -> pathlib.Path:
        if artifact.path.is_absolute() or self.path is None:
            return artifact.path
        return (self.path.parent / artifact.path).resolve()
