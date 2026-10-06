"""What a verification run produced."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from repro.core.claims import Availability, Registration
from repro.core.manifest import RegenerationState
from repro.core.outcomes import (
    Decision,
    Ordering,
    OrderingReason,
    Outcome,
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
