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

import decimal
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
    Ordering,
    OrderingReason,
    QuoteEvidence,
    Reason,
    RegistrationAuthority,
    TableCellEvidence,
    Validity,
    ValueEvidence,
    VerificationReport,
    Warning_,
)
from repro.regenerate import check_all
from repro.resolve import Resolution, resolve


class Backend(Protocol):
    """Evaluates one kind of evidence assertion against one artifact."""

    kind: str
    version: str

    def check(self, claim: Claim, evidence: Evidence, path: pathlib.Path) -> Decision: ...


def _base(claim: Claim, evidence: Evidence, backend: Backend) -> dict:
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
        if Warning_.WRONG_PAGE in warnings:
            # `page` is documented as verified when present, and the passage is not on the
            # page the manifest asserts. Reporting `match` with a warning made the assertion
            # unenforceable: no policy reads decision warnings, so it graded as verified.
            comparison, reason = ComparisonStatus.MISMATCH, Reason.WRONG_PAGE
        return Decision(
            **base,
            execution=ExecutionStatus.COMPLETED,
            extraction=extraction,
            comparison=comparison,
            reason=reason,
            detail=result.detail,
            warnings=warnings,
        )


# ------------------------------------------------------------------------------- values

#: How a resolution maps onto the extraction stage and a reason. `format_unsupported` is not
#: here: a format with no adapter means the check never ran, which is an execution fact.
_RESOLUTION_STATE = {
    Resolution.ABSENT: (ExtractionStatus.ABSENT, None),
    Resolution.COLUMN_ABSENT: (ExtractionStatus.ABSENT, Reason.COLUMN_ABSENT),
    Resolution.AMBIGUOUS: (ExtractionStatus.INVALID, Reason.ROW_AMBIGUOUS),
    Resolution.NOT_SCALAR: (ExtractionStatus.INVALID, Reason.SELECTOR_NOT_SCALAR),
    Resolution.SELECTOR_INVALID: (ExtractionStatus.INVALID, Reason.ROW_SELECTOR_INVALID),
}

#: Which "not there" reason fits each addressing scheme.
_ABSENT_REASON = {
    "tree": Reason.POINTER_ABSENT,
    "table": Reason.ROW_ABSENT,
    "table_position": Reason.ROW_ABSENT,
    "sqlite": Reason.ROW_ABSENT,
    "array": Reason.POINTER_ABSENT,
}


def compare_decimal(
    stored: decimal.Decimal, evidence: MetricEvidence | TableCellEvidence | ValueEvidence
) -> bool:
    """Does the stored value agree with the reported one, under the declared mode?"""
    reported = evidence.value
    if not stored.is_finite():
        # NaN and the infinities parse out of JSON but cannot equal a printed decimal. The
        # backend flags them before reaching here; this keeps the function total.
        return False
    if evidence.mode is ComparisonMode.PRINTED_PRECISION:
        # Round the stored value to the precision the manuscript printed. A paper reporting
        # 3.2 is not contradicted by a file holding 3.20001; a paper reporting 3.20000 is.
        # `quantize` raises whenever the *result* needs more digits than the context carries,
        # which is not only the case where the two values differ wildly: two identical
        # thirty-digit integers also exceed the default precision of 28, and were reported as
        # a mismatch. That is a defect in the arithmetic emitted as a contradicted manuscript,
        # which is the one thing this package must never do. Size the context to the operands.
        with decimal.localcontext() as context:
            context.prec = max(
                context.prec,
                len(stored.as_tuple().digits) + abs(int(reported.as_tuple().exponent)) + 2,
            )
            try:
                return stored.quantize(reported, rounding=decimal.ROUND_HALF_EVEN) == reported
            except decimal.InvalidOperation:
                # Genuinely beyond reach: the two differ by more orders of magnitude than any
                # precision reconciles. They disagree, and saying so is the answer.
                return False
    delta = abs(stored - reported)
    if evidence.mode is ComparisonMode.ABSOLUTE:
        return delta <= evidence.tolerance_value
    return delta <= evidence.tolerance_value * abs(reported)


class ValueBackend:
    """Assertion: this artifact holds this value at this locator.

    One implementation for every numeric kind. `metric` and `table` are shorthands that
    expose a locator, so the addressing rules and the invariant -- exactly one scalar -- do
    not depend on which spelling a manifest used.
    """

    kind = "value"
    version = "2"

    def check(self, claim: Claim, evidence: Evidence, path: pathlib.Path) -> Decision:
        if not isinstance(evidence, (MetricEvidence, TableCellEvidence, ValueEvidence)):
            raise TypeError(f"{type(self).__name__} received {type(evidence).__name__}")
        base = _base(claim, evidence, self)
        completed = {"execution": ExecutionStatus.COMPLETED}
        no_compare = {"comparison": ComparisonStatus.NOT_APPLICABLE}

        if isinstance(evidence, TableCellEvidence) and not evidence.addresses_one_row:
            # Both or neither given. A manifest that does not say which row it means is
            # malformed rather than a table that disagrees.
            return Decision(
                **base,
                **completed,
                **no_compare,
                extraction=ExtractionStatus.INVALID,
                reason=Reason.ROW_SELECTOR_INVALID,
                detail="give exactly one of `row` or `where`",
            )

        locator = evidence.locator
        base["locator_digest"] = locator.digest.value
        warnings = (Warning_.POSITIONAL_ADDRESS,) if locator.kind == "table_position" else ()

        resolution, extracted, detail = resolve(locator, path)

        if resolution is Resolution.FORMAT_UNSUPPORTED:
            # The check did not run. Reporting it as a missing value would say something
            # about the artifact that was never looked into.
            return Decision(
                **base,
                execution=ExecutionStatus.UNAVAILABLE,
                extraction=ExtractionStatus.NOT_ATTEMPTED,
                **no_compare,
                reason=Reason.FORMAT_UNSUPPORTED,
                detail=detail,
                warnings=warnings,
            )

        if resolution is not Resolution.RESOLVED or extracted is None:
            extraction, reason = _RESOLUTION_STATE[resolution]
            return Decision(
                **base,
                **completed,
                **no_compare,
                extraction=extraction,
                reason=reason or _ABSENT_REASON[locator.kind],
                detail=detail,
                warnings=warnings,
            )

        try:
            stored = decimal.Decimal(extracted.raw)
        except (decimal.InvalidOperation, ValueError):
            return Decision(
                **base,
                **completed,
                **no_compare,
                extraction=ExtractionStatus.INVALID,
                reason=Reason.VALUE_NOT_NUMERIC,
                detail=f"{' '.join(extracted.trace)} holds {extracted.raw!r}",
                warnings=warnings,
            )
        if not stored.is_finite():
            # `json.loads` accepts NaN, Infinity and -Infinity by default, so a result file
            # can carry one. It is not a quantity a printed value can agree with.
            return Decision(
                **base,
                **completed,
                **no_compare,
                extraction=ExtractionStatus.INVALID,
                reason=Reason.VALUE_NOT_NUMERIC,
                detail=f"{' '.join(extracted.trace)} holds {stored}",
                warnings=warnings,
            )

        agrees = compare_decimal(stored, evidence)
        where = " ".join(extracted.trace) or locator.kind
        return Decision(
            **base,
            **completed,
            extraction=ExtractionStatus.EXTRACTED,
            comparison=ComparisonStatus.MATCH if agrees else ComparisonStatus.MISMATCH,
            reason=Reason.VALUE_MATCH if agrees else Reason.VALUE_MISMATCH,
            detail=(
                f"{where} = {stored}"
                if agrees
                else f"{evidence.name}: manuscript prints {evidence.reported}, "
                f"{path.name} holds {stored} at {where}"
            ),
            warnings=warnings,
        )


class MetricBackend(ValueBackend):
    """`kind: metric` -- a JSON Pointer into a structured file."""

    kind = "metric"


class TableBackend(ValueBackend):
    """`kind: table` -- a column plus a row selector in a delimited file."""

    kind = "table"


DEFAULT_BACKENDS: tuple[Backend, ...] = (
    QuoteBackend(),
    MetricBackend(),
    TableBackend(),
    ValueBackend(),
)


# ------------------------------------------------------------------------------------ engine


def _artifact_state(artifact: ArtifactRef, path: pathlib.Path) -> ArtifactState:
    if not path.exists():
        # Not authoritative, whether or not it was pinned: there are no bytes to be the
        # declared ones. Calling it authoritative made every decision against it claim to
        # describe a file that was never read.
        return ArtifactState(
            artifact_id=artifact.id,
            validity=Validity.ARTIFACT_ABSENT,
            exists=False,
            expected=artifact.digest.value if artifact.digest else None,
        )
    # A path that exists but cannot be hashed -- a directory, a mode-000 file, a dangling
    # symlink -- is a fact about that artifact. Raising suppressed the report for every other
    # claim in the manifest because of one bad path.
    try:
        actual = Digest.of_file(path).value
    except OSError as e:
        return ArtifactState(
            artifact_id=artifact.id,
            validity=Validity.ARTIFACT_ABSENT,
            expected=artifact.digest.value if artifact.digest else None,
            exists=False,
            detail=f"cannot be read: {e.strerror or e}",
        )
    if not artifact.is_pinned or artifact.digest is None:
        return ArtifactState(
            artifact_id=artifact.id,
            validity=Validity.UNPINNED_ARTIFACT,
            actual=actual,
        )
    if actual != artifact.digest.value:
        return ArtifactState(
            artifact_id=artifact.id,
            validity=Validity.BROKEN_PIN,
            expected=artifact.digest.value,
            actual=actual,
        )
    return ArtifactState(
        artifact_id=artifact.id,
        validity=Validity.AUTHORITATIVE,
        expected=artifact.digest.value,
        actual=actual,
    )


def _ordering(
    claim: Claim, manifest: Manifest, states: dict[str, ArtifactState]
) -> tuple[Ordering, OrderingReason, str, RegistrationAuthority | None]:
    """Did the runs producing this claim's evidence start after its plan was registered?

    Returns an outcome, the reason it was reached, a human-readable detail, and the weakest
    registration authority among the runs that applied. Every condition that stops the check
    yields `unchecked` with its own reason rather than a verdict: an absent record is not
    evidence that a result predates its plan, and reporting it as one would manufacture a
    finding out of a gap.
    """
    if not claim.confirmatory:
        return Ordering.NOT_APPLICABLE, OrderingReason.NOT_CONFIRMATORY, "", None

    produced = {e.artifact for e in claim.evidence}
    runs = [r for r in manifest.runs if produced & {o.artifact for o in r.outputs}]
    if not runs:
        return (
            Ordering.UNCHECKED,
            OrderingReason.NO_RUN_RECORD,
            f"no run record produces {', '.join(sorted(produced))}",
            None,
        )

    authority = min((r.registration_authority for r in runs), key=lambda a: a.rank)

    def unchecked(reason: OrderingReason, detail: str):
        return Ordering.UNCHECKED, reason, detail, authority

    # More than one run claiming the same artifact with different registrations does not say
    # which one produced the bytes being checked.
    for artifact_id in sorted(produced):
        claimants = [r for r in runs if r.output(artifact_id) is not None]
        if len({(r.registered_plan, r.registered_at) for r in claimants}) > 1:
            return unchecked(
                OrderingReason.AMBIGUOUS_PRODUCING_RUN,
                f"{len(claimants)} runs claim to produce {artifact_id}",
            )

    without_plan = sorted({r.id for r in runs if not r.registered_plan})
    if without_plan:
        return unchecked(
            OrderingReason.NO_REGISTERED_PLAN,
            f"run {', '.join(without_plan)} names no registered plan",
        )

    undated = sorted({r.id for r in runs if r.registered_at is None or r.started_at is None})
    if undated:
        return unchecked(
            OrderingReason.TIMESTAMP_MISSING,
            f"run {', '.join(undated)} records no registration or start time",
        )

    # The plan document, where it is a declared artifact, must be the one that was pinned.
    for run in runs:
        state = states.get(run.registered_plan)
        if state is None:
            continue
        if state.validity is Validity.BROKEN_PIN:
            return unchecked(
                OrderingReason.REGISTERED_PLAN_CHANGED,
                f"plan {run.registered_plan} is not the document that was "
                f"pinned, so its timestamp attests to nothing",
            )
        if False:
            pass

    # Each output must be bound to the bytes actually read, not merely to a path.
    for run in runs:
        for artifact_id in sorted(produced & {o.artifact for o in run.outputs}):
            output = run.output(artifact_id)
            if output is None or output.digest is None:
                return unchecked(
                    OrderingReason.RUN_OUTPUT_UNLINKED,
                    f"run {run.id} names {artifact_id} but records no digest "
                    f"for it, so any later file at that path would qualify",
                )
            actual = states[artifact_id].actual if artifact_id in states else None
            if actual is not None and actual != output.digest.value:
                return unchecked(
                    OrderingReason.RUN_OUTPUT_CHANGED,
                    f"{artifact_id} holds {actual[:12]}, but run {run.id} "
                    f"produced {output.digest.value[:12]}",
                )

    # Every run is dated by this point -- the guard above returned otherwise -- but binding
    # the timestamps is what makes that legible, to a reader and to a type checker.
    dated = [
        (r, r.registered_at, r.started_at)
        for r in runs
        if r.registered_at is not None and r.started_at is not None
    ]
    inverted = [
        (r, registered, started) for r, registered, started in dated if started < registered
    ]
    if inverted:
        run, registered_at, started_at = inverted[0]
        return (
            Ordering.VIOLATED,
            OrderingReason.RUN_PRECEDES_REGISTRATION,
            f"run {run.id} started {started_at.isoformat()}, before "
            f"{run.registered_plan} was registered {registered_at.isoformat()}",
            authority,
        )

    pinned = sum(1 for r in runs if r.registered_plan in states)
    detail = (
        f"{len(runs)} run(s) started after registration"
        + (f", {pinned} against a pinned plan" if pinned else "")
        + f"; authority {authority.value}"
    )
    return Ordering.ORDERED, OrderingReason.RUN_FOLLOWS_REGISTRATION, detail, authority


def verify(
    manifest: Manifest, backends: tuple[Backend, ...] = DEFAULT_BACKENDS, regenerate: bool = False
) -> VerificationReport:
    """Check every evidence assertion in a manifest and report what was found.

    Returns facts. No verdict: see `repro.policy` for whether a given set of facts is
    acceptable, which depends on what the project is for.

    `regenerate` runs any declared regeneration commands in a sandbox. Off by default,
    because verifying a manifest should never execute what the manifest names.
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
            for evidence in claim.evidence
        )
        ordering, ordering_reason, ordering_detail, authority = _ordering(claim, manifest, states)
        assessments.append(
            ClaimAssessment(
                claim_id=claim.id,
                claim_digest=claim.digest.value,
                confirmatory=claim.confirmatory,
                registration=claim.registration,
                registration_note=claim.registration_note,
                availability=claim.availability,
                ordering=ordering,
                ordering_reason=ordering_reason,
                ordering_detail=ordering_detail,
                registration_authority=authority,
                decisions=decisions,
            )
        )

    return VerificationReport(
        project=manifest.project,
        manifest_digest=Digest.of_text(manifest.model_dump_json()).value,
        artifacts=tuple(states.values()),
        claims=tuple(assessments),
        regenerations=check_all(manifest, states, regenerate),
    )


def _check(
    claim: Claim,
    evidence: Evidence,
    manifest: Manifest,
    paths: dict[str, pathlib.Path],
    states: dict[str, ArtifactState],
    registry: dict[str, Backend],
) -> Decision:
    backend = registry.get(evidence.kind)
    if backend is None:
        raise UnknownEvidenceKindError(evidence.kind, tuple(registry))

    base = {
        "claim_id": claim.id,
        "claim_digest": claim.digest.value,
        "kind": evidence.kind,
        "artifact_id": evidence.artifact,
        "backend": backend.kind,
        "backend_version": backend.version,
    }
    unchecked = {
        "execution": ExecutionStatus.UNAVAILABLE,
        "extraction": ExtractionStatus.NOT_ATTEMPTED,
        "comparison": ComparisonStatus.NOT_APPLICABLE,
    }

    artifact = manifest.artifact(evidence.artifact)
    if artifact is None:
        return Decision(
            **base,
            **unchecked,
            reason=Reason.ARTIFACT_UNDECLARED,
            detail=f"manifest declares no artifact {evidence.artifact!r}",
        )
    path = paths[artifact.id]
    state = states[artifact.id]
    if not state.exists:
        return Decision(
            **base,
            **unchecked,
            reason=Reason.ARTIFACT_MISSING,
            detail=f"{path} does not exist",
            validity=state.validity,
        )

    try:
        decision = backend.check(claim, evidence, path)
    except BackendUnavailableError as e:
        decision = Decision(**base, **unchecked, reason=Reason.EXTRACTOR_MISSING, detail=e.detail)
    except ArtifactUnreadableError as e:
        decision = Decision(**base, **unchecked, reason=Reason.ARTIFACT_UNREADABLE, detail=e.detail)
    except Exception as e:
        # A defect in a backend is a defect, not an abstention. Recording it as `unchecked`
        # would make a TypeError indistinguishable from a missing extractor, which is the
        # confusion this package exists to prevent.
        decision = Decision(
            **base,
            execution=ExecutionStatus.FAILED,
            extraction=ExtractionStatus.NOT_ATTEMPTED,
            comparison=ComparisonStatus.NOT_APPLICABLE,
            reason=Reason.BACKEND_DEFECT,
            detail=f"{type(e).__name__}: {e}",
        )

    return decision.model_copy(
        update={
            "validity": state.validity,
            "artifact_digest": state.actual,
        }
    )
