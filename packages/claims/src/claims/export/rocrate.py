"""The check records as an RO-Crate metadata document.

RO-Crate 1.3 describes files, the software that made them and the runs of that software, and
the Process Run Crate profile says how one run is written down. Neither has a term for what a
check record states: that the value at an address in a file was compared with a value a
manuscript prints. This writes the files, the commands and their recorded re-runs in the terms
those two already have, and the checks in a small profile of this tool's own,
`https://reproducible.science/ro-crate/claim-check/0.1/`, which adds what is missing and
nothing else. Experimental, like the record it projects.

The projection is of `claims.record.ExportRecord` and of nothing beside it. `from_ro_crate`
reads the records back, and for a record this version understands the two are inverse, so
what a record holds a crate holds. A file no record names is not in the crate: an artifact
the manifest declares that no assertion reads, and that no command upstream of one reads or
writes, appears in no record.

Nothing here is evaluated, and no time is taken: every date in the document is one a record
carries, so the same records give the same bytes.
"""

from __future__ import annotations

import json
import pathlib
import shlex
import urllib.parse
from collections.abc import Sequence
from typing import Any

from claims.exceptions import ReproError
from claims.models import Regeneration
from claims.record import (
    CheckType,
    Command,
    ExportRecord,
    FileState,
    NormalizedOutcome,
    read_outcome,
)

METADATA_FILE = "ro-crate-metadata.json"

RO_CRATE = "https://w3id.org/ro/crate/1.3"
RO_CRATE_CONTEXT = "https://w3id.org/ro/crate/1.3/context"
PROCESS_RUN_CRATE = "https://w3id.org/ro/wfrun/process/0.6"
PROFILE = "https://reproducible.science/ro-crate/claim-check/0.1/"
PROFILE_VERSION = "0.1-experimental"

#: The terms the profile adds, each defined under its own anchor on the profile's page. A term
#: is here only where schema.org, as the RO-Crate context carries it, has none that says the
#: same thing.
TERMS = (
    "ClaimCheck",
    "DeclaredCommand",
    "FileRead",
    "addressKind",
    "argv",
    "assertionIndex",
    "assertionKind",
    "assertionName",
    "assertionPosition",
    "backend",
    "backendVersion",
    "canonicalAddress",
    "checkType",
    "checkWarning",
    "checkerVersion",
    "claimDigest",
    "comparisonMode",
    "comparisonStage",
    "computedValue",
    "conversion",
    "convertedValue",
    "declaredInput",
    "declaredOutput",
    "declaredPlaces",
    "durationSeconds",
    "executionStage",
    "exitCode",
    "extractionDigest",
    "extractionStage",
    "extractionTool",
    "extractionToolVersion",
    "fileRead",
    "freshness",
    "historyLastChangedAt",
    "historyStates",
    "lastRerun",
    "manifest",
    "manifestLine",
    "memberCount",
    "nativeOutcome",
    "nativeReason",
    "outcome",
    "outputDigest",
    "passageLine",
    "pinnedDigest",
    "printedValue",
    "readsFile",
    "recordVersion",
    "rerunReason",
    "rerunState",
    "side",
    "staleCause",
    "statistic",
    "tieLower",
    "tiePrinted",
    "tieUpper",
    "tolerance",
    "upstream",
    "validity",
    "whereStated",
)

#: What each outcome and check type is, as the crate's own entity for the term says it.
_OUTCOMES = {
    NormalizedOutcome.MATCH: "The file was read, the address resolved, a comparison ran, and "
    "the two agreed.",
    NormalizedOutcome.MISMATCH: "The file was read, the address resolved, a comparison ran, "
    "and the two differed.",
    NormalizedOutcome.NOT_FOUND: "The file was readable and the address did not resolve to "
    "exactly one value of the kind the assertion needs. Nothing was compared.",
    NormalizedOutcome.NOT_CHECKED: "No comparison occurred, because something it needed was "
    "absent or was skipped.",
    NormalizedOutcome.ERROR: "The tool failed.",
}
_CHECK_TYPES = {
    CheckType.VALUE_COMPARISON: "A value the manuscript prints, against the value at an "
    "address in a file.",
    CheckType.PASSAGE_PRESENCE: "A passage occurs in a file.",
    CheckType.CORRESPONDENCE: "The values at two addresses, in two files, agree.",
    CheckType.AGGREGATE_COMPARISON: "A value the manuscript prints, against a statistic "
    "computed over the values at several addresses.",
    CheckType.ARTIFACT_IDENTITY: "A file's bytes are the bytes that were recorded.",
    CheckType.LINEAGE_CHECK: "A file was produced by a recorded process from recorded inputs.",
    CheckType.RERUN_COMPARISON: "What a command wrote when run again, against what it wrote "
    "before.",
    CheckType.COVERAGE_CHECK: "Whether something the manuscript states has a claim declared "
    "for it.",
    CheckType.OTHER: "A proposition none of the other check types names.",
}

#: A command that ran to its end completed, whatever its output then held. Only one that did
#: not finish, or finished and wrote nothing, failed.
_FAILED = "http://schema.org/FailedActionStatus"
_COMPLETED = "http://schema.org/CompletedActionStatus"

#: RO-Crate requires a root data entity to say how the crate may be used, and a record does
#: not know. The property is therefore a statement that nothing is stated, which the
#: specification allows as text, and never a guess at a license.
LICENSE_NOT_STATED = (
    "Not stated. The check records this crate is written from carry no license, and the "
    "terms of each file are those of the project it belongs to."
)

Entity = dict[str, Any]


class NothingToExportError(ReproError):
    """No assertion was checked, so there is no record for a crate to describe."""

    def __init__(self) -> None:
        super().__init__(
            "no assertion was checked, so there is nothing for an RO-Crate to describe"
        )


class ConflictingRecordsError(ReproError):
    """Two records say different things about what one identifier names."""

    def __init__(self, identifier: str) -> None:
        self.identifier = identifier
        super().__init__(
            f"the records disagree about {identifier!r}; one crate describes one run of the "
            f"checker over one manifest"
        )


class NotAClaimCheckCrateError(ReproError):
    """A document is not one this module wrote."""

    def __init__(self, detail: str) -> None:
        super().__init__(f"not a claim-check crate: {detail}")


def _ref(identifier: str) -> dict[str, str]:
    return {"@id": identifier}


def _local(kind: str, *parts: str | int) -> str:
    return f"#{kind}/" + "/".join(urllib.parse.quote(str(part), safe="") for part in parts)


def _packed(values: Sequence[Any]) -> Any:
    """RO-Crate JSON-LD is compacted: one value stands alone, several are an array."""
    return values[0] if len(values) == 1 else list(values)


def _unpacked(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _present(entity: Entity) -> Entity:
    return {key: value for key, value in entity.items() if value is not None}


class _Graph:
    """The entities of one crate, each stated once."""

    def __init__(self) -> None:
        self.entities: dict[str, Entity] = {}
        self.files: dict[str, str] = {}
        """`@id` by artifact id."""

    def add(self, entity: Entity) -> str:
        identifier = entity["@id"]
        held = self.entities.setdefault(identifier, entity)
        if held != entity:
            raise ConflictingRecordsError(identifier)
        return identifier

    def file(self, state: FileState) -> str:
        """The entity for one declared file, by the path it has in the crate.

        A file that is on disk under a path inside the project is a data entity at that path.
        One that is absent, undeclared, outside the project, or at a path another artifact
        already has is described under a local identifier, which RO-Crate keeps for a file
        that is not in the crate.
        """
        path = pathlib.PurePosixPath(state.path)
        inside = bool(state.path) and not path.is_absolute() and ".." not in path.parts
        identifier = urllib.parse.quote(state.path)
        taken = identifier in self.entities and self.files.get(state.artifact) != identifier
        if not inside or state.on_disk is None or taken:
            identifier = _local("artifact", state.artifact)
        self.files[state.artifact] = identifier
        return self.add(
            _present(
                {
                    "@id": identifier,
                    "@type": "File",
                    "name": state.path or state.artifact,
                    "identifier": state.artifact,
                    "alternateName": state.path
                    if state.path and identifier != state.path
                    else None,
                    "encodingFormat": state.media_type or None,
                    "sha256": state.on_disk,
                    "pinnedDigest": state.pinned,
                    "validity": state.validity.value if state.validity else None,
                }
            )
        )

    def term(self, word: str, said: str) -> dict[str, str]:
        return _ref(
            self.add(
                {
                    "@id": f"{PROFILE}#{word}",
                    "@type": "DefinedTerm",
                    "name": word,
                    "termCode": word,
                    "description": said,
                }
            )
        )

    def command(self, command: Command) -> str:
        """A declared command as the tool Process Run Crate asks for, and its latest recorded
        re-run as the run of that tool."""
        identifier = _local("command", command.id)
        inputs = [_ref(self.file(wanted)) for wanted in command.inputs]
        output = _ref(self.file(command.output))
        rerun = command.last_rerun
        if rerun is not None:
            failed = rerun.state is Regeneration.FAILED
            self.add(
                _present(
                    {
                        "@id": _local("rerun", command.id),
                        "@type": "CreateAction",
                        "name": f"Re-run of {command.id}",
                        "description": shlex.join(command.command),
                        "instrument": _ref(identifier),
                        "object": _packed(inputs) if inputs else None,
                        "result": output,
                        "startTime": rerun.started_at or None,
                        "endTime": rerun.ended_at or None,
                        "actionStatus": _ref(
                            self.add(
                                {
                                    "@id": _FAILED if failed else _COMPLETED,
                                    "@type": "ActionStatusType",
                                    "name": "failed" if failed else "completed",
                                }
                            )
                        ),
                        "error": (rerun.reason or None) if failed else None,
                        "rerunState": rerun.state.value,
                        "rerunReason": rerun.reason,
                        "checkerVersion": rerun.checker_version or None,
                        "exitCode": rerun.exit_code,
                        "durationSeconds": rerun.duration_seconds,
                        "outputDigest": rerun.output_digest,
                    }
                )
            )
        return self.add(
            _present(
                {
                    "@id": identifier,
                    # Process Run Crate says a tool SHOULD be a SoftwareApplication, a
                    # SoftwareSourceCode or a ComputationalWorkflow. RO-Crate 1.3 requires the
                    # first to have a `url` and a `version` and the other two to be files, and
                    # a declared command is an argv with none of those. `HowTo` is the type
                    # the specification itself offers for a shell command.
                    "@type": ["HowTo", "DeclaredCommand"],
                    "name": command.id,
                    "identifier": command.id,
                    "description": shlex.join(command.command),
                    "argv": json.dumps(list(command.command), ensure_ascii=False),
                    "declaredInput": _packed(inputs) if inputs else None,
                    "declaredOutput": output,
                    "freshness": command.state.value,
                    "staleCause": _packed(list(command.causes)) if command.causes else None,
                    "lastRerun": _ref(_local("rerun", command.id)) if rerun else None,
                }
            )
        )


def _check(record: ExportRecord, graph: _Graph) -> str:
    claim, assertion = record.claim, record.assertion
    identifier = _local("check", claim.id, assertion.index)
    passage = next((p for p in claim.passages if p.assertion == assertion.index), None)

    manifest = None
    if record.manifest.path:
        name = pathlib.PurePosixPath(record.manifest.path).name
        manifest = graph.add(
            _present(
                {
                    "@id": urllib.parse.quote(name),
                    "@type": "File",
                    "name": name,
                    "alternateName": record.manifest.path if record.manifest.path != name else None,
                    "description": "The manifest the assertions were read from.",
                    "encodingFormat": "application/yaml",
                    "sha256": record.manifest.digest,
                }
            )
        )
    checker = graph.add(
        {
            "@id": _local("checker", record.checker.name, record.checker.version),
            "@type": "SoftwareApplication",
            "name": record.checker.name,
            "version": record.checker.version,
            **({"url": record.checker.url} if record.checker.url else {}),
        }
    )
    stated = graph.add(
        _present(
            {
                "@id": _local("claim", claim.id),
                "@type": "Claim",
                "name": claim.id,
                "identifier": claim.id,
                "text": claim.text,
                "whereStated": claim.where,
                "claimDigest": claim.digest,
                "manifestLine": claim.line,
            }
        )
    )
    reads = []
    for position, read in enumerate(record.reads):
        address = read.address.model_dump(mode="json") if read.address else None
        reads.append(
            _ref(
                graph.add(
                    _present(
                        {
                            "@id": f"{identifier}/read/{position}",
                            "@type": ["PropertyValue", "FileRead"],
                            "name": f"{read.artifact} as read for {claim.id}",
                            "readsFile": _ref(graph.file(read)),
                            "side": read.side or None,
                            "addressKind": address["kind"] if address else None,
                            "canonicalAddress": json.dumps(
                                address, sort_keys=True, separators=(",", ":"), ensure_ascii=False
                            )
                            if address
                            else None,
                            "value": read.stored,
                            "convertedValue": read.converted,
                        }
                    )
                )
            )
        )
    execution = record.execution
    upstream = [_ref(graph.command(command)) for command in execution.commands] if execution else []
    stages, reader, comparison = record.stages, record.reader, record.comparison
    tie = comparison.tie if comparison else None
    return graph.add(
        _present(
            {
                "@id": identifier,
                "@type": ["CheckAction", "ClaimCheck"],
                "name": " ".join(
                    part for part in (claim.id, assertion.kind, assertion.name) if part
                ),
                "description": record.detail or None,
                "recordVersion": record.record,
                "instrument": _ref(checker),
                "endTime": record.checked_at.isoformat(),
                "manifest": _ref(manifest) if manifest else None,
                "object": _ref(stated),
                "assertionKind": assertion.kind,
                "assertionName": assertion.name or None,
                "assertionIndex": assertion.index,
                "assertionPosition": assertion.position,
                "manifestLine": assertion.line,
                "passageLine": passage.line if passage else None,
                "checkType": graph.term(record.check_type.value, _CHECK_TYPES[record.check_type]),
                "fileRead": _packed(reads) if reads else None,
                "printedValue": record.printed,
                "comparisonMode": comparison.mode.value if comparison else None,
                "tolerance": comparison.tolerance if comparison else None,
                "declaredPlaces": comparison.places if comparison else None,
                "conversion": comparison.conversion if comparison else None,
                "statistic": comparison.statistic if comparison else None,
                "memberCount": comparison.count if comparison else None,
                "computedValue": comparison.computed if comparison else None,
                "tieLower": tie.lower if tie else None,
                "tieUpper": tie.upper if tie else None,
                "tiePrinted": tie.printed if tie else None,
                # Through `read_outcome`: a match this version does not understand leaves here
                # as not-checked, as it leaves every exporter.
                "outcome": graph.term(read_outcome(record).value, _OUTCOMES[read_outcome(record)]),
                "nativeOutcome": record.native_outcome,
                "nativeReason": record.native_reason,
                "executionStage": stages.execution.value if stages else None,
                "extractionStage": stages.extraction.value if stages else None,
                "comparisonStage": stages.comparison.value if stages else None,
                "backend": reader.backend or None,
                "backendVersion": reader.backend_version or None,
                "extractionTool": reader.tool or None,
                "extractionToolVersion": reader.tool_version or None,
                "extractionDigest": reader.extraction_digest or None,
                "checkWarning": _packed(list(record.warnings)) if record.warnings else None,
                "freshness": execution.state.value if execution else None,
                "upstream": _packed(upstream) if upstream else None,
                "historyStates": record.history.states if record.history else None,
                "historyLastChangedAt": record.history.last_changed_at if record.history else None,
            }
        )
    )


def to_ro_crate(records: Sequence[ExportRecord]) -> str:
    """The text of an `ro-crate-metadata.json` describing these records.

    The crate's root is the directory the manifest is in, so a file's `@id` is the path the
    manifest declares for it. Conformance to Process Run Crate is declared only where the
    records hold a recorded re-run, since that profile is about runs.
    """
    if not records:
        raise NothingToExportError()
    graph = _Graph()
    checks = [_check(record, graph) for record in records]
    entities = graph.entities
    reruns = [name for name, entity in entities.items() if entity["@type"] == "CreateAction"]
    files = [name for name, entity in entities.items() if entity["@type"] == "File"]

    profiles: list[Entity] = [
        {
            "@id": PROFILE,
            "@type": ["CreativeWork", "Profile"],
            "name": "Claim check crate (experimental)",
            "version": PROFILE_VERSION,
        }
    ]
    if reruns:
        profiles.append(
            {
                "@id": PROCESS_RUN_CRATE,
                "@type": ["CreativeWork", "Profile"],
                "name": "Process Run Crate",
                "version": "0.6",
            }
        )
    manifests = sorted({record.manifest.path for record in records if record.manifest.path})
    root = {
        "@id": "./",
        "@type": "Dataset",
        "name": f"Claim checks of {', '.join(manifests) or 'a manifest held in memory'}",
        "description": (
            f"{len(records)} assertion(s) about pinned files, each as it was checked: the "
            "file read, the address, the value stored there, the value reported and the "
            "outcome. A record of comparisons, not a verdict on the claims."
        ),
        "datePublished": max(record.checked_at for record in records).isoformat(),
        "license": LICENSE_NOT_STATED,
        "conformsTo": _packed([_ref(profile["@id"]) for profile in profiles]),
        "hasPart": _packed([_ref(name) for name in sorted(files)]),
        "mentions": _packed([_ref(name) for name in (*checks, *sorted(reruns))]),
    }
    descriptor = {
        "@id": METADATA_FILE,
        "@type": "CreativeWork",
        "conformsTo": _ref(RO_CRATE),
        "about": _ref("./"),
    }
    document = {
        "@context": [RO_CRATE_CONTEXT, {term: f"{PROFILE}#{term}" for term in TERMS}],
        "@graph": [descriptor, root, *profiles, *(entities[name] for name in sorted(entities))],
    }
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


# ----------------------------------------------------------------------------- reading back


def _file_state(entity: Entity) -> dict[str, Any]:
    identifier = entity["@id"]
    return {
        "artifact": entity["identifier"],
        "path": entity.get("alternateName")
        or ("" if identifier.startswith("#") else urllib.parse.unquote(identifier)),
        "media_type": entity.get("encodingFormat", ""),
        "validity": entity.get("validity"),
        "pinned": entity.get("pinnedDigest"),
        "on_disk": entity.get("sha256"),
    }


def _fragment(reference: dict[str, str]) -> str:
    return reference["@id"].removeprefix(f"{PROFILE}#")


def _commands(
    check: Entity, read_artifacts: list[str], entities: dict[str, Entity]
) -> list[dict[str, Any]]:
    """The commands a check names, with how far each is from what the check reads.

    A crate states the distance nowhere, because it follows from the graph: a command that
    writes a file the check reads is at 0, and one that writes an input of a command at `n` is
    at `n + 1`.
    """
    named = [entities[ref["@id"]] for ref in _unpacked(check.get("upstream"))]
    artifact = {
        name: entity["identifier"] for name, entity in entities.items() if entity.get("identifier")
    }
    producers = {artifact[c["declaredOutput"]["@id"]]: c for c in named}
    steps: dict[str, int] = {}
    pending = [(producers[name], 0) for name in read_artifacts if name in producers]
    while pending:
        command, distance = pending.pop(0)
        if steps.get(command["@id"], distance + 1) <= distance:
            continue
        steps[command["@id"]] = distance
        for wanted in _unpacked(command.get("declaredInput")):
            if artifact[wanted["@id"]] in producers:
                pending.append((producers[artifact[wanted["@id"]]], distance + 1))

    commands = []
    for command in named:
        rerun = entities[command["lastRerun"]["@id"]] if "lastRerun" in command else None
        commands.append(
            {
                "id": command["identifier"],
                "command": json.loads(command["argv"]),
                "steps": steps[command["@id"]],
                "output": _file_state(entities[command["declaredOutput"]["@id"]]),
                "inputs": [
                    _file_state(entities[ref["@id"]])
                    for ref in _unpacked(command.get("declaredInput"))
                ],
                "state": command["freshness"],
                "causes": _unpacked(command.get("staleCause")),
                "last_rerun": {
                    "started_at": rerun.get("startTime", ""),
                    "ended_at": rerun.get("endTime", ""),
                    "state": rerun["rerunState"],
                    "reason": rerun["rerunReason"],
                    "checker_version": rerun.get("checkerVersion", ""),
                    "exit_code": rerun.get("exitCode"),
                    "duration_seconds": rerun.get("durationSeconds"),
                    "output_digest": rerun.get("outputDigest"),
                }
                if rerun
                else None,
            }
        )
    return commands


def from_ro_crate(text: str) -> tuple[ExportRecord, ...]:
    """The check records a crate written by `to_ro_crate` holds, in the order it lists them.

    For a record this version understands, the inverse of `to_ro_crate`. Reads a document this
    module wrote and makes no attempt at one written elsewhere, expanded or reshaped.
    """
    try:
        entities = {entity["@id"]: entity for entity in json.loads(text)["@graph"]}
        root = entities["./"]
    except (ValueError, KeyError, TypeError) as e:
        raise NotAClaimCheckCrateError(f"no flattened graph with a root data entity: {e}") from e
    if PROFILE not in [ref["@id"] for ref in _unpacked(root.get("conformsTo"))]:
        raise NotAClaimCheckCrateError(f"the root data entity does not conform to {PROFILE}")

    checks = [
        entities[ref["@id"]]
        for ref in _unpacked(root.get("mentions"))
        if "ClaimCheck" in _unpacked(entities[ref["@id"]]["@type"])
    ]
    passages: dict[str, list[dict[str, Any]]] = {}
    for check in checks:
        if check["assertionKind"] == "quote":
            read = entities[_unpacked(check["fileRead"])[0]["@id"]]
            file = _file_state(entities[read["readsFile"]["@id"]])
            passages.setdefault(check["object"]["@id"], []).append(
                {
                    "assertion": check["assertionIndex"],
                    "artifact": file["artifact"],
                    "path": file["path"],
                    "text": check["printedValue"],
                    "line": check.get("passageLine"),
                }
            )

    records = []
    for check in checks:
        claim, checker = entities[check["object"]["@id"]], entities[check["instrument"]["@id"]]
        manifest = entities[check["manifest"]["@id"]] if "manifest" in check else None
        reads: list[dict[str, Any]] = []
        for ref in _unpacked(check.get("fileRead")):
            read = entities[ref["@id"]]
            reads.append(
                {
                    **_file_state(entities[read["readsFile"]["@id"]]),
                    "side": read.get("side", ""),
                    "address": json.loads(read["canonicalAddress"])
                    if "canonicalAddress" in read
                    else None,
                    "stored": read.get("value"),
                    "converted": read.get("convertedValue"),
                }
            )
        commands = _commands(check, [read["artifact"] for read in reads], entities)
        records.append(
            ExportRecord.model_validate(
                {
                    "record": check["recordVersion"],
                    "checker": {
                        "name": checker["name"],
                        "version": checker["version"],
                        "url": checker.get("url", ""),
                    },
                    "checked_at": check["endTime"],
                    "manifest": {
                        "path": manifest.get("alternateName")
                        or urllib.parse.unquote(manifest["@id"]),
                        "digest": manifest.get("sha256"),
                    }
                    if manifest
                    else {},
                    "claim": {
                        "id": claim["identifier"],
                        "text": claim["text"],
                        "where": claim.get("whereStated"),
                        "digest": claim["claimDigest"],
                        "line": claim.get("manifestLine"),
                        "passages": passages.get(claim["@id"], []),
                    },
                    "assertion": {
                        "kind": check["assertionKind"],
                        "name": check.get("assertionName", ""),
                        "index": check["assertionIndex"],
                        "position": check["assertionPosition"],
                        "line": check.get("manifestLine"),
                    },
                    "check_type": _fragment(check["checkType"]),
                    "reads": reads,
                    "printed": check.get("printedValue"),
                    "comparison": {
                        "mode": check["comparisonMode"],
                        "tolerance": check["tolerance"],
                        "places": check.get("declaredPlaces"),
                        "conversion": check.get("conversion"),
                        "statistic": check.get("statistic"),
                        "count": check.get("memberCount"),
                        "computed": check.get("computedValue"),
                        "tie": {
                            "lower": check["tieLower"],
                            "upper": check["tieUpper"],
                            "printed": check["tiePrinted"],
                        }
                        if "tieLower" in check
                        else None,
                    }
                    if "comparisonMode" in check
                    else None,
                    "outcome": _fragment(check["outcome"]),
                    "native_outcome": check["nativeOutcome"],
                    "native_reason": check["nativeReason"],
                    "detail": check.get("description", ""),
                    "stages": {
                        "execution": check["executionStage"],
                        "extraction": check["extractionStage"],
                        "comparison": check["comparisonStage"],
                    }
                    if "executionStage" in check
                    else None,
                    "reader": {
                        "backend": check.get("backend", ""),
                        "backend_version": check.get("backendVersion", ""),
                        "tool": check.get("extractionTool", ""),
                        "tool_version": check.get("extractionToolVersion", ""),
                        "extraction_digest": check.get("extractionDigest", ""),
                    },
                    "warnings": _unpacked(check.get("checkWarning")),
                    "execution": {"state": check["freshness"], "commands": commands}
                    if commands
                    else None,
                    "history": {
                        "states": check["historyStates"],
                        "last_changed_at": check.get("historyLastChangedAt"),
                    }
                    if "historyStates" in check
                    else None,
                }
            )
        )
    return tuple(records)


__all__ = [
    "METADATA_FILE",
    "PROCESS_RUN_CRATE",
    "PROFILE",
    "PROFILE_VERSION",
    "RO_CRATE",
    "TERMS",
    "ConflictingRecordsError",
    "NotAClaimCheckCrateError",
    "NothingToExportError",
    "from_ro_crate",
    "to_ro_crate",
]
