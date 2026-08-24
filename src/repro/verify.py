"""The verification engine.

The engine reads no artifacts itself. It resolves each artifact's pin once, dispatches each
evidence assertion to the backend registered for its kind, and records what came back. What
it adds on top of the backends is the part that has to be uniform:

  * **Pins are checked before evidence.** A source that moved is known before any decision is
    computed against it, and those decisions are marked non-authoritative rather than being
    silently reported as if the declared file had been read.
  * **A backend that cannot run is not a claim that failed.** `BackendUnavailableError`
    becomes `execution=unavailable` with the backend's own reason attached.
  * **A defect is not a scientific outcome.** Any other exception becomes
    `execution=failed`, which flattens to `error` and never to `unchecked`. Letting a
    `TypeError` become an abstention is the same failure this package exists to prevent, one
    level up.
"""
from __future__ import annotations

import csv
import decimal
import io
import json
import pathlib
from typing import Protocol

from repro.exceptions import (
    ArtifactUnreadableError,
    BackendUnavailableError,
    UnknownEvidenceKindError,
)
from repro.models import (
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
    QuoteEvidence,
    Reason,
    TableCellEvidence,
    Validity,
    VerificationReport,
    Warning_,
)


class Backend(Protocol):
    """Evaluates one kind of evidence assertion against one artifact."""

    kind: str
    version: str

    def check(self, claim: Claim, evidence: Evidence, path: pathlib.Path) -> Decision: ...


def _base(claim: Claim, evidence: Evidence, backend: "Backend") -> dict:
    return {
        "claim_id": claim.id,
        "claim_digest": claim.digest.value,
        "kind": evidence.kind,
        "artifact_id": evidence.artifact,
        "backend": backend.kind,
        "backend_version": backend.version,
    }


# -------------------------------------------------------------------------------- quotations

_QUOTE_STATE = {
    "found": (ExtractionStatus.EXTRACTED, ComparisonStatus.MATCH, Reason.PASSAGE_PRESENT),
    "not found": (ExtractionStatus.EXTRACTED, ComparisonStatus.MISMATCH, Reason.PASSAGE_ABSENT),
}

_QUOTE_WARNINGS = {
    "short": Warning_.SHORT,
    "truncated": Warning_.TRUNCATED,
    "normalized": Warning_.NORMALIZED,
    "page": Warning_.WRONG_PAGE,
}


class QuoteBackend:
    """Assertion: this passage occurs in this artifact.

    A passage that is absent from a source that was read successfully is a `mismatch`: the
    artifact was extracted and does not contain what the assertion says it contains. That is
    a different fact from a source that could not be read, which is `unavailable`.
    """

    kind = "quote"
    version = "1"

    def check(self, claim: Claim, evidence: Evidence, path: pathlib.Path) -> Decision:
        if not isinstance(evidence, QuoteEvidence):
            raise TypeError(f"QuoteBackend received {type(evidence).__name__}")
        try:
            from citations.verify import check_one
        except ImportError as e:
            raise BackendUnavailableError("quote", f"citations is not installed: {e}") from e

        result = check_one(evidence.text, path, evidence.page)
        base = _base(claim, evidence, self)
        warnings = tuple(_QUOTE_WARNINGS[w] for w in result.warnings if w in _QUOTE_WARNINGS)

        if result.state == "unchecked":
            # The extractor could not produce text. Distinguishing this from an absent
            # passage is the reason the three stages are separate.
            raise BackendUnavailableError("quote", result.detail or "no text extracted")

        extraction, comparison, reason = _QUOTE_STATE[result.state]
        return Decision(**base, execution=ExecutionStatus.COMPLETED, extraction=extraction,
                        comparison=comparison, reason=reason, detail=result.detail,
                        warnings=warnings)


# ----------------------------------------------------------------------------------- metrics

_MISSING = object()


def resolve_pointer(document: object, pointer: str) -> object:
    """RFC 6901 JSON Pointer resolution. Returns `_MISSING` when the pointer does not resolve.

    `~1` is a literal `/` and `~0` a literal `~`, unescaped in that order, so a key containing
    a slash is addressable and a key containing a period is unremarkable.
    """
    if pointer == "":
        return document
    if not pointer.startswith("/"):
        raise ValueError(f"JSON Pointer must start with '/': {pointer!r}")
    node = document
    for raw in pointer[1:].split("/"):
        token = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(node, dict):
            if token not in node:
                return _MISSING
            node = node[token]
        elif isinstance(node, list):
            if not token.isdigit():
                return _MISSING
            index = int(token)
            if index >= len(node):
                return _MISSING
            node = node[index]
        else:
            return _MISSING
    return node


def compare_decimal(stored: decimal.Decimal,
                    evidence: "MetricEvidence | TableCellEvidence") -> bool:
    """Does the stored value agree with the reported one, under the declared mode?"""
    reported = evidence.value
    if evidence.mode is ComparisonMode.PRINTED_PRECISION:
        # Round the stored value to the precision the manuscript printed. A paper reporting
        # 3.2 is not contradicted by a file holding 3.20001; a paper reporting 3.20000 is.
        return stored.quantize(reported, rounding=decimal.ROUND_HALF_EVEN) == reported
    delta = abs(stored - reported)
    if evidence.mode is ComparisonMode.ABSOLUTE:
        return delta <= evidence.tolerance_value
    return delta <= evidence.tolerance_value * abs(reported)


class MetricBackend:
    """Assertion: this artifact holds this value at this location."""

    kind = "metric"
    version = "1"

    def check(self, claim: Claim, evidence: Evidence, path: pathlib.Path) -> Decision:
        if not isinstance(evidence, MetricEvidence):
            raise TypeError(f"MetricBackend received {type(evidence).__name__}")
        base = _base(claim, evidence, self)
        try:
            document = json.loads(path.read_text())
        except json.JSONDecodeError as e:
            raise ArtifactUnreadableError(path, f"not valid JSON: {e}") from e
        except OSError as e:
            raise ArtifactUnreadableError(path, str(e)) from e

        node = resolve_pointer(document, evidence.pointer)
        if node is _MISSING:
            # The artifact was read and is silent here. Silence is not contradiction.
            return Decision(**base, execution=ExecutionStatus.COMPLETED,
                            extraction=ExtractionStatus.ABSENT,
                            comparison=ComparisonStatus.NOT_APPLICABLE,
                            reason=Reason.POINTER_ABSENT,
                            detail=f"{evidence.pointer} does not resolve in {path.name}")
        if isinstance(node, bool) or not isinstance(node, (int, float, str)):
            return Decision(**base, execution=ExecutionStatus.COMPLETED,
                            extraction=ExtractionStatus.INVALID,
                            comparison=ComparisonStatus.NOT_APPLICABLE,
                            reason=Reason.VALUE_NOT_NUMERIC,
                            detail=f"{evidence.pointer} holds {type(node).__name__}")
        try:
            stored = decimal.Decimal(str(node))
        except decimal.InvalidOperation:
            return Decision(**base, execution=ExecutionStatus.COMPLETED,
                            extraction=ExtractionStatus.INVALID,
                            comparison=ComparisonStatus.NOT_APPLICABLE,
                            reason=Reason.VALUE_NOT_NUMERIC,
                            detail=f"{evidence.pointer} holds {node!r}")

        agrees = compare_decimal(stored, evidence)
        return Decision(
            **base, execution=ExecutionStatus.COMPLETED,
            extraction=ExtractionStatus.EXTRACTED,
            comparison=ComparisonStatus.MATCH if agrees else ComparisonStatus.MISMATCH,
            reason=Reason.VALUE_MATCH if agrees else Reason.VALUE_MISMATCH,
            detail=(f"{evidence.pointer} = {stored}" if agrees else
                    f"{evidence.name}: manuscript prints {evidence.reported}, "
                    f"{path.name} holds {stored}"))


# ------------------------------------------------------------------------------------ tables

#: Delimiters tried when a file's suffix does not settle it, most specific first.
_DELIMITERS = {".csv": ",", ".tsv": "\t", ".psv": "|"}


def sniff_delimiter(path: pathlib.Path, sample: str) -> str:
    """The delimiter for a table, from its suffix or from the header line.

    Suffix first, because a `.tsv` whose header happens to contain commas is still tab
    separated and sniffing it would split every row in the wrong place.
    """
    if (known := _DELIMITERS.get(path.suffix.lower())):
        return known
    header = sample.splitlines()[0] if sample.splitlines() else ""
    counts = {d: header.count(d) for d in (",", "\t", ";", "|")}
    best = max(counts, key=counts.get)
    return best if counts[best] else ","


def read_table(path: pathlib.Path, delimiter: str = "") -> tuple[list[str], list[dict]]:
    """Header and rows. Raises `ArtifactUnreadableError` when the file is not a table."""
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as e:
        raise ArtifactUnreadableError(path, str(e)) from e
    if not text.strip():
        raise ArtifactUnreadableError(path, "file is empty")
    reader = csv.DictReader(io.StringIO(text),
                            delimiter=delimiter or sniff_delimiter(path, text))
    rows = list(reader)
    if reader.fieldnames is None:
        raise ArtifactUnreadableError(path, "no header row")
    return list(reader.fieldnames), rows


def select_row(rows: list[dict], evidence: TableCellEvidence) -> tuple[list[int], str]:
    """Indices of the rows the evidence addresses, and how it addressed them."""
    if evidence.row is not None:
        return ([evidence.row] if 0 <= evidence.row < len(rows) else []), f"row {evidence.row}"
    matched = [i for i, r in enumerate(rows)
               if all((r.get(k) or "").strip() == v.strip() for k, v in evidence.where.items())]
    described = ", ".join(f"{k}={v!r}" for k, v in evidence.where.items())
    return matched, described


class TableBackend:
    """Assertion: this table holds this value in this cell.

    Delimited tables are what most published result artifacts actually are, so this is the
    variant a manuscript's own tables usually need.
    """

    kind = "table"
    version = "1"

    def check(self, claim: Claim, evidence: Evidence, path: pathlib.Path) -> Decision:
        if not isinstance(evidence, TableCellEvidence):
            raise TypeError(f"TableBackend received {type(evidence).__name__}")
        base = _base(claim, evidence, self)
        completed = {"execution": ExecutionStatus.COMPLETED}
        no_compare = {"comparison": ComparisonStatus.NOT_APPLICABLE}

        if not evidence.addresses_one_row:
            # Both or neither given. A manifest that does not say which row it means is
            # malformed rather than a table that disagrees.
            return Decision(**base, **completed, **no_compare,
                            extraction=ExtractionStatus.INVALID,
                            reason=Reason.ROW_SELECTOR_INVALID,
                            detail="give exactly one of `row` or `where`")

        header, rows = read_table(path, evidence.delimiter)
        if evidence.column not in header:
            return Decision(**base, **completed, **no_compare,
                            extraction=ExtractionStatus.ABSENT, reason=Reason.COLUMN_ABSENT,
                            detail=f"{path.name} has no column {evidence.column!r}; "
                                   f"columns are {', '.join(header[:8])}")

        matched, described = select_row(rows, evidence)
        if not matched:
            return Decision(**base, **completed, **no_compare,
                            extraction=ExtractionStatus.ABSENT, reason=Reason.ROW_ABSENT,
                            detail=f"no row in {path.name} where {described}")
        if len(matched) > 1:
            # Resolving to the first would make the check depend on row order, which is what
            # a selector exists to avoid.
            return Decision(**base, **completed, **no_compare,
                            extraction=ExtractionStatus.INVALID, reason=Reason.ROW_AMBIGUOUS,
                            detail=f"{len(matched)} rows in {path.name} where {described}")

        cell = (rows[matched[0]].get(evidence.column) or "").strip()
        try:
            stored = decimal.Decimal(cell)
        except (decimal.InvalidOperation, ValueError):
            return Decision(**base, **completed, **no_compare,
                            extraction=ExtractionStatus.INVALID,
                            reason=Reason.VALUE_NOT_NUMERIC,
                            detail=f"{evidence.column} at {described} holds {cell!r}")

        agrees = compare_decimal(stored, evidence)
        return Decision(
            **base, **completed, extraction=ExtractionStatus.EXTRACTED,
            comparison=ComparisonStatus.MATCH if agrees else ComparisonStatus.MISMATCH,
            reason=Reason.VALUE_MATCH if agrees else Reason.VALUE_MISMATCH,
            detail=(f"{evidence.column} at {described} = {stored}" if agrees else
                    f"{evidence.name}: manuscript prints {evidence.reported}, "
                    f"{path.name} holds {stored} at {described}"))


DEFAULT_BACKENDS: tuple[Backend, ...] = (QuoteBackend(), MetricBackend(), TableBackend())


# ------------------------------------------------------------------------------------ engine

def _artifact_state(artifact: ArtifactRef, path: pathlib.Path) -> ArtifactState:
    if not path.exists():
        return ArtifactState(artifact_id=artifact.id, validity=Validity.UNPINNED_ARTIFACT
                             if not artifact.is_pinned else Validity.AUTHORITATIVE,
                             exists=False, expected=artifact.digest.value
                             if artifact.digest else None)
    if not artifact.is_pinned:
        return ArtifactState(artifact_id=artifact.id, validity=Validity.UNPINNED_ARTIFACT,
                             actual=Digest.of_file(path).value)
    actual = Digest.of_file(path).value
    if actual != artifact.digest.value:
        return ArtifactState(artifact_id=artifact.id, validity=Validity.BROKEN_PIN,
                             expected=artifact.digest.value, actual=actual)
    return ArtifactState(artifact_id=artifact.id, validity=Validity.AUTHORITATIVE,
                         expected=artifact.digest.value, actual=actual)


def verify(manifest: Manifest,
           backends: tuple[Backend, ...] = DEFAULT_BACKENDS) -> VerificationReport:
    """Check every evidence assertion in a manifest and report what was found.

    Returns facts. No verdict: see `repro.policy` for whether a given set of facts is
    acceptable, which depends on what the project is for.
    """
    registry: dict[str, Backend] = {b.kind: b for b in backends}

    states: dict[str, ArtifactState] = {}
    paths: dict[str, pathlib.Path] = {}
    for artifact in manifest.artifacts:
        path = manifest.resolve(artifact)
        paths[artifact.id] = path
        states[artifact.id] = _artifact_state(artifact, path)

    assessments = []
    for claim in manifest.claims:
        decisions = tuple(
            _check(claim, evidence, manifest, paths, states, registry)
            for evidence in claim.evidence)
        assessments.append(ClaimAssessment(
            claim_id=claim.id, claim_digest=claim.digest.value,
            confirmatory=claim.confirmatory, availability=claim.availability,
            decisions=decisions))

    return VerificationReport(
        project=manifest.project,
        manifest_digest=Digest.of_text(manifest.model_dump_json()).value,
        artifacts=tuple(states.values()), claims=tuple(assessments))


def _check(claim: Claim, evidence: Evidence, manifest: Manifest,
           paths: dict[str, pathlib.Path], states: dict[str, ArtifactState],
           registry: dict[str, Backend]) -> Decision:
    backend = registry.get(evidence.kind)
    if backend is None:
        raise UnknownEvidenceKindError(evidence.kind, tuple(registry))

    base = {"claim_id": claim.id, "claim_digest": claim.digest.value, "kind": evidence.kind,
            "artifact_id": evidence.artifact, "backend": backend.kind,
            "backend_version": backend.version}
    unchecked = {"execution": ExecutionStatus.UNAVAILABLE,
                 "extraction": ExtractionStatus.NOT_ATTEMPTED,
                 "comparison": ComparisonStatus.NOT_APPLICABLE}

    artifact = manifest.artifact(evidence.artifact)
    if artifact is None:
        return Decision(**base, **unchecked, reason=Reason.ARTIFACT_UNDECLARED,
                        detail=f"manifest declares no artifact {evidence.artifact!r}")
    path = paths[artifact.id]
    state = states[artifact.id]
    if not state.exists:
        return Decision(**base, **unchecked, reason=Reason.ARTIFACT_MISSING,
                        detail=f"{path} does not exist", validity=state.validity)

    try:
        decision = backend.check(claim, evidence, path)
    except BackendUnavailableError as e:
        decision = Decision(**base, **unchecked, reason=Reason.EXTRACTOR_MISSING,
                            detail=e.detail)
    except ArtifactUnreadableError as e:
        decision = Decision(**base, **unchecked, reason=Reason.ARTIFACT_UNREADABLE,
                            detail=e.detail)
    except Exception as e:  # noqa: BLE001 - deliberate, see below
        # A defect in a backend is a defect, not an abstention. Recording it as `unchecked`
        # would make a TypeError indistinguishable from a missing extractor, which is the
        # confusion this package exists to prevent.
        decision = Decision(**base, execution=ExecutionStatus.FAILED,
                            extraction=ExtractionStatus.NOT_ATTEMPTED,
                            comparison=ComparisonStatus.NOT_APPLICABLE,
                            reason=Reason.BACKEND_DEFECT,
                            detail=f"{type(e).__name__}: {e}")

    return decision.model_copy(update={
        "validity": state.validity,
        "artifact_digest": state.actual,
    })
