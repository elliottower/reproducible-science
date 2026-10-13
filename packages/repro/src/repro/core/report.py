"""What a verification run produced."""

from __future__ import annotations

import enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from repro.core.claims import Availability, Registration
from repro.core.manifest import RegenerationState
from repro.core.outcomes import (
    Decision,
    Ordering,
    OrderingReason,
    Outcome,
    Reason,
    RegistrationAuthority,
    Validity,
)

SCHEMA_VERSION = "repro/1"

_SHA256_HEX = r"^[a-f0-9]{64}$"


# ------------------------------------------------------------------------------------ report


class ArtifactState(BaseModel):
    """What was found at each artifact's path, before any evidence was read."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    artifact_id: str
    validity: Validity
    expected: str | None = None
    actual: str | None = None
    exists: bool = True
    detail: str = ""
    """Why, where the state needs one -- a path that exists and cannot be read."""


class ClaimAssessment(BaseModel):
    """One claim's availability, and the decisions on the evidence it offered."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    claim_id: str
    claim_digest: str
    confirmatory: bool = False
    registration: Registration = Registration.EXPLORATORY
    registration_note: str = ""
    availability: Availability
    ordering: Ordering = Ordering.NOT_APPLICABLE
    ordering_reason: OrderingReason = OrderingReason.NOT_CONFIRMATORY
    ordering_detail: str = ""
    registration_authority: RegistrationAuthority | None = None
    """The weakest authority among the runs that produced this claim's evidence, or None
    where no run applies."""
    decisions: tuple[Decision, ...] = ()

    @property
    def outcomes(self) -> tuple[Outcome, ...]:
        if self.availability is Availability.NOT_OFFERED:
            return (Outcome.NOT_OFFERED,)
        return tuple(d.outcome for d in self.decisions)


class VerificationReport(BaseModel):
    """Facts about what was checked. Frozen, and carries no verdict.

    Whether a project passes is a policy question -- a missing optional citation may be
    acceptable where an unchecked confirmatory result is not -- so the engine reports what
    happened and `repro.policy` decides what it means.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = SCHEMA_VERSION
    project: str = ""
    manifest_digest: str = ""
    artifacts: tuple[ArtifactState, ...] = ()
    claims: tuple[ClaimAssessment, ...] = ()

    @property
    def decisions(self) -> tuple[Decision, ...]:
        return tuple(d for c in self.claims for d in c.decisions)

    @property
    def counts(self) -> dict[str, int]:
        tally: dict[str, int] = {}
        for claim in self.claims:
            for outcome in claim.outcomes:
                tally[outcome.value] = tally.get(outcome.value, 0) + 1
        return tally

    def artifacts_with(self, validity: Validity) -> tuple[str, ...]:
        return tuple(a.artifact_id for a in self.artifacts if a.validity is validity)


# ------------------------------------------------------------------------------ reproduction


class Environment(BaseModel):
    """Where a re-run happened, as far as the tool can observe it.

    Nothing here names a person or a machine: no hostname, no user, no absolute path. These
    records are committed to repositories that become public.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    system: str = ""
    release: str = ""
    machine: str = ""
    processor: str = ""
    python: str = ""
    lockfile: str = ""
    """Name of the lockfile found at the top of the project, if any."""
    lockfile_digest: str = ""
    gpus: tuple[str, ...] = ()
    """Model and driver per device, as `nvidia-smi` reports them. Empty where it is absent."""
    variables: dict[str, str] = {}
    """The environment variables that bear on determinism, where set."""


class ReproductionReport(BaseModel):
    """What one `repro reproduce` invocation ran and found. Frozen, and carries no verdict."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = SCHEMA_VERSION
    project: str = ""
    manifest_digest: str = ""
    tool_version: str = ""
    started_at: str = ""
    ended_at: str = ""
    environment: Environment = Environment()
    regenerations: tuple[RegenerationState, ...] = ()

    @property
    def counts(self) -> dict[str, int]:
        tally: dict[str, int] = {}
        for state in self.regenerations:
            tally[state.state.value] = tally.get(state.state.value, 0) + 1
        return tally


# --------------------------------------------------------------------------------- staleness


class Freshness(enum.StrEnum):
    """Whether a file is still what a recorded re-run produced.

    Relative to the record of re-runs, never to the digests a manifest carries for its own
    regenerations: a manifest rebuilt from the files on disk agrees with them whether or not
    any command ran. A pin that no longer matches its file is `Validity.BROKEN_PIN`, a
    different fact that `repro verify` reports.
    """

    CURRENT = "current"
    """A recorded re-run of the producing command read the inputs now on disk and its output is
    the one now on disk, and the same holds for every producer upstream. Consistent with a
    recorded re-run; nothing was executed to establish it."""
    STALE = "stale"
    """Re-runs are recorded and none matches the files now on disk, here or upstream."""
    NEVER_RERUN = "never_rerun"
    """A command produces the file and the record holds no re-run of it that reproduced."""
    NO_PRODUCER = "no_producer"
    """No declared command writes the file, so there is nothing upstream to compare."""
    UNDETERMINED = "undetermined"
    """A file the comparison needs is missing, or the producers form a cycle."""
    PARTLY_OUTSIDE = "partly_outside_the_record"
    """Of an assertion or a claim only: some of what it reads is current, and the rest has no
    producer."""


class StaleCause(enum.StrEnum):
    """Why a regeneration is not current."""

    INPUT_CHANGED = "input_changed"
    COMMAND_CHANGED = "command_changed"
    OUTPUT_CHANGED = "output_changed"
    UPSTREAM_STALE = "upstream_stale"
    INPUT_MISSING = "input_missing"
    OUTPUT_MISSING = "output_missing"
    CYCLE = "cycle"


class StaleFinding(BaseModel):
    """One difference between a regeneration's latest recorded re-run and the files on disk.

    Stated once per regeneration and file, where the difference is, however many records and
    claims lie downstream of it.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    cause: StaleCause
    regeneration: str
    artifact: str
    observed: str | None = None
    """The digest the re-run recorded for the file."""
    on_disk: str | None = None
    rerun_at: str | None = None
    """When the re-run compared against started."""


class PinDisagreement(BaseModel):
    """A regeneration whose recorded digest for an input is not that artifact's pin."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    regeneration: str
    artifact: str
    recorded: str
    pinned: str


class RegenerationNode(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    artifact: str
    state: Freshness
    causes: tuple[StaleCause, ...] = ()
    upstream: str | None = None
    """The nearest upstream producer in this state, where the state comes from upstream."""
    distance: int | None = None
    """How many producers lie between this record and `upstream`, counting `upstream`."""
    rerun_at: str | None = None
    """When the re-run compared against started. None where no re-run is recorded."""


class ArtifactNode(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    path: str = ""
    state: Freshness
    producer: str | None = None
    on_disk: str | None = None


class AssertionNode(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: str
    artifacts: tuple[str, ...] = ()
    state: Freshness


class ClaimNode(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    state: Freshness
    assertions: tuple[AssertionNode, ...] = ()


class Edge(BaseModel):
    """`reads` runs from a claim to an artifact, `produced_by` from an artifact to its
    regeneration, and `consumes` from a regeneration to an input."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["reads", "produced_by", "consumes"]
    source: str
    target: str
    recorded: str | None = None
    """The digest the manifest's regeneration record names."""
    observed: str | None = None
    """The digest the re-run compared against recorded."""
    on_disk: str | None = None


class StalenessReport(BaseModel):
    """What `repro stale` found, as the graph it walked. Frozen, and carries no verdict."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = SCHEMA_VERSION
    project: str = ""
    manifest_digest: str = ""
    reruns: int = 0
    """How many invocations the record of re-runs holds."""
    claims: tuple[ClaimNode, ...] = ()
    artifacts: tuple[ArtifactNode, ...] = ()
    regenerations: tuple[RegenerationNode, ...] = ()
    edges: tuple[Edge, ...] = ()
    findings: tuple[StaleFinding, ...] = ()
    record_disagrees_with_pin: tuple[PinDisagreement, ...] = ()


# --------------------------------------------------------------------------------- one claim


class FileRead(BaseModel):
    """One file an assertion reads: its pin, and what sits at the declared address."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    artifact: str
    path: str = ""
    side: str = ""
    """Which side of a `correspondence` this is, in the author's word for it."""
    validity: Validity | None = None
    """None where the manifest declares no such artifact."""
    pinned: str | None = None
    on_disk: str | None = None
    address: str = ""
    """Where the assertion looks. Empty for a quotation, which addresses no value."""
    stored: str | None = None
    """The value at the address, as stored. None where none was read."""


class AssertionAccount(BaseModel):
    """One assertion of a claim, as `repro verify` evaluates it now."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: str
    name: str = ""
    printed: str | None = None
    """The value as the manuscript prints it, or the passage a quotation asserts."""
    reads: tuple[FileRead, ...] = ()
    outcome: Outcome
    reason: Reason
    detail: str = ""
    state: Freshness


class ChainNode(BaseModel):
    """One file a claim rests on: a file it reads, or a file upstream of one."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    artifact: str
    path: str = ""
    steps: int
    """How many commands lie between the claim and this file. 0 for a file the claim reads."""
    validity: Validity | None = None
    state: Freshness
    command: tuple[str, ...] = ()
    volatile: tuple[str, ...] = ()
    """The fields the record leaves out of the comparison of its output."""
    regeneration: RegenerationNode | None = None
    """The record that writes the file. None where no command is recorded for it."""


class NotEstablishedKind(enum.StrEnum):
    """What a line under `not established` is about."""

    NO_PRODUCER = "no_producer"
    NEVER_RERUN = "never_rerun"
    ABSENT = "absent"
    BROKEN_PIN = "broken_pin"
    CYCLE = "cycle"
    UNCHECKED = "unchecked"
    NOT_FOUND = "not_found"
    ERROR = "error"
    NO_EVIDENCE = "no_evidence"
    UNDECLARED_INPUTS = "undeclared_inputs"
    ADDRESS = "address"
    COMPARISON = "comparison"


class NotEstablished(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: NotEstablishedKind
    subject: str = ""
    """The file, record or assertion the line names. Empty for the lines that hold of the
    design."""
    said: str


class ClaimAccount(BaseModel):
    """What `repro why` found for one claim. Frozen, and carries no verdict."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = SCHEMA_VERSION
    project: str = ""
    manifest_digest: str = ""
    claim_id: str
    text: str = ""
    where: str | None = None
    assertions: tuple[AssertionAccount, ...] = ()
    chain: tuple[ChainNode, ...] = ()
    """Every file the claim rests on, nearest first."""
    edges: tuple[Edge, ...] = ()
    """The edges of the staleness graph that lie on the chain."""
    findings: tuple[StaleFinding, ...] = ()
    not_established: tuple[NotEstablished, ...] = ()
    outcomes: dict[Outcome, int] = Field(default_factory=dict)
    """How many of the claim's assertions have each outcome, in the order `Outcome` declares
    them. An outcome no assertion has is left out."""
    states: dict[Freshness, int] = Field(default_factory=dict)
    """How many of the claim's assertions are in each state against the record of re-runs."""
