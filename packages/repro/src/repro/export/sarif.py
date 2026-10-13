"""The check records as a SARIF 2.1.0 log, for GitHub code scanning.

A projection for display, and a lossy one. SARIF has a place for a tool, a rule, a message, a
file and a line, and a digest per file. It has none for an address inside a file, a stored
value beside a reported one, a comparison rule, or which proposition was checked, so those
travel in each result's property bag under `repro/checkRecord`, where the whole record sits.
`NOT_CARRIED_NATIVELY` lists them.

What becomes a result is what a reader has to act on: `mismatch`, `not-found` and `error`.
A `match` is a result only where asked for, as `kind: pass`: GitHub does not read `kind` and
opens a warning alert for a pass, so it is not the default. A `not-checked` assertion is
never a result, since a result reads as a finding and a `pass` reads as a success, and it is
neither: it is a notification on the invocation, counted in the run's properties.

Reads `repro.record.ExportRecord` and nothing else, and every outcome through
`repro.record.read_outcome`, so a word this version does not know is never shown as a pass.
"""

from __future__ import annotations

import collections
import datetime
import hashlib
import json
import posixpath
import warnings
from collections.abc import Sequence
from typing import Any

from repro.record import CheckType, ExportRecord, NormalizedOutcome, read_outcome

SCHEMA = "https://json.schemastore.org/sarif-2.1.0.json"
VERSION = "2.1.0"

#: Where the whole record sits in a result's or a notification's property bag.
RECORD_PROPERTY = "repro/checkRecord"

#: The partial fingerprint this exporter defines: a digest over the claim id and what
#: identifies the assertion within it. It does not move when a line does.
FINGERPRINT = "reproAssertion/v1"

#: The one partial fingerprint GitHub reads. Supplied, and set from `FINGERPRINT`: left out,
#: the upload action hashes the text of the annotated line, which for an assertion annotated
#: at its manifest entry is `- kind: metric` on every one of them.
GITHUB_FINGERPRINT = "primaryLocationLineHash"

#: GitHub keeps this many results of a run and drops the rest by severity.
GITHUB_RESULT_LIMIT = 5000

#: The fields of a record SARIF has no property for. Each is in the property bag and nowhere
#: else in the log.
NOT_CARRIED_NATIVELY = (
    "record",
    "manifest.digest",
    "claim.text",
    "claim.digest",
    "claim.where",
    "claim.passages",
    "assertion.kind",
    "assertion.name",
    "assertion.position",
    "assertion.index",
    "check_type",
    "reads.validity",
    "reads.pinned",
    "reads.side",
    "reads.address",
    "reads.stored",
    "reads.converted",
    "printed",
    "comparison",
    "outcome",
    "native_outcome",
    "native_reason",
    "stages",
    "reader",
    "warnings",
    "execution",
    "history",
)

#: `kind` and `level` for each outcome that is a result. SARIF 3.27.9: `fail` is "a problem
#: whose severity is specified by the level property", `pass` is "evaluated, and no problem
#: was found". 3.27.10: a level other than `none` is only for `fail`.
_RESULT = {
    NormalizedOutcome.MISMATCH: ("fail", "error"),
    NormalizedOutcome.NOT_FOUND: ("fail", "warning"),
    NormalizedOutcome.ERROR: ("fail", "error"),
    NormalizedOutcome.MATCH: ("pass", "none"),
}


class ResultLimitWarning(UserWarning):
    """A log holds more results than GitHub keeps."""


_SAID = {
    NormalizedOutcome.MATCH: "The file was read, the address resolved, and the two agreed.",
    NormalizedOutcome.MISMATCH: (
        "The file was read and the address resolved, and what it holds is not what the "
        "manuscript reports."
    ),
    NormalizedOutcome.NOT_FOUND: (
        "The file was read and the declared address did not resolve to one value. Nothing "
        "was compared."
    ),
    NormalizedOutcome.NOT_CHECKED: (
        "No comparison occurred: a file, a reader or a format it needed was absent."
    ),
    NormalizedOutcome.ERROR: "The checker failed on this assertion. Nothing was compared.",
}

_HELP = {
    NormalizedOutcome.MATCH: "Nothing to do.",
    NormalizedOutcome.MISMATCH: (
        "Either the manuscript or the file is out of date. `repro why <claim>` prints the "
        "stored value beside the reported one, and what produced the file."
    ),
    NormalizedOutcome.NOT_FOUND: (
        "Correct the address in repro.yaml, or the file. A file that is silent on a value "
        "does not contradict it, so this is not a mismatch."
    ),
    NormalizedOutcome.NOT_CHECKED: (
        "Supply what the check needs: the file, or the extra that reads its format."
    ),
    NormalizedOutcome.ERROR: "A defect in the checker or a backend. Report it with the detail.",
}


def _rule_id(outcome: NormalizedOutcome, record: ExportRecord) -> str:
    return f"repro/{outcome.value}/{record.native_reason}"


def _descriptor(outcome: NormalizedOutcome, record: ExportRecord) -> dict[str, Any]:
    reason = record.native_reason.replace("_", " ")
    descriptor: dict[str, Any] = {
        "id": _rule_id(outcome, record),
        "name": "".join(
            part.capitalize()
            for part in f"{outcome.value}_{record.native_reason}".replace("-", "_").split("_")
        ),
        "shortDescription": {"text": f"{outcome.value}: {reason}"},
        "fullDescription": {"text": _SAID[outcome]},
        "help": {"text": _HELP[outcome]},
    }
    if outcome in _RESULT and _RESULT[outcome][0] == "fail":
        descriptor["defaultConfiguration"] = {"level": _RESULT[outcome][1]}
    return descriptor


def _uri(record: ExportRecord, path: str) -> str:
    """A declared path as named from where the checker ran: the manifest's directory, then
    the path the manifest gives."""
    return posixpath.normpath(posixpath.join(posixpath.dirname(record.manifest.path), path))


def _physical(uri: str, line: int | None) -> dict[str, Any]:
    location: dict[str, Any] = {"artifactLocation": {"uri": uri}}
    if line is not None:
        location["region"] = {"startLine": line}
    return location


def _location(record: ExportRecord) -> dict[str, Any] | None:
    """The one place a result is shown, or None where the record names no file.

    The sentence, where the claim quotes one from a text file and it was found on one line:
    the assertion's own passage first, then another of the claim's. Otherwise the assertion's
    entry in the manifest. A line is never estimated.
    """
    located = [passage for passage in record.claim.passages if passage.line is not None]
    own = [passage for passage in located if passage.assertion == record.assertion.index]
    for passage in (*own, *located):
        return {"physicalLocation": _physical(_uri(record, passage.path), passage.line)}
    if not record.manifest.path:
        return None
    return {
        "physicalLocation": _physical(
            record.manifest.path, record.assertion.line or record.claim.line
        )
    }


def _related(record: ExportRecord) -> list[dict[str, Any]]:
    """Each file the assertion reads, and its entry in the manifest where the result is shown
    at the quoted sentence and not there."""
    related = []
    for read in record.reads:
        if not read.path:
            continue
        held = f" holds {read.stored}" if read.stored is not None else ""
        side = f"{read.side}: " if read.side else ""
        related.append(
            {
                "id": len(related) + 1,
                "physicalLocation": _physical(_uri(record, read.path), None),
                "message": {"text": f"{side}{read.artifact}{held}"},
            }
        )
    quoted = any(passage.line is not None for passage in record.claim.passages)
    if quoted and record.manifest.path and record.assertion.line is not None:
        related.append(
            {
                "id": len(related) + 1,
                "physicalLocation": _physical(record.manifest.path, record.assertion.line),
                "message": {"text": "declared here"},
            }
        )
    return related


def _message(record: ExportRecord, outcome: NormalizedOutcome) -> str:
    subject = f"{record.assertion.kind} {record.assertion.name}".strip()
    said = record.detail or record.native_reason.replace("_", " ")
    return f"{record.claim.id}: {subject}: {outcome.value}. {said}"


def _fingerprint(record: ExportRecord) -> str:
    """A digest over the assertion's identity (the claim's id, its kind, its name and its
    position among the claim's assertions of that kind and name) and what it declares: the
    files and addresses it reads, and for a quotation the passage.

    Not the index, which moves when an assertion of another kind is inserted above, and not a
    line. An address or a passage that is edited is another alert, as it is another assertion.
    """
    identity = [
        record.claim.id,
        record.assertion.kind,
        record.assertion.name,
        record.assertion.position,
        [
            [read.artifact, read.address.model_dump(mode="json") if read.address else None]
            for read in record.reads
        ],
        record.printed if record.check_type is CheckType.PASSAGE_PRESENCE else None,
    ]
    canonical = json.dumps(identity, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _properties(record: ExportRecord) -> dict[str, Any]:
    return {RECORD_PROPERTY: record.model_dump(mode="json", exclude_none=True)}


def to_sarif_log(records: Sequence[ExportRecord], include_matches: bool = False) -> str:
    """One SARIF run over the records, as JSON text.

    A result for each `mismatch`, `not-found` and `error`, and for each `match` where
    `include_matches` is set. A notification for each `not-checked`, and for each `error`
    beside its result.
    """
    shown = [
        (record, outcome)
        for record in records
        for outcome in (read_outcome(record),)
        if outcome in _RESULT and (include_matches or outcome is not NormalizedOutcome.MATCH)
    ]
    noted = [
        (record, outcome)
        for record in records
        for outcome in (read_outcome(record),)
        if outcome in (NormalizedOutcome.NOT_CHECKED, NormalizedOutcome.ERROR)
    ]

    rules = {_rule_id(outcome, record): _descriptor(outcome, record) for record, outcome in shown}
    rule_index = {rule: index for index, rule in enumerate(sorted(rules))}
    descriptors = {
        _rule_id(outcome, record): _descriptor(outcome, record) for record, outcome in noted
    }
    descriptor_index = {name: index for index, name in enumerate(sorted(descriptors))}

    results = []
    for record, outcome in shown:
        kind, level = _RESULT[outcome]
        fingerprint = _fingerprint(record)
        result: dict[str, Any] = {
            "ruleId": _rule_id(outcome, record),
            "ruleIndex": rule_index[_rule_id(outcome, record)],
            "kind": kind,
            "level": level,
            "message": {"text": _message(record, outcome)},
            "partialFingerprints": {
                FINGERPRINT: fingerprint,
                GITHUB_FINGERPRINT: f"{fingerprint[:16]}:1",
            },
            "properties": _properties(record),
        }
        if (location := _location(record)) is not None:
            result["locations"] = [location]
        if related := _related(record):
            result["relatedLocations"] = related
        results.append(result)

    if len(results) > GITHUB_RESULT_LIMIT:
        warnings.warn(
            f"{len(results)} results: GitHub keeps the {GITHUB_RESULT_LIMIT} most severe of a "
            f"run and drops the rest. Leave out --include-matches, or split the manifest.",
            ResultLimitWarning,
            stacklevel=2,
        )

    notifications = []
    for record, outcome in noted:
        failed = outcome is NormalizedOutcome.ERROR
        notification: dict[str, Any] = {
            "descriptor": {
                "id": _rule_id(outcome, record),
                "index": descriptor_index[_rule_id(outcome, record)],
            },
            # 3.58.6: `error` is a condition that left the results "incorrect or incomplete",
            # and `warning` one where "the analysis might be incomplete but the results that
            # were generated are probably valid".
            "level": "error" if failed else "warning",
            "message": {"text": _message(record, outcome)},
            "properties": _properties(record),
        }
        if (location := _location(record)) is not None:
            notification["locations"] = [location]
        notifications.append(notification)

    files: dict[str, dict[str, Any]] = {}
    for record in records:
        for read in record.reads:
            if read.path:
                files.setdefault(
                    _uri(record, read.path),
                    {
                        "location": {"uri": _uri(record, read.path)},
                        **({"mimeType": read.media_type} if read.media_type else {}),
                        **({"hashes": {"sha-256": read.on_disk}} if read.on_disk else {}),
                    },
                )

    counts = collections.Counter(read_outcome(record).value for record in records)
    unchecked = collections.Counter(
        record.native_reason
        for record in records
        if read_outcome(record) is NormalizedOutcome.NOT_CHECKED
    )
    first = records[0] if records else None
    run: dict[str, Any] = {
        "tool": {
            "driver": {
                "name": first.checker.name if first else "repro",
                **({"version": first.checker.version} if first else {}),
                **({"informationUri": first.checker.url} if first and first.checker.url else {}),
                "rules": [rules[name] for name in sorted(rules)],
                "notifications": [descriptors[name] for name in sorted(descriptors)],
            }
        },
        "invocations": [
            {
                # 3.20.21: a notification at level `error` "SHALL mean that the run failed".
                "executionSuccessful": not any(
                    outcome is NormalizedOutcome.ERROR for _, outcome in noted
                ),
                **(
                    {
                        "endTimeUtc": first.checked_at.astimezone(datetime.UTC).strftime(
                            "%Y-%m-%dT%H:%M:%SZ"
                        )
                    }
                    if first
                    else {}
                ),
                "toolExecutionNotifications": notifications,
            }
        ],
        "artifacts": [files[uri] for uri in sorted(files)],
        "results": results,
        "columnKind": "unicodeCodePoints",
        "properties": {
            "repro/recordVersion": first.record if first else "",
            "repro/assertions": len(records),
            "repro/outcomes": {
                outcome.value: counts[outcome.value] for outcome in NormalizedOutcome
            },
            "repro/notCheckedReasons": dict(sorted(unchecked.items())),
            "repro/matchesIncluded": "yes" if include_matches else "no",
        },
    }
    return json.dumps({"$schema": SCHEMA, "version": VERSION, "runs": [run]}, indent=2) + "\n"


__all__ = [
    "FINGERPRINT",
    "GITHUB_FINGERPRINT",
    "GITHUB_RESULT_LIMIT",
    "NOT_CARRIED_NATIVELY",
    "RECORD_PROPERTY",
    "ResultLimitWarning",
    "to_sarif_log",
]
