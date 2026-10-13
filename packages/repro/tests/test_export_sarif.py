"""The check records as SARIF, for GitHub code scanning.

A lossy projection, and the tests say where: what becomes a result, what becomes a
notification, where a result is shown, and which fields of a record SARIF has no place for.
The mapping is checked against SARIF 2.1.0 sections 3.27.9 (`kind`), 3.27.10 (`level`),
3.20.21 and 3.58.6 (notifications).
"""

from __future__ import annotations

import datetime
import json
import os
import pathlib

import jsonschema
import pytest
from repro import load
from repro.cli import main
from repro.export.sarif import (
    FINGERPRINT,
    GITHUB_FINGERPRINT,
    GITHUB_RESULT_LIMIT,
    NOT_CARRIED_NATIVELY,
    RECORD_PROPERTY,
    ResultLimitWarning,
    to_sarif_log,
)
from repro.models import Digest
from repro.record import check_records
from repro.verify import DEFAULT_BACKENDS, MetricBackend

CASES = pathlib.Path(__file__).parent / "conformance" / "cases"
WHEN = datetime.datetime(2026, 10, 13, 12, 0, tzinfo=datetime.UTC)

#: The official SARIF 2.1.0 JSON Schema is OASIS's, published under its IPR policy and with no
#: licence that plainly allows a copy here. Point this at a download of
#: https://docs.oasis-open.org/sarif/sarif/v2.1.0/errata01/os/schemas/sarif-schema-2.1.0.json
#: and the schema tests run against it.
OFFICIAL_SCHEMA = os.environ.get("REPRO_SARIF_SCHEMA")


class Broken(MetricBackend):
    def check(self, claim, evidence, paths):
        raise TypeError("a defect, not a finding")


def records_of(name, backends=DEFAULT_BACKENDS):
    return check_records(load(CASES / name / "repro.yaml"), WHEN, backends)


def run_of(records, **options):
    log = json.loads(to_sarif_log(records, **options))
    assert log["version"] == "2.1.0"
    (run,) = log["runs"]
    return run


def notifications(run):
    return run["invocations"][0]["toolExecutionNotifications"]


# ---------------------------------------------------------------------- what becomes a result


def test_a_mismatch_is_one_error_result_at_the_assertion_s_line_in_the_manifest(monkeypatch):
    monkeypatch.chdir(CASES / "value_mismatch")
    (result,) = run_of(check_records(load("repro.yaml"), WHEN))["results"]
    assert (result["kind"], result["level"]) == ("fail", "error")
    assert result["ruleId"] == "repro/mismatch/value_mismatch"
    lines = pathlib.Path("repro.yaml").read_text().splitlines()
    location = result["locations"][0]["physicalLocation"]
    assert location["artifactLocation"]["uri"] == "repro.yaml"
    assert lines[location["region"]["startLine"] - 1] == "  - kind: metric"
    assert "manuscript prints 9.9" in result["message"]["text"]
    assert "holds 3.2" in result["message"]["text"]


def test_an_address_that_does_not_resolve_is_a_warning_result():
    (result,) = run_of(records_of("pointer_absent"))["results"]
    assert (result["kind"], result["level"]) == ("fail", "warning")
    assert result["ruleId"] == "repro/not-found/pointer_absent"


def test_a_match_is_no_result_unless_asked_for():
    records = records_of("value_match")
    run = run_of(records)
    assert run["results"] == [] and notifications(run) == []
    (result,) = run_of(records, include_matches=True)["results"]
    assert (result["kind"], result["level"]) == ("pass", "none")
    assert result["ruleId"] == "repro/match/value_match"


def test_an_assertion_that_was_not_checked_is_a_notification_and_never_a_result():
    for options in ({}, {"include_matches": True}):
        run = run_of(records_of("artifact_missing"), **options)
        assert run["results"] == []
        (notification,) = notifications(run)
        assert notification["level"] == "warning"
        assert notification["descriptor"]["id"] == "repro/not-checked/artifact_missing"
        assert run["invocations"][0]["executionSuccessful"] is True
        assert run["properties"]["repro/outcomes"]["not-checked"] == 1
        assert run["properties"]["repro/notCheckedReasons"] == {"artifact_missing": 1}


def test_a_defect_is_a_result_and_a_notification_that_fails_the_run():
    run = run_of(records_of("value_match", backends=(Broken(),)))
    (result,) = run["results"]
    assert (result["kind"], result["level"]) == ("fail", "error")
    assert result["ruleId"] == "repro/error/backend_defect"
    (notification,) = notifications(run)
    assert notification["level"] == "error"
    assert run["invocations"][0]["executionSuccessful"] is False


def test_a_word_this_version_does_not_know_is_never_shown_as_a_pass():
    (record,) = records_of("value_match")
    unknown = record.model_copy(update={"native_outcome": "confirmed"})
    run = run_of([unknown], include_matches=True)
    assert run["results"] == []
    assert [n["level"] for n in notifications(run)] == ["warning"]
    assert run["properties"]["repro/outcomes"] == {
        "match": 0,
        "mismatch": 0,
        "not-found": 0,
        "not-checked": 1,
        "error": 0,
    }


def every_run():
    for case in sorted(CASES.iterdir()):
        records = check_records(load(case / "repro.yaml"), WHEN)
        yield case.name, records, run_of(records, include_matches=True)


def test_every_log_is_well_formed_over_every_fixture():
    for name, records, run in every_run():
        driver = run["tool"]["driver"]
        rules = [rule["id"] for rule in driver["rules"]]
        described = [descriptor["id"] for descriptor in driver["notifications"]]
        assert len(run["results"]) + len(notifications(run)) == len(records), name
        for result in run["results"]:
            assert rules[result["ruleIndex"]] == result["ruleId"], name
            # 3.27.10: a level other than `none` belongs to `fail` alone.
            assert (result["level"] == "none") == (result["kind"] != "fail"), name
            assert result["kind"] in ("fail", "pass"), name
            assert len(result["locations"]) == 1, "GitHub shows no result without a location"
            assert result["locations"][0]["physicalLocation"]["region"]["startLine"] >= 1
        for notification in notifications(run):
            assert (
                described[notification["descriptor"]["index"]] == notification["descriptor"]["id"]
            )
        for rule in driver["rules"]:
            assert rule["shortDescription"]["text"] and rule["fullDescription"]["text"]
            assert rule["help"]["text"]


@pytest.mark.skipif(not OFFICIAL_SCHEMA, reason="REPRO_SARIF_SCHEMA names no schema file")
def test_every_log_validates_against_the_official_schema():
    schema = json.loads(pathlib.Path(OFFICIAL_SCHEMA or "").read_text())
    validator = jsonschema.Draft4Validator(schema)
    for _, records, _ in every_run():
        for options in ({}, {"include_matches": True}):
            validator.validate(json.loads(to_sarif_log(records, **options)))
    validator.validate(json.loads(to_sarif_log(records_of("value_match", backends=(Broken(),)))))
    validator.validate(json.loads(to_sarif_log([])))


# -------------------------------------------------------------------------------- where it is


@pytest.fixture
def project(tmp_path, monkeypatch):
    """A paper that says thirty-five, a file that holds thirty-six, and a manifest one
    directory down from where the checker runs."""
    root = tmp_path / "study"
    root.mkdir()
    (root / "totals.json").write_text('{"responders": 36}\n')
    (root / "paper.md").write_text(
        "# Results\n\nOf those invited,\nthirty-five participants\nresponded (35 of 60).\n"
    )
    totals, paper = Digest.of_file(root / "totals.json"), Digest.of_file(root / "paper.md")
    (root / "repro.yaml").write_text(
        "schema_version: repro/1\n"
        "artifacts:\n"
        f"- {{id: totals, path: totals.json, digest: {{algorithm: sha256, value: {totals.value}}}}}\n"
        f"- {{id: paper, path: paper.md, digest: {{algorithm: sha256, value: {paper.value}}}}}\n"
        "claims:\n"
        "- id: responders\n"
        "  text: Thirty-five participants responded.\n"
        "  where: Results, first paragraph\n"
        "  evidence:\n"
        "  - kind: quote\n"
        "    artifact: paper\n"
        "    text: thirty-five participants responded\n"
        "  - kind: metric\n"
        "    artifact: totals\n"
        "    name: responders\n"
        "    reported: '35'\n"
        "    pointer: /responders\n"
        "- id: unquoted\n"
        "  text: Thirty-five.\n"
        "  evidence:\n"
        "  - kind: metric\n"
        "    artifact: totals\n"
        "    name: responders\n"
        "    reported: '35'\n"
        "    pointer: /responders\n"
    )
    monkeypatch.chdir(tmp_path)
    return root


def test_a_result_is_shown_at_the_sentence_the_claim_quotes(project):
    quoted, unquoted = run_of(check_records(load("study/repro.yaml"), WHEN))["results"]
    location = quoted["locations"][0]["physicalLocation"]
    # The claim's quotation starts on line 4 of the paper, and the paths are as named from
    # the directory the checker ran in.
    assert location == {"artifactLocation": {"uri": "study/paper.md"}, "region": {"startLine": 4}}
    assert [
        (r["physicalLocation"]["artifactLocation"]["uri"], r["message"]["text"])
        for r in quoted["relatedLocations"]
    ] == [("study/totals.json", "totals holds 36"), ("study/repro.yaml", "declared here")]

    fallback = unquoted["locations"][0]["physicalLocation"]
    assert fallback["artifactLocation"]["uri"] == "study/repro.yaml"
    lines = (project / "repro.yaml").read_text().splitlines()
    assert lines[fallback["region"]["startLine"] - 1] == "  - kind: metric"
    assert lines[fallback["region"]["startLine"] - 3] == "  text: Thirty-five."


def test_a_passage_that_cannot_be_placed_on_one_line_falls_back_to_the_manifest(project):
    paper = project / "paper.md"
    paper.write_text(paper.read_text() + "\nAgain: thirty-five participants responded.\n")
    results = run_of(check_records(load("study/repro.yaml"), WHEN))["results"]
    # The quotation is now ambiguous and is a result itself, beside the two numbers.
    assert [r["ruleId"].split("/")[1] for r in results] == ["not-found", "mismatch", "mismatch"]
    for result in results:
        located = result["locations"][0]["physicalLocation"]
        assert located["artifactLocation"]["uri"] == "study/repro.yaml"


def test_each_file_read_travels_with_its_digest(project):
    run = run_of(check_records(load("study/repro.yaml"), WHEN))
    assert {a["location"]["uri"]: a["hashes"]["sha-256"] for a in run["artifacts"]} == {
        "study/paper.md": Digest.of_file(project / "paper.md").value,
        "study/totals.json": Digest.of_file(project / "totals.json").value,
    }


def test_a_fingerprint_follows_the_assertion_and_not_its_line_or_its_position(project):
    def fingerprints():
        results = run_of(check_records(load("study/repro.yaml"), WHEN))["results"]
        return [result["partialFingerprints"] for result in results]

    before = fingerprints()
    assert len({prints[FINGERPRINT] for prints in before}) == 2
    for prints in before:
        assert prints[GITHUB_FINGERPRINT] == f"{prints[FINGERPRINT][:16]}:1"

    # The paper gains a paragraph above the sentence, and the claim a quotation above its
    # number: every line moves and the metric is now the third assertion.
    paper = project / "paper.md"
    paper.write_text("A new opening paragraph.\n\n" + paper.read_text())
    manifest = project / "repro.yaml"
    manifest.write_text(
        manifest.read_text().replace(
            "  - kind: metric\n    artifact: totals\n    name: responders\n    reported: '35'\n"
            "    pointer: /responders\n- id: unquoted",
            "  - kind: quote\n    artifact: paper\n    text: Of those invited\n"
            "  - kind: metric\n    artifact: totals\n    name: responders\n    reported: '35'\n"
            "    pointer: /responders\n- id: unquoted",
        )
    )
    assert fingerprints() == before


# --------------------------------------------------------------------------- what is not said


def paths_in(value, prefix=""):
    if isinstance(value, dict):
        for key, inner in value.items():
            yield f"{prefix}{key}"
            yield from paths_in(inner, f"{prefix}{key}.")
    elif isinstance(value, list):
        for inner in value:
            yield from paths_in(inner, prefix)


def test_the_whole_record_is_in_the_property_bag(project):
    records = check_records(load("study/repro.yaml"), WHEN)
    run = run_of(records, include_matches=True)
    assert [result["properties"][RECORD_PROPERTY] for result in run["results"]] == [
        json.loads(record.to_json()) for record in records
    ]


def test_documented_loss(project):
    """What SARIF says natively, and what it has no property for.

    Natively: the tool and its version, the time, the claim id and the detail in the message,
    each file's path, media type and digest on disk, and the lines. Everything in
    `NOT_CARRIED_NATIVELY` is in the property bag and nowhere else in the log.
    """
    native = {
        "checker",
        "checker.name",
        "checker.version",
        "checked_at",
        "manifest",
        "manifest.path",
        "claim",
        "claim.id",
        "claim.line",
        "assertion",
        "assertion.line",
        "reads",
        "reads.artifact",
        "reads.path",
        "reads.media_type",
        "reads.on_disk",
        "detail",
    }
    records = check_records(load("study/repro.yaml"), WHEN)
    found = {path for record in records for path in paths_in(json.loads(record.to_json()))}
    lost = {
        path
        for path in found
        if any(path == name or path.startswith(f"{name}.") for name in NOT_CARRIED_NATIVELY)
    }
    assert found - lost <= native, sorted(found - lost - native)
    assert set(NOT_CARRIED_NATIVELY) - {"execution", "history"} <= found

    log = json.loads(to_sarif_log(records))
    for result in log["runs"][0]["results"]:
        del result["properties"]
    said = json.dumps(log)
    for record in records:
        assert record.claim.digest not in said
        assert '"native_outcome"' not in said and '"check_type"' not in said


def test_more_results_than_github_keeps_is_warned_about_and_nothing_is_dropped():
    (record,) = records_of("value_match")
    many = [record] * (GITHUB_RESULT_LIMIT + 1)
    with pytest.warns(ResultLimitWarning, match="5001 results"):
        log = json.loads(to_sarif_log(many, include_matches=True))
    assert len(log["runs"][0]["results"]) == GITHUB_RESULT_LIMIT + 1
    assert json.loads(to_sarif_log(many))["runs"][0]["results"] == []


# ------------------------------------------------------------------------------- the command


def test_export_sarif_prints_a_log_and_exits_0_on_a_mismatch(project, capsys):
    assert main(["export", "sarif", "study/repro.yaml"]) == 0
    log = json.loads(capsys.readouterr().out)
    assert [r["ruleId"] for r in log["runs"][0]["results"]] == ["repro/mismatch/value_mismatch"] * 2
    assert log["runs"][0]["properties"]["repro/matchesIncluded"] == "no"

    assert main(["export", "sarif", "study/repro.yaml", "--include-matches"]) == 0
    kinds = [r["kind"] for r in json.loads(capsys.readouterr().out)["runs"][0]["results"]]
    assert kinds == ["pass", "fail", "fail"]


def test_include_matches_belongs_to_sarif(project, capsys):
    assert main(["export", "record", "study/repro.yaml", "--include-matches"]) == 2
    assert "repro export sarif" in capsys.readouterr().out
