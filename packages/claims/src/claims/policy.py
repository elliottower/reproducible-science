"""Whether a set of facts is acceptable.

The engine reports what happened. Whether that constitutes a pass depends on what the project
is for: an unchecked citation in a working draft is unremarkable, and an unchecked
confirmatory result in a submission is not. Folding that judgment into the engine would make
one project's standard everyone's.

A policy maps each outcome to a severity and returns the violations, so the same report can be
assessed under several standards without being recomputed.
"""

from __future__ import annotations

import enum
from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict, Field

from claims.models import (
    Availability,
    Freshness,
    NumbersReport,
    Ordering,
    Outcome,
    Regeneration,
    RegistrationAuthority,
    ReproductionReport,
    StalenessReport,
    Standing,
    Validity,
    VerificationReport,
    Warning_,
)

#: What each note `claims.reported` puts on a decision says, by warning.
REPORTED_SAID = {
    Warning_.REPORTED_NOT_IN_CLAIM: "the claim's text prints numbers and none agrees with "
    "`reported`",
    Warning_.REPORTED_NOT_IN_MANUSCRIPT: "the passages the claim quotes print numbers and none "
    "agrees with `reported`",
    Warning_.COARSE_PRECISION: "`reported` has under two significant digits, so printed "
    "precision accepts a wide range of stored values",
    Warning_.ROUNDING_CROSSES_THRESHOLD: "the stored value and `reported` lie on opposite "
    "sides of 0.05",
    Warning_.LOOSE_TOLERANCE: "the tolerance is more than a tenth of the reported value",
}


class Severity(enum.StrEnum):
    ERROR = "error"
    WARNING = "warning"
    IGNORE = "ignore"


class Violation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    severity: Severity
    rule: str
    subject: str
    detail: str


class Assessment(BaseModel):
    """A policy's verdict on one report."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    policy: str
    passed: bool
    violations: tuple[Violation, ...] = ()

    @property
    def errors(self) -> tuple[Violation, ...]:
        return tuple(v for v in self.violations if v.severity is Severity.ERROR)

    @property
    def warnings(self) -> tuple[Violation, ...]:
        return tuple(v for v in self.violations if v.severity is Severity.WARNING)


class Policy(BaseModel):
    """A named standard: which outcomes are errors, which are warnings, which are ignored."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str

    outcomes: dict[Outcome, Severity] = Field(default_factory=dict)
    """Severity per outcome. An outcome absent from this map is ignored."""

    confirmatory_outcomes: dict[Outcome, Severity] = Field(default_factory=dict)
    """Overrides applied to claims marked confirmatory, where the same outcome may be graver.
    An unchecked exploratory citation and an unchecked preregistered result are not the same
    event."""

    broken_pin: Severity = Severity.ERROR
    unpinned_artifact: Severity = Severity.WARNING
    artifact_alias: Severity = Severity.WARNING
    """Two artifact ids whose paths resolve to one file. An assertion comparing the two
    compares the file with itself, so it agrees whatever the file holds."""
    artifact_same_bytes: Severity = Severity.WARNING
    """Two files at different paths holding the same bytes. A warning under every profile:
    identical outputs can be legitimate, two seeds that converged, and a correspondence that
    reads one place through both is `sides_read_one_place` whatever this says."""
    artifact_absent: Severity = Severity.ERROR
    """Nothing at the declared path. Without this the assertions against it are merely
    unchecked, which the publication profile tolerates, so a manifest naming a result file
    that was never produced would pass."""

    ordering_violated: Severity = Severity.ERROR
    """A confirmatory result whose run started before its plan was registered."""
    ordering_unchecked: Severity = Severity.WARNING
    """A confirmatory claim whose ordering could not be established. Not a finding that the
    ordering is wrong, which is why it is separable from `ordering_violated`."""

    minimum_registration_authority: RegistrationAuthority | None = None
    """The weakest attestation a confirmatory claim may rest on. A self-recorded timestamp
    establishes internal consistency, not chronology, so a project that needs chronology
    requires better. None accepts any."""
    weak_registration_authority: Severity = Severity.WARNING

    regeneration_changed: Severity = Severity.ERROR
    """A re-run after which a number the manuscript prints is different."""
    regeneration_failed: Severity = Severity.ERROR
    """A declared command that did not finish, or finished and wrote nothing."""
    regeneration_unchecked: Severity = Severity.WARNING
    """A re-run whose output a number could not be read from. Not a finding that the number
    changed, which is why it is separable from `regeneration_changed`."""
    regeneration_not_rerun: Severity = Severity.IGNORE
    """A record that was skipped or refused. Leaving out a week of training is an ordinary
    choice; a project that requires every record to run raises this."""

    stale: Severity = Severity.WARNING
    """A regeneration whose recorded re-runs no longer match the files on disk, here or
    upstream. A warning by default: the number may be unchanged, and only a re-run says."""
    never_rerun: Severity = Severity.WARNING
    """A regeneration the record holds no reproduced re-run of."""
    staleness_undetermined: Severity = Severity.WARNING
    """A regeneration that could not be compared: a file is missing, or the records form a
    cycle."""
    rerun_record_broken: Severity = Severity.ERROR
    """The record of re-runs does not verify as a chain: an entry edited, removed, moved or
    unreadable, or entries cut from the end. Every `current` rests on that record, so one
    rewritten by hand can make any file current."""
    rerun_record_unanchored: Severity = Severity.WARNING
    """The chain verifies and its head file is missing or behind it, so entries cut from the
    end would not be found."""
    rerun_record_unchained: Severity = Severity.IGNORE
    """Entries written before the record was chained, which nothing links but their order."""

    inferred: Severity = Severity.ERROR
    """An assertion the manifest marks `basis: inferred`: proposed by a program or a model and
    not accepted by an author. Graded whatever its outcome, so a draft binding that happens to
    match never passes as a verified one."""

    reported_mismatch: Severity = Severity.WARNING
    """A `reported` value the claim's own text does not print, where the text prints numbers:
    the number checked against the file is not the number the claim states. A warning by default
    and an error under `strict`."""

    reported_consistency: Severity = Severity.WARNING
    """The other notes `claims.reported` makes: a `reported` value the passages the claim quotes
    do not print, one printed to under two significant digits or rounded across 0.05, or a
    tolerance above a tenth of the value. Each says the comparison is wider or less direct than
    it looks, and none that it is wrong: a passage prints other numbers than the one checked, or
    a count as a word, and `0.03` is the right print of a stored `0.0314`. A warning under every
    policy."""

    unbound_numbers: Severity = Severity.WARNING
    """Numbers the manuscript prints that no assertion accounts for, as `repro numbers`
    counts them. A warning wherever there are any; `--max-unbound N` makes more than N an
    error under any policy. Graded by `assess_numbers`, never by `assess`."""
    quotation_corrected: Severity = Severity.WARNING
    """A quotation `citations verify` reports `corrected`: found in a passage a person recorded
    where the extractor misreads the page, and not in the extractor's text. A warning by
    default: the record is the author's, and it is never a match."""

    require_one_check: bool = True
    """A run that evaluated nothing is not a pass. Without this a project with no evidence
    anywhere satisfies every other condition trivially."""

    def assess(self, report: VerificationReport) -> Assessment:
        violations: list[Violation] = []

        for artifact in report.artifacts:
            if artifact.validity is Validity.ARTIFACT_ABSENT:
                violations.append(
                    Violation(
                        severity=self.artifact_absent,
                        rule="artifact.absent",
                        subject=artifact.artifact_id,
                        detail="nothing at the declared path",
                    )
                )
            elif artifact.validity is Validity.BROKEN_PIN:
                violations.append(
                    Violation(
                        severity=self.broken_pin,
                        rule="artifact.pin",
                        subject=artifact.artifact_id,
                        detail=f"pinned {(artifact.expected or '')[:12]}, "
                        f"found {(artifact.actual or '')[:12]}",
                    )
                )
            elif artifact.validity is Validity.UNPINNED_ARTIFACT:
                violations.append(
                    Violation(
                        severity=self.unpinned_artifact,
                        rule="artifact.unpinned",
                        subject=artifact.artifact_id,
                        detail="no digest recorded",
                    )
                )

        # One violation per pair, named from the artifact declared first.
        for at, artifact in enumerate(report.artifacts):
            later = {other.artifact_id for other in report.artifacts[at + 1 :]}
            for other in artifact.same_path_as:
                if other in later:
                    violations.append(
                        Violation(
                            severity=self.artifact_alias,
                            rule="artifact.alias",
                            subject=artifact.artifact_id,
                            detail=f"{artifact.artifact_id} and {other} name the same file, so "
                            f"an assertion comparing them compares the file with itself",
                        )
                    )
            for other in artifact.same_digest_as:
                if other in later:
                    violations.append(
                        Violation(
                            severity=self.artifact_same_bytes,
                            rule="artifact.same_bytes",
                            subject=artifact.artifact_id,
                            detail=f"{artifact.artifact_id} and {other} hold the same bytes "
                            f"({(artifact.actual or '')[:12]}), so an assertion comparing them "
                            f"compares one content with itself",
                        )
                    )

        checked = 0
        for claim in report.claims:
            table = self.confirmatory_outcomes if claim.confirmatory else self.outcomes
            if claim.availability is Availability.NOT_OFFERED:
                severity = table.get(
                    Outcome.NOT_OFFERED, self.outcomes.get(Outcome.NOT_OFFERED, Severity.IGNORE)
                )
                if severity is not Severity.IGNORE:
                    violations.append(
                        Violation(
                            severity=severity,
                            rule="claim.no_evidence",
                            subject=claim.claim_id,
                            detail="claim offers no evidence",
                        )
                    )
                continue
            if claim.ordering is Ordering.VIOLATED:
                violations.append(
                    Violation(
                        severity=self.ordering_violated,
                        rule="claim.ordering_violated",
                        subject=claim.claim_id,
                        detail=claim.ordering_detail,
                    )
                )
            elif claim.ordering is Ordering.UNCHECKED:
                violations.append(
                    Violation(
                        severity=self.ordering_unchecked,
                        rule=f"claim.ordering_unchecked.{claim.ordering_reason.value}",
                        subject=claim.claim_id,
                        detail=claim.ordering_detail,
                    )
                )
            elif (
                self.minimum_registration_authority is not None
                and claim.registration_authority is not None
                and claim.registration_authority.rank < self.minimum_registration_authority.rank
            ):
                violations.append(
                    Violation(
                        severity=self.weak_registration_authority,
                        rule="claim.registration_authority",
                        subject=claim.claim_id,
                        detail=f"registration is {claim.registration_authority.value}; "
                        f"{self.minimum_registration_authority.value} or better required",
                    )
                )

            for decision in claim.decisions:
                checked += 1
                severity = table.get(
                    decision.outcome, self.outcomes.get(decision.outcome, Severity.IGNORE)
                )
                if severity is not Severity.IGNORE:
                    violations.append(
                        Violation(
                            severity=severity,
                            rule=f"evidence.{decision.outcome.value}",
                            subject=f"{claim.claim_id}/{decision.kind}",
                            detail=decision.detail or decision.reason.value,
                        )
                    )
                if decision.inferred and self.inferred is not Severity.IGNORE:
                    violations.append(
                        Violation(
                            severity=self.inferred,
                            rule="evidence.inferred",
                            subject=f"{claim.claim_id}/{decision.kind}",
                            detail=f"inferred, not declared, and {decision.said}: no author has "
                            "accepted the address, so nothing is counted for it",
                        )
                    )
                # The one decision warning a policy reads. The others qualify a check that
                # ran; this one says a declared check did not, so it is graded as an unchecked
                # assertion is, on a decision whose passage is `verified`.
                unchecked = table.get(
                    Outcome.UNCHECKED, self.outcomes.get(Outcome.UNCHECKED, Severity.IGNORE)
                )
                if Warning_.PAGE_UNCHECKED in decision.warnings and (
                    unchecked is not Severity.IGNORE
                ):
                    violations.append(
                        Violation(
                            severity=unchecked,
                            rule="evidence.page_unchecked",
                            subject=f"{claim.claim_id}/{decision.kind}",
                            detail=decision.detail or "the declared page was not checked",
                        )
                    )
                if (
                    self.reported_consistency is not Severity.IGNORE
                    and Warning_.REPORTED_UNCOMPARED in decision.warnings
                ):
                    violations.append(
                        Violation(
                            severity=Severity.WARNING,
                            rule=f"evidence.{Warning_.REPORTED_UNCOMPARED.value}",
                            subject=f"{claim.claim_id}/{decision.kind}",
                            detail="`reported` is checked against nothing the claim or its "
                            "manuscript prints",
                        )
                    )
                for warning in decision.warnings:
                    if warning not in REPORTED_SAID:
                        continue
                    graded = (
                        self.reported_mismatch
                        if warning is Warning_.REPORTED_NOT_IN_CLAIM
                        else self.reported_consistency
                    )
                    if graded is not Severity.IGNORE:
                        violations.append(
                            Violation(
                                severity=graded,
                                rule=f"evidence.{warning.value}",
                                subject=f"{claim.claim_id}/{decision.kind}",
                                detail=REPORTED_SAID[warning],
                            )
                        )

        if self.require_one_check and checked == 0:
            violations.append(
                Violation(
                    severity=Severity.ERROR,
                    rule="report.empty",
                    subject=report.project,
                    detail="no evidence assertion was evaluated",
                )
            )

        return Assessment(
            policy=self.name,
            violations=tuple(violations),
            passed=not any(v.severity is Severity.ERROR for v in violations),
        )

    def assess_numbers(self, report: NumbersReport, limit: int | None = None) -> Assessment:
        """Whether the manuscript's unbound numbers are acceptable: a warning where there are
        any, and an error where there are more than `limit`. With no limit, never an error:
        how many numbers a manuscript may leave unbound is the author's to say."""
        unbound = report.counts[Standing.UNBOUND]
        if not unbound:
            return Assessment(policy=self.name, passed=True)
        severity = Severity.ERROR if limit is not None and unbound > limit else self.unbound_numbers
        if severity is Severity.IGNORE:
            return Assessment(policy=self.name, passed=True)
        bound = f"; at most {limit} allowed" if limit is not None else ""
        violation = Violation(
            severity=severity,
            rule="numbers.unbound",
            subject=report.project,
            detail=f"{unbound} printed number(s) no assertion accounts for{bound}",
        )
        return Assessment(
            policy=self.name,
            violations=(violation,),
            passed=severity is not Severity.ERROR,
        )

    def assess_citations(self, counts: Mapping[str, int]) -> Assessment:
        """Whether what `citations verify` counted is acceptable beyond its own exit code: the
        quotations it reports `corrected`, graded as `quotation_corrected` says."""
        n = counts.get("corrected", 0)
        violations = (
            ()
            if not n or self.quotation_corrected is Severity.IGNORE
            else (
                Violation(
                    severity=self.quotation_corrected,
                    rule="citations.corrected",
                    subject="citations",
                    detail=f"{n} quotation{'' if n == 1 else 's'} found in a passage recorded "
                    f"by hand, not in the extractor's text",
                ),
            )
        )
        return Assessment(
            policy=self.name,
            violations=violations,
            passed=not any(v.severity is Severity.ERROR for v in violations),
        )

    def assess_reproduction(self, report: ReproductionReport) -> Assessment:
        """Whether a set of re-runs is acceptable. The counterpart of `assess` for
        `repro.reproduce`: the same severities, over the five outcomes a re-run can have."""
        severities = {
            Regeneration.CHANGED: self.regeneration_changed,
            Regeneration.FAILED: self.regeneration_failed,
            Regeneration.UNCHECKED: self.regeneration_unchecked,
            Regeneration.NOT_RERUN: self.regeneration_not_rerun,
        }
        violations = tuple(
            Violation(
                severity=severities[state.state],
                rule=f"reproduction.{state.state.value}.{state.reason.value}",
                subject=state.regeneration_id,
                detail=state.detail or state.reason.value,
            )
            for state in report.regenerations
            if state.state is not Regeneration.REPRODUCED
        )
        return Assessment(
            policy=self.name,
            violations=violations,
            passed=not any(v.severity is Severity.ERROR for v in violations),
        )

    def assess_staleness(self, report: StalenessReport) -> Assessment:
        """Whether what `claims.stale` found is acceptable. One violation per regeneration
        that is not current; a file with no producer is counted in the report and never
        graded."""
        severities = {
            Freshness.STALE: self.stale,
            Freshness.NEVER_RERUN: self.never_rerun,
            Freshness.UNDETERMINED: self.staleness_undetermined,
        }
        violations = tuple(
            Violation(
                severity=severities[node.state],
                rule=f"staleness.{node.state.value}",
                subject=node.id,
                detail=(
                    f"upstream {node.upstream}"
                    if node.upstream
                    else ", ".join(cause.value for cause in node.causes) or node.state.value
                ),
            )
            for node in report.regenerations
            if node.state in severities
        ) + self._record_violations(report)
        return Assessment(
            policy=self.name,
            violations=violations,
            passed=not any(v.severity is Severity.ERROR for v in violations),
        )

    def _record_violations(self, report: StalenessReport) -> tuple[Violation, ...]:
        """The record of re-runs itself, where it is not the chain `repro reproduce` wrote."""
        record = report.record
        if record is None:
            return ()
        if record.broken:
            severity, rule = self.rerun_record_broken, record.status
        elif record.status in ("no_anchor", "extended"):
            severity, rule = self.rerun_record_unanchored, record.status
        elif record.unchained:
            severity, rule = self.rerun_record_unchained, "unchained"
        else:
            return ()
        if severity is Severity.IGNORE:
            return ()
        detail = "; ".join(record.problems) or (
            f"{record.unchained} of {record.entries} entries predate the chain"
        )
        return (
            Violation(
                severity=severity,
                rule=f"staleness.record.{rule}",
                subject=".repro/reproductions.jsonl",
                detail=detail,
            ),
        )


EXPLORATORY = Policy(
    name="exploratory",
    outcomes={
        Outcome.MISMATCH: Severity.ERROR,
        Outcome.ERROR: Severity.ERROR,
        Outcome.NOT_FOUND: Severity.WARNING,
        Outcome.UNCHECKED: Severity.WARNING,
        Outcome.NOT_OFFERED: Severity.IGNORE,
    },
    unpinned_artifact=Severity.IGNORE,
    # A draft is what a proposal is for.
    inferred=Severity.WARNING,
    # A draft may point at a file the analysis has not written yet.
    artifact_absent=Severity.WARNING,
    ordering_unchecked=Severity.IGNORE,
    quotation_corrected=Severity.IGNORE,
    never_rerun=Severity.IGNORE,
    staleness_undetermined=Severity.IGNORE,
    rerun_record_broken=Severity.WARNING,
    rerun_record_unanchored=Severity.IGNORE,
)

PUBLICATION = Policy(
    name="publication",
    outcomes={
        Outcome.MISMATCH: Severity.ERROR,
        Outcome.ERROR: Severity.ERROR,
        Outcome.NOT_FOUND: Severity.ERROR,
        Outcome.UNCHECKED: Severity.WARNING,
        Outcome.NOT_OFFERED: Severity.WARNING,
    },
    confirmatory_outcomes={
        Outcome.MISMATCH: Severity.ERROR,
        Outcome.ERROR: Severity.ERROR,
        Outcome.NOT_FOUND: Severity.ERROR,
        Outcome.UNCHECKED: Severity.ERROR,
        Outcome.NOT_OFFERED: Severity.ERROR,
    },
    quotation_corrected=Severity.WARNING,
)

STRICT = Policy(
    name="strict",
    outcomes={o: Severity.ERROR for o in Outcome if o is not Outcome.VERIFIED},
    confirmatory_outcomes={o: Severity.ERROR for o in Outcome if o is not Outcome.VERIFIED},
    unpinned_artifact=Severity.ERROR,
    artifact_alias=Severity.ERROR,
    ordering_unchecked=Severity.ERROR,
    regeneration_unchecked=Severity.ERROR,
    regeneration_not_rerun=Severity.WARNING,
    reported_mismatch=Severity.ERROR,
    # A correction is an author's record, accepted by the author, so not an error even here.
    quotation_corrected=Severity.WARNING,
    stale=Severity.ERROR,
    never_rerun=Severity.ERROR,
    staleness_undetermined=Severity.ERROR,
    rerun_record_unanchored=Severity.ERROR,
    rerun_record_unchained=Severity.WARNING,
)

PROFILES = {p.name: p for p in (EXPLORATORY, PUBLICATION, STRICT)}

__all__ = [
    "EXPLORATORY",
    "PROFILES",
    "PUBLICATION",
    "STRICT",
    "Assessment",
    "Policy",
    "Severity",
    "Violation",
]
