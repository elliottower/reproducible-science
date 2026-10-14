"""The one rule both readers of other checkers' results give a time with no offset, and the one
rule for where they write."""

from __future__ import annotations

import datetime
import json

import pytest
from claims.cli import main
from claims.foreign.common import ForeignError, aware, offset


@pytest.mark.parametrize("text", ["+9:00", "09:00", "+0900", "+24:00", "+01:60", "Z", "UTC"])
def test_an_offset_is_written_with_sign_hours_colon_and_minutes(text):
    with pytest.raises(ForeignError, match=r"\+HH:MM"):
        offset(text)


@pytest.mark.parametrize(
    ("text", "hours"), [("+00:00", 0), ("-05:30", -5.5), ("+23:59", 23 + 59 / 60)]
)
def test_an_offset_is_the_signed_hours_and_minutes_it_writes(text, hours):
    assert offset(text).utcoffset(None) == datetime.timedelta(hours=hours)


def test_a_time_keeps_its_own_offset_and_a_naive_one_takes_only_the_given_one():
    given = offset("+09:00")
    assert aware("2026-10-14T09:00:00Z", given, "t").utcoffset() == datetime.timedelta(0)
    assert aware("2026-10-14T09:00:00-04:00", given, "t").utcoffset() == datetime.timedelta(
        hours=-4
    )
    assert aware("2026-10-14T09:00:00", given, "t").utcoffset() == datetime.timedelta(hours=9)
    with pytest.raises(ForeignError, match="no UTC offset"):
        aware("2026-10-14T09:00:00", None, "t")


def _clew_export(tmp_path) -> str:
    path = tmp_path / ".scitex" / "clew" / "runtime" / "claims.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": "1.4",
                "generated_at": "2026-10-03T08:00:00Z",
                "attestation": {"tool": "scitex-clew", "version": "0.21.0"},
                "claims": [],
            }
        )
    )
    return str(path)


def test_both_readers_refuse_the_same_offset_and_an_existing_output_the_same_way(tmp_path, capsys):
    source = _clew_export(tmp_path)
    assert main(["from-clew", source, "--offset", "+0900"]) == 2
    assert "+HH:MM" in capsys.readouterr().out
    out = tmp_path / "records.jsonl"
    out.write_text("kept\n")
    assert main(["from-clew", source, "--output", str(out)]) == 2
    assert "never overwrites" in capsys.readouterr().out
    assert out.read_text() == "kept\n"
    report, config = tmp_path / "report.json", tmp_path / "paperdelta.yaml"
    assert main(["from-paperdelta", str(report), "--config", str(config), "--offset", "+0900"]) == 2
    assert "+HH:MM" in capsys.readouterr().out
