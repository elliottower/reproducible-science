"""One contract for verifying declared evidence assertions against pinned artifacts.

A quotation in a manuscript and a number in a results file are the same kind of object: a
typed value asserted to be extractable from a pinned artifact. This package verifies that
assertion -- and nothing beyond it. Whether the evidence *supports* the sentence citing it is
a question about entailment, addressed elsewhere with model-based methods.

    from repro import load, verify
    from repro.policy import PUBLICATION

    report = verify(load("repro.yaml"))       # facts
    verdict = PUBLICATION.assess(report)      # judgment

Facts and judgment are separate calls because a missing optional citation is acceptable in a
draft and not in a submission, and one project's standard should not be everyone's.

Nothing here prints, exits, or reads global state.
"""
from repro.exceptions import (
    ArtifactMissingError,
    ArtifactUnreadableError,
    BackendUnavailableError,
    DigestMismatchError,
    ManifestError,
    ReproError,
    UnknownEvidenceKindError,
)
from repro.manifest import DEFAULT_NAME, find, load
from repro.models import (
    SCHEMA_VERSION,
    ArtifactRef,
    ArtifactState,
    Availability,
    Claim,
    ClaimAssessment,
    ComparisonMode,
    ComparisonStatus,
    Decision,
    Digest,
    Evidence,
    ExecutionStatus,
    ExtractionStatus,
    Manifest,
    MetricEvidence,
    Outcome,
    QuoteEvidence,
    Reason,
    TableCellEvidence,
    Validity,
    VerificationReport,
    Warning_,
)
from repro.policy import EXPLORATORY, PROFILES, PUBLICATION, STRICT, Assessment, Policy, Severity
from repro.verify import (
    DEFAULT_BACKENDS,
    Backend,
    MetricBackend,
    QuoteBackend,
    TableBackend,
    read_table,
    verify,
)

__version__ = "0.3.0"

__all__ = [
    "ReproError", "ManifestError", "ArtifactMissingError", "ArtifactUnreadableError",
    "DigestMismatchError", "BackendUnavailableError", "UnknownEvidenceKindError",
    "SCHEMA_VERSION", "Digest", "ArtifactRef", "ArtifactState",
    "Evidence", "QuoteEvidence", "MetricEvidence", "TableCellEvidence", "ComparisonMode",
    "Claim", "Availability", "Manifest",
    "ExecutionStatus", "ExtractionStatus", "ComparisonStatus",
    "Outcome", "Validity", "Reason", "Warning_",
    "Decision", "ClaimAssessment", "VerificationReport",
    "load", "find", "DEFAULT_NAME",
    "verify", "Backend", "QuoteBackend", "MetricBackend", "TableBackend",
    "read_table", "DEFAULT_BACKENDS",
    "Policy", "Assessment", "Severity", "EXPLORATORY", "PUBLICATION", "STRICT", "PROFILES",
    "__version__",
]
