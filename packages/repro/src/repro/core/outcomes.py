"""The verdict vocabulary: three stages, one derived outcome, and why it obtained.

Execution, extraction and comparison are reported separately. Collapsing them is how a
missing extractor becomes a quotation that failed to check out."""

from __future__ import annotations

import enum

from pydantic import BaseModel, ConfigDict

SCHEMA_VERSION = "repro/1"

_SHA256_HEX = r"^[a-f0-9]{64}$"


# ---------------------------------------------------------------------------------- outcomes


class ExecutionStatus(enum.StrEnum):
    COMPLETED = "completed"
    UNAVAILABLE = "unavailable"
    """The backend could not run: a missing binary, an unreadable file, an absent registry."""
    FAILED = "failed"
    """The backend raised something unexpected. A defect, never a scientific outcome."""


class ExtractionStatus(enum.StrEnum):
    EXTRACTED = "extracted"
    ABSENT = "absent"
    """The artifact was read and holds no such value. Silence, which is not contradiction."""
    INVALID = "invalid"
    """A value was located and is not of the type the assertion requires."""
    NOT_ATTEMPTED = "not_attempted"


class ComparisonStatus(enum.StrEnum):
    MATCH = "match"
    MISMATCH = "mismatch"
    NOT_APPLICABLE = "not_applicable"


class Outcome(enum.StrEnum):
    """The flattened view, for display and for tools that want one field.

    Derived from the three stages, never set directly, so the flattening cannot drift from
    what the stages say.
    """

    VERIFIED = "verified"
    MISMATCH = "mismatch"
    NOT_FOUND = "not_found"
    UNCHECKED = "unchecked"
    ERROR = "error"
    NOT_OFFERED = "not_offered"


class Ordering(enum.StrEnum):
    """Whether a confirmatory claim's evidence was produced after the plan it names.

    The outcome is separate from the reason, on the same principle the evidence stages
    follow: a check that could not run is not a check that failed. `unchecked` carries an
    `OrderingReason` saying which of eight conditions stopped it, because collapsing a
    missing run record, an unpinned plan, and an unlinked output into one word loses the
    only information that says what to fix.
    """

    ORDERED = "ordered"
    """Every run producing this claim's evidence started after its plan was registered."""
    VIOLATED = "violated"
    """A run started before the plan it names was registered."""
    UNCHECKED = "unchecked"
    """The record does not settle it. Not a finding that the ordering is wrong."""
    NOT_APPLICABLE = "not_applicable"
    """The claim is not confirmatory, so there is no registration for it to postdate."""


class OrderingReason(enum.StrEnum):
    """Why an ordering check reached the outcome it did."""

    RUN_FOLLOWS_REGISTRATION = "run_follows_registration"
    RUN_PRECEDES_REGISTRATION = "run_precedes_registration"
    NO_RUN_RECORD = "no_run_record"
    NO_REGISTERED_PLAN = "no_registered_plan"
    REGISTERED_PLAN_UNPINNED = "registered_plan_unpinned"
    REGISTERED_PLAN_CHANGED = "registered_plan_changed"
    RUN_OUTPUT_UNLINKED = "run_output_unlinked"
    """The run names an artifact but records no digest for it, so a later file with the same
    name can be presented as the output of an earlier run."""
    RUN_OUTPUT_CHANGED = "run_output_changed"
    TIMESTAMP_MISSING = "timestamp_missing"
    AMBIGUOUS_PRODUCING_RUN = "ambiguous_producing_run"
    NOT_CONFIRMATORY = "not_confirmatory"


class RegistrationAuthority(enum.StrEnum):
    """Who attests to the registration timestamp.

    A hash and two self-recorded timestamps establish internal consistency, not chronology:
    an actor who can write `registered_at`, `started_at` and the plan digest after seeing
    results can manufacture an ordered history. Recording the authority makes that limit a
    field rather than a caveat, and lets a policy require better than the weakest one.
    """

    SELF_RECORDED = "self_recorded"
    GIT_REMOTE = "git_remote"
    OSF = "osf"
    ZENODO = "zenodo"
    TRUSTED_TIMESTAMP = "trusted_timestamp"

    @property
    def rank(self) -> int:
        return _AUTHORITY_RANK[self]


_AUTHORITY_RANK = {
    RegistrationAuthority.SELF_RECORDED: 0,
    RegistrationAuthority.GIT_REMOTE: 1,
    RegistrationAuthority.OSF: 2,
    RegistrationAuthority.ZENODO: 2,
    RegistrationAuthority.TRUSTED_TIMESTAMP: 3,
}


class Validity(enum.StrEnum):
    """Whether a decision describes the artifact the manifest declared."""

    AUTHORITATIVE = "authoritative"
    UNPINNED_ARTIFACT = "unpinned_artifact"
    """No digest was recorded, so the file read may not be the file meant."""
    BROKEN_PIN = "broken_pin"
    """The file read is provably not the file that was pinned. The comparison still ran and
    its result is reported, marked non-authoritative, because a diagnostic is more useful than
    a blank."""
    ARTIFACT_ABSENT = "artifact_absent"
    """Nothing exists at the declared path. No comparison ran, so no decision against this
    artifact describes anything that was read."""


class Reason(enum.StrEnum):
    """Why an outcome obtained. Machine-readable, so a tool can route by cause."""

    PASSAGE_PRESENT = "passage_present"
    VALUE_MATCH = "value_match"
    PASSAGE_ABSENT = "passage_absent"
    VALUE_MISMATCH = "value_mismatch"
    POINTER_ABSENT = "pointer_absent"
    COLUMN_ABSENT = "column_absent"
    ROW_ABSENT = "row_absent"
    ROW_AMBIGUOUS = "row_ambiguous"
    ROW_SELECTOR_INVALID = "row_selector_invalid"
    SELECTOR_NOT_SCALAR = "selector_not_scalar"
    """The locator resolved to a container. A list or mapping is not a value."""
    FORMAT_UNSUPPORTED = "format_unsupported"
    """No adapter addresses this format. Reported rather than approximated: falling back to
    searching the file for the printed number would find it wherever it appears and call
    that verification."""
    WRONG_PAGE = "wrong_page"
    """The passage occurs in the artifact, on a different page than the one asserted."""
    VALUE_NOT_NUMERIC = "value_not_numeric"
    EXTRACTOR_MISSING = "extractor_missing"
    ARTIFACT_MISSING = "artifact_missing"
    ARTIFACT_UNREADABLE = "artifact_unreadable"
    ARTIFACT_UNDECLARED = "artifact_undeclared"
    BACKEND_DEFECT = "backend_defect"
    NOT_OFFERED = "not_offered"


class Warning_(enum.StrEnum):
    """Notes about the evidence itself, orthogonal to the outcome."""

    SHORT = "short"
    TRUNCATED = "truncated"
    NORMALIZED = "normalized"
    WRONG_PAGE = "wrong_page"
    POSITIONAL_ADDRESS = "positional_address"
    """Addressed by row index, which names a different cell if the table is reordered."""


class Decision(BaseModel):
    """The outcome of evaluating one evidence assertion. Frozen: a decision that can be
    edited after the fact records nothing."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    claim_id: str
    claim_digest: str
    kind: str

    execution: ExecutionStatus
    extraction: ExtractionStatus
    comparison: ComparisonStatus
    reason: Reason
    detail: str = ""

    validity: Validity = Validity.AUTHORITATIVE
    artifact_id: str = ""
    artifact_digest: str | None = None
    """The digest of the bytes actually read, so the decision can be re-checked against the
    same content rather than the same path."""

    locator_digest: str | None = None
    """The digest of the canonical locator, so a decision binds how the value was addressed
    as well as what was read. A selector edited after the fact changes this even where the
    artifact is untouched."""

    backend: str = ""
    backend_version: str = ""
    """Named because the same inputs can receive different decisions after a backend upgrade,
    and a stored decision that does not say which backend produced it cannot be compared with
    a later one."""

    warnings: tuple[Warning_, ...] = ()

    @property
    def outcome(self) -> Outcome:
        if self.execution is ExecutionStatus.FAILED:
            return Outcome.ERROR
        if self.execution is ExecutionStatus.UNAVAILABLE:
            return Outcome.UNCHECKED
        if self.extraction in (ExtractionStatus.ABSENT, ExtractionStatus.INVALID):
            return Outcome.NOT_FOUND
        if self.comparison is ComparisonStatus.MATCH:
            return Outcome.VERIFIED
        if self.comparison is ComparisonStatus.MISMATCH:
            return Outcome.MISMATCH
        return Outcome.UNCHECKED

    @property
    def is_authoritative(self) -> bool:
        return self.validity is Validity.AUTHORITATIVE
