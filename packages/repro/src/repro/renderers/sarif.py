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

from repro.models import Ordering, Outcome, Validity, VerificationReport
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
_SEVERITY_ORDER = {"note": 0, "warning": 1, "error": 2}


def _rules() -> list[dict[str, Any]]:
    return (
        [
            {
                "id": f"repro/{outcome.value}",
                "name": outcome.value.replace("_", " ").title().replace(" ", ""),
                "shortDescription": {"text": text},
                "defaultConfiguration": {"level": _KIND[outcome][1]},
            }
            for outcome, text in [
                (Outcome.VERIFIED, "The artifact holds what the claim says it holds."),
                (Outcome.MISMATCH, "The artifact was read and holds something else."),
                (Outcome.NOT_FOUND, "The artifact was read and holds no such value."),
                (Outcome.UNCHECKED, "No comparison was made."),
                (Outcome.ERROR, "A verifier failed."),
                (Outcome.NOT_OFFERED, "The claim offers no evidence."),
            ]
        ]
        + [
            {
                # Artifact-level results carry these ids. A ruleId with no matching rule object is
                # what a strict SARIF consumer rejects, so they are declared beside the outcomes.
                "id": f"repro/{validity.value}",
                "name": validity.value.replace("_", " ").title().replace(" ", ""),
                "shortDescription": {"text": text},
                "defaultConfiguration": {"level": "error"},
            }
            for validity, text in [
                (Validity.BROKEN_PIN, "The file read is not the file that was pinned."),
                (Validity.ARTIFACT_ABSENT, "Nothing exists at the declared path."),
            ]
        ]
        + [
            {
                "id": f"repro/ordering_{ordering.value}",
                "name": f"Ordering{ordering.value.title()}",
                "shortDescription": {"text": text},
                "defaultConfiguration": {"level": level},
            }
            for ordering, text, level in [
                (
                    Ordering.VIOLATED,
                    "A confirmatory run started before the plan it names was registered.",
                    "error",
                ),
                (
                    Ordering.UNCHECKED,
                    "A confirmatory claim's ordering could not be established.",
                    "warning",
                ),
            ]
        ]
    )


def to_sarif(
    report: VerificationReport, assessment: Assessment | None = None, version: str = "0"
) -> dict[str, Any]:
    """One SARIF run over a verification report.

    `assessment` raises a result's level to what a policy says it is worth. Without one, each
    result carries the default level for its outcome, so the output describes what was found
    and takes no position on whether it is acceptable.
    """
    by_subject: dict[str, str] = {}
    if assessment is not None:
        for violation in assessment.violations:
            # Last-write-wins on a key two decisions can share: `claim_id/kind` is not
            # unique across a claim's evidence, so an error-level mismatch rendered at the
            # warning level of a `not_found` beside it. Keep the gravest.
            existing = by_subject.get(violation.subject)
            level = _LEVEL[violation.severity]
            if existing is None or _SEVERITY_ORDER[level] > _SEVERITY_ORDER[existing]:
                by_subject[violation.subject] = level

    artifacts = [
        {
            "location": {"uri": state.artifact_id},
            **({"hashes": {"sha-256": state.actual}} if state.actual else {}),
            "description": {"text": state.validity.value},
        }
        for state in report.artifacts
    ]
    index = {state.artifact_id: i for i, state in enumerate(report.artifacts)}

    # SARIF results are heterogeneous by design -- a result carries different keys depending
    # on what it reports -- so the value type is annotated rather than inferred from whichever
    # entry happens to be appended first.
    results: list[dict[str, Any]] = []
    for claim in report.claims:
        if not claim.decisions:
            results.append(
                {
                    "ruleId": f"repro/{Outcome.NOT_OFFERED.value}",
                    "kind": "informational",
                    "level": "note",
                    "message": {"text": f"{claim.claim_id}: no evidence offered"},
                    "partialFingerprints": {"claimDigest": claim.claim_digest},
                }
            )
            continue
        for decision in claim.decisions:
            kind, level = _KIND[decision.outcome]
            subject = f"{claim.claim_id}/{decision.kind}"
            entry: dict[str, Any] = {
                "ruleId": f"repro/{decision.outcome.value}",
                "kind": kind,
                "level": by_subject.get(subject, level),
                "message": {
                    "text": f"{claim.claim_id}: {decision.detail or decision.reason.value}"
                },
                "properties": {
                    "execution": decision.execution.value,
                    "extraction": decision.extraction.value,
                    "comparison": decision.comparison.value,
                    "reason": decision.reason.value,
                    "validity": decision.validity.value,
                    "backend": f"{decision.backend}/{decision.backend_version}",
                    # The toolchain that read the bytes, kept apart from the backend's
                    # protocol version: a renderer that showed only the latter would repeat
                    # in the output the gap the fields exist to close.
                    "extractor": f"{decision.tool}/{decision.tool_version}",
                    "extractionDigest": decision.extraction_digest,
                },
                # A fingerprint over the claim and the bytes read, so a result is the same
                # result across runs and a different one when either changes.
                "partialFingerprints": {
                    "claimDigest": decision.claim_digest,
                    **(
                        {"artifactDigest": decision.artifact_digest}
                        if decision.artifact_digest
                        else {}
                    ),
                },
            }
            # A correspondence reads two artifacts and names neither in `artifact_id`, so its
            # locations come from the sides. SARIF takes a list, and a finding about two files
            # that pointed at one of them would send a reader to the wrong half.
            located = [s.artifact_id for s in decision.sides] or [decision.artifact_id]
            entry["locations"] = [
                {"physicalLocation": {"artifactLocation": {"uri": uri, "index": index[uri]}}}
                for uri in located
                if uri in index
            ]
            if not entry["locations"]:
                del entry["locations"]
            if decision.warnings:
                entry["properties"]["warnings"] = [w.value for w in decision.warnings]
            if decision.validity is not Validity.AUTHORITATIVE:
                entry["properties"]["nonAuthoritative"] = True
            results.append(entry)

    for claim in report.claims:
        if claim.ordering is Ordering.VIOLATED:
            kind, level = "fail", "error"
        elif claim.ordering is Ordering.UNCHECKED:
            # Nothing is asserted either way, which is `notApplicable` rather than a
            # low-severity failure -- the same distinction the outcome kinds preserve.
            kind, level = "notApplicable", "warning"
        else:
            continue
        results.append(
            {
                "ruleId": f"repro/ordering_{claim.ordering.value}",
                "kind": kind,
                "level": by_subject.get(claim.claim_id, level),
                "message": {"text": f"{claim.claim_id}: {claim.ordering_detail}"},
                "properties": {
                    "claimDigest": claim.claim_digest,
                    "orderingReason": claim.ordering_reason.value,
                    **(
                        {"registrationAuthority": claim.registration_authority.value}
                        if claim.registration_authority
                        else {}
                    ),
                },
            }
        )

    for state in report.artifacts:
        if state.validity is Validity.BROKEN_PIN:
            message = (
                f"{state.artifact_id}: pinned {(state.expected or '')[:12]}, "
                f"found {(state.actual or '')[:12]}"
            )
        elif state.validity is Validity.ARTIFACT_ABSENT:
            message = f"{state.artifact_id}: nothing at the declared path"
        else:
            continue
        results.append(
            {
                "ruleId": f"repro/{state.validity.value}",
                "kind": "fail",
                "level": "error",
                "message": {"text": message},
                "locations": [
                    {
                        "physicalLocation": {
                            "artifactLocation": {
                                "uri": state.artifact_id,
                                "index": index[state.artifact_id],
                            }
                        }
                    }
                ],
            }
        )

    return {
        "$schema": SCHEMA,
        "version": VERSION,
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "repro",
                        "version": version,
                        "informationUri": "https://github.com/elliottower/reproducible-science",
                        "rules": [
                            *_rules(),
                            {
                                "id": "repro/broken_pin",
                                "shortDescription": {
                                    "text": "The file read is not the file that was pinned."
                                },
                                "defaultConfiguration": {"level": "error"},
                            },
                        ],
                    }
                },
                "artifacts": artifacts,
                "results": results,
                "properties": {
                    "project": report.project,
                    "manifestDigest": report.manifest_digest,
                    **(
                        {"policy": assessment.policy, "passed": assessment.passed}
                        if assessment
                        else {}
                    ),
                },
            }
        ],
    }
