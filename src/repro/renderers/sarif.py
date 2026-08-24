"""SARIF 2.1.0 output.

SARIF is what code-scanning tools emit and what GitHub renders inline on a pull request, so a
report in this format shows up where a reviewer already looks rather than in a log they have
to open.

Two parts of the format fit this work unusually well. `artifacts[].hashes` carries a sha-256
per file, so the digests a report is computed against travel with it rather than being
described in prose. And `result.kind` distinguishes `fail`, `informational` and
`notApplicable` from `level`, which lets a check that could not run stay separate from one
that ran and failed -- the distinction this package exists to preserve, and one most report
formats cannot express.
"""
from __future__ import annotations

from typing import Any

from repro.models import Outcome, Validity, VerificationReport
from repro.policy import Assessment, Severity

SCHEMA = "https://json.schemastore.org/sarif-2.1.0.json"
VERSION = "2.1.0"

#: SARIF splits an outcome into `kind` (what happened) and `level` (how bad). A check that did
#: not run is `notApplicable`, never a `fail` at a lower level, because severity is not the
#: axis on which "unchecked" differs from "mismatch".
_KIND = {
    Outcome.VERIFIED: ("pass", "none"),
    Outcome.MISMATCH: ("fail", "error"),
    Outcome.NOT_FOUND: ("fail", "warning"),
    Outcome.UNCHECKED: ("notApplicable", "none"),
    Outcome.ERROR: ("fail", "error"),
    Outcome.NOT_OFFERED: ("informational", "note"),
}

_LEVEL = {Severity.ERROR: "error", Severity.WARNING: "warning", Severity.IGNORE: "note"}


def _rules() -> list[dict[str, Any]]:
    return [{
        "id": f"repro/{outcome.value}",
        "name": outcome.value.replace("_", " ").title().replace(" ", ""),
        "shortDescription": {"text": text},
        "defaultConfiguration": {"level": _KIND[outcome][1]},
    } for outcome, text in [
        (Outcome.VERIFIED, "The artifact holds what the claim says it holds."),
        (Outcome.MISMATCH, "The artifact was read and holds something else."),
        (Outcome.NOT_FOUND, "The artifact was read and holds no such value."),
        (Outcome.UNCHECKED, "No comparison was made."),
        (Outcome.ERROR, "A verifier failed."),
        (Outcome.NOT_OFFERED, "The claim offers no evidence."),
    ]]


def to_sarif(report: VerificationReport, assessment: Assessment | None = None,
             version: str = "0") -> dict[str, Any]:
    """One SARIF run over a verification report.

    `assessment` raises a result's level to what a policy says it is worth. Without one, each
    result carries the default level for its outcome, so the output describes what was found
    and takes no position on whether it is acceptable.
    """
    by_subject: dict[str, str] = {}
    if assessment is not None:
        for violation in assessment.violations:
            by_subject[violation.subject] = _LEVEL[violation.severity]

    artifacts = [{
        "location": {"uri": state.artifact_id},
        **({"hashes": {"sha-256": state.actual}} if state.actual else {}),
        "description": {"text": state.validity.value},
    } for state in report.artifacts]
    index = {state.artifact_id: i for i, state in enumerate(report.artifacts)}

    results = []
    for claim in report.claims:
        if not claim.decisions:
            results.append({
                "ruleId": f"repro/{Outcome.NOT_OFFERED.value}",
                "kind": "informational", "level": "note",
                "message": {"text": f"{claim.claim_id}: no evidence offered"},
                "partialFingerprints": {"claimDigest": claim.claim_digest},
            })
            continue
        for decision in claim.decisions:
            kind, level = _KIND[decision.outcome]
            subject = f"{claim.claim_id}/{decision.kind}"
            entry: dict[str, Any] = {
                "ruleId": f"repro/{decision.outcome.value}",
                "kind": kind,
                "level": by_subject.get(subject, level),
                "message": {"text": f"{claim.claim_id}: {decision.detail or decision.reason.value}"},
                "properties": {
                    "execution": decision.execution.value,
                    "extraction": decision.extraction.value,
                    "comparison": decision.comparison.value,
                    "reason": decision.reason.value,
                    "validity": decision.validity.value,
                    "backend": f"{decision.backend}/{decision.backend_version}",
                },
                # A fingerprint over the claim and the bytes read, so a result is the same
                # result across runs and a different one when either changes.
                "partialFingerprints": {
                    "claimDigest": decision.claim_digest,
                    **({"artifactDigest": decision.artifact_digest}
                       if decision.artifact_digest else {}),
                },
            }
            if decision.artifact_id in index:
                entry["locations"] = [{"physicalLocation": {
                    "artifactLocation": {"uri": decision.artifact_id,
                                         "index": index[decision.artifact_id]}}}]
            if decision.warnings:
                entry["properties"]["warnings"] = [w.value for w in decision.warnings]
            if decision.validity is not Validity.AUTHORITATIVE:
                entry["properties"]["nonAuthoritative"] = True
            results.append(entry)

    for state in report.artifacts:
        if state.validity is Validity.BROKEN_PIN:
            results.append({
                "ruleId": "repro/broken_pin", "kind": "fail", "level": "error",
                "message": {"text": f"{state.artifact_id}: pinned {(state.expected or '')[:12]}, "
                                    f"found {(state.actual or '')[:12]}"},
                "locations": [{"physicalLocation": {
                    "artifactLocation": {"uri": state.artifact_id,
                                         "index": index[state.artifact_id]}}}],
            })

    return {
        "$schema": SCHEMA,
        "version": VERSION,
        "runs": [{
            "tool": {"driver": {
                "name": "repro",
                "version": version,
                "informationUri": "https://github.com/elliottower/reproducible-science",
                "rules": _rules() + [{
                    "id": "repro/broken_pin",
                    "shortDescription": {"text": "The file read is not the file that was pinned."},
                    "defaultConfiguration": {"level": "error"},
                }],
            }},
            "artifacts": artifacts,
            "results": results,
            "properties": {"project": report.project,
                           "manifestDigest": report.manifest_digest,
                           **({"policy": assessment.policy,
                               "passed": assessment.passed} if assessment else {})},
        }],
    }
