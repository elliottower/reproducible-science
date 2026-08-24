"""The evidence contract.

A quotation in a manuscript and a number in a results file are the same kind of object: a
typed value asserted to be extractable from a pinned artifact. This package verifies that
assertion and nothing beyond it.

**What a decision evaluates.** Each decision evaluates an *evidence assertion* -- "this passage
occurs in this artifact", "this artifact holds this value at this location" -- and never the
truth of the manuscript claim the evidence is offered for. A source can contain a quotation
verbatim while the quotation fails to support the sentence citing it, and a passage can be
absent while the claim is true and supported elsewhere. Entailment between evidence and claim
is a separate question, addressed by the claim-verification literature with model-based
methods, and out of scope here.

That distinction governs the vocabulary. `SUPPORTED` and `REFUTED` name a semantic relation
between evidence and claim; this package reports `MATCH` and `MISMATCH`, which name what a
byte comparison found.

**Three stages, reported separately.** A check has to execute, extract, and compare, and each
can fail differently:

    execution    did the check run at all?          completed | unavailable | failed
    extraction   was the value located?             extracted | absent | invalid | not_attempted
    comparison   did it match what was claimed?     match | mismatch | not_applicable

Collapsing these is how a missing PDF extractor becomes a quotation that failed to check out,
and how a results file that is silent on a value becomes one that contradicts it. A selector
that resolves to nothing is `completed / absent / not_applicable`: the check ran, the value is
not there, and no comparison was possible. A missing extractor is
`unavailable / not_attempted / not_applicable`: nothing ran.

**Availability is a claim-level fact, not a check outcome.** Whether a claim offers evidence
cannot be the result of checking evidence, because there is none to pass to a backend. It
lives on the claim.
"""
from __future__ import annotations

import decimal
import enum
import json
import hashlib
import pathlib
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = "repro/1"

_SHA256_HEX = r"^[a-f0-9]{64}$"


# --------------------------------------------------------------------------------- artifacts

class Digest(BaseModel):
    """A content address."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    algorithm: Literal["sha256"] = "sha256"
    value: Annotated[str, Field(pattern=_SHA256_HEX)]
    """Lowercase hex. The pattern is enforced because a truncated or uppercase digest compares
    unequal to a correct one and reads, in a report, as a tampered file."""

    def __str__(self) -> str:
        return f"{self.algorithm}:{self.value}"

    @classmethod
    def of_file(cls, path: pathlib.Path) -> "Digest":
        h = hashlib.sha256()
        with path.open("rb") as fh:
            for block in iter(lambda: fh.read(1 << 20), b""):
                h.update(block)
        return cls(value=h.hexdigest())

    @classmethod
    def of_text(cls, text: str) -> "Digest":
        return cls(value=hashlib.sha256(text.encode("utf-8")).hexdigest())


class ArtifactRef(BaseModel):
    """A file a manifest names, whether or not it has been pinned.

    Separate from `PinnedArtifact` because "identified by content" and "may carry no digest"
    cannot both be true of one type. An unpinned reference is a legitimate thing to write down
    and an illegitimate thing to verify against, and the type says which it is.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    path: pathlib.Path
    digest: Digest | None = None
    media_type: str = "application/octet-stream"

    @property
    def is_pinned(self) -> bool:
        return self.digest is not None


# ---------------------------------------------------------------------------------- evidence

class _EvidenceBase(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    artifact: str
    """Id of the artifact this value is asserted to come from. The artifact carries the pin;
    evidence never repeats a digest, so there is one source of truth per file."""


# --------------------------------------------------------------------------------- locators

#: Scalar types a row predicate may hold. Deliberately not a string expression language: a
#: string predicate needs a parser, coercion rules, and an escaping grammar, and every
#: implementation would disagree about the edges.
PredicateValue = str | int | float | bool


class Locator(BaseModel):
    """Where a value sits in an artifact.

    One contract over several file formats, rather than one pointer syntax pretending every
    file is a tree. JSON Pointer works because JSON has a single tree data model and a
    pointer resolves to at most one value; it says nothing about table keys, multidimensional
    indices, or database rows. Each variant below addresses its format the way that format
    already addresses itself.

    The invariant every variant shares: a locator resolves to **exactly one scalar**. Zero is
    absent, two or more is ambiguous, and a container is not a value. No backend may quietly
    take the first match.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    contract: Literal[1] = 1
    """Version of the locator contract, carried so a stored decision says which rules it was
    resolved under."""

    def canonical(self) -> str:
        """Canonical JSON: sorted keys, no whitespace, no coercion.

        Hashed separately from the artifact, so a decision binds both what was read and how
        it was addressed. Changing a selector changes the digest even where the file does
        not.
        """
        return json.dumps(self.model_dump(mode="json"), sort_keys=True,
                          separators=(",", ":"), ensure_ascii=False)

    @property
    def digest(self) -> Digest:
        return Digest.of_text(self.canonical())


class TreeLocator(Locator):
    """RFC 6901 JSON Pointer into JSON, or into YAML restricted to a JSON-compatible tree."""

    kind: Literal["tree"] = "tree"
    pointer: str


class TableLocator(Locator):
    """A column plus a predicate that must match exactly one row."""

    kind: Literal["table"] = "table"
    column: str
    where: dict[str, PredicateValue] = Field(default_factory=dict)
    delimiter: str = ""

    @model_validator(mode="after")
    def _predicate_must_select(self):
        if not self.where:
            raise ValueError("a table locator needs a `where` predicate; to address by "
                             "position use kind: table_position")
        return self


class TablePositionLocator(Locator):
    """A column plus a row index. Weaker on purpose, and reported as such.

    Sorting, filtering or inserting a row changes what row 37 means, so a positional address
    has no semantic identity. The artifact pin still makes it reproducible, which is why this
    is a distinct locator carrying a warning rather than a refusal.
    """

    kind: Literal["table_position"] = "table_position"
    column: str
    row: int = Field(ge=0)
    delimiter: str = ""


class ArrayLocator(Locator):
    """A named array plus a multidimensional index, for `.npy` and `.npz`."""

    kind: Literal["array"] = "array"
    array: str | None = None
    """Required for `.npz`, which holds many arrays; omitted for `.npy`, which holds one."""
    index: tuple[int, ...]


class SqliteLocator(Locator):
    """A table, a column, and a predicate that must match exactly one row."""

    kind: Literal["sqlite"] = "sqlite"
    table: str
    column: str
    where: dict[str, PredicateValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _predicate_must_select(self):
        if not self.where:
            raise ValueError("a sqlite locator needs a `where` predicate")
        return self


ValueLocator = Annotated[
    TreeLocator | TableLocator | TablePositionLocator | ArrayLocator | SqliteLocator,
    Field(discriminator="kind")]


class QuoteEvidence(_EvidenceBase):
    """Assertion: this passage occurs in this artifact."""

    kind: Literal["quote"] = "quote"

    text: str
    section: str | None = None
    """Where the source puts it, as the source names it. Recorded, never verified."""

    page: int | None = None
    """Verified when present, for paginated sources."""


class ComparisonMode(enum.StrEnum):
    """How a reported number is compared with a stored one."""

    PRINTED_PRECISION = "printed_precision"
    """Compare at the precision the manuscript printed. `3.20` requires two decimals to
    agree; `3.2` requires one. This is why `reported` is a string."""

    ABSOLUTE = "absolute"
    """Agree when |stored - reported| <= tolerance."""

    RELATIVE = "relative"
    """Agree when |stored - reported| <= tolerance * |reported|."""


class MetricEvidence(_EvidenceBase):
    """Assertion: this artifact holds this value at this location."""

    kind: Literal["metric"] = "metric"

    name: str
    reported: str
    """The value exactly as the manuscript prints it, as a string.

    A string because YAML parses `3.20` to the float `3.2`, discarding the precision the
    manuscript chose, and because binary floats do not represent decimal fractions exactly.
    Parsed with `decimal.Decimal`."""

    pointer: str
    """RFC 6901 JSON Pointer: `/comparisons/primary/delta`.

    JSON Pointer rather than a dotted path because a dotted path cannot distinguish a mapping
    key containing a period from a nesting level, nor list index `0` from mapping key `"0"`,
    and specifying an escape grammar for a new selector language is work already done."""

    mode: ComparisonMode = ComparisonMode.PRINTED_PRECISION
    tolerance: str = "0"
    """As a decimal string, for the same reason as `reported`. Ignored for
    `printed_precision`."""

    @property
    def value(self) -> decimal.Decimal:
        return decimal.Decimal(self.reported)

    @property
    def tolerance_value(self) -> decimal.Decimal:
        return decimal.Decimal(self.tolerance)

    @property
    def locator(self) -> TreeLocator:
        """`metric` is sugar for a tree locator, and resolves through the same adapter."""
        return TreeLocator(pointer=self.pointer)


class TableCellEvidence(_EvidenceBase):
    """Assertion: this table holds this value in this cell.

    Most published result artifacts are delimited tables rather than JSON, so addressing a
    cell is what a manuscript's own tables usually need. A cell is named by its column and by
    one of two ways of picking the row.
    """

    kind: Literal["table"] = "table"

    name: str
    reported: str
    """The value exactly as the manuscript prints it, as a string. See `MetricEvidence`."""

    column: str
    """Header name of the column holding the value."""

    row: int | None = None
    """Zero-based index among data rows, excluding the header."""

    where: dict[str, str] = Field(default_factory=dict)
    """Select the row whose named columns hold these values: `{"model": "LASSO-Cox"}`.

    Preferred over `row`, because a row index silently addresses a different cell when a table
    is reordered or a row is inserted, and a table that has been reordered is exactly the case
    a checker exists to notice. A selector matching no rows, or more than one, is reported
    rather than resolved."""

    delimiter: str = ""
    """Override the delimiter. Empty means infer it from the file's suffix and contents."""

    mode: ComparisonMode = ComparisonMode.PRINTED_PRECISION
    tolerance: str = "0"

    @property
    def value(self) -> decimal.Decimal:
        return decimal.Decimal(self.reported)

    @property
    def tolerance_value(self) -> decimal.Decimal:
        return decimal.Decimal(self.tolerance)

    @property
    def addresses_one_row(self) -> bool:
        """Exactly one row selector must be given."""
        return (self.row is None) != (not self.where)

    @property
    def locator(self) -> TableLocator | TablePositionLocator:
        """`table` is sugar for one of the two table locators."""
        if self.row is not None:
            return TablePositionLocator(column=self.column, row=self.row,
                                        delimiter=self.delimiter)
        return TableLocator(column=self.column, where=dict(self.where),
                            delimiter=self.delimiter)


class ValueEvidence(_EvidenceBase):
    """Assertion: this artifact holds this value at this locator.

    The general form. `metric` and `table` remain as shorthand for the two commonest cases,
    and every kind resolves through the same adapters, so a manifest never has to choose
    between a convenient spelling and a supported one.
    """

    kind: Literal["value"] = "value"

    name: str
    reported: str
    """The value exactly as the manuscript prints it, as a string. See `MetricEvidence`."""

    locator: ValueLocator
    """Which value, in the addressing its format already has. Kept separate from `reported`,
    `mode` and `tolerance`: a locator identifies a stored value and says nothing about what
    it should be."""

    mode: ComparisonMode = ComparisonMode.PRINTED_PRECISION
    tolerance: str = "0"

    @property
    def value(self) -> decimal.Decimal:
        return decimal.Decimal(self.reported)

    @property
    def tolerance_value(self) -> decimal.Decimal:
        return decimal.Decimal(self.tolerance)


Evidence = Annotated[QuoteEvidence | MetricEvidence | TableCellEvidence | ValueEvidence,
                     Field(discriminator="kind")]
"""Every kind of evidence, discriminated on `kind`.

`protocol` was a third variant and is not one. Its integrity check is the artifact pin, which
every artifact already carries, and its content check -- that a registered document states a
given hypothesis -- is a quotation against the plan. What remains distinct about a protocol is
temporal: whether a confirmatory run postdates its registration. That needs a run record, is
unimplemented, and is not smuggled in as a third evidence kind in the meantime.
"""


# ------------------------------------------------------------------------------------ claims

class Availability(enum.StrEnum):
    """Whether a claim offers anything to check. A property of the claim, not of a check."""

    OFFERED = "offered"
    NOT_OFFERED = "not_offered"


class Registration(enum.StrEnum):
    """Whether a plan could have fixed this claim's outcome in advance.

    Three states, because two conflate different things. A descriptive measurement that was
    never registered and an exhaustive count that nothing could have registered look identical
    under a boolean and are not the same claim.
    """

    CONFIRMATORY = "confirmatory"
    """Reports a preregistered outcome. The ordering check applies."""
    EXPLORATORY = "exploratory"
    """An outcome that a plan could have fixed and did not. The default: a claim that says
    nothing about registration is exploratory, never inapplicable."""
    NOT_APPLICABLE = "not_applicable"
    """No outcome was selected, so registration has nothing to bind -- an exhaustive
    deterministic measurement reports whatever it finds. Must carry a reason: this state is
    asserted, never assumed, or it is a way for any claim to opt out of being graded."""


class Claim(BaseModel):
    """A statement made in a manuscript, and the evidence offered for it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    text: str
    where: str | None = None
    registration: Registration = Registration.EXPLORATORY
    registration_note: str = ""
    """Why registration does not apply. Required when `registration` is `not_applicable`, and
    the same convention a preregistration uses for an inapplicable heading: N/A with a reason,
    never a blank."""

    evidence: tuple[Evidence, ...] = ()

    @model_validator(mode="before")
    @classmethod
    def _accept_confirmatory_flag(cls, data):
        """`confirmatory: true|false` still parses, so manifests written against the boolean
        keep working. `false` becomes `exploratory` and not `not_applicable`: a boolean never
        carried the distinction, so reading one in cannot invent it."""
        if isinstance(data, dict) and "confirmatory" in data:
            data = dict(data)
            flag = data.pop("confirmatory")
            data.setdefault("registration", Registration.CONFIRMATORY if flag
                            else Registration.EXPLORATORY)
        return data

    @model_validator(mode="after")
    def _not_applicable_needs_a_reason(self):
        if self.registration is Registration.NOT_APPLICABLE and not self.registration_note:
            raise ValueError(
                f"claim {self.id!r}: registration 'not_applicable' needs a registration_note "
                f"saying why no plan could have fixed this outcome")
        return self

    @property
    def confirmatory(self) -> bool:
        return self.registration is Registration.CONFIRMATORY

    @property
    def availability(self) -> Availability:
        return Availability.OFFERED if self.evidence else Availability.NOT_OFFERED

    @property
    def digest(self) -> Digest:
        """Content address of the claim as evaluated.

        A decision names this so it cannot silently remain attached to text that has since
        been edited.
        """
        return Digest.of_text(f"{self.id}\x00{self.text}\x00{self.where or ''}")


# ---------------------------------------------------------------------------------- outcomes

class ExecutionStatus(enum.StrEnum):
    COMPLETED = "completed"
    UNAVAILABLE = "unavailable"
    """The backend could not run: a missing binary, an unreadable file, an absent registry."""
    FAILED = "failed"
    """The backend raised something unexpected. A defect, never a scientific outcome."""


class ExtractionStatus(enum.StrEnum):
    EXTRACTED = "extracted"
    ABSENT = "absent"
    """The artifact was read and holds no such value. Silence, which is not contradiction."""
    INVALID = "invalid"
    """A value was located and is not of the type the assertion requires."""
    NOT_ATTEMPTED = "not_attempted"


class ComparisonStatus(enum.StrEnum):
    MATCH = "match"
    MISMATCH = "mismatch"
    NOT_APPLICABLE = "not_applicable"


class Outcome(enum.StrEnum):
    """The flattened view, for display and for tools that want one field.

    Derived from the three stages, never set directly, so the flattening cannot drift from
    what the stages say.
    """

    VERIFIED = "verified"
    MISMATCH = "mismatch"
    NOT_FOUND = "not_found"
    UNCHECKED = "unchecked"
    ERROR = "error"
    NOT_OFFERED = "not_offered"


class Ordering(enum.StrEnum):
    """Whether a confirmatory claim's evidence was produced after the plan it names.

    The outcome is separate from the reason, on the same principle the evidence stages
    follow: a check that could not run is not a check that failed. `unchecked` carries an
    `OrderingReason` saying which of eight conditions stopped it, because collapsing a
    missing run record, an unpinned plan, and an unlinked output into one word loses the
    only information that says what to fix.
    """

    ORDERED = "ordered"
    """Every run producing this claim's evidence started after its plan was registered."""
    VIOLATED = "violated"
    """A run started before the plan it names was registered."""
    UNCHECKED = "unchecked"
    """The record does not settle it. Not a finding that the ordering is wrong."""
    NOT_APPLICABLE = "not_applicable"
    """The claim is not confirmatory, so there is no registration for it to postdate."""


class OrderingReason(enum.StrEnum):
    """Why an ordering check reached the outcome it did."""

    RUN_FOLLOWS_REGISTRATION = "run_follows_registration"
    RUN_PRECEDES_REGISTRATION = "run_precedes_registration"
    NO_RUN_RECORD = "no_run_record"
    NO_REGISTERED_PLAN = "no_registered_plan"
    REGISTERED_PLAN_UNPINNED = "registered_plan_unpinned"
    REGISTERED_PLAN_CHANGED = "registered_plan_changed"
    RUN_OUTPUT_UNLINKED = "run_output_unlinked"
    """The run names an artifact but records no digest for it, so a later file with the same
    name can be presented as the output of an earlier run."""
    RUN_OUTPUT_CHANGED = "run_output_changed"
    TIMESTAMP_MISSING = "timestamp_missing"
    AMBIGUOUS_PRODUCING_RUN = "ambiguous_producing_run"
    NOT_CONFIRMATORY = "not_confirmatory"


class RegistrationAuthority(enum.StrEnum):
    """Who attests to the registration timestamp.

    A hash and two self-recorded timestamps establish internal consistency, not chronology:
    an actor who can write `registered_at`, `started_at` and the plan digest after seeing
    results can manufacture an ordered history. Recording the authority makes that limit a
    field rather than a caveat, and lets a policy require better than the weakest one.
    """

    SELF_RECORDED = "self_recorded"
    GIT_REMOTE = "git_remote"
    OSF = "osf"
    ZENODO = "zenodo"
    TRUSTED_TIMESTAMP = "trusted_timestamp"

    @property
    def rank(self) -> int:
        return _AUTHORITY_RANK[self]


_AUTHORITY_RANK = {
    RegistrationAuthority.SELF_RECORDED: 0,
    RegistrationAuthority.GIT_REMOTE: 1,
    RegistrationAuthority.OSF: 2,
    RegistrationAuthority.ZENODO: 2,
    RegistrationAuthority.TRUSTED_TIMESTAMP: 3,
}


class Validity(enum.StrEnum):
    """Whether a decision describes the artifact the manifest declared."""

    AUTHORITATIVE = "authoritative"
    UNPINNED_ARTIFACT = "unpinned_artifact"
    """No digest was recorded, so the file read may not be the file meant."""
    BROKEN_PIN = "broken_pin"
    """The file read is provably not the file that was pinned. The comparison still ran and
    its result is reported, marked non-authoritative, because a diagnostic is more useful than
    a blank."""
    ARTIFACT_ABSENT = "artifact_absent"
    """Nothing exists at the declared path. No comparison ran, so no decision against this
    artifact describes anything that was read."""


class Reason(enum.StrEnum):
    """Why an outcome obtained. Machine-readable, so a tool can route by cause."""

    PASSAGE_PRESENT = "passage_present"
    VALUE_MATCH = "value_match"
    PASSAGE_ABSENT = "passage_absent"
    VALUE_MISMATCH = "value_mismatch"
    POINTER_ABSENT = "pointer_absent"
    COLUMN_ABSENT = "column_absent"
    ROW_ABSENT = "row_absent"
    ROW_AMBIGUOUS = "row_ambiguous"
    ROW_SELECTOR_INVALID = "row_selector_invalid"
    SELECTOR_NOT_SCALAR = "selector_not_scalar"
    """The locator resolved to a container. A list or mapping is not a value."""
    FORMAT_UNSUPPORTED = "format_unsupported"
    """No adapter addresses this format. Reported rather than approximated: falling back to
    searching the file for the printed number would find it wherever it appears and call
    that verification."""
    VALUE_NOT_NUMERIC = "value_not_numeric"
    EXTRACTOR_MISSING = "extractor_missing"
    ARTIFACT_MISSING = "artifact_missing"
    ARTIFACT_UNREADABLE = "artifact_unreadable"
    ARTIFACT_UNDECLARED = "artifact_undeclared"
    BACKEND_DEFECT = "backend_defect"
    NOT_OFFERED = "not_offered"


class Warning_(enum.StrEnum):
    """Notes about the evidence itself, orthogonal to the outcome."""

    SHORT = "short"
    TRUNCATED = "truncated"
    NORMALIZED = "normalized"
    WRONG_PAGE = "wrong_page"
    POSITIONAL_ADDRESS = "positional_address"
    """Addressed by row index, which names a different cell if the table is reordered."""


class Decision(BaseModel):
    """The outcome of evaluating one evidence assertion. Frozen: a decision that can be
    edited after the fact records nothing."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    claim_id: str
    claim_digest: str
    kind: str

    execution: ExecutionStatus
    extraction: ExtractionStatus
    comparison: ComparisonStatus
    reason: Reason
    detail: str = ""

    validity: Validity = Validity.AUTHORITATIVE
    artifact_id: str = ""
    artifact_digest: str | None = None
    """The digest of the bytes actually read, so the decision can be re-checked against the
    same content rather than the same path."""

    locator_digest: str | None = None
    """The digest of the canonical locator, so a decision binds how the value was addressed
    as well as what was read. A selector edited after the fact changes this even where the
    artifact is untouched."""

    backend: str = ""
    backend_version: str = ""
    """Named because the same inputs can receive different decisions after a backend upgrade,
    and a stored decision that does not say which backend produced it cannot be compared with
    a later one."""

    warnings: tuple[Warning_, ...] = ()

    @property
    def outcome(self) -> Outcome:
        if self.execution is ExecutionStatus.FAILED:
            return Outcome.ERROR
        if self.execution is ExecutionStatus.UNAVAILABLE:
            return Outcome.UNCHECKED
        if self.extraction in (ExtractionStatus.ABSENT, ExtractionStatus.INVALID):
            return Outcome.NOT_FOUND
        if self.comparison is ComparisonStatus.MATCH:
            return Outcome.VERIFIED
        if self.comparison is ComparisonStatus.MISMATCH:
            return Outcome.MISMATCH
        return Outcome.UNCHECKED

    @property
    def is_authoritative(self) -> bool:
        return self.validity is Validity.AUTHORITATIVE


# ---------------------------------------------------------------------------------- manifest

class Provenance(BaseModel):
    """Where a manifest's artifacts came from.

    Recorded, never verified. The pin is the artifact's digest: a commit identifies a tree,
    and a tree does not establish that the file on disk today is the file that was in it.
    A reader who wants these exact bytes uses the commit to fetch them and the digest to
    confirm they arrived.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    repository: str = ""
    """Remote URL, or a local path where there is no remote."""

    commit: str = ""
    """Full SHA of the revision the artifacts were read from."""

    dirty: bool = False
    """Whether the working tree had uncommitted changes when the manifest was written. A
    manifest built from a dirty tree names a commit that does not contain what was read."""

    generated_by: str = ""
    """The script that wrote this manifest, so the figures can be regenerated."""


class RunOutput(BaseModel):
    """An artifact a run produced, bound by digest rather than by name.

    Naming the artifact alone is not a binding: a later file written to the same path can be
    presented as the output of an earlier run, which is the manoeuvre the ordering check
    exists to detect. A run that records no digest is reported `run_output_unlinked`.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    artifact: str
    digest: Digest | None = None

    @model_validator(mode="before")
    @classmethod
    def _accept_a_bare_id(cls, data):
        """`outputs: [results]` parses, and is reported as unlinked rather than rejected."""
        return {"artifact": data} if isinstance(data, str) else data


class RunRecord(BaseModel):
    """A computation that produced artifacts, and the plan it was registered under."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    registered_plan: str = ""
    """The plan this run was registered under. Where it names a declared artifact, that
    document is pinned, so it cannot be edited after the fact without breaking the pin."""

    registration_authority: RegistrationAuthority = RegistrationAuthority.SELF_RECORDED
    """Who attests to `registered_at`. Defaults to the weakest, which is what an unqualified
    timestamp in a file actually is."""

    registered_at: AwareDatetime | None = None
    started_at: AwareDatetime | None = None
    """Both must carry an offset. A naive timestamp compared against an aware one is either a
    crash or a silently wrong ordering, and an ordering that is wrong by a timezone is the
    failure this check exists to catch."""

    outputs: tuple[RunOutput, ...] = ()

    def output(self, artifact_id: str) -> "RunOutput | None":
        return next((o for o in self.outputs if o.artifact == artifact_id), None)


class Regeneration(enum.StrEnum):
    """Whether the declared command reproduced the artifact it claims to have produced."""

    REPRODUCED = "reproduced"
    DIVERGED = "diverged"
    UNCHECKED = "unchecked"
    """Not attempted, or the inputs are not the ones declared. Regeneration is opt-in, so
    this is the ordinary state, not a finding."""


class RegenerationReason(enum.StrEnum):
    OUTPUT_MATCHES = "output_matches"
    OUTPUT_DIFFERS = "output_differs"
    NOT_REQUESTED = "not_requested"
    INPUT_UNPINNED = "input_unpinned"
    INPUT_CHANGED = "input_changed"
    INPUT_MISSING = "input_missing"
    COMMAND_FAILED = "command_failed"
    """The command exited non-zero. Where the inputs were copied into an empty directory,
    this also catches a script that needs a file the manifest never declared."""
    COMMAND_TIMED_OUT = "command_timed_out"
    OUTPUT_NOT_PRODUCED = "output_not_produced"
    RUNNER_UNAVAILABLE = "runner_unavailable"


class RegenerationRecord(BaseModel):
    """A command that produces an artifact from declared inputs.

    The honest analogue of the ordering check for a measurement no plan could have
    registered: not "did this follow its plan" but "does the pinned code, over the pinned
    inputs, still produce this". Opt-in, because it executes a command.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    command: tuple[str, ...]
    """argv, never a shell string. A shell string needs quoting rules, brings a shell's
    expansion with it, and turns a manifest into something that can run anything."""

    inputs: tuple[RunOutput, ...] = ()
    """Every artifact the command reads. Only these are placed in the working directory, so
    a command needing an undeclared file fails and says so."""

    output: RunOutput
    """The artifact the command writes, and the digest it is expected to have."""

    volatile: tuple[str, ...] = ()
    """JSON Pointers to fields removed before comparing. Literal byte identity is the right
    test only after timestamps, paths and environment metadata are controlled; naming them
    keeps the comparison honest instead of loosening it everywhere."""

    timeout_seconds: float = 300.0

    @model_validator(mode="after")
    def _command_is_not_empty(self):
        if not self.command:
            raise ValueError(f"regeneration {self.id!r}: command is empty")
        return self


class RegenerationState(BaseModel):
    """What happened when a regeneration record was checked."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    regeneration_id: str
    artifact_id: str
    state: Regeneration
    reason: RegenerationReason
    expected: str | None = None
    actual: str | None = None
    detail: str = ""


class Manifest(BaseModel):
    """One project: its artifacts and its claims."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = SCHEMA_VERSION
    project: str = ""
    provenance: Provenance | None = None
    artifacts: tuple[ArtifactRef, ...] = ()
    claims: tuple[Claim, ...] = ()
    runs: tuple[RunRecord, ...] = ()
    regenerations: tuple[RegenerationRecord, ...] = ()

    path: pathlib.Path | None = Field(default=None, exclude=True)

    def artifact(self, artifact_id: str) -> ArtifactRef | None:
        return next((a for a in self.artifacts if a.id == artifact_id), None)

    def resolve(self, artifact: ArtifactRef) -> pathlib.Path:
        if artifact.path.is_absolute() or self.path is None:
            return artifact.path
        return (self.path.parent / artifact.path).resolve()


# ------------------------------------------------------------------------------------ report

class ArtifactState(BaseModel):
    """What was found at each artifact's path, before any evidence was read."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    artifact_id: str
    validity: Validity
    expected: str | None = None
    actual: str | None = None
    exists: bool = True


class ClaimAssessment(BaseModel):
    """One claim's availability, and the decisions on the evidence it offered."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    claim_id: str
    claim_digest: str
    confirmatory: bool = False
    registration: Registration = Registration.EXPLORATORY
    registration_note: str = ""
    availability: Availability
    ordering: Ordering = Ordering.NOT_APPLICABLE
    ordering_reason: OrderingReason = OrderingReason.NOT_CONFIRMATORY
    ordering_detail: str = ""
    registration_authority: RegistrationAuthority | None = None
    """The weakest authority among the runs that produced this claim's evidence, or None
    where no run applies."""
    decisions: tuple[Decision, ...] = ()

    @property
    def outcomes(self) -> tuple[Outcome, ...]:
        if self.availability is Availability.NOT_OFFERED:
            return (Outcome.NOT_OFFERED,)
        return tuple(d.outcome for d in self.decisions)


class VerificationReport(BaseModel):
    """Facts about what was checked. Frozen, and carries no verdict.

    Whether a project passes is a policy question -- a missing optional citation may be
    acceptable where an unchecked confirmatory result is not -- so the engine reports what
    happened and `repro.policy` decides what it means.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = SCHEMA_VERSION
    project: str = ""
    manifest_digest: str = ""
    artifacts: tuple[ArtifactState, ...] = ()
    claims: tuple[ClaimAssessment, ...] = ()
    regenerations: tuple[RegenerationState, ...] = ()

    @property
    def decisions(self) -> tuple[Decision, ...]:
        return tuple(d for c in self.claims for d in c.decisions)

    @property
    def counts(self) -> dict[str, int]:
        tally: dict[str, int] = {}
        for claim in self.claims:
            for outcome in claim.outcomes:
                tally[outcome.value] = tally.get(outcome.value, 0) + 1
        return tally

    def artifacts_with(self, validity: Validity) -> tuple[str, ...]:
        return tuple(a.artifact_id for a in self.artifacts if a.validity is validity)


__all__ = [
    "SCHEMA_VERSION",
    "Digest", "ArtifactRef", "ArtifactState", "Provenance",
    "Evidence", "QuoteEvidence", "MetricEvidence", "TableCellEvidence", "ComparisonMode",
    "Claim", "Availability", "Manifest",
    "ExecutionStatus", "ExtractionStatus", "ComparisonStatus",
    "ValueEvidence", "Locator", "TreeLocator", "TableLocator", "TablePositionLocator", "ArrayLocator",
    "SqliteLocator", "ValueLocator", "PredicateValue",
    "Outcome", "Validity", "Reason", "Warning_", "Ordering", "OrderingReason", "RegistrationAuthority", "RunRecord", "RunOutput",
    "Registration", "Regeneration", "RegenerationReason",
    "RegenerationRecord", "RegenerationState",
    "Decision", "ClaimAssessment", "VerificationReport",
]
