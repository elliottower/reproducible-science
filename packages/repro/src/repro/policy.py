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

from pydantic import BaseModel, ConfigDict, Field

from repro.models import (
    Availability,
    Ordering,
    Outcome,
    Regeneration,
    RegistrationAuthority,
    ReproductionReport,
    Validity,
    VerificationReport,
)


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
    # A draft may point at a file the analysis has not written yet.
    artifact_absent=Severity.WARNING,
    ordering_unchecked=Severity.IGNORE,
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
)

STRICT = Policy(
    name="strict",
    outcomes={o: Severity.ERROR for o in Outcome if o is not Outcome.VERIFIED},
    confirmatory_outcomes={o: Severity.ERROR for o in Outcome if o is not Outcome.VERIFIED},
    unpinned_artifact=Severity.ERROR,
    ordering_unchecked=Severity.ERROR,
    regeneration_unchecked=Severity.ERROR,
    regeneration_not_rerun=Severity.WARNING,
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
