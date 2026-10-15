"""A PaperDelta report, read into one check record per occurrence and per comparative claim.

PaperDelta (https://github.com/amos689/paperdelta, MIT) reads a printed number from the
manuscript at an anchor, derives the expected value from the result files, renders it at the
places `paperdelta.yaml` declares under its own rounding mode, and compares the two. Its
`report.json` holds what it found for each occurrence. This module states that answer in the
check record's vocabulary, as PaperDelta gave it, and does not check anything again:

- an occurrence of a metric reduced `unique` is a `value-comparison`; one reduced `mean`,
  `sum` or `count`, or `statistics` printed as its mean, is an `aggregate-comparison` with one
  entry in `reads` per selected row;
- an occurrence of a derived metric, a statistic other than the mean, a compound display and a
  comparative claim are `other`: no check type of the record computes over two metrics or tests
  "A is greater than B", and PaperDelta's words for what was compared travel under
  `paperdelta`;
- `pass` is `match` and `mismatch` is `mismatch`; `unknown` is placed by its error code, and a
  code not listed here is `not-checked`, never a mismatch;
- a `pass` is `not-checked` where the report as a whole is unsettled: a finding on the project
  or on anything else that is no one item, such as `INPUT_CHANGED` or `INCOMPLETE_COVERAGE`,
  or an exit code the items' own findings do not account for. The finding is named as the
  reason. An exit code an item's own `unknown` or `mismatch` accounts for leaves every other
  number as reported.

The report does not carry the display or the rounding mode, so the configuration it was made
from is read too, and refused unless the report records a sha256 for it and that is its
sha256. A report that records none is refused, not read without the check. No file
is pinned in PaperDelta, so every file read is `unpinned_artifact`, with the digest the report
records as the one on disk.

`rerun=True` puts each value and aggregate comparison PaperDelta completed to this toolkit's
rule as well (the printed precision, half-even, either neighbor on a tie, and a number stored
as text is not a number), over the stored values the report lists. The record's outcome stays
PaperDelta's; the second answer is under `rerun`. Nothing is run and no PaperDelta code is
imported.
"""

from __future__ import annotations

import datetime
import decimal
import fractions
import hashlib
import json
import mimetypes
import pathlib
import re
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from claims import __version__
from claims.foreign.common import ForeignError, aware
from claims.models import ComparisonMode, Conversion, Digest, Statistic, Validity
from claims.record import (
    Address,
    AssertionRef,
    Checker,
    CheckType,
    ClaimRef,
    Comparison,
    ExportRecord,
    FileRead,
    ManifestRef,
    NormalizedOutcome,
)
from claims.verify import _aggregate, _agree, _agree_exact, _plain

CHECKER = "paperdelta"
CHECKER_URL = "https://github.com/amos689/paperdelta"
READER = "claims from-paperdelta"

#: The report schema versions this reader has read the definition of (`records.py`,
#: `REPORT_SCHEMA_MAX` at commit d73f574).
KNOWN_SCHEMAS = range(1, 10)

#: The rule `rerun` applies, in words a record carries.
OUR_RULE = "printed precision, half-even, either neighbor on a tie; text is not a number"

#: PaperDelta's error codes on an `unknown`, by the outcome each is in the record. A code not
#: listed is `not-checked`: an unknown word is never guessed into a finding.
NOT_FOUND_CODES = frozenset(
    {
        "MISSING_VALUE", "EMPTY_SELECTION", "AMBIGUOUS_SELECTION", "ANCHOR_MISSING",
        "ANCHOR_AMBIGUOUS", "INVALID_POINTER", "MISSING_COLUMN",
    }
)  # fmt: skip
NOT_CHECKED_CODES = frozenset(
    {
        "FILE_UNAVAILABLE", "UNSUPPORTED_SPAN", "UNSUPPORTED_DISPLAY", "RECORD_COUNT",
        "SEED_SET", "UNIT_MISMATCH", "STATISTICS_MISSING", "NUMERIC_ANCHOR", "PARTIAL_NUMBER",
    }
)  # fmt: skip
NOT_CHECKED_PREFIXES = ("UNREACHABLE_",)
ERROR_CODES = frozenset({"INVALID_JSON", "INVALID_CSV", "INVALID_NUMBER", "NONFINITE_NUMBER"})
ERROR_PREFIXES = ("XLSX_", "EXPORT_")

#: How a statistical display is read: its mean is an aggregate; anything else is `other`.
_MEAN = "mean"

_OUTCOMES = {"pass": NormalizedOutcome.MATCH, "mismatch": NormalizedOutcome.MISMATCH}

#: PaperDelta's reductions, by the record's statistic.
_STATISTICS = {"mean": Statistic.MEAN, "sum": Statistic.SUM, "count": Statistic.COUNT}


class PaperDeltaError(ForeignError):
    """A PaperDelta report, or the configuration it was made from, could not be read as one."""


# ----------------------------------------------------------------------- PaperDelta's files


class _Read(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")


class SourceEvidence(_Read):
    """One source's selected rows in a metric's state, in PaperDelta's field names."""

    source: str
    path: str
    field: str
    reduce: str
    count: int
    records: tuple[dict[str, Any], ...]
    locations: tuple[dict[str, Any], ...]
    format: str | None = None


class MetricState(_Read):
    status: str
    value: str | None = None
    unit: str | None = None
    definition: dict[str, Any] | None = None
    evidence: tuple[SourceEvidence, ...] = ()
    error: str | None = None

    @field_validator("value")
    @classmethod
    def _a_value_is_decimal_text(cls, value: str | None) -> str | None:
        """PaperDelta writes a metric's value as decimal text; anything else is not a report it
        wrote."""
        if value is None:
            return None
        try:
            number = decimal.Decimal(value)
        except decimal.InvalidOperation:
            raise ValueError(f"{value!r} is not decimal text") from None
        if not number.is_finite():
            raise ValueError(f"{value!r} is not a finite number")
        return value


class OccurrenceState(_Read):
    metric: str
    status: str
    location: dict[str, Any] | None = None
    expected: str | None = None
    actual: str | None = None
    evidence_fingerprint: str | None = None
    suggestion: dict[str, Any] | None = None
    error: str | None = None
    usage: str | None = None


class ClaimState(_Read):
    status: str
    metrics: tuple[str, ...] = ()
    location: dict[str, Any] | None = None
    error: str | None = None


class Diagnostic(_Read):
    """One finding in a report's `diagnostics`, in PaperDelta's field names."""

    rule: str
    subject: str = ""
    severity: str = ""
    message: str = ""


class Report(_Read):
    """The parts of a stored `report.json` a record is made from."""

    created_at: str
    report_schema_version: int
    tool_version: str
    ruleset_version: str
    config_path: str
    input_hashes: dict[str, str]
    metrics: dict[str, MetricState]
    occurrences: dict[str, OccurrenceState]
    claims: dict[str, ClaimState] = {}
    diagnostics: tuple[Diagnostic, ...] = ()
    exit_code: int | None = None


class Display(_Read):
    kind: str = "decimal"
    places: int = 1
    percent_symbol: bool = True
    statistics: dict[str, Any] | None = None


class OccurrenceConfig(_Read):
    file: str
    metric: str
    display: Display = Display()


class Source(_Read):
    path: str


class Config(_Read):
    """The parts of `paperdelta.yaml` the report does not repeat."""

    rounding: str = "half_up"
    sources: dict[str, Source] = {}
    metrics: dict[str, dict[str, Any]] = {}
    occurrences: dict[str, OccurrenceConfig] = {}
    claims: dict[str, dict[str, Any]] = {}


class Rerun(BaseModel):
    """One comparison put to this toolkit's rule, beside PaperDelta's answer."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    rule: str = OUR_RULE
    outcome: NormalizedOutcome
    detail: str
    agrees: bool
    """Whether the outcome is PaperDelta's."""


class PaperDeltaReading(BaseModel):
    """What one report gave: the records, and where the two rules disagree."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    records: tuple[ExportRecord, ...]
    disagreements: tuple[str, ...] = Field(default=())
    """Occurrences whose rerun outcome is not PaperDelta's, where `rerun` was asked for."""


class _DecimalLoader(yaml.SafeLoader):
    """The safe loader, with every float kept as the decimal written."""


_DecimalLoader.add_constructor(
    "tag:yaml.org,2002:float",
    lambda loader, node: decimal.Decimal(loader.construct_scalar(node)),
)


def _report(raw: bytes, where: str) -> Report:
    try:
        # Decimal-preserving: a stored 0.810 stays those digits.
        document = json.loads(raw.decode("utf-8"), parse_float=decimal.Decimal)
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise PaperDeltaError(f"{where} is not JSON: {e}") from e
    try:
        report = Report.model_validate(document)
    except ValidationError as e:
        raise PaperDeltaError(f"{where} is not a PaperDelta report: {e}") from e
    if report.report_schema_version not in KNOWN_SCHEMAS:
        raise PaperDeltaError(
            f"{where} is report schema {report.report_schema_version}; this reader knows "
            f"{KNOWN_SCHEMAS.start} to {KNOWN_SCHEMAS.stop - 1}"
        )
    return report


def _config(raw: bytes, where: str) -> Config:
    try:
        document = yaml.load(raw.decode("utf-8"), Loader=_DecimalLoader)
    except (UnicodeDecodeError, yaml.YAMLError) as e:
        raise PaperDeltaError(f"{where} is not YAML: {e}") from e
    try:
        return Config.model_validate(document)
    except ValidationError as e:
        raise PaperDeltaError(f"{where} is not a PaperDelta configuration: {e}") from e


# ----------------------------------------------------------------------------- the mapping


def _hex(hashed: str | None) -> str | None:
    """`sha256:<hex>` as the record writes a digest, or None for another form."""
    if hashed and re.fullmatch(r"sha256:[a-f0-9]{64}", hashed):
        return hashed.removeprefix("sha256:")
    return None


def _relative(path: str) -> str:
    """A path as a record names it: never absolute, since records are published."""
    pure = pathlib.PurePosixPath(path.replace("\\", "/"))
    return pure.name if pure.is_absolute() or re.match(r"^[A-Za-z]:", path) else pure.as_posix()


def checked_at(created_at: str, given: datetime.timezone | None) -> datetime.datetime:
    """When the report was made, with an offset: its own, or `given` where it was written with
    none. A time zone is never assumed."""
    return aware(created_at, given, "created_at")


#: The subjects of PaperDelta's findings about one item a record states: one number, one
#: comparative claim, or a metric one of them reads, whose failure is that item's own. A finding
#: on any other subject, such as `project`, a manuscript file, a figure, a fragment, a producer
#: record or an export, is stated by no record, and no record's result explains it.
ITEM_SUBJECTS = ("occurrence:", "claim:", "metric:")

#: The exit code each severity makes, as PaperDelta derives it.
_EXIT = {"unknown": 2, "error": 1}


def unsettled(report: Report) -> tuple[str, str] | None:
    """Why the report as a whole leaves a number's `pass` unsettled, as a rule and in words, or
    None where nothing does.

    PaperDelta reports a failure of the whole run, such as `INPUT_CHANGED` (a file changed
    while it was being checked) or `INCOMPLETE_COVERAGE`, as a finding on the subject
    `project`, and leaves every occurrence's status as it was. Any finding of severity
    `unknown` or `error` on a subject no record states (a figure, a fragment, a producer record or
    an export among them) is read the same way, whether or not the report carries an exit code. An exit code above the one the items' own findings make (2
    for an `unknown`, 1 for an `error`, 0 for none) is a failure nothing in the report names.
    An exit code the items' findings account for leaves each number's pass as reported.
    """
    run = [
        found
        for found in report.diagnostics
        if found.severity in _EXIT and not found.subject.startswith(ITEM_SUBJECTS)
    ]
    if run:
        rules = ", ".join(dict.fromkeys(found.rule for found in run))
        subjects = ", ".join(dict.fromkeys(found.subject for found in run))
        return rules, f"PaperDelta reports {rules} for {subjects}, which no number or claim here is"
    explained = max(
        (_EXIT[found.severity] for found in report.diagnostics if found.severity in _EXIT),
        default=0,
    )
    if report.exit_code is not None and report.exit_code > explained:
        return (
            f"EXIT_{report.exit_code}",
            f"PaperDelta exited {report.exit_code}, which no finding in the report accounts for",
        )
    return None


def outcome_of(status: str, code: str | None) -> NormalizedOutcome:
    """The record's outcome for a PaperDelta status and, on `unknown`, its error code."""
    if status in _OUTCOMES:
        return _OUTCOMES[status]
    if code in NOT_FOUND_CODES:
        return NormalizedOutcome.NOT_FOUND
    if code in ERROR_CODES or (code or "").startswith(ERROR_PREFIXES):
        return NormalizedOutcome.ERROR
    return NormalizedOutcome.NOT_CHECKED


def _where(location: dict[str, Any] | None, file: str) -> str:
    """Where the manuscript prints it, as text: file, then line and column or page."""
    if not location:
        return _relative(file)
    said = _relative(str(location.get("file") or file))
    if location.get("line"):
        return f"{said}:{location['line']}:{location.get('column', 1)}"
    page = (location.get("locator") or {}).get("page")
    return f"{said}, page {page}" if page else said


def _address(field: str, location: dict[str, Any], index: int, count: int) -> Address:
    """A PaperDelta evidence location as a record's address."""
    if "pointer" in location and "snapshot" in location:
        # A row of a normalized export: a pointer into a snapshot, not into the source file.
        named = {key: value for key, value in location.items() if key != "kind"}
        if "kind" in location:
            named["paperdelta_kind"] = location["kind"]
        return Address(kind="paperdelta-export", **named)
    if "pointer" in location:
        pointer = str(location["pointer"])
        # A pointer to a list selects every element; one to anything else is the one value.
        if count > 1:
            return Address(kind="tree", pointer=f"{pointer}/{index}")
        return Address(kind="tree", pointer=pointer, index=index)
    if "sheet" in location:
        return Address(
            kind="sheet",
            sheet=location["sheet"],
            column=field,
            where=location.get("key", {}),
            row=location.get("row"),
            cell=location.get("cell"),
        )
    return Address(
        kind="table", column=field, where=location.get("key", {}), line=location.get("line")
    )


def _stored_text(value: Any) -> str:
    """A stored value as text. An empty cell is the empty string; any other non-number is
    written as JSON."""
    if value is None:
        return ""
    if isinstance(value, decimal.Decimal | int) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, str):
        return value
    return json.dumps(value, default=str)


def _number(value: Any) -> decimal.Decimal | None:
    """A stored value as a number, where it is one: text is not, under this toolkit's rule."""
    if isinstance(value, bool) or not isinstance(value, decimal.Decimal | int):
        return None
    number = decimal.Decimal(value)
    return number if number.is_finite() else None


def _printed(actual: str | None) -> tuple[decimal.Decimal | None, bool]:
    """The number the manuscript prints, and whether a percent sign follows it."""
    if actual is None:
        return None, False
    compact = re.sub(r"\s|\\[,;! ]|~", "", actual).replace("−", "-")
    percent = compact.endswith(("\\%", "%"))
    compact = compact.removesuffix("\\%").removesuffix("%")
    if re.fullmatch(r"[+-]?\d{1,3}(,\d{3})+(\.\d+)?", compact):
        compact = compact.replace(",", "")
    try:
        number = decimal.Decimal(compact)
    except decimal.InvalidOperation:
        return None, percent
    return (number if number.is_finite() else None), percent


def _conversion(unit: str | None, display: Display) -> Conversion | None:
    return Conversion.PERCENT if unit == "fraction" and display.kind == "percent" else None


def _media_type(path: str) -> str:
    return mimetypes.guess_type(path)[0] or "application/octet-stream"


def _reads(
    evidence: tuple[SourceEvidence, ...],
    hashes: dict[str, str],
    compared: bool,
    conversion: Conversion | None,
) -> tuple[FileRead, ...]:
    """One entry per selected row, with its value where a comparison ran."""
    reads = []
    for source in evidence:
        for index, (record, location) in enumerate(
            zip(source.records, _spread(source.locations, len(source.records)), strict=True)
        ):
            value = record.get("value")
            number = _number(value) if value is not None else None
            if number is None and isinstance(value, str):
                try:
                    number = decimal.Decimal(value)
                except decimal.InvalidOperation:
                    number = None
            reads.append(
                FileRead(
                    artifact=source.source,
                    path=_relative(source.path),
                    media_type=_media_type(source.path),
                    validity=Validity.UNPINNED_ARTIFACT,
                    on_disk=_hex(hashes.get(source.path)),
                    address=_address(source.field, location, index, source.count),
                    stored=_stored_text(value) if compared else None,
                    converted=_plain(conversion.apply(number))
                    if compared and conversion is not None and number is not None
                    else None,
                )
            )
    return tuple(reads)


def _spread(locations: tuple[dict[str, Any], ...], count: int) -> tuple[dict[str, Any], ...]:
    """A JSON source has one location for every row it selects; a table has one per row."""
    if len(locations) == count:
        return locations
    if len(locations) == 1:
        return locations * count
    raise PaperDeltaError(f"{count} rows are selected and {len(locations)} located")


def _sources(
    metric: str, report: Report, config: Config, seen: frozenset[str] = frozenset()
) -> tuple[FileRead, ...]:
    """The files a metric reads where the report lists no rows for it: its source in the
    configuration, or the sources of a derived metric's arguments. No address and no value."""
    definition = config.metrics.get(metric, {})
    if "args" in definition and metric not in seen:
        return tuple(
            read
            for argument in definition["args"]
            for read in _sources(str(argument), report, config, seen | {metric})
        )
    source = config.sources.get(str(definition.get("source", "")))
    if source is None:
        return ()
    return (
        FileRead(
            artifact=str(definition["source"]),
            path=_relative(source.path),
            media_type=_media_type(source.path),
            validity=Validity.UNPINNED_ARTIFACT,
            on_disk=_hex(report.input_hashes.get(source.path)),
        ),
    )


def _kind(state: MetricState | None, display: Display) -> tuple[str, CheckType, str | None]:
    """The assertion kind, the check type and the statistic for one occurrence."""
    definition = (state.definition if state else None) or {}
    if "op" in definition:
        return "derived", CheckType.OTHER, None
    component = (display.statistics or {}).get("component")
    reduce = str(definition.get("reduce", "unique"))
    if component is not None and component != _MEAN:
        return "statistics", CheckType.OTHER, None
    if reduce == "statistics":
        return "aggregate", CheckType.AGGREGATE_COMPARISON, Statistic.MEAN.value
    if reduce in _STATISTICS:
        return "aggregate", CheckType.AGGREGATE_COMPARISON, _STATISTICS[reduce].value
    return "value", CheckType.VALUE_COMPARISON, None


def _rerun(
    check_type: CheckType,
    statistic: str | None,
    printed: decimal.Decimal | None,
    state: MetricState,
    conversion: Conversion | None,
    theirs: NormalizedOutcome,
) -> Rerun:
    """One comparison under this toolkit's rule, over the stored values the report lists."""

    def answer(outcome: NormalizedOutcome, detail: str) -> Rerun:
        return Rerun(outcome=outcome, detail=detail, agrees=outcome is theirs)

    if printed is None:
        return answer(NormalizedOutcome.NOT_CHECKED, "the printed text is not one number")
    values = [record.get("value") for source in state.evidence for record in source.records]
    numbers = [_number(value) for value in values]
    if statistic != Statistic.COUNT.value and any(number is None for number in numbers):
        said = ", ".join(
            repr(_stored_text(v)) for v, n in zip(values, numbers, strict=True) if n is None
        )
        return answer(NormalizedOutcome.NOT_FOUND, f"stored as no number: {said}")
    converted = [
        conversion.apply(number) if conversion and number is not None else number
        for number in numbers
    ]
    mode, zero = ComparisonMode.PRINTED_PRECISION, decimal.Decimal(0)
    if check_type is CheckType.VALUE_COMPARISON:
        if len(converted) != 1 or converted[0] is None:
            return answer(NormalizedOutcome.NOT_FOUND, f"{len(converted)} values selected, not one")
        held = _agree(converted[0], printed, mode, zero)
        computed = converted[0]
    elif statistic == Statistic.COUNT.value:
        # A count over members, each of which has to be a number, as an aggregate's is.
        if any(number is None for number in numbers):
            empty = sum(number is None for number in numbers)
            return answer(
                NormalizedOutcome.NOT_FOUND,
                f"{empty} of {len(numbers)} selected rows hold no number, and a count is of "
                "members that resolve",
            )
        computed = decimal.Decimal(len(numbers))
        held = _agree(computed, printed, mode, zero)
    else:
        exact = _aggregate(
            Statistic(statistic), [fractions.Fraction(n) for n in converted if n is not None]
        )
        held = _agree_exact(exact, printed, mode, zero)
        computed = decimal.Decimal(exact.numerator) / decimal.Decimal(exact.denominator)
    outcome = NormalizedOutcome.MATCH if held else NormalizedOutcome.MISMATCH
    return answer(outcome, f"{_plain(computed)} against printed {printed}")


def _paperdelta(**fields: Any) -> dict[str, Any]:
    """PaperDelta's own fields, with a location's file named as a record names a path."""
    location = fields.get("location")
    if location and "file" in location:
        fields["location"] = {**location, "file": _relative(str(location["file"]))}
    return {key: value for key, value in fields.items() if value is not None}


def read(
    report_raw: bytes,
    config_raw: bytes,
    report_path: str = "report.json",
    config_path: str = "paperdelta.yaml",
    given: datetime.timezone | None = None,
    rerun: bool = False,
) -> PaperDeltaReading:
    """The records one PaperDelta report gives, read with the configuration it was made from.

    A number PaperDelta passed is `not-checked` where the report as a whole is unsettled
    (`unsettled`), with the reason named, and is never a match.
    """
    report = _report(report_raw, report_path)
    config = _config(config_raw, config_path)
    recorded = _hex(report.input_hashes.get(report.config_path))
    digest = hashlib.sha256(config_raw).hexdigest()
    if recorded is None:
        raise PaperDeltaError(
            f"{report_path} records no sha256 for its configuration {report.config_path}, so "
            f"nothing says {config_path} is the configuration it was made from"
        )
    if recorded != digest:
        raise PaperDeltaError(
            f"{config_path} has sha256 {digest}, and the report was made from "
            f"{report.config_path} at {recorded}: give the configuration the report was made from"
        )
    when = checked_at(report.created_at, given)
    held_back = unsettled(report)
    checker = Checker(
        name=CHECKER,
        version=report.tool_version,
        url=CHECKER_URL,
        ruleset_version=report.ruleset_version,
    )
    manifest = ManifestRef(path=_relative(report.config_path), digest=digest)
    converted_by = {
        "name": READER,
        "version": __version__,
        "report": hashlib.sha256(report_raw).hexdigest(),
    }

    records: list[ExportRecord] = []
    disagreements: list[str] = []
    for name, occurrence in report.occurrences.items():
        declared = config.occurrences.get(name)
        display = declared.display if declared else Display()
        state = report.metrics.get(occurrence.metric)
        kind, check_type, statistic = _kind(state, display)
        outcome = outcome_of(occurrence.status, occurrence.error)
        if outcome is NormalizedOutcome.MATCH and held_back is not None:
            outcome = NormalizedOutcome.NOT_CHECKED
        compared = outcome in (NormalizedOutcome.MATCH, NormalizedOutcome.MISMATCH)
        unit = state.unit if state else None
        conversion = _conversion(unit, display)
        printed, percent_sign = _printed(occurrence.actual)
        valued = check_type is not CheckType.OTHER
        reads = (
            _reads(state.evidence, report.input_hashes, compared and valued, conversion)
            if state and state.evidence
            else _sources(occurrence.metric, report, config)
        )
        if not valued:
            reads = tuple(
                read.model_copy(update={"stored": None, "converted": None}) for read in reads
            )
        computed = None
        if valued and statistic is not None and compared and state and state.value is not None:
            value = decimal.Decimal(state.value)
            computed = _plain(conversion.apply(value) if conversion else value)
        comparison = (
            Comparison(
                mode=ComparisonMode.PRINTED_PRECISION,
                places=0 if display.kind == "integer" else display.places,
                conversion=conversion.value if conversion else None,
                statistic=statistic,
                count=len(reads) if statistic else None,
                computed=computed,
                rounding=config.rounding,
            )
            if valued
            else None
        )
        native = occurrence.error or ("VALUE_MISMATCH" if occurrence.status == "mismatch" else "")
        detail = ""
        if occurrence.status == "pass" and held_back is not None:
            native, detail = held_back[0], f"{held_back[1]}; this number's pass is not settled"
        elif occurrence.status == "mismatch":
            detail = f"printed {occurrence.actual}, expected {occurrence.expected}"
        elif occurrence.error and state is not None and state.error == occurrence.error:
            detail = f"metric {occurrence.metric}: {occurrence.error}"
        extra: dict[str, Any] = {
            "paperdelta": _paperdelta(
                occurrence=name,
                metric=occurrence.metric,
                unit=unit,
                definition=state.definition if state else None,
                display=display.model_dump(exclude_none=True),
                rounding=config.rounding,
                actual=occurrence.actual,
                expected=occurrence.expected,
                usage=occurrence.usage,
                location=occurrence.location,
                evidence_fingerprint=occurrence.evidence_fingerprint,
                suggestion=occurrence.suggestion,
                printed_percent_sign=percent_sign if occurrence.actual is not None else None,
            ),
            "converted_by": converted_by,
        }
        if rerun and valued and compared and state is not None:
            again = _rerun(check_type, statistic, printed, state, conversion, outcome)
            extra["rerun"] = again.model_dump(mode="json")
            if not again.agrees:
                disagreements.append(name)
        text_printed = None
        if valued:
            text_printed = str(printed) if printed is not None else occurrence.actual
        where = _where(occurrence.location, declared.file if declared else "")
        records.append(
            ExportRecord(
                checker=checker,
                checked_at=when,
                manifest=manifest,
                # A numeric occurrence has no sentence, so the claim's text is empty.
                claim=ClaimRef(
                    id=name, where=where, digest=Digest.of_text(f"{name}\x00\x00{where}").value
                ),
                assertion=AssertionRef(kind=kind, name=occurrence.metric, index=0),
                check_type=check_type,
                reads=reads,
                printed=text_printed,
                comparison=comparison,
                outcome=outcome,
                native_outcome=occurrence.status,
                native_reason=native,
                detail=detail,
                **extra,
            )
        )

    for name, claim in report.claims.items():
        declared_claim = config.claims.get(name, {})
        text = str(
            (claim.location or {}).get("text")
            or (declared_claim.get("anchor") or {}).get("exact")
            or ""
        )
        where = _where(claim.location, str(declared_claim.get("file", "")))
        reads = tuple(
            read.model_copy(update={"stored": None, "converted": None})
            for metric in claim.metrics
            for read in (
                _reads(report.metrics[metric].evidence, report.input_hashes, False, None)
                if metric in report.metrics and report.metrics[metric].evidence
                else _sources(metric, report, config)
            )
        )
        claim_outcome = outcome_of(claim.status, claim.error)
        claim_reason = claim.error or ("CLAIM_FALSE" if claim.status == "mismatch" else "")
        claim_detail = ""
        if claim_outcome is NormalizedOutcome.MATCH and held_back is not None:
            claim_outcome = NormalizedOutcome.NOT_CHECKED
            claim_reason, claim_detail = (
                held_back[0],
                f"{held_back[1]}; this claim's pass is not settled",
            )
        records.append(
            ExportRecord(
                checker=checker,
                checked_at=when,
                manifest=manifest,
                claim=ClaimRef(
                    id=name,
                    text=text,
                    where=where,
                    digest=Digest.of_text(f"{name}\x00{text}\x00{where}").value,
                ),
                assertion=AssertionRef(kind="comparison", name=name, index=0),
                check_type=CheckType.OTHER,
                reads=reads,
                outcome=claim_outcome,
                native_outcome=claim.status,
                native_reason=claim_reason,
                detail=claim_detail,
                paperdelta=_paperdelta(
                    claim=name,
                    metrics=list(claim.metrics),
                    predicate=declared_claim.get("predicate"),
                    scope=declared_claim.get("scope"),
                    location=claim.location,
                ),
                converted_by=converted_by,
            )
        )
    return PaperDeltaReading(records=tuple(records), disagreements=tuple(disagreements))


def from_paperdelta(
    report: pathlib.Path,
    config: pathlib.Path,
    given: datetime.timezone | None = None,
    rerun: bool = False,
) -> PaperDeltaReading:
    """Read a PaperDelta `report.json` with the `paperdelta.yaml` it was made from."""
    try:
        report_raw, config_raw = report.read_bytes(), config.read_bytes()
    except OSError as e:
        raise PaperDeltaError(f"could not be read: {e}") from e
    return read(report_raw, config_raw, report.name, config.name, given=given, rerun=rerun)
