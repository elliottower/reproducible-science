"""The record's version: the one written, the ones read, and the records 0.5.6 wrote.

`fixtures/records-0.5.6.jsonl` is the output of the released wheel, `uvx --from
reproducible-science==0.5.6 repro export record`, over seven conformance cases, unedited. It
is what a project that exported records before 0.6 holds, and 0.6 has to keep reading it.
The schemas are checked against it in `packages/repro/tests/test_record.py`, since this suite
also runs with `claims-cli` installed alone, and `jsonschema` is not a dependency of it.
"""

from __future__ import annotations

import collections
import copy
import datetime
import json
import pathlib

import pytest
from claims import load
from claims.export.rocrate import from_ro_crate, to_ro_crate
from claims.export.sarif import RECORD_PROPERTY, to_sarif_log
from claims.record import (
    ExportRecord,
    InvalidRecordError,
    NormalizedOutcome,
    check_records,
    problems,
    read_outcome,
    understood,
    validate,
)

HERE = pathlib.Path(__file__).parent
CASES = HERE / "conformance" / "cases"
RELEASED = HERE / "fixtures" / "records-0.5.6.jsonl"
WHEN = datetime.datetime(2026, 10, 14, 12, 0, tzinfo=datetime.UTC)

NEW = "reproducible.science/claim-check/0.1-experimental"
OLD = "repro.check/0.1-experimental"


def released():
    return [json.loads(line) for line in RELEASED.read_text().splitlines()]


def fresh(name="value_match"):
    (record,) = check_records(load(CASES / name / "repro.yaml"), WHEN)
    return json.loads(record.to_json())


def test_a_record_is_written_under_the_new_version():
    data = fresh()
    assert data["record"] == NEW


@pytest.mark.parametrize("version", [NEW, OLD])
def test_a_record_under_either_version_is_read(version):
    data = fresh() | {"record": version}
    record = validate(data)
    assert record.record == version
    assert problems(record) == ()
    assert understood(record)
    assert read_outcome(record) is NormalizedOutcome.MATCH


@pytest.mark.parametrize(
    "version",
    [
        "reproducible.science/claim-check/0.2-experimental",
        "repro.check/0.2-experimental",
        "claim-check/0.1-experimental",
        "",
    ],
)
def test_a_record_under_any_other_version_is_refused(version):
    data = fresh() | {"record": version}
    with pytest.raises(InvalidRecordError) as caught:
        validate(data)
    (said,) = caught.value.problems
    assert said == f"record is {version!r}; this reader knows {NEW!r} and {OLD!r}"


@pytest.mark.parametrize(
    "version", ["reproducible.science/claim-check/0.2-experimental", "repro.check/9.9", ""]
)
def test_a_match_under_a_version_this_reader_does_not_know_is_not_checked(version):
    record = ExportRecord.model_validate(fresh() | {"record": version})
    assert record.outcome is NormalizedOutcome.MATCH
    assert not understood(record)
    assert read_outcome(record) is NormalizedOutcome.NOT_CHECKED


def test_a_mismatch_under_a_version_this_reader_does_not_know_stays_a_mismatch():
    data = fresh("value_mismatch") | {"record": "reproducible.science/claim-check/0.2-experimental"}
    record = ExportRecord.model_validate(data)
    assert read_outcome(record) is NormalizedOutcome.MISMATCH


def test_the_released_records_are_the_ones_0_5_6_wrote():
    found = released()
    assert len(found) == 8
    assert {data["record"] for data in found} == {OLD}
    assert {data["checker"]["version"] for data in found} == {"0.5.6"}
    assert {data["check_type"] for data in found} == {
        "value-comparison",
        "passage-presence",
        "correspondence",
        "aggregate-comparison",
    }
    assert {data["outcome"] for data in found} == {"match", "mismatch", "not-found", "not-checked"}


def test_every_released_record_validates_and_reads_its_own_outcome():
    for data in released():
        record = validate(data)
        assert record.record == OLD
        assert problems(record) == ()
        assert read_outcome(record).value == data["outcome"]


def test_the_released_records_survive_an_ro_crate_unchanged():
    by_manifest = collections.defaultdict(list)
    for data in released():
        by_manifest[data["manifest"]["digest"]].append(validate(data))
    assert len(by_manifest) == 7
    for records in by_manifest.values():
        crate = to_ro_crate(records)
        checks = [e for e in json.loads(crate)["@graph"] if "recordVersion" in e]
        assert {check["recordVersion"] for check in checks} == {OLD}
        assert from_ro_crate(crate) == tuple(records)


def test_the_released_records_become_a_sarif_log_that_keeps_their_version():
    records = [validate(data) for data in released()]
    (run,) = json.loads(to_sarif_log(records, include_matches=True))["runs"]
    assert run["properties"]["repro/recordVersion"] == OLD
    assert run["properties"]["repro/outcomes"] == {
        "match": 4,
        "mismatch": 2,
        "not-found": 1,
        "not-checked": 1,
        "error": 0,
    }
    assert {result["properties"][RECORD_PROPERTY]["record"] for result in run["results"]} == {OLD}


def test_a_released_record_with_its_outcome_altered_is_still_refused():
    data = copy.deepcopy(released()[0])
    data["outcome"] = "match"
    with pytest.raises(InvalidRecordError):
        validate(data)
