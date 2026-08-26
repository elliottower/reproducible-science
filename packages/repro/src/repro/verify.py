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
  * **Every decision names the toolchain that read the bytes**, and the digest of what that
    toolchain produced. See `repro.toolchain` for why the backend's protocol version is not
    that.
"""

from __future__ import annotations

import decimal
import pathlib
from collections.abc import Mapping
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
    CorrespondenceEvidence,
    Decision,
    DecisionSide,
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
from repro.toolchain import UNKNOWN, binary_version, distribution_version

#: The distribution that ships `repro.adapters`, which is what reads a JSON pointer, a
#: delimited cell, a SQLite row or an array element. Its name on PyPI, because that is what
#: `importlib.metadata` answers to.
ADAPTER_DISTRIBUTION = "reproducible-science"


class Backend(Protocol):
    """Evaluates one kind of evidence assertion against the artifacts it names.

    `paths` holds one entry per artifact the assertion reads, keyed by id. Every kind but
    `correspondence` reads one, and takes it with `paths[evidence.artifact]`. A mapping rather
    than a path because an assertion whose two sides are both artifacts has no single file to
    be handed, and giving it one would make the engine pick a side.
    """

    kind: str
    version: str
    """The protocol version of this interface, written by hand."""
    tool: str
    """What performs the extraction: a binary's name, or an installed distribution's."""

    @property
    def tool_version(self) -> str:
        """The version `tool` reports, or `toolchain.UNKNOWN`."""
        ...

    def check(
        self, claim: Claim, evidence: Evidence, paths: Mapping[str, pathlib.Path]
    ) -> Decision: ...


#: Weakest first. A decision over two artifacts is no more authoritative than the worse of
#: them, and taking the better one would report a comparison against a file that moved as
#: though the declared bytes had been read.
_VALIDITY_RANK = {
    Validity.ARTIFACT_ABSENT: 0,
    Validity.BROKEN_PIN: 1,
    Validity.UNPINNED_ARTIFACT: 2,
    Validity.AUTHORITATIVE: 3,
}


def _base(
    claim: Claim, evidence: Evidence, backend: Backend, extraction_digest: str = UNKNOWN
) -> dict:
    """The fields every decision carries, whichever stage it stopped at.

    `extraction_digest` defaults to `unknown` rather than to an empty string: a decision the
    engine produced was one an extraction was sought for, and the empty value is reserved for
    a decision no backend produced.
    """
    named = evidence.artifacts
    return {
        "claim_id": claim.id,
        "claim_digest": claim.digest.value,
        "kind": evidence.kind,
        # Left empty where an assertion reads two files: `artifact_id` is singular, and
        # filling it with one of them would name a side the engine does not rank. The two are
        # recorded in `sides`.
        "artifact_id": named[0] if len(named) == 1 else "",
        "backend": backend.kind,
        "backend_version": backend.version,
        "tool": backend.tool,
        "tool_version": backend.tool_version,
        "extraction_digest": extraction_digest,
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
    tool = "pdftotext"

    @property
    def tool_version(self) -> str:
        return binary_version(self.tool)

    def check(
        self, claim: Claim, evidence: Evidence, paths: Mapping[str, pathlib.Path]
    ) -> Decision:
        if not isinstance(evidence, QuoteEvidence):
            raise TypeError(f"QuoteBackend received {type(evidence).__name__}")
        try:
            # Imported here rather than at module scope so an absent `citations` reports as a
            # backend that could not run, which is what the caller can act on.
            from citations.exceptions import SourceUnreadableError
            from citations.verify import check_one, extract
        except ImportError as e:
            raise BackendUnavailableError("quote", f"citations is not installed: {e}") from e

        path = paths[evidence.artifact]
        result = check_one(evidence.text, path, evidence.page)
        warnings = tuple(_QUOTE_WARNINGS[w] for w in result.warnings if w in _QUOTE_WARNINGS)

        if result.state == "unchecked":
            # The extractor could not produce text. Distinguishing this from an absent
            # passage is the reason the three stages are separate.
            raise BackendUnavailableError("quote", result.detail or "no text extracted")

        try:
            # `extract` memoizes per file, so this is the text `check_one` has just read
            # rather than a second run of `pdftotext`. It is the whole document: a digest over
            # the matched passage alone would be silent on an extractor that changed how it
            # reads every other page.
            extraction_digest = Digest.of_text(extract(path)).value
        except SourceUnreadableError:
            extraction_digest = UNKNOWN

        base = _base(claim, evidence, self, extraction_digest)
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
    Resolution.NUMBER_AS_WORD: (ExtractionStatus.INVALID, Reason.NUMBER_AS_WORD),
    Resolution.PASSAGE_AMBIGUOUS: (ExtractionStatus.INVALID, Reason.PASSAGE_AMBIGUOUS),
}

#: Which "not there" reason fits each addressing scheme.
_ABSENT_REASON = {
    "tree": Reason.POINTER_ABSENT,
    "table": Reason.ROW_ABSENT,
    "table_position": Reason.ROW_ABSENT,
    "sqlite": Reason.ROW_ABSENT,
    "array": Reason.POINTER_ABSENT,
    "prose": Reason.PASSAGE_ABSENT,
}


def compare_decimal(
    stored: decimal.Decimal, evidence: MetricEvidence | TableCellEvidence | ValueEvidence
) -> bool:
    """Does the stored value agree with the reported one, under the declared mode?"""
    return _agree(stored, evidence.value, evidence.mode, evidence.tolerance_value)


def _exponent(value: decimal.Decimal) -> int:
    """The power of ten a finite decimal's last digit sits at.

    `Decimal.as_tuple().exponent` is `int | Literal["n", "N", "F"]`: the strings tag NaN and
    the infinities, which have no precision for a comparison to be coarser or finer than.
    Every backend refuses a non-finite value with `value_not_numeric` before comparing, so
    reaching this with one is a defect in a backend rather than a fact about an artifact, and
    §5 says a defect is an `error` and never a scientific outcome. Raising is how it becomes
    one. Returning a number instead would compare two values at a precision nothing chose.
    """
    exponent = value.as_tuple().exponent
    if not isinstance(exponent, int):
        raise ValueError(
            f"{value} has no exponent: a non-finite value is refused before any comparison, "
            f"so reaching the comparison with one is a defect"
        )
    return exponent


def _agree(
    stored: decimal.Decimal,
    reported: decimal.Decimal,
    mode: ComparisonMode,
    tolerance: decimal.Decimal,
) -> bool:
    """Do two decimals agree under one mode? The arithmetic, with no evidence attached.

    Split out because a correspondence has two extracted values and no `reported` field to
    read a mode off, and duplicating the `printed_precision` rounding rule is how two
    spellings of the same comparison come to disagree.
    """
    if not stored.is_finite():
        # NaN and the infinities parse out of JSON but cannot equal a printed decimal. The
        # backend flags them before reaching here; this keeps the function total.
        return False
    if mode is ComparisonMode.PRINTED_PRECISION:
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
    if mode is ComparisonMode.ABSOLUTE:
        return delta <= tolerance
    return delta <= tolerance * abs(reported)


class ValueBackend:
    """Assertion: this artifact holds this value at this locator.

    One implementation for every numeric kind. `metric` and `table` are shorthands that
    expose a locator, so the addressing rules and the invariant -- exactly one scalar -- do
    not depend on which spelling a manifest used.
    """

    kind = "value"
    version = "2"
    tool = ADAPTER_DISTRIBUTION

    @property
    def tool_version(self) -> str:
        return distribution_version(self.tool)

    def check(
        self, claim: Claim, evidence: Evidence, paths: Mapping[str, pathlib.Path]
    ) -> Decision:
        if not isinstance(evidence, (MetricEvidence, TableCellEvidence, ValueEvidence)):
            raise TypeError(f"{type(self).__name__} received {type(evidence).__name__}")
        path = paths[evidence.artifact]
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

        # The adapter produced a value, so there is an extraction to hash. Recorded before the
        # comparison, and for a value that turns out not to be numeric: what the extractor
        # read is a fact about the extractor whatever the comparison then makes of it.
        base["extraction_digest"] = Digest.of_text(extracted.raw).value

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


# --------------------------------------------------------------------------- correspondences


class CorrespondenceBackend:
    """Assertion: two artifacts hold the same value.

    Two extractions precede one comparison, and the stages report that faithfully. A side that
    does not extract makes the comparison impossible rather than false: a document that never
    states the number does not contradict the file holding it, and reporting that as a
    disagreement would manufacture a finding out of a gap. The decision carries the failing
    side's own reason, so `pointer_absent` and `number_as_word` stay distinguishable.

    When both sides extract and disagree, the decision reports both values and names neither
    as wrong. Which of a specification and a test suite is in error is not something a byte
    comparison establishes.
    """

    kind = "correspondence"
    version = "1"
    #: The format adapters are this distribution, as they are for `ValueBackend`. The
    #: declaration is an approximation for one case: a `prose` side over a paginated source
    #: reaches `citations.verify.extract`, which runs the same `pdftotext` that `QuoteBackend`
    #: declares, and `Decision.tool` is one field where such an assertion has two extractors.
    #: `DecisionSide.extraction_digest` is what catches a change in either of them, since it
    #: moves whenever what a side read moves, whatever did the reading. Naming the tool per
    #: side needs the adapters to report which one they used, which this revision does not
    #: define.
    tool = ADAPTER_DISTRIBUTION

    @property
    def tool_version(self) -> str:
        return distribution_version(self.tool)

    def check(
        self, claim: Claim, evidence: Evidence, paths: Mapping[str, pathlib.Path]
    ) -> Decision:
        if not isinstance(evidence, CorrespondenceEvidence):
            raise TypeError(f"CorrespondenceBackend received {type(evidence).__name__}")
        base = _base(claim, evidence, self)
        no_compare = {"comparison": ComparisonStatus.NOT_APPLICABLE}

        readings = [(side, *resolve(side.locator, paths[side.artifact])) for side in evidence.sides]
        base["sides"] = tuple(
            DecisionSide(
                name=side.name,
                artifact_id=side.artifact,
                locator_digest=side.locator.digest.value,
                extracted=extracted.raw if extracted is not None else None,
                # Hashed per side before any comparison, and for a value that turns out not
                # to be numeric: what an extractor read is a fact about the extractor whatever
                # the comparison then makes of it.
                extraction_digest=(
                    Digest.of_text(extracted.raw).value if extracted is not None else UNKNOWN
                ),
            )
            for side, _, extracted, _ in readings
        )
        # The decision-level field covers both extractions, in the order the manifest declares
        # the sides, so it moves whenever either side's extraction moves. Which of the two
        # moved is on the sides; leaving this `unknown` would say the extraction was sought
        # and not obtained, and it was sought twice.
        base["extraction_digest"] = Digest.of_text(
            "\x00".join(s.extraction_digest for s in base["sides"])
        ).value

        unsupported = [(s, d) for s, r, _, d in readings if r is Resolution.FORMAT_UNSUPPORTED]
        if unsupported:
            side, detail = unsupported[0]
            return Decision(
                **base,
                execution=ExecutionStatus.UNAVAILABLE,
                extraction=ExtractionStatus.NOT_ATTEMPTED,
                **no_compare,
                reason=Reason.FORMAT_UNSUPPORTED,
                detail=f"{side.name}: {detail}",
            )

        completed = {"execution": ExecutionStatus.COMPLETED}
        unresolved = [
            (s, r, d) for s, r, e, d in readings if r is not Resolution.RESOLVED or e is None
        ]
        if unresolved:
            # Reported in the order the manifest declares the sides, which is a fact about the
            # manifest and not a ranking. Every failing side appears in the detail.
            side, resolution, _ = unresolved[0]
            extraction, reason = _RESOLUTION_STATE[resolution]
            return Decision(
                **base,
                **completed,
                **no_compare,
                extraction=extraction,
                reason=reason or _ABSENT_REASON[side.locator.kind],
                detail="; ".join(f"{s.name} ({s.artifact}): {d}" for s, _, d in unresolved),
            )

        numbers: list[decimal.Decimal] = []
        for side, _, extracted, _ in readings:
            raw = extracted.raw if extracted is not None else ""
            try:
                number = decimal.Decimal(raw)
            except (decimal.InvalidOperation, ValueError):
                number = decimal.Decimal("NaN")
            if not number.is_finite():
                return Decision(
                    **base,
                    **completed,
                    **no_compare,
                    extraction=ExtractionStatus.INVALID,
                    reason=Reason.VALUE_NOT_NUMERIC,
                    detail=f"{side.name} ({side.artifact}) holds {raw!r}",
                )
            numbers.append(number)

        left, right = evidence.sides
        a, b = numbers
        # `printed_precision` compares at the coarser of the two precisions, so a document
        # printing 0.65 agrees with a file holding 0.6478 and the answer does not depend on
        # which side the manifest wrote first. A larger exponent is the coarser value.
        coarse, fine = (a, b) if _exponent(a) >= _exponent(b) else (b, a)
        agrees = _agree(fine, coarse, evidence.mode, evidence.tolerance_value)
        return Decision(
            **base,
            **completed,
            extraction=ExtractionStatus.EXTRACTED,
            comparison=ComparisonStatus.MATCH if agrees else ComparisonStatus.MISMATCH,
            reason=Reason.VALUE_MATCH if agrees else Reason.VALUE_MISMATCH,
            detail=f"{evidence.name}: {left.name} {a}, {right.name} {b}",
            warnings=(
                (Warning_.POSITIONAL_ADDRESS,)
                if any(side.locator.kind == "table_position" for side in evidence.sides)
                else ()
            ),
        )


DEFAULT_BACKENDS: tuple[Backend, ...] = (
    QuoteBackend(),
    MetricBackend(),
    TableBackend(),
    ValueBackend(),
    CorrespondenceBackend(),
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

    produced = {a for e in claim.evidence for a in e.artifacts}
    runs = [r for r in manifest.runs if produced & {o.artifact for o in r.outputs}]
    covered = {o.artifact for r in runs for o in r.outputs}
    uncovered = sorted(produced - covered)
    if uncovered:
        # A claim can cite several artifacts. Taking the runs that produce *any* of them meant
        # adding a run record for one incidental artifact turned an unregistered result into
        # an ordered one, while the artifact carrying the number had no run at all.
        return (
            Ordering.UNCHECKED,
            OrderingReason.NO_RUN_RECORD,
            f"no run record produces {', '.join(uncovered)}",
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
            # Undeclared, so nothing pins it: the document backing an `ordered` verdict could
            # have been written after the results. Declaring the plan and leaving it unpinned
            # reported `unchecked`, so the more transparent manifest scored strictly worse.
            return unchecked(
                OrderingReason.REGISTERED_PLAN_UNPINNED,
                f"plan {run.registered_plan} is not a declared artifact, so nothing pins the "
                f"document the ordering rests on",
            )
        if state.validity is Validity.BROKEN_PIN:
            return unchecked(
                OrderingReason.REGISTERED_PLAN_CHANGED,
                f"plan {run.registered_plan} is not the document that was "
                f"pinned, so its timestamp attests to nothing",
            )
        if state.validity is not Validity.AUTHORITATIVE:
            return unchecked(
                OrderingReason.REGISTERED_PLAN_UNPINNED,
                f"plan {run.registered_plan} is declared but {state.validity.value}",
            )

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

    base = _base(claim, evidence, backend)
    unchecked = {
        "execution": ExecutionStatus.UNAVAILABLE,
        "extraction": ExtractionStatus.NOT_ATTEMPTED,
        "comparison": ComparisonStatus.NOT_APPLICABLE,
    }

    # Every artifact the assertion names, not only the first. An assertion reading two files
    # is unchecked if either is undeclared or absent, and no more authoritative than the worse
    # of the two pins.
    named = evidence.artifacts
    undeclared = [a for a in named if manifest.artifact(a) is None]
    if undeclared:
        return Decision(
            **base,
            **unchecked,
            reason=Reason.ARTIFACT_UNDECLARED,
            detail=f"manifest declares no artifact {', '.join(repr(a) for a in undeclared)}",
        )
    missing = [a for a in named if not states[a].exists]
    if missing:
        return Decision(
            **base,
            **unchecked,
            reason=Reason.ARTIFACT_MISSING,
            detail="; ".join(f"{paths[a]} does not exist" for a in missing),
            validity=min((states[a].validity for a in missing), key=_VALIDITY_RANK.__getitem__),
        )

    try:
        decision = backend.check(claim, evidence, {a: paths[a] for a in named})
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

    validity = min((states[a].validity for a in named), key=_VALIDITY_RANK.__getitem__)
    return decision.model_copy(
        update={
            "validity": validity,
            "artifact_digest": states[named[0]].actual if len(named) == 1 else None,
            # The backend knows which locator addressed which side; only the engine knows what
            # was at each path. Filling the digests here keeps both in one record.
            "sides": tuple(
                side.model_copy(
                    update={
                        "artifact_digest": states[side.artifact_id].actual,
                        "validity": states[side.artifact_id].validity,
                    }
                )
                for side in decision.sides
            ),
        }
    )
