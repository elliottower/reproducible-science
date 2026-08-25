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

The contract is defined in `repro.core`, one module per group. This module re-exports it,
so `from repro.models import X` continues to name the same objects.
"""

from __future__ import annotations

from repro.core.artifacts import SCHEMA_VERSION, ArtifactRef, Digest
from repro.core.claims import Availability, Claim, Registration
from repro.core.evidence import (
    ArrayLocator,
    ComparisonMode,
    Evidence,
    Locator,
    MetricEvidence,
    PredicateValue,
    QuoteEvidence,
    SqliteLocator,
    TableCellEvidence,
    TableLocator,
    TablePositionLocator,
    TreeLocator,
    ValueEvidence,
    ValueLocator,
)
from repro.core.manifest import (
    Manifest,
    Provenance,
    Regeneration,
    RegenerationReason,
    RegenerationRecord,
    RegenerationState,
    RunOutput,
    RunRecord,
)
from repro.core.outcomes import (
    ComparisonStatus,
    Decision,
    ExecutionStatus,
    ExtractionStatus,
    Ordering,
    OrderingReason,
    Outcome,
    Reason,
    RegistrationAuthority,
    Validity,
    Warning_,
)
from repro.core.report import ArtifactState, ClaimAssessment, VerificationReport

__all__ = [
    "SCHEMA_VERSION",
    "ArrayLocator",
    "ArtifactRef",
    "ArtifactState",
    "Availability",
    "Claim",
    "ClaimAssessment",
    "ComparisonMode",
    "ComparisonStatus",
    "Decision",
    "Digest",
    "Evidence",
    "ExecutionStatus",
    "ExtractionStatus",
    "Locator",
    "Manifest",
    "MetricEvidence",
    "Ordering",
    "OrderingReason",
    "Outcome",
    "PredicateValue",
    "Provenance",
    "QuoteEvidence",
    "Reason",
    "Regeneration",
    "RegenerationReason",
    "RegenerationRecord",
    "RegenerationState",
    "Registration",
    "RegistrationAuthority",
    "RunOutput",
    "RunRecord",
    "SqliteLocator",
    "TableCellEvidence",
    "TableLocator",
    "TablePositionLocator",
    "TreeLocator",
    "Validity",
    "ValueEvidence",
    "ValueLocator",
    "VerificationReport",
    "Warning_",
]
