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

from repro.models import Availability, Outcome, Validity, VerificationReport


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

    require_one_check: bool = True
    """A run that evaluated nothing is not a pass. Without this a project with no evidence
    anywhere satisfies every other condition trivially."""

    def assess(self, report: VerificationReport) -> Assessment:
        violations: list[Violation] = []

        for artifact in report.artifacts:
            if artifact.validity is Validity.BROKEN_PIN:
                violations.append(Violation(
                    severity=self.broken_pin, rule="artifact.pin", subject=artifact.artifact_id,
                    detail=f"pinned {(artifact.expected or '')[:12]}, "
                           f"found {(artifact.actual or '')[:12]}"))
            elif artifact.validity is Validity.UNPINNED_ARTIFACT:
                violations.append(Violation(
                    severity=self.unpinned_artifact, rule="artifact.unpinned",
                    subject=artifact.artifact_id, detail="no digest recorded"))

        checked = 0
        for claim in report.claims:
            table = self.confirmatory_outcomes if claim.confirmatory else self.outcomes
            if claim.availability is Availability.NOT_OFFERED:
                severity = table.get(Outcome.NOT_OFFERED, self.outcomes.get(
                    Outcome.NOT_OFFERED, Severity.IGNORE))
                if severity is not Severity.IGNORE:
                    violations.append(Violation(
                        severity=severity, rule="claim.no_evidence", subject=claim.claim_id,
                        detail="claim offers no evidence"))
                continue
            for decision in claim.decisions:
                checked += 1
                severity = table.get(decision.outcome,
                                     self.outcomes.get(decision.outcome, Severity.IGNORE))
                if severity is not Severity.IGNORE:
                    violations.append(Violation(
                        severity=severity, rule=f"evidence.{decision.outcome.value}",
                        subject=f"{claim.claim_id}/{decision.kind}",
                        detail=decision.detail or decision.reason.value))

        if self.require_one_check and checked == 0:
            violations.append(Violation(
                severity=Severity.ERROR, rule="report.empty", subject=report.project,
                detail="no evidence assertion was evaluated"))

        return Assessment(
            policy=self.name, violations=tuple(violations),
            passed=not any(v.severity is Severity.ERROR for v in violations))


EXPLORATORY = Policy(
    name="exploratory",
    outcomes={Outcome.MISMATCH: Severity.ERROR, Outcome.ERROR: Severity.ERROR,
              Outcome.NOT_FOUND: Severity.WARNING, Outcome.UNCHECKED: Severity.WARNING,
              Outcome.NOT_OFFERED: Severity.IGNORE},
    unpinned_artifact=Severity.IGNORE,
)

PUBLICATION = Policy(
    name="publication",
    outcomes={Outcome.MISMATCH: Severity.ERROR, Outcome.ERROR: Severity.ERROR,
              Outcome.NOT_FOUND: Severity.ERROR, Outcome.UNCHECKED: Severity.WARNING,
              Outcome.NOT_OFFERED: Severity.WARNING},
    confirmatory_outcomes={Outcome.MISMATCH: Severity.ERROR, Outcome.ERROR: Severity.ERROR,
                           Outcome.NOT_FOUND: Severity.ERROR,
                           Outcome.UNCHECKED: Severity.ERROR,
                           Outcome.NOT_OFFERED: Severity.ERROR},
)

STRICT = Policy(
    name="strict",
    outcomes={o: Severity.ERROR for o in Outcome if o is not Outcome.VERIFIED},
    confirmatory_outcomes={o: Severity.ERROR for o in Outcome if o is not Outcome.VERIFIED},
    unpinned_artifact=Severity.ERROR,
)

PROFILES = {p.name: p for p in (EXPLORATORY, PUBLICATION, STRICT)}

__all__ = ["Severity", "Violation", "Assessment", "Policy",
           "EXPLORATORY", "PUBLICATION", "STRICT", "PROFILES"]
