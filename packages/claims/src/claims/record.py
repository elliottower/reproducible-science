"""One checked assertion, as a record another program can read.

`repro verify` prints a report and `repro why` an account, and each is shaped for its reader.
This is the same evaluation stated once per assertion and for no reader in particular: the
checker and its version read this file, with this digest, at this address, obtained this
value, compared it with the value the manuscript reports under this rule, and returned this
outcome. An exporter to another format reads these records and nothing else, so a fact an
exporter needs is added here and reaches every format.

Nothing is evaluated here that `repro verify` does not evaluate. Each assertion goes through
`claims.verify.check_evidence`, each pin through `claims.verify.artifact_states`, and what is
known of the commands upstream comes from `claims.stale.stale` and the record of re-runs.
Executes nothing and writes nothing.

**Experimental.** The version is in every record, and a field may change before `1.0`.

A conversion, where the file stores a fraction and the manuscript prints a percentage, is a
second value beside `stored` on the file read: `converted`, which is then the one compared.
An aggregate, a statistic over several runs, is one entry in `reads` per member, each with
its own `stored`, and the statistic and what it computed in `comparison`.
"""

from __future__ import annotations

import collections
import datetime
import enum
import json
import pathlib
import re
from collections.abc import Iterable, Mapping
from typing import Any

import yaml
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError

from claims.adapters.reads import reading_once
from claims.exceptions import ReproError
from claims.models import (
    AggregateEvidence,
    ArtifactState,
    Claim,
    ComparisonMode,
    ComparisonStatus,
    CorrespondenceEvidence,
    Decision,
    Digest,
    Evidence,
    ExecutionStatus,
    ExtractionStatus,
    Freshness,
    Manifest,
    MetricEvidence,
    Outcome,
    QuoteEvidence,
    Reason,
    Regeneration,
    RegenerationState,
    StalenessReport,
    TableCellEvidence,
    Validity,
    ValueEvidence,
)
from claims.reruns import reruns, upstream
from claims.resolve import stored
from claims.stale import stale
from claims.toolchain import distribution_version
from claims.verify import (
    ADAPTER_DISTRIBUTION,
    DEFAULT_BACKENDS,
    Backend,
    artifact_states,
    check_evidence,
)

RECORD_VERSION = "repro.check/0.1-experimental"

CHECKER = "repro"

#: Where the checker is described. A record names it so a reader can find out what the tool
#: is without knowing the name already.
CHECKER_URL = "https://github.com/elliottower/reproducible-science"


class CheckType(enum.StrEnum):
    """Which proposition a record is about. Closed, and defined once, in SPEC 7.10.

    Two tools can both say `verified` and have checked different things, so a record names
    the proposition as well as the outcome. The first three are the ones this tool checks. The
    rest are reserved for a record written from another tool's result, and this tool emits
    none of them.
    """

    VALUE_COMPARISON = "value-comparison"
    """A value the manuscript prints, against the value at an address in a file."""
    PASSAGE_PRESENCE = "passage-presence"
    """A passage occurs in a file."""
    CORRESPONDENCE = "correspondence"
    """The values at two addresses, in two files, agree."""
    AGGREGATE_COMPARISON = "aggregate-comparison"
    """A value the manuscript prints, against a statistic computed over the values at
    several addresses. No one stored value is the value compared."""
    ARTIFACT_IDENTITY = "artifact-identity"
    """A file's bytes are the bytes that were recorded. No value in it is compared."""
    LINEAGE_CHECK = "lineage-check"
    """A file was produced by a recorded process from recorded inputs."""
    RERUN_COMPARISON = "rerun-comparison"
    """What a command wrote when run again, against what it wrote before."""
    COVERAGE_CHECK = "coverage-check"
    """Whether something the manuscript states has a claim declared for it."""
    OTHER = "other"
    """A proposition none of the above names. Never read as a comparison of values."""


class NormalizedOutcome(enum.StrEnum):
    """What a check found, in five words defined by their preconditions. SPEC 7.10.

    The emitting tool's own word travels beside it in `native_outcome`.
    """

    MATCH = "match"
    """The file was read, the address resolved, a comparison ran, and the two agreed."""
    MISMATCH = "mismatch"
    """The file was read, the address resolved, a comparison ran, and the two differed."""
    NOT_FOUND = "not-found"
    """The file was readable and the address did not resolve to exactly one value of the kind
    the assertion needs. Nothing was compared."""
    NOT_CHECKED = "not-checked"
    """No comparison occurred, because something it needed was absent or was skipped."""
    ERROR = "error"
    """The tool failed."""


#: The proposition each evidence kind asserts.
CHECK_TYPES: dict[str, CheckType] = {
    "metric": CheckType.VALUE_COMPARISON,
    "aggregate": CheckType.AGGREGATE_COMPARISON,
    "table": CheckType.VALUE_COMPARISON,
    "value": CheckType.VALUE_COMPARISON,
    "quote": CheckType.PASSAGE_PRESENCE,
    "correspondence": CheckType.CORRESPONDENCE,
}

#: The check types whose `match` this version can read as a comparison that held.
UNDERSTOOD_CHECK_TYPES = frozenset(CHECK_TYPES.values())

#: The address kinds this version knows: every locator of SPEC 3.6, and a quotation's.
KNOWN_ADDRESS_KINDS = frozenset(
    {"tree", "table", "table_position", "array", "sheet", "sqlite", "prose", "passage"}
)

#: The outcome words each checker is known to emit, by checker name. A word from a checker
#: that is not listed here is not understood, whatever it looks like.
NATIVE_OUTCOMES: dict[str, frozenset[str]] = {
    CHECKER: frozenset(outcome.value for outcome in Outcome),
}


class UnmappedError(ReproError):
    """An outcome or an evidence kind has no place in the record's vocabulary yet."""

    def __init__(self, what: str, value: str) -> None:
        self.what = what
        self.value = value
        super().__init__(f"{what} {value!r} has no mapping into a check record")


def normalized(outcome: Outcome) -> NormalizedOutcome:
    """The record's outcome for one of this tool's own. The one place the mapping is written.

    Total by a test over every member and never by a default: an outcome added to the engine
    and not placed here raises, since any fallback would be a guess about what a check found.
    `not_offered` is here for that reason, though no record is written for a claim that offers
    no evidence.
    """
    mapping = {
        Outcome.VERIFIED: NormalizedOutcome.MATCH,
        Outcome.MISMATCH: NormalizedOutcome.MISMATCH,
        Outcome.NOT_FOUND: NormalizedOutcome.NOT_FOUND,
        Outcome.UNCHECKED: NormalizedOutcome.NOT_CHECKED,
        Outcome.NOT_OFFERED: NormalizedOutcome.NOT_CHECKED,
        Outcome.ERROR: NormalizedOutcome.ERROR,
    }
    if outcome not in mapping:
        raise UnmappedError("outcome", str(outcome))
    return mapping[outcome]


def check_type(kind: str) -> CheckType:
    """The proposition an evidence kind asserts, or `UnmappedError` for a kind not placed."""
    if kind not in CHECK_TYPES:
        raise UnmappedError("evidence kind", kind)
    return CHECK_TYPES[kind]


#: The address kind of a quotation, which has no locator: the passage is the address.
PASSAGE = "passage"

#: Suffixes read as text when a quoted passage is looked for by line. Anything else is left
#: without a line, since a line in an extraction is not a line in the file.
TEXT_SUFFIXES = (".txt", ".md", ".markdown", ".tex", ".rst")

_SHA256_HEX = r"^[a-f0-9]{64}$"

_CONFIG = ConfigDict(frozen=True, extra="allow")


class Checker(BaseModel):
    model_config = _CONFIG

    name: str
    version: str
    url: str = ""
    """Where the checker is described."""


class ManifestRef(BaseModel):
    """The manifest the assertion was read from."""

    model_config = _CONFIG

    path: str = ""
    """As named from the directory the checker ran in where the manifest lies under it, and
    its file name otherwise. Never absolute: records are committed and published."""
    digest: str | None = Field(default=None, pattern=_SHA256_HEX)
    """sha256 of the manifest's bytes. None for a manifest that was not read from a file."""


class Passage(BaseModel):
    """A passage one of the claim's quote assertions names, and where it sits."""

    model_config = _CONFIG

    assertion: int
    """Index of the quote assertion within the claim."""
    artifact: str
    path: str = ""
    text: str
    line: int | None = Field(default=None, ge=1)
    """The line the passage starts on, where the artifact is a text file and holds the
    passage exactly once up to whitespace. None otherwise: a line is never guessed."""


class ClaimRef(BaseModel):
    model_config = _CONFIG

    id: str
    text: str = ""
    where: str | None = None
    """Where the manuscript makes the claim, in the author's words."""
    digest: str
    line: int | None = Field(default=None, ge=1)
    """The line of the manifest the claim is declared on."""
    passages: tuple[Passage, ...] = ()


class AssertionRef(BaseModel):
    model_config = _CONFIG

    kind: str
    name: str = ""
    position: int = Field(default=0, ge=0)
    """Which of the claim's assertions of this kind and name it is, from 0. With the claim's
    id, the kind and the name, this is the identity an assertion keeps across edits, and the
    one `.repro/checks.jsonl` records a history under."""
    index: int = Field(ge=0)
    """Where it is among all of the claim's assertions, from 0, as the manifest orders them."""
    line: int | None = Field(default=None, ge=1)
    """The line of the manifest the assertion is declared on."""


class Address(BaseModel):
    """Where in a file an assertion looks, tagged by `kind`.

    The fields beside `kind` are those of the locator: `{"kind": "tree", "pointer": ...}`,
    `{"kind": "table", "column": ..., "where": {...}}`, and so on for each kind SPEC 3.6
    defines. A quotation is `{"kind": "passage"}` with the page or the neighbouring text it
    names. A kind this version does not know is kept as it was written.
    """

    model_config = _CONFIG

    kind: str


class FileState(BaseModel):
    """One declared file: its pin, and what is on disk."""

    model_config = _CONFIG

    artifact: str
    path: str = ""
    media_type: str = ""
    validity: Validity | None = None
    """None where the manifest declares no such artifact."""
    pinned: str | None = None
    on_disk: str | None = None


class FileRead(FileState):
    """One file an assertion reads, the address it reads, and the value there."""

    side: str = ""
    """Which side of a `correspondence` this is, in the author's word for it."""
    address: Address | None = None
    """None where the assertion names no one address."""
    stored: str | None = None
    """The value at the address, as the file stores it. None where none was read."""
    converted: str | None = None
    """`stored` under the conversion `comparison` names, which is then the value compared.
    None where no conversion is declared or no number was read."""


class Tie(BaseModel):
    """A compared value exactly halfway between two values at the printed precision, either
    of which a manuscript may print."""

    model_config = _CONFIG

    lower: str
    upper: str
    printed: str


class Comparison(BaseModel):
    """The rule a printed value was compared under, and what it was compared with where that
    is not a stored value as it stands."""

    model_config = _CONFIG

    mode: ComparisonMode
    tolerance: str = "0"
    places: int | None = None
    """The decimal places the assertion declares the manuscript reports the value to."""
    conversion: str | None = None
    """The conversion declared between what a file stores and what is printed: `percent` or
    `fraction`. A side of a `correspondence` that declares one says so in its address."""
    statistic: str | None = None
    """What an `aggregate` computes over the values in `reads`."""
    count: int | None = None
    """How many members an `aggregate` declares, which is how many entries `reads` has."""
    computed: str | None = None
    """That statistic of the values read, which is what was compared with `printed`."""
    tie: Tie | None = None


class Stages(BaseModel):
    """The three stages SPEC 4 reports separately, from which the outcome is derived."""

    model_config = _CONFIG

    execution: ExecutionStatus
    extraction: ExtractionStatus
    comparison: ComparisonStatus


class Reader(BaseModel):
    """What read the bytes: the backend, and the program that extracted from the file."""

    model_config = _CONFIG

    backend: str = ""
    backend_version: str = ""
    tool: str = ""
    tool_version: str = ""
    extraction_digest: str = ""


class Rerun(BaseModel):
    """One witnessed re-run of a command, as `repro reproduce` recorded it."""

    model_config = _CONFIG

    started_at: str = ""
    ended_at: str = ""
    """When the invocation that ran the command started and ended. The command ran between
    the two; `duration_seconds` is its own."""
    state: Regeneration
    reason: str = ""
    checker_version: str = ""
    exit_code: int | None = None
    duration_seconds: float | None = None
    output_digest: str | None = None
    """The digest of the output the re-run wrote."""


class Command(BaseModel):
    """A declared command upstream of what the assertion reads."""

    model_config = _CONFIG

    id: str
    command: tuple[str, ...]
    steps: int = Field(ge=0)
    """How many commands lie between the assertion and this one. 0 for a command that writes
    a file the assertion reads."""
    output: FileState
    inputs: tuple[FileState, ...] = ()
    state: Freshness
    causes: tuple[str, ...] = ()
    last_rerun: Rerun | None = None
    """The latest re-run of the command that the record of re-runs holds, whatever it found.
    None where none is recorded."""


class Execution(BaseModel):
    """What is known of the commands that produce what the assertion reads."""

    model_config = _CONFIG

    state: Freshness
    """The assertion's state against the record of re-runs, as `repro stale` gives it."""
    commands: tuple[Command, ...]
    """Nearest first."""


class History(BaseModel):
    """A pointer into the record of checks, for the assertion a record is about."""

    model_config = _CONFIG

    states: int = Field(ge=0)
    """How many states the record of checks holds for the assertion."""
    last_changed_at: str | None = None
    """When a check last found it different from the state recorded before."""


class ExportRecord(BaseModel):
    """One assertion, as it was checked. Frozen, and carries no verdict."""

    model_config = _CONFIG

    record: str = RECORD_VERSION
    checker: Checker
    checked_at: AwareDatetime
    manifest: ManifestRef = ManifestRef()
    claim: ClaimRef
    assertion: AssertionRef
    check_type: CheckType
    reads: tuple[FileRead, ...] = ()
    printed: str | None = None
    """The value as the manuscript prints it, the manifest's `reported`, or the passage a
    quotation asserts. None for a `correspondence`, which compares two files and prints no
    value of its own."""
    comparison: Comparison | None = None
    """None for a quotation, which is present or absent."""
    outcome: NormalizedOutcome
    native_outcome: str
    """The checker's own word for what it found, as it prints it."""
    native_reason: str
    """The checker's own reason for the outcome."""
    detail: str = ""
    stages: Stages | None = None
    """The three stages this tool derives its outcome from. None in a record written from a
    tool that reports none."""
    reader: Reader = Reader()
    warnings: tuple[str, ...] = ()
    """The checker's own notes on the evidence, as it words them."""
    execution: Execution | None = None
    """Present only where a declared command writes a file the assertion reads."""
    history: History | None = None
    """What the project's record of checks holds for this assertion. Reserved: nothing writes
    it yet, and a record is derived when it is exported, from no stored state."""

    def to_json(self) -> str:
        """One line. A field with nothing known is left out."""
        return json.dumps(self.model_dump(mode="json", exclude_none=True), ensure_ascii=False)


# ---------------------------------------------------------------------------------- building


def _state(artifact_id: str, manifest: Manifest, states: dict[str, ArtifactState]) -> dict:
    declared, state = manifest.artifact(artifact_id), states.get(artifact_id)
    return {
        "artifact": artifact_id,
        "path": declared.path.as_posix() if declared else "",
        "media_type": declared.media_type if declared else "",
        "validity": state.validity if state else None,
        "pinned": state.expected if state else None,
        "on_disk": state.actual if state else None,
    }


def _address(
    evidence: QuoteEvidence | MetricEvidence | TableCellEvidence | ValueEvidence,
) -> Address | None:
    if isinstance(evidence, QuoteEvidence):
        named = evidence.model_dump(
            mode="json", exclude={"kind", "artifact", "text"}, exclude_defaults=True
        )
        return Address(kind=PASSAGE, **named)
    if isinstance(evidence, TableCellEvidence) and not evidence.addresses_one_row:
        # Neither `row` nor `where`, or both: there is no one address to state.
        return None
    return Address.model_validate(evidence.locator.model_dump(mode="json"))


def _reads(
    evidence: Evidence,
    decision: Decision,
    manifest: Manifest,
    states: dict[str, ArtifactState],
    paths: dict[str, pathlib.Path],
) -> tuple[FileRead, ...]:
    # A value is stated only where the check ran. An address may still resolve where a
    # backend failed or a format on the other side has no reader, and a record that held the
    # value would report a reading no check was made with.
    ran = decision.execution is ExecutionStatus.COMPLETED
    if isinstance(evidence, CorrespondenceEvidence):
        read = {side.name: side for side in decision.sides}
        return tuple(
            FileRead(
                **_state(side.artifact, manifest, states),
                side=side.name,
                address=Address.model_validate(
                    side.locator.model_dump(mode="json")
                    | ({"conversion": side.conversion.value} if side.conversion else {})
                ),
                stored=read[side.name].extracted if ran and side.name in read else None,
                converted=read[side.name].converted if ran and side.name in read else None,
            )
            for side in evidence.sides
        )
    if isinstance(evidence, AggregateEvidence):
        # No member was read where a file is absent or undeclared: the engine stops before
        # the backend, and the decision lists none.
        found = [(member.extracted, member.converted) for member in decision.members]
        return tuple(
            FileRead(
                **_state(member.artifact, manifest, states),
                address=Address.model_validate(member.locator.model_dump(mode="json")),
                stored=value if ran else None,
                converted=converted if ran else None,
            )
            for member, (value, converted) in zip(
                evidence.members, found or [(None, None)] * evidence.count, strict=True
            )
        )
    path = paths.get(evidence.artifact)
    return (
        FileRead(
            **_state(evidence.artifact, manifest, states),
            address=_address(evidence),
            stored=stored(evidence, path) if ran and path is not None else None,
            converted=decision.converted if ran else None,
        ),
    )


def _comparison(evidence: Evidence, decision: Decision) -> Comparison | None:
    if isinstance(evidence, QuoteEvidence):
        return None
    conversion = getattr(evidence, "conversion", None)
    return Comparison(
        mode=evidence.mode,
        tolerance=evidence.tolerance,
        places=getattr(evidence, "places", None),
        conversion=conversion.value if conversion else None,
        statistic=decision.statistic.value if decision.statistic else None,
        count=evidence.count if isinstance(evidence, AggregateEvidence) else None,
        computed=decision.computed,
        tie=Tie(**decision.tie.model_dump()) if decision.tie else None,
    )


def _declared_lines(path: pathlib.Path) -> dict[int, tuple[int, tuple[int, ...]]]:
    """For each claim by position in the manifest: its line, and the line of each assertion.

    Read off the YAML as written, so a line is where an editor shows the claim. Empty where
    the file does not parse into the expected shape; the manifest loader has then already
    refused it.
    """
    loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
    try:
        root = yaml.compose(path.read_text(encoding="utf-8"), Loader=loader)
    except (OSError, yaml.YAMLError):
        return {}
    if not isinstance(root, yaml.MappingNode):
        return {}

    def child(node: yaml.MappingNode, key: str) -> yaml.Node | None:
        return next((value for name, value in node.value if name.value == key), None)

    claims = child(root, "claims")
    if not isinstance(claims, yaml.SequenceNode):
        return {}
    lines = {}
    for index, claim in enumerate(claims.value):
        evidence = child(claim, "evidence") if isinstance(claim, yaml.MappingNode) else None
        lines[index] = (
            claim.start_mark.line + 1,
            tuple(item.start_mark.line + 1 for item in evidence.value)
            if isinstance(evidence, yaml.SequenceNode)
            else (),
        )
    return lines


def _passage_line(
    path: pathlib.Path, passage: str, texts: dict[pathlib.Path, str | None]
) -> int | None:
    """The line a passage starts on in a text file that holds it exactly once, else None.

    Matched up to whitespace and no further. A passage found only after the normalization a
    quotation is checked under gets no line, and neither does one that occurs twice.
    """
    if path.suffix.lower() not in TEXT_SUFFIXES or not passage.split():
        return None
    if path not in texts:
        try:
            texts[path] = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            texts[path] = None
    text = texts[path]
    if text is None:
        return None
    found = list(re.finditer(r"\s+".join(re.escape(word) for word in passage.split()), text))
    return text.count("\n", 0, found[0].start()) + 1 if len(found) == 1 else None


def _rerun(when: tuple[str, str, str], entry: RegenerationState) -> Rerun:
    started_at, ended_at, version = when
    return Rerun(
        started_at=started_at,
        ended_at=ended_at,
        state=entry.state,
        reason=entry.reason.value,
        checker_version=version,
        exit_code=entry.exit_code,
        duration_seconds=entry.duration_seconds,
        output_digest=entry.actual,
    )


def _execution(
    evidence: Evidence,
    state: Freshness,
    manifest: Manifest,
    states: dict[str, ArtifactState],
    report: StalenessReport,
    latest: dict[str, Rerun],
) -> Execution | None:
    """The commands upstream of what one assertion reads, nearest first, or None where no
    declared command writes a file it reads."""
    records = {record.id: record for record in manifest.regenerations}
    producers = {record.output.artifact: record for record in manifest.regenerations}
    steps: dict[str, int] = {}
    for name in evidence.artifacts:
        producer = producers.get(name)
        if producer is None:
            continue
        for record_id, distance in {**upstream(producer, producers), producer.id: 0}.items():
            steps[record_id] = min(distance, steps.get(record_id, distance))
    if not steps:
        return None
    nodes = {node.id: node for node in report.regenerations}
    return Execution(
        state=state,
        commands=tuple(
            Command(
                id=record_id,
                command=records[record_id].command,
                steps=steps[record_id],
                output=FileState(**_state(records[record_id].output.artifact, manifest, states)),
                inputs=tuple(
                    FileState(**_state(wanted.artifact, manifest, states))
                    for wanted in records[record_id].inputs
                ),
                state=nodes[record_id].state,
                causes=tuple(cause.value for cause in nodes[record_id].causes),
                last_rerun=latest.get(record_id),
            )
            for record_id in sorted(steps, key=steps.__getitem__)
        ),
    )


def _manifest_ref(manifest: Manifest) -> ManifestRef:
    if manifest.path is None:
        return ManifestRef()
    here = pathlib.Path.cwd().resolve()
    resolved = manifest.path.resolve()
    return ManifestRef(
        path=resolved.relative_to(here).as_posix()
        if resolved.is_relative_to(here)
        else resolved.name,
        digest=Digest.of_file(manifest.path).value,
    )


def check_records(
    manifest: Manifest,
    checked_at: datetime.datetime | None = None,
    backends: tuple[Backend, ...] = DEFAULT_BACKENDS,
) -> tuple[ExportRecord, ...]:
    """Check every assertion in a manifest and return one record for each, in the order the
    manifest declares them.

    `checked_at` is the time every record carries; now, where none is given. Executes nothing
    and writes nothing.
    """
    when = checked_at or datetime.datetime.now(datetime.UTC).replace(microsecond=0)
    checker = Checker(
        name=CHECKER, version=distribution_version(ADAPTER_DISTRIBUTION), url=CHECKER_URL
    )
    reference = _manifest_ref(manifest)
    lines = _declared_lines(manifest.path) if manifest.path else {}

    report = stale(manifest)
    root = manifest.path.parent if manifest.path else pathlib.Path.cwd()
    latest: dict[str, Rerun] = {}
    for invocation in reruns(root):
        stamp = (invocation.started_at, invocation.ended_at, invocation.tool_version)
        for entry in invocation.regenerations:
            if entry.executed:
                latest[entry.regeneration_id] = _rerun(stamp, entry)

    states, paths = artifact_states(manifest)
    registry: dict[str, Backend] = {b.kind: b for b in backends}
    texts: dict[pathlib.Path, str | None] = {}
    records = []
    with reading_once():
        for position, (claim, node) in enumerate(zip(manifest.claims, report.claims, strict=True)):
            claim_line, evidence_lines = lines.get(position, (None, ()))
            reference_to_claim = ClaimRef(
                id=claim.id,
                text=claim.text,
                where=claim.where,
                digest=claim.digest.value,
                line=claim_line,
                passages=_passages(claim, manifest, paths, texts),
            )
            seen: collections.Counter[tuple[str, str]] = collections.Counter()
            for index, (evidence, freshness) in enumerate(
                zip(claim.evidence, node.assertions, strict=True)
            ):
                decision = check_evidence(claim, evidence, manifest, paths, states, registry)
                records.append(
                    ExportRecord(
                        checker=checker,
                        checked_at=when,
                        manifest=reference,
                        claim=reference_to_claim,
                        assertion=AssertionRef(
                            kind=evidence.kind,
                            name=getattr(evidence, "name", ""),
                            position=seen[evidence.kind, getattr(evidence, "name", "")],
                            index=index,
                            line=evidence_lines[index] if index < len(evidence_lines) else None,
                        ),
                        check_type=check_type(evidence.kind),
                        reads=_reads(evidence, decision, manifest, states, paths),
                        printed=evidence.text
                        if isinstance(evidence, QuoteEvidence)
                        else getattr(evidence, "reported", None),
                        comparison=_comparison(evidence, decision),
                        outcome=normalized(decision.outcome),
                        native_outcome=decision.outcome.value,
                        native_reason=decision.reason.value,
                        detail=decision.detail,
                        stages=Stages(
                            execution=decision.execution,
                            extraction=decision.extraction,
                            comparison=decision.comparison,
                        ),
                        reader=Reader(
                            backend=decision.backend,
                            backend_version=decision.backend_version,
                            tool=decision.tool,
                            tool_version=decision.tool_version,
                            extraction_digest=decision.extraction_digest,
                        ),
                        warnings=tuple(warning.value for warning in decision.warnings),
                        execution=_execution(
                            evidence, freshness.state, manifest, states, report, latest
                        ),
                    )
                )
                seen[evidence.kind, getattr(evidence, "name", "")] += 1
    return tuple(records)


def _passages(
    claim: Claim,
    manifest: Manifest,
    paths: dict[str, pathlib.Path],
    texts: dict[pathlib.Path, str | None],
) -> tuple[Passage, ...]:
    found = []
    for index, evidence in enumerate(claim.evidence):
        if not isinstance(evidence, QuoteEvidence):
            continue
        declared, path = manifest.artifact(evidence.artifact), paths.get(evidence.artifact)
        found.append(
            Passage(
                assertion=index,
                artifact=evidence.artifact,
                path=declared.path.as_posix() if declared else "",
                text=evidence.text,
                line=_passage_line(path, evidence.text, texts) if path is not None else None,
            )
        )
    return tuple(found)


def to_jsonl(records: Iterable[ExportRecord]) -> str:
    """JSON Lines: one record per line, in the order given."""
    return "".join(f"{record.to_json()}\n" for record in records)


# -------------------------------------------------------------------------------- validating


class InvalidRecordError(ReproError):
    """A record does not say something a check could have found."""

    def __init__(self, problems: tuple[str, ...]) -> None:
        self.problems = problems
        super().__init__("; ".join(problems))


def _flattened(stages: Stages) -> Outcome:
    """The outcome SPEC 4 derives from three stages, by the rule `Decision` derives it."""
    return Decision(
        claim_id="",
        claim_digest="",
        kind="",
        execution=stages.execution,
        extraction=stages.extraction,
        comparison=stages.comparison,
        reason=Reason.NOT_OFFERED,
    ).outcome


def _pin_problems(file: FileState) -> list[str]:
    """Validity is a fact about a file and its pin, and the two digests have to bear it out."""
    name = f"file {file.artifact!r}"
    if file.validity is Validity.AUTHORITATIVE and (not file.pinned or file.pinned != file.on_disk):
        return [f"{name} is authoritative, so its pinned digest must be the one on disk"]
    if file.validity is Validity.BROKEN_PIN and (
        not file.pinned or not file.on_disk or file.pinned == file.on_disk
    ):
        return [f"{name} is a broken pin, so it must carry two digests that differ"]
    if file.validity is Validity.UNPINNED_ARTIFACT and file.pinned:
        return [f"{name} is unpinned, so it must carry no pinned digest"]
    if file.validity is Validity.ARTIFACT_ABSENT and file.on_disk:
        return [f"{name} is absent, so it must carry no digest on disk"]
    return []


def understood(record: ExportRecord) -> bool:
    """Whether this version knows what the record's outcome is an outcome of.

    It does where the checker's own word is one that checker is known to emit, the check type
    is one whose comparison this version can read, and every address is of a kind it knows.
    """
    return (
        record.native_outcome in NATIVE_OUTCOMES.get(record.checker.name, frozenset())
        and record.check_type in UNDERSTOOD_CHECK_TYPES
        and all(
            read.address is None or read.address.kind in KNOWN_ADDRESS_KINDS
            for read in record.reads
        )
    )


def read_outcome(record: ExportRecord) -> NormalizedOutcome:
    """The outcome a consumer may act on: the record's, except that a `match` it does not
    understand is `not-checked`.

    Unknown stays unknown. A word, a check type or an address kind this version has never
    seen may be a success in the tool that wrote it, and nothing here can tell, so it is never
    passed on as one. Every exporter reads the outcome through this.
    """
    if record.outcome is NormalizedOutcome.MATCH and not understood(record):
        return NormalizedOutcome.NOT_CHECKED
    return record.outcome


def _a(word: str) -> str:
    return "an" if word[:1] in "aeiou" else "a"


def _value_problems(record: ExportRecord) -> list[str]:
    """What each check type has to carry for its outcome to be one a check could reach."""
    values = [read.stored for read in record.reads if read.stored is not None]
    converted = [read.converted for read in record.reads if read.converted is not None]
    compared = record.outcome in (NormalizedOutcome.MATCH, NormalizedOutcome.MISMATCH)
    comparison = record.comparison
    word = record.outcome.value
    found = []
    if comparison is not None and comparison.tie is not None:
        tie = comparison.tie
        if record.outcome is NormalizedOutcome.MATCH and tie.printed not in (tie.lower, tie.upper):
            found.append("a match on a tie prints one of the two values the tie lies between")
    if record.check_type is CheckType.VALUE_COMPARISON:
        if compared and (record.printed is None or not values):
            found.append(f"a value-comparison that is a {word} needs a stored and a printed value")
        elif compared and comparison is not None and comparison.conversion and not converted:
            found.append(
                f"a {word} under the conversion {comparison.conversion!r} needs the converted "
                f"value that was compared"
            )
    elif record.check_type is CheckType.AGGREGATE_COMPARISON:
        if comparison is None or not comparison.statistic or comparison.count is None:
            found.append("an aggregate-comparison names its statistic and its count")
        elif comparison.count != len(record.reads):
            found.append(
                f"an aggregate-comparison of {comparison.count} members reads "
                f"{len(record.reads)} files"
            )
        elif compared and (
            record.printed is None or comparison.computed is None or len(values) != comparison.count
        ):
            found.append(
                f"an aggregate-comparison that is a {word} needs the printed value, every "
                f"member's stored value and what the statistic computed"
            )
    elif record.check_type is CheckType.PASSAGE_PRESENCE:
        if compared and not record.printed:
            found.append(f"a passage-presence that is a {word} needs the passage looked for")
        if values:
            found.append("a passage-presence compares no value, so none can be stored")
    elif record.check_type is CheckType.CORRESPONDENCE:
        if len(record.reads) != 2 or record.printed is not None:
            found.append("a correspondence reads two files and prints no value of its own")
        elif compared and len(values) != 2:
            found.append(f"a correspondence that is a {word} needs the value stored on each side")
    elif record.check_type is not CheckType.RERUN_COMPARISON and (
        values or record.printed is not None or record.comparison is not None
    ):
        # Identity, lineage and coverage are facts about a file or a manuscript as a whole.
        # A pair of values on one of them would say a value was compared, and none was.
        found.append(f"a {record.check_type.value} compares no values, so it carries none")
    return found


def problems(record: ExportRecord) -> tuple[str, ...]:
    """What a record says that no check could have found. Empty where it is consistent.

    A schema says which fields a record may hold. This says which records are possible: an
    outcome whose preconditions the rest of the record contradicts, fields its check type
    cannot have, a `match` under a word this version does not know.
    """
    found = []
    if record.record != RECORD_VERSION:
        found.append(f"record is {record.record!r}; this reader knows {RECORD_VERSION!r}")

    known = record.native_outcome in NATIVE_OUTCOMES.get(record.checker.name, frozenset())
    if not known and record.outcome is NormalizedOutcome.MATCH:
        found.append(
            f"{record.checker.name!r} is not known to emit {record.native_outcome!r}, and a "
            f"word that is not understood is not-checked at best, never a match"
        )
    if known and record.checker.name == CHECKER:
        expected = normalized(Outcome(record.native_outcome))
        if expected is not record.outcome:
            found.append(
                f"outcome {record.outcome.value!r} is not what {record.native_outcome!r} "
                f"normalizes to, which is {expected.value!r}"
            )
        if record.stages is not None and _flattened(record.stages).value != record.native_outcome:
            found.append(f"{record.native_outcome!r} does not follow from the stages recorded")

    placed = CHECK_TYPES.get(record.assertion.kind)
    if record.checker.name == CHECKER and placed is not None and placed is not record.check_type:
        found.append(
            f"{_a(record.assertion.kind)} {record.assertion.kind!r} assertion is {_a(placed.value)} "
            f"{placed.value}, and the record "
            f"says {record.check_type.value}"
        )

    values = [read.stored for read in record.reads if read.stored is not None]
    stages = record.stages
    if record.outcome in (NormalizedOutcome.MATCH, NormalizedOutcome.MISMATCH):
        # The file was read, the address resolved and a comparison ran.
        if any(read.validity is Validity.ARTIFACT_ABSENT for read in record.reads):
            found.append(f"a {record.outcome.value} needs every file to have been read")
        if stages is not None and (
            stages.execution is not ExecutionStatus.COMPLETED
            or stages.extraction is not ExtractionStatus.EXTRACTED
            or stages.comparison.value != record.outcome.value
        ):
            found.append(f"a {record.outcome.value} needs a comparison that ran and found one")
    else:
        if stages is not None and stages.comparison is not ComparisonStatus.NOT_APPLICABLE:
            found.append(f"{record.outcome.value} means nothing was compared")
    if record.outcome is NormalizedOutcome.NOT_FOUND:
        if any(read.validity is Validity.ARTIFACT_ABSENT for read in record.reads):
            found.append("not-found needs a readable file; an absent one is not-checked")
        if stages is not None and stages.execution is not ExecutionStatus.COMPLETED:
            found.append("not-found needs a check that ran")
    if record.outcome in (NormalizedOutcome.NOT_CHECKED, NormalizedOutcome.ERROR) and values:
        found.append(f"{record.outcome.value} means no check ran, so no stored value was read")
    if (
        record.outcome is NormalizedOutcome.ERROR
        and stages is not None
        and stages.execution is not ExecutionStatus.FAILED
    ):
        found.append("error means the tool failed, and the stages say it did not")

    found += _value_problems(record)
    for read in record.reads:
        found += _pin_problems(read)
    if record.execution is not None:
        if not record.execution.commands:
            found.append("an execution block names one or more commands, or is left out")
        for command in record.execution.commands:
            for file in (command.output, *command.inputs):
                found += _pin_problems(file)
    return tuple(found)


def validate(data: Mapping[str, Any]) -> ExportRecord:
    """Read one record, or raise `InvalidRecordError` saying everything wrong with it."""
    try:
        record = ExportRecord.model_validate(data)
    except ValidationError as e:
        raise InvalidRecordError(
            tuple(
                f"{'.'.join(str(x) for x in error['loc']) or '(top level)'}: {error['msg']}"
                for error in e.errors()
            )
        ) from e
    if found := problems(record):
        raise InvalidRecordError(found)
    return record


__all__ = [
    "CHECKER",
    "CHECKER_URL",
    "CHECK_TYPES",
    "KNOWN_ADDRESS_KINDS",
    "NATIVE_OUTCOMES",
    "PASSAGE",
    "RECORD_VERSION",
    "UNDERSTOOD_CHECK_TYPES",
    "Address",
    "AssertionRef",
    "CheckType",
    "Checker",
    "ClaimRef",
    "Command",
    "Comparison",
    "Execution",
    "ExportRecord",
    "FileRead",
    "FileState",
    "History",
    "InvalidRecordError",
    "ManifestRef",
    "NormalizedOutcome",
    "Passage",
    "Reader",
    "Rerun",
    "Stages",
    "Tie",
    "UnmappedError",
    "check_records",
    "check_type",
    "normalized",
    "problems",
    "read_outcome",
    "to_jsonl",
    "understood",
    "validate",
]
