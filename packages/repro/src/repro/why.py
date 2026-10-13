"""For one claim: what the record establishes, and what it does not.

`repro verify` answers for every assertion and `repro stale` for every file. This puts the two
answers for one claim side by side, with the commands and files upstream of what it reads, and
then lists what nothing in the record covers: a file no command is recorded for, a command with
no re-run that reproduced, an assertion that was not checked.

Nothing is evaluated here that those two do not evaluate. Each assertion goes through
`repro.verify.check_evidence`, each state comes from `repro.stale.stale`, and the chain is the
part of that report's graph `repro.regenerate.upstream` reaches from the files the claim reads.
Executes nothing and writes nothing.
"""

from __future__ import annotations

import collections
import difflib
import json
import pathlib

from repro.adapters.reads import reading_once
from repro.exceptions import ReproError
from repro.models import (
    AggregateEvidence,
    AssertionAccount,
    ChainNode,
    Claim,
    ClaimAccount,
    Conversion,
    CorrespondenceEvidence,
    Decision,
    Evidence,
    FileRead,
    Freshness,
    Locator,
    Manifest,
    NotEstablished,
    NotEstablishedKind,
    Outcome,
    QuoteEvidence,
    StaleCause,
    TableCellEvidence,
    TreeLocator,
    Validity,
)
from repro.regenerate import upstream
from repro.reproduce import stored
from repro.stale import stale
from repro.verify import DEFAULT_BACKENDS, Backend, artifact_states, check_evidence

#: Ids named in an error. A manifest can declare thousands.
MAX_LISTED = 10

#: What the design does not check. An account ends on each that applies to it: the first where
#: a command is recorded, the second where an assertion has an address, the third where there
#: is an assertion.
UNDECLARED_INPUTS = (
    "the inputs each command declares are the author's list; a file a command reads and does "
    "not declare is invisible"
)
ADDRESS_IS_CHOSEN = (
    "the address is the author's choice; nothing checks that it holds the quantity the "
    "sentence means"
)
COMPARISON_ONLY = (
    "a verified assertion says the declared value or passage is in the file, not that the "
    "analysis is right"
)

#: What is said of a file no command is recorded for, by what its pin found.
_TAKEN_AS_GIVEN = {
    Validity.AUTHORITATIVE: "its bytes are pinned and taken as given",
    Validity.UNPINNED_ARTIFACT: "its bytes are not pinned and are taken as given",
    Validity.BROKEN_PIN: "its bytes are not the pinned ones and are taken as given",
}

_NOT_CHECKED = {
    Outcome.UNCHECKED: NotEstablishedKind.UNCHECKED,
    Outcome.NOT_FOUND: NotEstablishedKind.NOT_FOUND,
    Outcome.ERROR: NotEstablishedKind.ERROR,
}


class UnknownClaimError(ReproError):
    """A claim was named that the manifest does not declare."""

    def __init__(self, unknown: str, declared: tuple[str, ...]) -> None:
        self.unknown = unknown
        self.declared = declared
        near = tuple(difflib.get_close_matches(unknown, declared, n=MAX_LISTED))
        listed = near or declared[:MAX_LISTED]
        more = len(declared) - len(listed)
        super().__init__(
            f"the manifest declares no claim {unknown!r}; "
            + ("nearest: " if near else "declared: ")
            + (", ".join(listed) or "none")
            + (f", and {more} more" if more > 0 and not near else "")
        )


def address(locator: Locator) -> str:
    """A locator as a reader would write it: a JSON Pointer bare, any other by its fields."""
    if isinstance(locator, TreeLocator):
        return locator.pointer
    fields = locator.model_dump(mode="json", exclude={"contract", "kind"}, exclude_defaults=True)
    return ", ".join(
        f"{key} {json.dumps(value, ensure_ascii=False)}" for key, value in fields.items()
    )


#: One file an assertion reads: the artifact, the side it is, the address, the value stored
#: there, and the conversion declared for it with the value under it.
Held = tuple[str, str, str, str | None, Conversion | None, str | None]


def _held(evidence: Evidence, decision: Decision, paths: dict[str, pathlib.Path]) -> list[Held]:
    """Each file an assertion reads, and what was found at the address in it."""
    if isinstance(evidence, QuoteEvidence):
        return [(evidence.artifact, "", "", None, None, None)]
    if isinstance(evidence, CorrespondenceEvidence):
        read = {side.name: side for side in decision.sides}
        return [
            (
                side.artifact,
                side.name,
                address(side.locator),
                read[side.name].extracted if side.name in read else None,
                side.conversion,
                read[side.name].converted if side.name in read else None,
            )
            for side in evidence.sides
        ]
    if isinstance(evidence, AggregateEvidence):
        # No member was read where a file is absent or undeclared: the engine stops before
        # the backend, and the decision lists none.
        read = [(m.extracted, m.converted) for m in decision.members]
        return [
            (member.artifact, "", address(member.locator), stored, evidence.conversion, converted)
            for member, (stored, converted) in zip(
                evidence.members, read or [(None, None)] * evidence.count, strict=True
            )
        ]
    if isinstance(evidence, TableCellEvidence) and not evidence.addresses_one_row:
        # Neither `row` nor `where`, or both: there is no one address to show.
        return [(evidence.artifact, "", "", None, None, None)]
    path = paths.get(evidence.artifact)
    return [
        (
            evidence.artifact,
            "",
            address(evidence.locator),
            stored(evidence, path) if path is not None else None,
            evidence.conversion,
            decision.converted,
        )
    ]


def _not_established(
    claim: Claim, assertions: tuple[AssertionAccount, ...], chain: tuple[ChainNode, ...]
) -> tuple[NotEstablished, ...]:
    """What the record does not cover for this claim, then what the design does not check."""
    lines = []
    for node in chain:
        if node.regeneration is None and node.validity in _TAKEN_AS_GIVEN:
            lines.append(
                NotEstablished(
                    kind=NotEstablishedKind.NO_PRODUCER,
                    subject=node.path or node.artifact,
                    said=f"no command is recorded for it; {_TAKEN_AS_GIVEN[node.validity]}",
                )
            )
    for node in chain:
        if node.validity is Validity.ARTIFACT_ABSENT:
            lines.append(
                NotEstablished(
                    kind=NotEstablishedKind.ABSENT,
                    subject=node.path or node.artifact,
                    said="nothing at the declared path",
                )
            )
        elif node.regeneration is not None and node.validity is Validity.BROKEN_PIN:
            lines.append(
                NotEstablished(
                    kind=NotEstablishedKind.BROKEN_PIN,
                    subject=node.path or node.artifact,
                    said="its bytes are not the pinned ones",
                )
            )
    for node in chain:
        record = node.regeneration
        if record is None:
            continue
        # A record on a cycle is compared with no re-run, whether or not one is recorded.
        if StaleCause.CYCLE in record.causes:
            lines.append(
                NotEstablished(
                    kind=NotEstablishedKind.CYCLE,
                    subject=record.id,
                    said="on a cycle of commands, so it is compared with no re-run",
                )
            )
        elif record.rerun_at is None:
            lines.append(
                NotEstablished(
                    kind=NotEstablishedKind.NEVER_RERUN,
                    subject=record.id,
                    said="no re-run that reproduced is recorded; nothing in the record shows "
                    f"the command produces {node.path or node.artifact}",
                )
            )
    if not claim.evidence:
        lines.append(
            NotEstablished(
                kind=NotEstablishedKind.NO_EVIDENCE,
                subject=claim.id,
                said="the claim offers no evidence, so nothing was checked",
            )
        )
    for assertion in assertions:
        if assertion.outcome in _NOT_CHECKED:
            reason = assertion.reason.value.replace("_", " ")
            lines.append(
                NotEstablished(
                    kind=_NOT_CHECKED[assertion.outcome],
                    subject=f"{assertion.kind} {assertion.name}".strip(),
                    said=f"{assertion.outcome.value.replace('_', ' ')}: {reason}"
                    + (f": {assertion.detail}" if assertion.detail else ""),
                )
            )
    if any(node.regeneration is not None for node in chain):
        lines.append(
            NotEstablished(kind=NotEstablishedKind.UNDECLARED_INPUTS, said=UNDECLARED_INPUTS)
        )
    if any(read.address for assertion in assertions for read in assertion.reads):
        lines.append(NotEstablished(kind=NotEstablishedKind.ADDRESS, said=ADDRESS_IS_CHOSEN))
    if assertions:
        lines.append(NotEstablished(kind=NotEstablishedKind.COMPARISON, said=COMPARISON_ONLY))
    return tuple(lines)


def why(
    manifest: Manifest, claim_id: str, backends: tuple[Backend, ...] = DEFAULT_BACKENDS
) -> ClaimAccount:
    """Evaluate one claim's assertions and say what each file it rests on is, against the
    record of re-runs.

    Executes nothing and writes nothing.
    """
    claim = next((c for c in manifest.claims if c.id == claim_id), None)
    if claim is None:
        raise UnknownClaimError(claim_id, tuple(c.id for c in manifest.claims))

    report = stale(manifest)
    states, paths = artifact_states(manifest)
    registry: dict[str, Backend] = {b.kind: b for b in backends}
    with reading_once():
        decisions = [
            check_evidence(claim, evidence, manifest, paths, states, registry)
            for evidence in claim.evidence
        ]
        held = [
            _held(evidence, decision, paths)
            for evidence, decision in zip(claim.evidence, decisions, strict=True)
        ]

    def read(
        artifact_id: str,
        side: str,
        where: str,
        value: str | None,
        conversion: Conversion | None,
        converted: str | None,
    ) -> FileRead:
        declared, state = manifest.artifact(artifact_id), states.get(artifact_id)
        return FileRead(
            artifact=artifact_id,
            path=declared.path.as_posix() if declared else "",
            side=side,
            validity=state.validity if state else None,
            pinned=state.expected if state else None,
            on_disk=state.actual if state else None,
            address=where,
            stored=value,
            conversion=conversion,
            converted=converted,
        )

    freshness = next(node for node in report.claims if node.id == claim.id).assertions
    assertions = tuple(
        AssertionAccount(
            kind=evidence.kind,
            name=getattr(evidence, "name", ""),
            printed=evidence.text
            if isinstance(evidence, QuoteEvidence)
            else getattr(evidence, "reported", None),
            reads=tuple(read(*found) for found in files),
            places=getattr(evidence, "places", None),
            tie=decision.tie,
            statistic=evidence.statistic if isinstance(evidence, AggregateEvidence) else None,
            computed=decision.computed,
            outcome=decision.outcome,
            reason=decision.reason,
            detail=decision.detail,
            state=node.state,
        )
        for evidence, decision, files, node in zip(
            claim.evidence, decisions, held, freshness, strict=True
        )
    )

    # The records upstream of each file the claim reads, by `upstream`, and so the files: each
    # record's output at the record's distance and its inputs one step further.
    records = {record.id: record for record in manifest.regenerations}
    producers = {record.output.artifact: record for record in manifest.regenerations}
    steps: dict[str, int] = {}
    for name in dict.fromkeys(name for evidence in claim.evidence for name in evidence.artifacts):
        steps[name] = 0
        producer = producers.get(name)
        if producer is None:
            continue
        for record_id, distance in {**upstream(producer, producers), producer.id: 0}.items():
            record = records[record_id]
            for artifact_id, at in (
                (record.output.artifact, distance),
                *((wanted.artifact, distance + 1) for wanted in record.inputs),
            ):
                steps[artifact_id] = min(at, steps.get(artifact_id, at))

    nodes = {node.artifact: node for node in report.regenerations}
    chain = tuple(
        ChainNode(
            artifact=name,
            path=declared.path.as_posix() if declared else "",
            steps=steps[name],
            validity=states[name].validity if name in states else None,
            state=nodes[name].state if name in nodes else Freshness.NO_PRODUCER,
            command=producers[name].command if name in producers else (),
            volatile=producers[name].volatile if name in producers else (),
            regeneration=nodes.get(name),
        )
        for name in sorted(steps, key=steps.__getitem__)
        for declared in (manifest.artifact(name),)
    )
    on_chain = {node.regeneration.id for node in chain if node.regeneration}
    by_outcome = collections.Counter(assertion.outcome for assertion in assertions)
    by_state = collections.Counter(assertion.state for assertion in assertions)

    return ClaimAccount(
        project=report.project,
        manifest_digest=report.manifest_digest,
        claim_id=claim.id,
        text=claim.text,
        where=claim.where,
        assertions=assertions,
        chain=chain,
        edges=tuple(
            edge
            for edge in report.edges
            if (edge.kind == "reads" and edge.source == claim.id)
            or (edge.kind == "produced_by" and edge.target in on_chain)
            or (edge.kind == "consumes" and edge.source in on_chain)
        ),
        findings=tuple(found for found in report.findings if found.regeneration in on_chain),
        not_established=_not_established(claim, assertions, chain),
        outcomes={outcome: by_outcome[outcome] for outcome in Outcome if by_outcome[outcome]},
        states={state: by_state[state] for state in Freshness if by_state[state]},
    )


__all__ = [
    "ADDRESS_IS_CHOSEN",
    "COMPARISON_ONLY",
    "UNDECLARED_INPUTS",
    "UnknownClaimError",
    "address",
    "why",
]
