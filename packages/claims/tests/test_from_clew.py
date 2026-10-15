from __future__ import annotations

import datetime
import json

import pytest
from claims.cli import main
from claims.foreign.clew import ClewError, records
from claims.foreign.common import offset
from claims.models import Validity
from claims.record import (
    NATIVE_OUTCOMES,
    UNDERSTOOD_CHECK_TYPES,
    CheckType,
    NormalizedOutcome,
    problems,
    read_outcome,
    validate,
)

HASH = "a" * 64


def claim(root, claim_id, status, **fields):
    entry = {
        "claim_id": claim_id,
        "file_path": str(root / "paper" / "main.tex"),
        "line_number": 12,
        "claim_type": "statistic",
        "claim_value": "p = 0.003",
        "source_session": "session-1",
        "source_file": str(root / "results" / "stats.csv"),
        "source_hash": HASH,
        "registered_at": "2026-10-01T09:00:00+02:00",
        "verified_at": "2026-10-02T10:30:00+02:00",
        "status": status,
        "resolved_status": status,
        "chain_has_exception": False,
        "chain_has_frozen": False,
        "grounded": None,
        "exception_reasons": [],
    }
    return entry | fields


def export(root, claims, schema="1.4"):
    path = root / ".scitex" / "clew" / "runtime" / "claims.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": schema,
                "generated_at": "2026-10-03T08:00:00Z",
                "attestation": {
                    "tool": "scitex-clew",
                    "version": "0.21.0",
                    "url": "https://example.org/clew",
                },
                "claims": claims,
            }
        )
    )
    return path


def by_type(found):
    return {(r.claim.id, r.check_type): r for r in found}


def test_each_stored_status_becomes_the_checks_clew_ran(tmp_path):
    path = export(
        tmp_path,
        [
            claim(tmp_path, "c-registered", "registered", verified_at=None),
            claim(tmp_path, "c-missing", "missing"),
            claim(tmp_path, "c-mismatch", "mismatch"),
            claim(tmp_path, "c-suspect", "suspect"),
            claim(tmp_path, "c-verified", "verified"),
            claim(tmp_path, "c-exception", "verified", resolved_status="exception"),
        ],
    )
    found = records(path)
    got = {(r.claim.id, r.check_type.value): (r.outcome, r.native_outcome) for r in found}
    identity, lineage = "artifact-identity", "lineage-check"
    match, mismatch, unchecked = (
        NormalizedOutcome.MATCH,
        NormalizedOutcome.MISMATCH,
        NormalizedOutcome.NOT_CHECKED,
    )
    assert got == {
        ("c-registered", identity): (unchecked, "registered"),
        ("c-missing", identity): (unchecked, "missing"),
        ("c-mismatch", identity): (mismatch, "mismatch"),
        ("c-suspect", identity): (match, "suspect"),
        ("c-suspect", lineage): (mismatch, "suspect"),
        ("c-verified", identity): (match, "verified"),
        ("c-verified", lineage): (match, "verified"),
        ("c-exception", identity): (match, "verified"),
        ("c-exception", lineage): (unchecked, "exception"),
    }
    absent = by_type(found)["c-missing", CheckType.ARTIFACT_IDENTITY].reads[0]
    assert absent.validity is Validity.ARTIFACT_ABSENT and absent.on_disk is None


def test_no_record_compares_a_value_and_every_record_is_one_a_check_could_reach(tmp_path):
    statuses = ["registered", "missing", "mismatch", "suspect", "verified", "superseded"]
    path = export(tmp_path, [claim(tmp_path, f"c-{s}", s) for s in statuses])
    found = records(path)
    assert len(found) == len(statuses) + 2
    for record in found:
        assert record.check_type in (CheckType.ARTIFACT_IDENTITY, CheckType.LINEAGE_CHECK)
        assert record.printed is None and record.comparison is None
        assert all(read.stored is None for read in record.reads)
        assert problems(record) == ()
        assert record.native_outcome in NATIVE_OUTCOMES["scitex-clew"]
        assert record.claim_value == "p = 0.003"
        assert record.reads[0].pinned == HASH
        # The record survives a round trip through its own JSON and validation.
        assert validate(json.loads(record.to_json())) == record


def test_a_clew_verified_is_not_passed_on_as_a_value_that_held(tmp_path):
    path = export(tmp_path, [claim(tmp_path, "c", "verified")])
    found = records(path)
    assert CheckType.ARTIFACT_IDENTITY not in UNDERSTOOD_CHECK_TYPES
    assert [r.outcome for r in found] == [NormalizedOutcome.MATCH] * 2
    assert [read_outcome(r) for r in found] == [NormalizedOutcome.NOT_CHECKED] * 2


def test_naive_times_are_refused_without_an_offset_and_never_read_as_utc(tmp_path):
    path = export(
        tmp_path,
        [
            claim(
                tmp_path,
                "c",
                "verified",
                registered_at="2026-10-01T09:00:00",
                verified_at="2026-10-02T10:30:00.123456",
            )
        ],
    )
    with pytest.raises(ClewError, match="--offset"):
        records(path)
    found = records(path, given=offset("+09:00"))
    when = found[0].checked_at
    assert when.utcoffset() == datetime.timedelta(hours=9)
    assert when == datetime.datetime(2026, 10, 2, 1, 30, 0, 123456, tzinfo=datetime.UTC)
    assert found[0].clew["registered_at"] == "2026-10-01T09:00:00+09:00"


def test_a_claim_never_verified_is_dated_by_the_export(tmp_path):
    path = export(tmp_path, [claim(tmp_path, "c", "registered", verified_at=None)])
    assert records(path)[0].checked_at == datetime.datetime(2026, 10, 3, 8, tzinfo=datetime.UTC)


def test_paths_are_relative_to_the_project_and_never_absolute(tmp_path):
    outside = tmp_path / "elsewhere" / "other.csv"
    root = tmp_path / "project"
    path = export(
        root,
        [
            claim(root, "inside", "verified"),
            claim(root, "outside", "verified", source_file=str(outside)),
        ],
    )
    found = by_type(records(path))
    inside = found["inside", CheckType.ARTIFACT_IDENTITY]
    assert inside.claim.where == "paper/main.tex:L12"
    assert inside.reads[0].path == "results/stats.csv" and inside.warnings == ()
    cut = found["outside", CheckType.ARTIFACT_IDENTITY]
    assert cut.reads[0].path == "other.csv"
    assert cut.warnings == ("the source file lies outside the project root; named by its file",)
    written = "".join(r.to_json() for r in found.values())
    assert str(tmp_path) not in written


def test_an_export_away_from_clew_s_default_place_needs_a_root(tmp_path):
    root = tmp_path / "project"
    default = export(root, [claim(root, "c", "verified")])
    moved = tmp_path / "claims.json"
    moved.write_bytes(default.read_bytes())
    with pytest.raises(ClewError, match="--root"):
        records(moved)
    assert records(moved, root=root)[0].reads[0].path == "results/stats.csv"


def test_a_schema_version_this_reader_has_not_read_is_refused(tmp_path):
    path = export(tmp_path, [claim(tmp_path, "c", "verified")], schema="1.3")
    with pytest.raises(ClewError, match=r"schema .1\.3."):
        records(path)


def test_a_claim_with_no_source_file_was_not_checked(tmp_path):
    path = export(
        tmp_path, [claim(tmp_path, "c", "registered", source_file=None, source_hash=None)]
    )
    (only,) = records(path)
    assert only.outcome is NormalizedOutcome.NOT_CHECKED and only.reads == ()
    assert problems(only) == ()


def test_the_command_writes_records_and_never_overwrites(tmp_path, capsys):
    path = export(tmp_path, [claim(tmp_path, "c", "suspect")])
    out = tmp_path / "records.jsonl"
    assert main(["from-clew", str(path), "-o", str(out)]) == 0
    lines = [json.loads(line) for line in out.read_text().splitlines()]
    assert [line["check_type"] for line in lines] == ["artifact-identity", "lineage-check"]
    assert all(validate(line) for line in lines)
    assert main(["from-clew", str(path), "-o", str(out)]) == 2
    assert "never overwrites" in capsys.readouterr().out
    assert main(["from-clew", str(path), "--format", "text"]) == 0
    assert capsys.readouterr().out == ("artifact-identity: 1 match\nlineage-check: 1 mismatch\n")
