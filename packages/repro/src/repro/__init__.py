"""One contract for verifying declared evidence assertions against pinned artifacts.

A quotation in a manuscript and a number in a results file are the same kind of object: a
typed value asserted to be extractable from a pinned artifact. This package verifies that
assertion -- and nothing beyond it. Whether the evidence *supports* the sentence citing it is
a question about entailment, addressed elsewhere with model-based methods.

    from repro import load, verify
    from repro.renderers import to_sarif
from repro.policy import PUBLICATION

    report = verify(load("repro.yaml"))       # facts
    verdict = PUBLICATION.assess(report)      # judgment

Facts and judgment are separate calls because a missing optional citation is acceptable in a
draft and not in a submission, and one project's standard should not be everyone's.

Nothing here prints, exits, or reads global state.
"""

import importlib
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _version

# The contract and the engine are the `claims` package, which this one depends on and adds
# the commands that run things to. Every name this package has always exported is that
# package's, the same object under the same name.
import claims as _claims
from claims import (
    DEFAULT_BACKENDS,
    DEFAULT_NAME,
    EXPLORATORY,
    PROFILES,
    PUBLICATION,
    SCHEMA_VERSION,
    STRICT,
    ArtifactMissingError,
    ArtifactRef,
    ArtifactState,
    ArtifactUnreadableError,
    Assessment,
    Availability,
    Backend,
    BackendUnavailableError,
    Claim,
    ClaimAssessment,
    ComparisonMode,
    ComparisonStatus,
    Decision,
    Digest,
    DigestMismatchError,
    Evidence,
    ExecutionStatus,
    ExtractionStatus,
    Manifest,
    ManifestError,
    MetricBackend,
    MetricEvidence,
    Outcome,
    Policy,
    QuoteBackend,
    QuoteEvidence,
    Reason,
    ReproError,
    Resolution,
    Severity,
    TableBackend,
    TableCellEvidence,
    UnknownEvidenceKindError,
    Validity,
    ValueBackend,
    VerificationReport,
    Warning_,
    find,
    load,
    read_table,
    resolve_pointer,
    sniff_delimiter,
    to_sarif,
)

# `repro.resolve` and `repro.verify` have always been these two functions, though modules of
# the same names exist. Importing a submodule binds it on the package under its name, so the
# modules are loaded here first and the functions bound after them, for good.
importlib.import_module("repro.resolve")
importlib.import_module("repro.verify")
resolve = _claims.resolve
verify = _claims.verify

try:
    __version__ = _version("reproducible-science")
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
