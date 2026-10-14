"""One contract for verifying declared evidence assertions against pinned artifacts.

A quotation in a manuscript and a number in a results file are the same kind of object: a
typed value asserted to be extractable from a pinned artifact. This package verifies that
assertion -- and nothing beyond it. Whether the evidence *supports* the sentence citing it is
a question about entailment, addressed elsewhere with model-based methods.

    from repro import load, verify
    from claims.renderers import to_sarif
from claims.policy import PUBLICATION

    report = verify(load("repro.yaml"))       # facts
    verdict = PUBLICATION.assess(report)      # judgment

Facts and judgment are separate calls because a missing optional citation is acceptable in a
draft and not in a submission, and one project's standard should not be everyone's.

Nothing here prints, exits, or reads global state.
"""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _version

from claims.exceptions import (
    ArtifactMissingError,
    ArtifactUnreadableError,
    BackendUnavailableError,
    DigestMismatchError,
    ManifestError,
    ReproError,
    UnknownEvidenceKindError,
)
from claims.manifest import DEFAULT_NAME, find, load
from claims.models import (
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
from claims.policy import EXPLORATORY, PROFILES, PUBLICATION, STRICT, Assessment, Policy, Severity
from claims.renderers import to_sarif
from claims.resolve import Resolution, read_table, resolve, resolve_pointer, sniff_delimiter
from claims.toolchain import DISTRIBUTION
from claims.verify import (
    DEFAULT_BACKENDS,
    Backend,
    MetricBackend,
    QuoteBackend,
    TableBackend,
    ValueBackend,
    verify,
)

# The version of the distribution this installation names itself by: `reproducible-science`
# where that is installed, which is what a SARIF file has always carried, and `claims-cli`
# where this package is installed alone.
try:
    __version__ = _version(DISTRIBUTION)
except PackageNotFoundError:  # a source tree with nothing installed
    __version__ = "0+unknown"

__all__ = [
    "DEFAULT_BACKENDS",
    "DEFAULT_NAME",
    "EXPLORATORY",
    "PROFILES",
    "PUBLICATION",
    "SCHEMA_VERSION",
    "STRICT",
    "ArtifactMissingError",
    "ArtifactRef",
    "ArtifactState",
    "ArtifactUnreadableError",
    "Assessment",
    "Availability",
    "Backend",
    "BackendUnavailableError",
    "Claim",
    "ClaimAssessment",
    "ComparisonMode",
    "ComparisonStatus",
    "Decision",
    "Digest",
    "DigestMismatchError",
    "Evidence",
    "ExecutionStatus",
    "ExtractionStatus",
    "Manifest",
    "ManifestError",
    "MetricBackend",
    "MetricEvidence",
    "Outcome",
    "Policy",
    "QuoteBackend",
    "QuoteEvidence",
    "Reason",
    "ReproError",
    "Resolution",
    "Severity",
    "TableBackend",
    "TableCellEvidence",
    "UnknownEvidenceKindError",
    "Validity",
    "ValueBackend",
    "VerificationReport",
    "Warning_",
    "__version__",
    "find",
    "load",
    "read_table",
    "resolve",
    "resolve_pointer",
    "sniff_delimiter",
    "to_sarif",
    "verify",
]
