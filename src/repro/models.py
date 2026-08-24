"""The evidence contract.

A quotation in a manuscript and a number in a results file are the same kind of object: a
typed value asserted to be extractable from a pinned artifact. This package verifies that
assertion and nothing beyond it.

**What a decision evaluates.** Each decision evaluates an *evidence assertion* -- "this passage
occurs in this artifact", "this artifact holds this value at this location" -- and never the
truth of the manuscript claim the evidence is offered for. A source can contain a quotation
verbatim while the quotation fails to support the sentence citing it, and a passage can be
absent while the claim is true and supported elsewhere. Entailment between evidence and claim
is a separate question, addressed by the claim-verification literature with model-based
methods, and out of scope here.

That distinction governs the vocabulary. `SUPPORTED` and `REFUTED` name a semantic relation
between evidence and claim; this package reports `MATCH` and `MISMATCH`, which name what a
byte comparison found.

**Three stages, reported separately.** A check has to execute, extract, and compare, and each
can fail differently:

    execution    did the check run at all?          completed | unavailable | failed
    extraction   was the value located?             extracted | absent | invalid | not_attempted
    comparison   did it match what was claimed?     match | mismatch | not_applicable

Collapsing these is how a missing PDF extractor becomes a quotation that failed to check out,
and how a results file that is silent on a value becomes one that contradicts it. A selector
that resolves to nothing is `completed / absent / not_applicable`: the check ran, the value is
not there, and no comparison was possible. A missing extractor is
`unavailable / not_attempted / not_applicable`: nothing ran.

**Availability is a claim-level fact, not a check outcome.** Whether a claim offers evidence
cannot be the result of checking evidence, because there is none to pass to a backend. It
lives on the claim.
"""
from __future__ import annotations

import decimal
import enum
import hashlib
import pathlib
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = "repro/1"

_SHA256_HEX = r"^[a-f0-9]{64}$"


# --------------------------------------------------------------------------------- artifacts

class Digest(BaseModel):
    """A content address."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    algorithm: Literal["sha256"] = "sha256"
    value: Annotated[str, Field(pattern=_SHA256_HEX)]
    """Lowercase hex. The pattern is enforced because a truncated or uppercase digest compares
    unequal to a correct one and reads, in a report, as a tampered file."""

    def __str__(self) -> str:
        return f"{self.algorithm}:{self.value}"

    @classmethod
    def of_file(cls, path: pathlib.Path) -> "Digest":
        h = hashlib.sha256()
        with path.open("rb") as fh:
            for block in iter(lambda: fh.read(1 << 20), b""):
                h.update(block)
        return cls(value=h.hexdigest())

    @classmethod
    def of_text(cls, text: str) -> "Digest":
        return cls(value=hashlib.sha256(text.encode("utf-8")).hexdigest())


class ArtifactRef(BaseModel):
    """A file a manifest names, whether or not it has been pinned.

    Separate from `PinnedArtifact` because "identified by content" and "may carry no digest"
    cannot both be true of one type. An unpinned reference is a legitimate thing to write down
    and an illegitimate thing to verify against, and the type says which it is.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    path: pathlib.Path
    digest: Digest | None = None
    media_type: str = "application/octet-stream"

    @property
    def is_pinned(self) -> bool:
        return self.digest is not None


# ---------------------------------------------------------------------------------- evidence

class _EvidenceBase(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    artifact: str
    """Id of the artifact this value is asserted to come from. The artifact carries the pin;
    evidence never repeats a digest, so there is one source of truth per file."""


class QuoteEvidence(_EvidenceBase):
    """Assertion: this passage occurs in this artifact."""

    kind: Literal["quote"] = "quote"

    text: str
    section: str | None = None
    """Where the source puts it, as the source names it. Recorded, never verified."""

    page: int | None = None
    """Verified when present, for paginated sources."""


class ComparisonMode(enum.StrEnum):
    """How a reported number is compared with a stored one."""

    PRINTED_PRECISION = "printed_precision"
    """Compare at the precision the manuscript printed. `3.20` requires two decimals to
    agree; `3.2` requires one. This is why `reported` is a string."""

    ABSOLUTE = "absolute"
    """Agree when |stored - reported| <= tolerance."""

    RELATIVE = "relative"
    """Agree when |stored - reported| <= tolerance * |reported|."""


class MetricEvidence(_EvidenceBase):
    """Assertion: this artifact holds this value at this location."""

    kind: Literal["metric"] = "metric"

    name: str
    reported: str
    """The value exactly as the manuscript prints it, as a string.

    A string because YAML parses `3.20` to the float `3.2`, discarding the precision the
    manuscript chose, and because binary floats do not represent decimal fractions exactly.
    Parsed with `decimal.Decimal`."""

    pointer: str
    """RFC 6901 JSON Pointer: `/comparisons/primary/delta`.

    JSON Pointer rather than a dotted path because a dotted path cannot distinguish a mapping
    key containing a period from a nesting level, nor list index `0` from mapping key `"0"`,
    and specifying an escape grammar for a new selector language is work already done."""

    mode: ComparisonMode = ComparisonMode.PRINTED_PRECISION
    tolerance: str = "0"
    """As a decimal string, for the same reason as `reported`. Ignored for
    `printed_precision`."""

    @property
    def value(self) -> decimal.Decimal:
        return decimal.Decimal(self.reported)

    @property
    def tolerance_value(self) -> decimal.Decimal:
        return decimal.Decimal(self.tolerance)


class TableCellEvidence(_EvidenceBase):
    """Assertion: this table holds this value in this cell.

    Most published result artifacts are delimited tables rather than JSON, so addressing a
    cell is what a manuscript's own tables usually need. A cell is named by its column and by
    one of two ways of picking the row.
    """

    kind: Literal["table"] = "table"

    name: str
    reported: str
    """The value exactly as the manuscript prints it, as a string. See `MetricEvidence`."""

    column: str
    """Header name of the column holding the value."""

    row: int | None = None
    """Zero-based index among data rows, excluding the header."""

    where: dict[str, str] = Field(default_factory=dict)
    """Select the row whose named columns hold these values: `{"model": "LASSO-Cox"}`.

    Preferred over `row`, because a row index silently addresses a different cell when a table
    is reordered or a row is inserted, and a table that has been reordered is exactly the case
    a checker exists to notice. A selector matching no rows, or more than one, is reported
    rather than resolved."""

    delimiter: str = ""
    """Override the delimiter. Empty means infer it from the file's suffix and contents."""

    mode: ComparisonMode = ComparisonMode.PRINTED_PRECISION
    tolerance: str = "0"

    @property
    def value(self) -> decimal.Decimal:
        return decimal.Decimal(self.reported)

    @property
    def tolerance_value(self) -> decimal.Decimal:
        return decimal.Decimal(self.tolerance)

    @property
    def addresses_one_row(self) -> bool:
        """Exactly one row selector must be given."""
        return (self.row is None) != (not self.where)


Evidence = Annotated[QuoteEvidence | MetricEvidence | TableCellEvidence,
                     Field(discriminator="kind")]
"""Every kind of evidence, discriminated on `kind`.

`protocol` was a third variant and is not one. Its integrity check is the artifact pin, which
every artifact already carries, and its content check -- that a registered document states a
given hypothesis -- is a quotation against the plan. What remains distinct about a protocol is
temporal: whether a confirmatory run postdates its registration. That needs a run record, is
unimplemented, and is not smuggled in as a third evidence kind in the meantime.
"""


# ------------------------------------------------------------------------------------ claims

class Availability(enum.StrEnum):
    """Whether a claim offers anything to check. A property of the claim, not of a check."""

    OFFERED = "offered"
    NOT_OFFERED = "not_offered"


class Claim(BaseModel):
    """A statement made in a manuscript, and the evidence offered for it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    text: str
    where: str | None = None
    confirmatory: bool = False
    """Whether this reports a preregistered outcome. Recorded now; governs the ordering check
    specified for a later revision."""

    evidence: tuple[Evidence, ...] = ()

    @property
    def availability(self) -> Availability:
        return Availability.OFFERED if self.evidence else Availability.NOT_OFFERED

    @property
    def digest(self) -> Digest:
        """Content address of the claim as evaluated.

        A decision names this so it cannot silently remain attached to text that has since
        been edited.
        """
        return Digest.of_text(f"{self.id}\x00{self.text}\x00{self.where or ''}")


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


class Validity(enum.StrEnum):
    """Whether a decision describes the artifact the manifest declared."""

    AUTHORITATIVE = "authoritative"
    UNPINNED_ARTIFACT = "unpinned_artifact"
    """No digest was recorded, so the file read may not be the file meant."""
    BROKEN_PIN = "broken_pin"
    """The file read is provably not the file that was pinned. The comparison still ran and
    its result is reported, marked non-authoritative, because a diagnostic is more useful than
    a blank."""


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


class Manifest(BaseModel):
    """One project: its artifacts and its claims."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = SCHEMA_VERSION
    project: str = ""
    provenance: Provenance | None = None
    artifacts: tuple[ArtifactRef, ...] = ()
    claims: tuple[Claim, ...] = ()

    path: pathlib.Path | None = Field(default=None, exclude=True)

    def artifact(self, artifact_id: str) -> ArtifactRef | None:
        return next((a for a in self.artifacts if a.id == artifact_id), None)

    def resolve(self, artifact: ArtifactRef) -> pathlib.Path:
        if artifact.path.is_absolute() or self.path is None:
            return artifact.path
        return (self.path.parent / artifact.path).resolve()


# ------------------------------------------------------------------------------------ report

class ArtifactState(BaseModel):
    """What was found at each artifact's path, before any evidence was read."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    artifact_id: str
    validity: Validity
    expected: str | None = None
    actual: str | None = None
    exists: bool = True


class ClaimAssessment(BaseModel):
    """One claim's availability, and the decisions on the evidence it offered."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    claim_id: str
    claim_digest: str
    confirmatory: bool = False
    availability: Availability
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


__all__ = [
    "SCHEMA_VERSION",
    "Digest", "ArtifactRef", "ArtifactState", "Provenance",
    "Evidence", "QuoteEvidence", "MetricEvidence", "TableCellEvidence", "ComparisonMode",
    "Claim", "Availability", "Manifest",
    "ExecutionStatus", "ExtractionStatus", "ComparisonStatus",
    "Outcome", "Validity", "Reason", "Warning_",
    "Decision", "ClaimAssessment", "VerificationReport",
]
