"""A record of what each assertion said when it was checked.

`repro verify` reports on a manifest as it is now. After a check does not verify, the
`reported` value, the address or the claim's text can be edited until it does, and the report
of the last run shows none of that. `record` appends to `.repro/checks.jsonl`, beside the
record of re-runs, each assertion whose declaration, artifact digest or outcome differs from
the last line recorded for it, so a later reader can say what was checked before.

The record is append-only, one JSON object per line. A run that finds every assertion as it
was last recorded writes nothing, so the file grows with changes and not with runs. A line
holds only the assertions that changed: an assertion's history is the lines that name it, in
order, and its state at any time is the last of them.

What the record cannot show: a check run with `--no-record`, an assertion removed and put
back unchanged, and anything done to the file itself, which is why it is committed.
"""

from __future__ import annotations

import collections
import datetime
import json
import pathlib

from pydantic import ValidationError

from repro.exceptions import ReproError
from repro.models import (
    CheckedAssertion,
    CheckRecord,
    Claim,
    CorrespondenceEvidence,
    Decision,
    Evidence,
    Locator,
    Manifest,
    QuoteEvidence,
    TableCellEvidence,
    TreeLocator,
    VerificationReport,
)

#: Where each check that found something changed is appended, beside the manifest.
RECORD = pathlib.Path(".repro") / "checks.jsonl"

#: Which assertion a line is about: the claim's id, the kind, the name and the position.
Identity = tuple[str, str, str, int]


class ChecksUnreadableError(ReproError):
    """A line of the record of checks is not one `repro verify` wrote."""

    def __init__(self, path: pathlib.Path, line: int, detail: str) -> None:
        self.path = path
        self.line = line
        super().__init__(f"{path}:{line}: {detail}")


def address(locator: Locator) -> str:
    """A locator as a reader would write it: a JSON Pointer bare, any other by its fields."""
    if isinstance(locator, TreeLocator):
        return locator.pointer
    fields = locator.model_dump(mode="json", exclude={"contract", "kind"}, exclude_defaults=True)
    return ", ".join(
        f"{key} {json.dumps(value, ensure_ascii=False)}" for key, value in fields.items()
    )


def _address(evidence: Evidence) -> str:
    if isinstance(evidence, QuoteEvidence):
        return ""
    if isinstance(evidence, CorrespondenceEvidence):
        return "; ".join(
            f"{side.name}: {side.artifact} at {address(side.locator)}" for side in evidence.sides
        )
    if isinstance(evidence, TableCellEvidence) and not evidence.addresses_one_row:
        # Neither `row` nor `where`, or both: there is no one address to record.
        return ""
    return address(evidence.locator)


def checked(
    claim: Claim, decisions: tuple[Decision, ...], at: str = ""
) -> tuple[CheckedAssertion, ...]:
    """Each assertion of one claim as a check found it, in the order declared."""
    seen: collections.Counter[tuple[str, str]] = collections.Counter()
    found = []
    for evidence, decision in zip(claim.evidence, decisions, strict=True):
        name = getattr(evidence, "name", "")
        found.append(
            CheckedAssertion(
                claim_id=claim.id,
                kind=evidence.kind,
                name=name,
                position=seen[evidence.kind, name],
                claim_digest=claim.digest.value,
                printed=evidence.text
                if isinstance(evidence, QuoteEvidence)
                else getattr(evidence, "reported", None),
                address=_address(evidence),
                digests={side.artifact_id: side.artifact_digest for side in decision.sides}
                or dict.fromkeys(evidence.artifacts, decision.artifact_digest),
                outcome=decision.outcome,
                reason=decision.reason,
                checked_at=at,
            )
        )
        seen[evidence.kind, name] += 1
    return tuple(found)


def checks(root: pathlib.Path) -> tuple[CheckRecord, ...]:
    """Every line of the project's record of checks, oldest first. Empty where the project
    has no record."""
    path = root / RECORD
    if not path.is_file():
        return ()
    lines = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            lines.append(CheckRecord.model_validate_json(line))
        except ValidationError as e:
            first = e.errors()[0]
            where = ".".join(str(x) for x in first["loc"]) or "(top level)"
            raise ChecksUnreadableError(path, number, f"{where}: {first['msg']}") from e
    return tuple(lines)


def history(root: pathlib.Path) -> dict[Identity, tuple[CheckedAssertion, ...]]:
    """Per assertion, each way the record holds it, oldest first."""
    found: dict[Identity, list[CheckedAssertion]] = collections.defaultdict(list)
    for line in checks(root):
        for assertion in line.assertions:
            found[assertion.identity].append(assertion)
    return {identity: tuple(states) for identity, states in found.items()}


def record(manifest: Manifest, report: VerificationReport) -> pathlib.Path | None:
    """Append what one `repro verify` found to the project's record of checks, and return
    where. None where every assertion is as it was last recorded, and nothing was written.

    Appended, one object per line, so an earlier line is never rewritten.
    """
    root = manifest.path.parent if manifest.path else pathlib.Path.cwd()
    at = datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds")
    past = history(root)
    changed = tuple(
        assertion
        for claim, assessed in zip(manifest.claims, report.claims, strict=True)
        for assertion in checked(claim, assessed.decisions, at)
        if assertion.identity not in past or not assertion.same_as(past[assertion.identity][-1])
    )
    if not changed:
        return None
    target = root / RECORD
    target.parent.mkdir(parents=True, exist_ok=True)
    line = CheckRecord(checked_at=at, assertions=changed)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(line.model_dump(mode="json"), sort_keys=True) + "\n")
    return target


__all__ = [
    "RECORD",
    "ChecksUnreadableError",
    "Identity",
    "address",
    "checked",
    "checks",
    "history",
    "record",
]
