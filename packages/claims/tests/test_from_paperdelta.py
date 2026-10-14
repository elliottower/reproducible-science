"""A PaperDelta report, read into check records, against PaperDelta's own example and against
reports built by hand where the two tools' rules give different answers on the same inputs.

`fixtures/paperdelta/` is PaperDelta's report for its research-paper example after the data
changed, with the configuration it was made from, copied unedited at commit d73f574 (MIT; the
notice is beside them). The hand-built reports follow `StoredReport` in PaperDelta's
`records.py` at that commit, schema 9.
"""

from __future__ import annotations

import datetime
import decimal
import hashlib
import json
import pathlib

import pytest
from claims.cli import main
from claims.foreign.common import ForeignError, offset
from claims.foreign.paperdelta import (
    PaperDeltaError,
    checked_at,
    from_paperdelta,
    outcome_of,
    read,
)
from claims.record import (
    CheckType,
    NormalizedOutcome,
    problems,
    read_outcome,
    understood,
    validate,
)

HERE = pathlib.Path(__file__).parent / "fixtures" / "paperdelta"
REPORT, CONFIG = HERE / "report.json", HERE / "paperdelta.yaml"

#: One occurrence of each case in the note's section 2.4, with a count over an empty cell.
#: Each is (unit, reduce, stored values, display, PaperDelta's status, printed, expected).
CONFIG_TEXT = """\
schema_version: 9
paper: {entry: paper.tex}
rounding: half_up
sources:
  table: {path: results.csv, format: csv, primary_key: [model], columns: {model: string, v: decimal}}
  tree: {path: results.json, format: json}
metrics:
  tie: {source: table, field: v, where: {model: tie}, unit: fraction}
  finer: {source: table, field: v, where: {model: finer}, unit: scalar}
  coarser: {source: table, field: v, where: {model: coarser}, unit: scalar}
  text: {source: tree, field: /acc, unit: scalar}
  rows: {source: table, field: v, reduce: count, unit: count}
occurrences:
  tie_printed:
    file: paper.tex
    anchor: {exact: '4.2\\\\%'}
    metric: tie
    display: {kind: percent, places: 1}
  finer_printed:
    file: paper.tex
    anchor: {exact: '4.20'}
    metric: finer
    display: {kind: decimal, places: 1}
  coarser_printed:
    file: paper.tex
    anchor: {exact: '3.1'}
    metric: coarser
    display: {kind: decimal, places: 2}
  text_printed:
    file: paper.tex
    anchor: {exact: '0.84'}
    metric: text
    display: {kind: decimal, places: 2}
  rows_printed:
    file: paper.tex
    anchor: {exact: '3'}
    metric: rows
    display: {kind: integer}
"""


def _location(text: str, line: int, file: str = "paper.tex") -> dict:
    return {
        "file": file,
        "start": 10,
        "end": 10 + len(text),
        "byte_start": 10,
        "byte_end": 10 + len(text.encode()),
        "line": line,
        "column": 11,
        "text": text,
    }


def _table_metric(name: str, values: list, unit: str, reduce: str = "unique") -> dict:
    keys = [
        {"model": name} if len(values) == 1 else {"model": f"{name}{i}"} for i in range(len(values))
    ]
    return {
        "status": "ok",
        "value": str(len(values)) if reduce == "count" else str(values[0]),
        "unit": unit,
        "fingerprint": "sha256:" + "1" * 64,
        "definition_fingerprint": "sha256:" + "2" * 64,
        "definition": {
            "source": "table",
            "field": "v",
            "where": {},
            "reduce": reduce,
            "unit": unit,
        },
        "evidence": [
            {
                "source": "table",
                "path": "results.csv",
                "field": "v",
                "where": {},
                "reduce": reduce,
                "count": len(values),
                "records": [
                    {"key": key, "value": value} for key, value in zip(keys, values, strict=True)
                ],
                "locations": [{"key": key, "line": i + 2} for i, key in enumerate(keys)],
            }
        ],
        "dependencies": [],
    }


def _occurrence(metric: str, status: str, actual: str, expected: str, line: int) -> dict:
    state = {
        "metric": metric,
        "status": status,
        "location": _location(actual, line),
        "expected": expected,
        "actual": actual,
        "evidence_fingerprint": "sha256:" + "3" * 64,
        "usage": "prose",
    }
    if status == "mismatch":
        state["suggestion"] = {"replacement": expected, "blocked_by": []}
    return state


def _report(config: bytes, created_at: str = "2026-10-14T09:00:00+11:00", **changes) -> dict:
    report = {
        "created_at": created_at,
        "report_schema_version": 9,
        "tool_version": "2.0.0",
        "ruleset_version": "9",
        "config_path": "paperdelta.yaml",
        "input_hashes": {
            "paperdelta.yaml": "sha256:" + hashlib.sha256(config).hexdigest(),
            "results.csv": "sha256:" + "4" * 64,
            "results.json": "sha256:" + "5" * 64,
        },
        "metrics": {
            "tie": _table_metric("tie", [decimal.Decimal("0.0425")], "fraction"),
            "finer": _table_metric("finer", [decimal.Decimal("4.2051")], "scalar"),
            "coarser": _table_metric("coarser", [decimal.Decimal("3.14159")], "scalar"),
            "text": {
                "status": "ok",
                "value": "0.84",
                "unit": "scalar",
                "fingerprint": "sha256:" + "1" * 64,
                "definition_fingerprint": "sha256:" + "2" * 64,
                "definition": {"source": "tree", "field": "/acc", "reduce": "unique"},
                "evidence": [
                    {
                        "source": "tree",
                        "path": "results.json",
                        "field": "/acc",
                        "where": {},
                        "reduce": "unique",
                        "count": 1,
                        # PaperDelta accepts a number written as a JSON string.
                        "records": [{"index": 0, "value": "0.84"}],
                        "locations": [{"pointer": "/acc"}],
                    }
                ],
            },
            "rows": _table_metric(
                "rows", [decimal.Decimal("0.5"), None, decimal.Decimal("0.7")], "count", "count"
            ),
        },
        "occurrences": {
            "tie_printed": _occurrence("tie", "mismatch", "4.2\\%", "4.3\\%", 1),
            "finer_printed": _occurrence("finer", "pass", "4.20", "4.2", 2),
            "coarser_printed": _occurrence("coarser", "mismatch", "3.1", "3.14", 3),
            "text_printed": _occurrence("text", "pass", "0.84", "0.84", 4),
            "rows_printed": _occurrence("rows", "pass", "3", "3", 5),
        },
        "claims": {},
        "figures": {},
        "diagnostics": [],
        "changes": [],
        "baseline": None,
        "coverage": {},
        "exit_code": 1,
    }
    report.update(changes)
    if "diagnostics" not in changes:
        # PaperDelta's finding for each mismatch, which is what makes its exit code 1.
        report["diagnostics"] = [
            {
                "id": f"occurrence:{name}/VALUE_MISMATCH",
                "rule": "VALUE_MISMATCH",
                "subject": f"occurrence:{name}",
                "severity": "error",
                "message": "",
            }
            for name, state in report["occurrences"].items()
            if state["status"] == "mismatch"
        ]
    return report


def _dump(report: dict) -> bytes:
    """JSON, with each stored decimal written as the number it is. A float's repr is the
    shortest text that reads back as it, so each value here is written as the digits typed."""
    return json.dumps(report, default=float).encode()


def _by_id(reading) -> dict:
    return {record.claim.id: record for record in reading.records}


def test_every_record_from_paperdelta_s_own_report_is_one_a_check_could_have_made():
    reading = from_paperdelta(REPORT, CONFIG, rerun=True)
    assert len(reading.records) == 6
    for record in reading.records:
        assert problems(record) == ()
        assert validate(json.loads(record.to_json())) == record


def test_paperdelta_s_answers_are_carried_as_it_gave_them():
    found = _by_id(from_paperdelta(REPORT, CONFIG))
    assert {name: record.outcome for name, record in found.items()} == {
        "abstract_accuracy": NormalizedOutcome.MISMATCH,
        "appendix_accuracy": NormalizedOutcome.MISMATCH,
        "gain_text": NormalizedOutcome.MISMATCH,
        "table_accuracy": NormalizedOutcome.MISMATCH,
        "table_baseline": NormalizedOutcome.MATCH,
        "main_comparison": NormalizedOutcome.MISMATCH,
    }
    baseline = found["table_baseline"]
    assert baseline.checker.name == "paperdelta" and baseline.checker.version == "0.1.0a2"
    assert baseline.checked_at == datetime.datetime(
        2026, 10, 2, 20, 2, 49, 992450, tzinfo=datetime.UTC
    )
    assert baseline.manifest.digest == hashlib.sha256(CONFIG.read_bytes()).hexdigest()
    assert baseline.claim.where == "paper/results.tex:9:12"


def test_a_mean_over_seeds_is_an_aggregate_whose_members_are_the_rows_read():
    baseline = _by_id(from_paperdelta(REPORT, CONFIG))["table_baseline"]
    assert baseline.check_type is CheckType.AGGREGATE_COMPARISON
    assert baseline.comparison.statistic == "mean" and baseline.comparison.count == 3
    assert [read.stored for read in baseline.reads] == ["0.809", "0.810", "0.811"]
    # A fraction printed as a percentage: each member moved two places, no digit changed.
    assert [read.converted for read in baseline.reads] == ["80.9", "81.0", "81.1"]
    assert baseline.comparison.computed == "81.0" and baseline.printed == "81.0"
    assert {read.validity.value for read in baseline.reads} == {"unpinned_artifact"}
    assert {read.on_disk for read in baseline.reads} == {
        "f064b2d251d71d8de97d8ab6933d29c7037d520911433f0410552e20c124d9d2"
    }
    assert baseline.reads[0].address.model_dump() == {
        "kind": "table",
        "column": "accuracy",
        "where": {"dataset": "Data-A", "model": "Baseline", "seed": 1, "split": "test"},
        "line": 5,
    }
    assert understood(baseline) and read_outcome(baseline) is NormalizedOutcome.MATCH


def test_a_derived_metric_and_a_comparative_claim_are_never_read_as_a_comparison_of_values():
    found = _by_id(from_paperdelta(REPORT, CONFIG))
    for name in ("gain_text", "main_comparison"):
        record = found[name]
        assert record.check_type is CheckType.OTHER
        assert record.printed is None and record.comparison is None
        assert all(read.stored is None for read in record.reads) and record.reads
        assert read_outcome(record) is not NormalizedOutcome.MATCH
    assert found["main_comparison"].claim.text == "Our method outperforms Baseline on Data-A."
    assert found["gain_text"].model_extra["paperdelta"]["actual"] == "3.1"


def test_the_two_rules_disagree_where_section_2_4_says_they_do(tmp_path):
    config = CONFIG_TEXT.encode()
    reading = read(_dump(_report(config)), config, rerun=True)
    found = _by_id(reading)
    ours = {name: record.model_extra["rerun"]["outcome"] for name, record in found.items()}
    theirs = {name: record.outcome.value for name, record in found.items()}
    assert theirs == {
        "tie_printed": "mismatch",
        "finer_printed": "match",
        "coarser_printed": "mismatch",
        "text_printed": "match",
        "rows_printed": "match",
    }
    # 0.0425 as a percentage is 4.25, a tie at one place: half-up says 4.3 only, and this
    # toolkit takes either neighbor. 4.2051 printed as 4.20 is 4.21 at the printed two places.
    # 3.14159 printed as 3.1 is 3.1 at the printed one place. A JSON string is not a number,
    # and a count of three rows, one of them empty, is not a count of three numbers.
    assert ours == {
        "tie_printed": "match",
        "finer_printed": "mismatch",
        "coarser_printed": "match",
        "text_printed": "not-found",
        "rows_printed": "not-found",
    }
    assert set(reading.disagreements) == set(found)
    for record in reading.records:
        assert problems(record) == ()


def test_a_tie_is_recorded_with_paperdelta_s_rounding_and_the_converted_value():
    config = CONFIG_TEXT.encode()
    tie = _by_id(read(_dump(_report(config)), config))["tie_printed"]
    assert tie.printed == "4.2" and tie.model_extra["paperdelta"]["printed_percent_sign"]
    assert tie.reads[0].stored == "0.0425" and tie.reads[0].converted == "4.25"
    assert tie.comparison.conversion == "percent" and tie.comparison.places == 1
    assert tie.comparison.model_extra["rounding"] == "half_up"
    assert "rerun" not in tie.model_extra


@pytest.mark.parametrize(
    ("code", "outcome"),
    [
        ("ANCHOR_MISSING", NormalizedOutcome.NOT_FOUND),
        ("AMBIGUOUS_SELECTION", NormalizedOutcome.NOT_FOUND),
        ("SEED_SET", NormalizedOutcome.NOT_CHECKED),
        ("UNREACHABLE_TEX", NormalizedOutcome.NOT_CHECKED),
        ("INVALID_CSV", NormalizedOutcome.ERROR),
        ("XLSX_FORMULA", NormalizedOutcome.ERROR),
        ("EXPORT_PROVENANCE", NormalizedOutcome.ERROR),
        ("A_CODE_NOT_YET_WRITTEN", NormalizedOutcome.NOT_CHECKED),
        (None, NormalizedOutcome.NOT_CHECKED),
    ],
)
def test_an_unknown_is_placed_by_its_code_and_never_guessed_into_a_mismatch(code, outcome):
    assert outcome_of("unknown", code) is outcome


def test_an_unresolved_occurrence_carries_no_value_and_names_its_source_from_the_configuration():
    config = CONFIG_TEXT.encode()
    report = _report(config)
    report["metrics"]["finer"] = {"status": "unknown", "error": "MISSING_COLUMN"}
    report["occurrences"]["finer_printed"] = {
        "metric": "finer",
        "status": "unknown",
        "error": "MISSING_COLUMN",
    }
    record = _by_id(read(_dump(report), config, rerun=True))["finer_printed"]
    assert record.outcome is NormalizedOutcome.NOT_FOUND
    assert record.native_outcome == "unknown" and record.native_reason == "MISSING_COLUMN"
    assert [(read.path, read.stored, read.address) for read in record.reads] == [
        ("results.csv", None, None)
    ]
    assert "rerun" not in record.model_extra
    assert problems(record) == ()


def test_a_time_without_an_offset_is_refused_unless_the_offset_is_given():
    config = CONFIG_TEXT.encode()
    naive = _dump(_report(config, created_at="2026-10-14T09:00:00"))
    with pytest.raises(ForeignError, match="no UTC offset"):
        read(naive, config)
    records = read(naive, config, given=offset("+11:00")).records
    assert {record.checked_at.utcoffset() for record in records} == {datetime.timedelta(hours=11)}
    assert checked_at("2026-10-14T09:00:00Z", None).utcoffset() == datetime.timedelta(0)


def test_a_configuration_the_report_was_not_made_from_is_refused():
    config = CONFIG_TEXT.encode()
    with pytest.raises(PaperDeltaError, match="the report was made from"):
        read(_dump(_report(config)), config + b"# edited\n")


def test_a_report_schema_this_reader_has_not_read_is_refused():
    config = CONFIG_TEXT.encode()
    with pytest.raises(PaperDeltaError, match="report schema 10"):
        read(_dump(_report(config, report_schema_version=10)), config)


def test_no_path_in_a_record_is_absolute():
    config = CONFIG_TEXT.encode()
    report = _report(config)
    report["occurrences"]["tie_printed"]["location"]["file"] = "/home/someone/paper.tex"
    report["metrics"]["tie"]["evidence"][0]["path"] = "/home/someone/results.csv"
    tie = _by_id(read(_dump(report), config))["tie_printed"]
    assert tie.claim.where == "paper.tex:1:11"
    assert tie.reads[0].path == "results.csv"
    assert "/home/" not in tie.to_json()


def test_the_command_writes_records_and_says_where_the_rules_disagree(tmp_path, capsys):
    config, report = tmp_path / "paperdelta.yaml", tmp_path / "report.json"
    config.write_text(CONFIG_TEXT)
    report.write_bytes(_dump(_report(CONFIG_TEXT.encode())))
    args = ["from-paperdelta", str(report), "--config", str(config)]

    assert main([*args, "--rerun", "--format", "text"]) == 0
    said = capsys.readouterr().out
    assert "5 records, 5 where the two rules disagree" in said
    assert "tie_printed: paperdelta mismatch -> mismatch; this toolkit's rule: match" in said

    out = tmp_path / "records.jsonl"
    assert main([*args, "--output", str(out)]) == 0
    lines = out.read_text().splitlines()
    assert len(lines) == 5 and all(problems(validate(json.loads(line))) == () for line in lines)
    assert main([*args, "--output", str(out)]) == 2
    assert "never overwrites" in capsys.readouterr().out
    assert len(out.read_text().splitlines()) == 5


def _project(rule: str) -> dict:
    return {
        "id": f"project/{rule}",
        "rule": rule,
        "subject": "project",
        "severity": "unknown",
        "message": "",
    }


@pytest.mark.parametrize("rule", ["INPUT_CHANGED", "INCOMPLETE_COVERAGE"])
def test_a_pass_under_a_project_diagnostic_is_not_checked_and_names_it(rule):
    config = CONFIG_TEXT.encode()
    report = _report(config, exit_code=2)
    report["diagnostics"].append(_project(rule))
    found = _by_id(read(_dump(report), config, rerun=True))
    for name in ("finer_printed", "text_printed", "rows_printed"):
        record = found[name]
        assert record.native_outcome == "pass"
        assert record.outcome is NormalizedOutcome.NOT_CHECKED
        assert record.native_reason == rule
        assert "not settled" in record.detail
        assert all(read.stored is None for read in record.reads)
        assert "rerun" not in (record.model_extra or {})
        assert problems(record) == ()
    assert found["tie_printed"].outcome is NormalizedOutcome.MISMATCH


def test_an_exit_code_no_finding_accounts_for_leaves_every_pass_unsettled():
    config = CONFIG_TEXT.encode()
    found = _by_id(read(_dump(_report(config, exit_code=2)), config))
    assert found["finer_printed"].outcome is NormalizedOutcome.NOT_CHECKED
    assert found["finer_printed"].native_reason == "EXIT_2"
    silent = _report(config, exit_code=1, diagnostics=[])
    assert _by_id(read(_dump(silent), config))["text_printed"].native_reason == "EXIT_1"


def test_a_mismatch_elsewhere_does_not_unsettle_a_number_that_passed():
    config = CONFIG_TEXT.encode()
    found = _by_id(read(_dump(_report(config)), config))
    assert found["finer_printed"].outcome is NormalizedOutcome.MATCH


def test_a_report_recording_no_hash_for_its_configuration_is_refused():
    config = CONFIG_TEXT.encode()
    report = _report(config)
    del report["input_hashes"]["paperdelta.yaml"]
    with pytest.raises(PaperDeltaError, match="records no sha256 for its configuration"):
        read(_dump(report), config)


def test_a_metric_value_that_is_not_a_number_is_refused_and_does_not_crash():
    config = CONFIG_TEXT.encode()
    report = _report(config)
    report["metrics"]["rows"]["value"] = "three"
    with pytest.raises(PaperDeltaError, match="is not decimal text"):
        read(_dump(report), config)


def test_an_export_location_carrying_its_own_kind_is_kept_under_another_name():
    config = CONFIG_TEXT.encode()
    report = _report(config)
    report["metrics"]["text"]["evidence"][0]["locations"] = [
        {"pointer": "/acc", "snapshot": "export-1", "kind": "mlflow"}
    ]
    (read_,) = _by_id(read(_dump(report), config))["text_printed"].reads
    assert read_.address.kind == "paperdelta-export"
    assert read_.address.model_extra["paperdelta_kind"] == "mlflow"


def test_an_exit_code_one_number_s_own_unknown_accounts_for_leaves_the_others_as_reported():
    config = CONFIG_TEXT.encode()
    report = _report(config, exit_code=2)
    report["occurrences"]["coarser_printed"].update(status="unknown", error="MISSING_VALUE")
    report["diagnostics"] = [
        {
            "id": "occurrence:coarser_printed/MISSING_VALUE",
            "rule": "MISSING_VALUE",
            "subject": "occurrence:coarser_printed",
            "severity": "unknown",
            "message": "",
        },
        {
            "id": "occurrence:tie_printed/VALUE_MISMATCH",
            "rule": "VALUE_MISMATCH",
            "subject": "occurrence:tie_printed",
            "severity": "error",
            "message": "",
        },
    ]
    found = _by_id(read(_dump(report), config))
    for name in ("finer_printed", "text_printed", "rows_printed"):
        assert found[name].outcome is NormalizedOutcome.MATCH
    assert found["coarser_printed"].outcome is NormalizedOutcome.NOT_FOUND
    assert found["tie_printed"].outcome is NormalizedOutcome.MISMATCH


def test_a_finding_on_no_one_item_unsettles_every_pass_with_no_exit_code_given():
    config = CONFIG_TEXT.encode()
    report = _report(config)
    del report["exit_code"]
    report["diagnostics"].append(
        {
            "id": "paper.tex/DYNAMIC_TEX",
            "rule": "DYNAMIC_TEX",
            "subject": "paper.tex",
            "severity": "unknown",
            "message": "",
        }
    )
    passed = _by_id(read(_dump(report), config))["finer_printed"]
    assert passed.outcome is NormalizedOutcome.NOT_CHECKED
    assert passed.native_reason == "DYNAMIC_TEX"
    assert "paper.tex" in passed.detail


@pytest.mark.parametrize(
    "subject", ["provenance:notebook", "figure:fig1", "fragment:table2", "export:pdf"]
)
def test_a_failure_of_something_no_record_states_unsettles_every_pass(subject):
    config = CONFIG_TEXT.encode()
    report = _report(config, exit_code=2)
    report["diagnostics"].append(
        {
            "id": f"{subject}/PROVENANCE_UNKNOWN",
            "rule": "PROVENANCE_UNKNOWN",
            "subject": subject,
            "severity": "unknown",
            "message": "",
        }
    )
    passed = _by_id(read(_dump(report), config))["finer_printed"]
    assert passed.outcome is NormalizedOutcome.NOT_CHECKED
    assert passed.native_reason == "PROVENANCE_UNKNOWN"
    assert subject in passed.detail
