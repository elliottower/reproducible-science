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

The contract is defined in `claims.core`, one module per group. This module re-exports it,
so `from claims.models import X` continues to name the same objects.
"""

from __future__ import annotations

from claims.core.artifacts import SCHEMA_VERSION, ArtifactRef, Digest, Origin
from claims.core.checks import CheckedAssertion, CheckRecord, RecordSetAside, RecordState
from claims.core.claims import Availability, Claim, Registration
from claims.core.evidence import (
    AggregateEvidence,
    AggregateMember,
    ArrayLocator,
    ComparisonMode,
    Conversion,
    CorrespondenceEvidence,
    CorrespondenceSide,
    Evidence,
    Locator,
    MetricEvidence,
    NumberForm,
    PredicateValue,
    ProseLocator,
    QuoteEvidence,
    SheetLocator,
    SqliteLocator,
    Statistic,
    TableCellEvidence,
    TableLocator,
    TablePositionLocator,
    TreeLocator,
    ValueEvidence,
    ValueLocator,
)
from claims.core.manifest import (
    ClaimReading,
    InputReading,
    Manifest,
    Provenance,
    Reading,
    Regeneration,
    RegenerationReason,
    RegenerationRecord,
    RegenerationState,
    RunOutput,
    RunRecord,
    SetAside,
)
from claims.core.numbers import (
    NumberRule,
    NumbersReport,
    PrintedNumber,
    SetAsideCount,
    Standing,
    TextInventory,
)
from claims.core.outcomes import (
    ComparisonStatus,
    Decision,
    DecisionMember,
    DecisionSide,
    ExecutionStatus,
    ExtractionStatus,
    Ordering,
    OrderingReason,
    Outcome,
    Reason,
    RegistrationAuthority,
    Tie,
    Validity,
    Warning_,
)
from claims.core.report import (
    ArtifactNode,
    ArtifactState,
    AssertionAccount,
    AssertionNode,
    ChainNode,
    ClaimAccount,
    ClaimAssessment,
    ClaimNode,
    Edge,
    Environment,
    FileRead,
    Freshness,
    NotEstablished,
    NotEstablishedKind,
    PinDisagreement,
    RegenerationNode,
    ReproductionReport,
    StaleCause,
    StaleFinding,
    StalenessReport,
    VerificationReport,
    Witness,
)

__all__ = [
    "SCHEMA_VERSION",
    "AggregateEvidence",
    "AggregateMember",
    "ArrayLocator",
    "ArtifactNode",
    "ArtifactRef",
    "ArtifactState",
    "AssertionAccount",
    "AssertionNode",
    "Availability",
    "ChainNode",
    "CheckRecord",
    "CheckedAssertion",
    "Claim",
    "ClaimAccount",
    "ClaimAssessment",
    "ClaimNode",
    "ClaimReading",
    "ComparisonMode",
    "ComparisonStatus",
    "Conversion",
    "CorrespondenceEvidence",
    "CorrespondenceSide",
    "Decision",
    "DecisionMember",
    "DecisionSide",
    "Digest",
    "Edge",
    "Environment",
    "Evidence",
    "ExecutionStatus",
    "ExtractionStatus",
    "FileRead",
    "Freshness",
    "InputReading",
    "Locator",
    "Manifest",
    "MetricEvidence",
    "NotEstablished",
    "NotEstablishedKind",
    "NumberForm",
    "NumberRule",
    "NumbersReport",
    "Ordering",
    "OrderingReason",
    "Origin",
    "Outcome",
    "PinDisagreement",
    "PredicateValue",
    "PrintedNumber",
    "ProseLocator",
    "Provenance",
    "QuoteEvidence",
    "Reading",
    "Reason",
    "RecordSetAside",
    "RecordState",
    "Regeneration",
    "RegenerationNode",
    "RegenerationReason",
    "RegenerationRecord",
    "RegenerationState",
    "Registration",
    "RegistrationAuthority",
    "ReproductionReport",
    "RunOutput",
    "RunRecord",
    "SetAside",
    "SetAsideCount",
    "SheetLocator",
    "SqliteLocator",
    "StaleCause",
    "StaleFinding",
    "StalenessReport",
    "Standing",
    "Statistic",
    "TableCellEvidence",
    "TableLocator",
    "TablePositionLocator",
    "TextInventory",
    "Tie",
    "TreeLocator",
    "Validity",
    "ValueEvidence",
    "ValueLocator",
    "VerificationReport",
    "Warning_",
    "Witness",
]
