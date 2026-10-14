"""The check record: one line per checked assertion, for another program to read.

The fixtures are the conformance corpus, so every outcome and every evidence kind the contract
defines is put through the record. Two things are held throughout: a record states what
`repro verify` found and nothing else, and a record that says something no check could have
found is refused.
"""

from __future__ import annotations

import copy
import datetime
import hashlib
import json
import pathlib

import jsonschema
import pytest
from repro import load, verify
from repro.cli import main
from repro.models import (
    ArtifactRef,
    Claim,
    Digest,
    InputReading,
    Manifest,
    MetricEvidence,
    Outcome,
    Regeneration,
    RegenerationReason,
    RegenerationRecord,
    RegenerationState,
    ReproductionReport,
    RunOutput,
)
from repro.record import (
    CHECK_TYPES,
    RECORD_VERSION,
    CheckType,
    ExportRecord,
    InvalidRecordError,
    NormalizedOutcome,
    UnmappedError,
    check_records,
    check_type,
    normalized,
    problems,
    read_outcome,
    to_jsonl,
    understood,
    validate,
)
from repro.reproduce import append
from repro.verify import DEFAULT_BACKENDS, MetricBackend

ROOT = pathlib.Path(__file__).resolve().parents[3]
CASES = sorted(
    (
        pathlib.Path(__file__).resolve().parents[2] / "claims" / "tests" / "conformance" / "cases"
    ).iterdir()
)
SCHEMA = ROOT / "docs" / "schemas" / "claim-check-0.1-experimental.schema.json"
WHEN = datetime.datetime(2026, 10, 13, 12, 0, tzinfo=datetime.UTC)


def case(name):
    return load(
        pathlib.Path(__file__).resolve().parents[2]
        / "claims"
        / "tests"
        / "conformance"
        / "cases"
        / name
        / "repro.yaml"
    )


def one(name, backends=DEFAULT_BACKENDS):
    (record,) = check_records(case(name), WHEN, backends)
    return record


def as_dict(record):
    return json.loads(record.to_json())


def refused(data):
    with pytest.raises(InvalidRecordError) as caught:
        validate(data)
    return " | ".join(caught.value.problems)


class Broken(MetricBackend):
    def check(self, claim, evidence, paths):
        raise TypeError("a defect, not a finding")


# ------------------------------------------------------------------- every fixture, one record


@pytest.mark.parametrize("path", CASES, ids=lambda p: p.name)
def test_a_fixture_yields_one_consistent_record_per_assertion(path):
    manifest = load(path / "repro.yaml")
    records = check_records(manifest, WHEN)
    expected = json.loads((path / "expected.json").read_text())
    offered = [(o, r) for o, r in zip(expected["outcomes"], expected["reasons"], strict=True) if r]

    assert len(records) == sum(len(claim.evidence) for claim in manifest.claims)
    assert [(r.native_outcome, r.native_reason) for r in records] == offered
    for record in records:
        assert problems(record) == ()
        assert record.outcome is normalized(Outcome(record.native_outcome))
        assert record.check_type is CHECK_TYPES[record.assertion.kind]


@pytest.mark.parametrize("path", CASES, ids=lambda p: p.name)
def test_a_record_survives_a_line_of_json_and_fits_the_schema(path):
    schema = json.loads(SCHEMA.read_text())
    records = check_records(load(path / "repro.yaml"), WHEN)
    lines = to_jsonl(records).splitlines()
    assert len(lines) == len(records)
    for line, record in zip(lines, records, strict=True):
        jsonschema.validate(json.loads(line), schema)
        assert validate(json.loads(line)) == record


def test_the_schema_on_disk_is_the_one_the_model_gives():
    generated = json.dumps(ExportRecord.model_json_schema(), indent=2, sort_keys=True) + "\n"
    assert SCHEMA.read_text() == generated, (
        f"{SCHEMA.relative_to(ROOT)} is stale: write "
        "json.dumps(ExportRecord.model_json_schema(), indent=2, sort_keys=True) to it"
    )


def test_the_schema_is_published_at_the_address_its_id_names():
    schema = json.loads(SCHEMA.read_text())
    published = schema["$id"].removeprefix("https://reproducible.science/")
    assert published == f"schemas/{SCHEMA.name}"
    served = ROOT / "site" / "public" / published
    assert served.read_text() == SCHEMA.read_text(), (
        f"{served.relative_to(ROOT)} is stale: run `npm run sync` in site/"
    )


def booleans(value, path=""):
    if isinstance(value, bool):
        yield path
    elif isinstance(value, dict):
        for key, inner in value.items():
            # A row predicate is the author's own value, and may be a boolean.
            if key != "address":
                yield from booleans(inner, f"{path}/{key}")
    elif isinstance(value, list):
        for index, inner in enumerate(value):
            yield from booleans(inner, f"{path}/{index}")


@pytest.mark.parametrize("path", CASES, ids=lambda p: p.name)
def test_no_field_is_a_bare_boolean(path):
    for record in check_records(load(path / "repro.yaml"), WHEN):
        assert list(booleans(as_dict(record))) == []
        assert not {"verified", "passed", "ok", "success"} & set(as_dict(record))


# ------------------------------------------------------------------------- what a record says


def test_a_mismatched_value_carries_what_is_stored_and_what_is_reported():
    record = one("value_mismatch")
    assert (record.outcome, record.native_outcome) == (NormalizedOutcome.MISMATCH, "mismatch")
    assert record.check_type is CheckType.VALUE_COMPARISON
    (read,) = record.reads
    assert (read.stored, record.printed) == ("3.2", "9.9")
    assert read.address.model_dump() == {"kind": "tree", "contract": 1, "pointer": "/delta"}
    assert (
        read.pinned
        == read.on_disk
        == Digest.of_file(CASES[0].parent / "value_mismatch" / "results.json").value
    )
    assert (record.comparison.mode.value, record.comparison.tolerance) == ("printed_precision", "0")


def test_a_table_cell_is_addressed_by_its_column_and_row():
    record = one("table_cell_mismatch")
    (read,) = record.reads
    assert read.address.model_dump(exclude={"contract", "delimiter"}) == {
        "kind": "table",
        "column": "accuracy",
        "where": {"model": "LASSO-Cox"},
    }
    assert (read.stored, record.printed) == ("0.6478999999999999", "0.900")


def test_a_quotation_reports_the_passage_and_stores_no_value():
    present, absent = one("passage_present"), one("passage_absent")
    assert present.check_type is absent.check_type is CheckType.PASSAGE_PRESENCE
    assert (present.outcome, absent.outcome) == (
        NormalizedOutcome.MATCH,
        NormalizedOutcome.MISMATCH,
    )
    assert present.printed == "matches the Haar expectation"
    assert present.reads[0].address.kind == "passage"
    assert present.reads[0].stored is None and present.comparison is None


def test_a_correspondence_carries_both_sides_and_no_reported_value():
    record = one("correspondence_mismatch")
    assert record.check_type is CheckType.CORRESPONDENCE
    assert record.printed is None
    assert [(r.side, r.artifact, r.stored) for r in record.reads] == [
        ("stated", "doc", "18"),
        ("measured", "counts", "19"),
    ]
    assert [r.address.kind for r in record.reads] == ["prose", "tree"]


def test_an_aggregate_carries_every_member_the_statistic_and_what_it_computed():
    record = one("aggregate_mismatch")
    assert record.check_type is CheckType.AGGREGATE_COMPARISON
    assert record.comparison.count == len(record.reads) == 4
    assert [(read.artifact, read.stored) for read in record.reads] == [
        ("run0", "1"),
        ("run1", "1"),
        ("run2", "2"),
        ("run3", "4"),
    ]
    assert (record.comparison.statistic, record.comparison.computed, record.printed) == (
        "mean",
        "2",
        "4",
    )
    assert record.outcome is NormalizedOutcome.MISMATCH


def test_a_conversion_is_named_and_the_converted_value_sits_beside_the_stored_one():
    converted, plain = check_records(case("value_match_converted"), WHEN)
    (read,) = converted.reads
    assert converted.comparison.conversion == "percent"
    assert (read.stored, read.converted, converted.printed) == ("0.0424", "4.24", "4.2")
    assert converted.outcome is NormalizedOutcome.MATCH
    # The same address with no conversion declared: nothing is converted, and it differs.
    assert plain.comparison.conversion is None and plain.reads[0].converted is None
    assert plain.outcome is NormalizedOutcome.MISMATCH


def test_declared_places_travel_with_the_comparison():
    mismatch, _ = check_records(case("value_places_mismatch"), WHEN)
    assert mismatch.comparison.places == 1
    assert (mismatch.printed, mismatch.native_reason) == ("4.20", "places_mismatch")


def test_one_side_that_does_not_resolve_is_not_found_and_keeps_the_side_that_did():
    record = one("correspondence_side_absent")
    assert (record.outcome, record.native_outcome) == (NormalizedOutcome.NOT_FOUND, "not_found")
    assert sum(read.stored is not None for read in record.reads) == 1


def test_an_absent_file_is_not_checked_and_its_validity_is_stated_apart():
    record = one("artifact_missing")
    assert (record.outcome, record.native_outcome) == (NormalizedOutcome.NOT_CHECKED, "unchecked")
    (read,) = record.reads
    assert read.validity.value == "artifact_absent" and read.on_disk is None


def test_a_broken_pin_is_a_fact_about_the_file_and_leaves_the_outcome_alone():
    record = one("broken_pin")
    (read,) = record.reads
    assert read.validity.value == "broken_pin" and read.pinned != read.on_disk
    assert record.native_outcome == "verified"


def test_a_backend_defect_is_an_error_and_reads_no_value():
    record = one("value_match", backends=(Broken(),))
    assert (record.outcome, record.native_outcome) == (NormalizedOutcome.ERROR, "error")
    assert record.native_reason == "backend_defect"
    assert record.reads[0].stored is None
    assert problems(record) == ()


def test_every_record_names_the_checker_the_time_and_the_manifest(monkeypatch, tmp_path):
    manifest = CASES[0].parent / "value_match" / "repro.yaml"
    monkeypatch.chdir(manifest.parent.parent)
    record = one("value_match")
    assert record.record == RECORD_VERSION
    assert record.checker.name == "repro" and record.checker.version
    assert record.checker.url == "https://github.com/elliottower/reproducible-science"
    assert record.checked_at == WHEN
    assert record.manifest.path == "value_match/repro.yaml"
    assert record.manifest.digest == hashlib.sha256(manifest.read_bytes()).hexdigest()

    # From a directory the manifest does not lie under, only its name: a record is committed
    # and published, and never says where on a machine it was made.
    monkeypatch.chdir(tmp_path)
    assert one("value_match").manifest.path == "repro.yaml"


# ------------------------------------------------------------------------------- the mapping


@pytest.mark.parametrize(
    ("outcome", "expected"),
    [
        (Outcome.VERIFIED, NormalizedOutcome.MATCH),
        (Outcome.MISMATCH, NormalizedOutcome.MISMATCH),
        (Outcome.NOT_FOUND, NormalizedOutcome.NOT_FOUND),
        (Outcome.UNCHECKED, NormalizedOutcome.NOT_CHECKED),
        (Outcome.ERROR, NormalizedOutcome.ERROR),
        (Outcome.NOT_OFFERED, NormalizedOutcome.NOT_CHECKED),
    ],
)
def test_each_outcome_normalizes_to_one_word(outcome, expected):
    assert normalized(outcome) is expected


def test_no_outcome_is_left_without_a_mapping():
    assert {normalized(outcome) for outcome in Outcome} == set(NormalizedOutcome)


def test_an_outcome_or_a_kind_with_no_mapping_is_refused_and_never_defaulted():
    with pytest.raises(UnmappedError):
        normalized("partial")
    with pytest.raises(UnmappedError):
        check_type("vote")


def test_only_verified_normalizes_to_match():
    assert [o for o in Outcome if normalized(o) is NormalizedOutcome.MATCH] == [Outcome.VERIFIED]


# ----------------------------------------------------------------------------- the validator


def changed(name, **edits):
    data = copy.deepcopy(as_dict(one(name)))
    for dotted, value in edits.items():
        target = data
        *parents, last = dotted.split("__")
        for key in parents:
            target = target[int(key)] if key.isdigit() else target[key]
        if value is None:
            target.pop(last, None)
        else:
            target[last] = value
    return data


def test_a_mismatch_without_a_stored_value_is_refused():
    assert "needs a stored and a printed value" in refused(
        changed("value_mismatch", reads__0__stored=None)
    )


def test_a_mismatch_without_a_reported_value_is_refused():
    assert "needs a stored and a printed value" in refused(changed("value_mismatch", printed=None))


def test_a_correspondence_missing_one_side_of_a_match_is_refused():
    assert "needs the value stored on each side" in refused(
        changed("correspondence_match", reads__1__stored=None)
    )


def test_a_converted_comparison_without_the_converted_value_is_refused():
    data = as_dict(check_records(case("value_match_converted"), WHEN)[0])
    del data["reads"][0]["converted"]
    assert "needs the converted value that was compared" in refused(data)


def test_an_aggregate_without_its_statistic_or_its_count_is_refused():
    for missing in ("statistic", "count"):
        data = changed("aggregate_match")
        del data["comparison"][missing]
        assert "names its statistic and its count" in refused(data)


def test_an_aggregate_whose_count_is_not_its_members_is_refused():
    data = changed("aggregate_match")
    data["reads"].pop()
    assert "members reads" in refused(data)


def test_an_aggregate_match_missing_a_member_s_value_or_what_was_computed_is_refused():
    assert "every member's stored value" in refused(
        changed("aggregate_match", reads__0__stored=None)
    )
    assert "what the statistic computed" in refused(
        changed("aggregate_match", comparison__computed=None)
    )


def test_an_aggregate_is_not_called_a_comparison_with_one_stored_value():
    said = refused(changed("aggregate_match", check_type="value-comparison"))
    assert "an 'aggregate' assertion is an aggregate-comparison" in said
    record = one("aggregate_match")
    assert record.check_type.value == "aggregate-comparison"
    assert understood(record) and read_outcome(record) is NormalizedOutcome.MATCH


def test_a_match_on_a_tie_prints_one_of_its_two_values():
    data = changed("value_match")
    data["comparison"]["tie"] = {"lower": "3.2", "upper": "3.3", "printed": "3.2"}
    assert validate(data).comparison.tie.upper == "3.3"
    data["comparison"]["tie"]["printed"] = "3.4"
    assert "prints one of the two values" in refused(data)


def test_warnings_travel_as_the_tool_words_them():
    assert one("passage_present").warnings == ("short",)


def test_a_passage_presence_that_stores_a_value_is_refused():
    assert "compares no value" in refused(changed("passage_present", reads__0__stored="3.2"))


def test_not_checked_carrying_a_comparison_is_refused():
    said = refused(changed("artifact_missing", stages__comparison="match", reads__0__stored="3.2"))
    assert "means nothing was compared" in said
    assert "no stored value was read" in said


def test_an_outcome_its_native_word_does_not_give_is_refused():
    assert "is not what 'mismatch' normalizes to" in refused(
        changed("value_mismatch", outcome="match")
    )


def test_a_native_word_the_stages_do_not_give_is_refused():
    assert "does not follow from the stages" in refused(
        changed("value_mismatch", stages__comparison="match")
    )


def test_not_found_against_an_absent_file_is_refused():
    data = changed(
        "pointer_absent",
        reads__0__validity="artifact_absent",
        reads__0__on_disk=None,
    )
    assert "not-found needs a readable file" in refused(data)


def test_a_match_against_an_absent_file_is_refused():
    data = changed("value_match", reads__0__validity="artifact_absent", reads__0__on_disk=None)
    assert "needs every file to have been read" in refused(data)


def test_an_error_whose_stages_say_the_tool_ran_is_refused():
    data = as_dict(one("value_match", backends=(Broken(),)))
    data["stages"]["execution"] = "completed"
    assert "error means the tool failed" in refused(data)


def test_validity_the_digests_do_not_bear_out_is_refused():
    assert "authoritative" in refused(changed("value_match", reads__0__on_disk="0" * 64))
    assert "broken pin" in refused(changed("value_match", reads__0__validity="broken_pin"))
    assert "unpinned" in refused(changed("value_match", reads__0__validity="unpinned_artifact"))


def test_a_check_type_that_compares_nothing_cannot_carry_a_pair_of_values():
    assert "compares no values" in refused(changed("value_match", check_type="artifact-identity"))
    identity = changed(
        "value_match",
        check_type="artifact-identity",
        printed=None,
        comparison=None,
        reads__0__stored=None,
        stages=None,
        native_outcome="verified",
    )
    identity["checker"]["name"] = "another-tool"
    identity["outcome"] = "not-checked"
    assert validate(identity).check_type is CheckType.ARTIFACT_IDENTITY


def test_a_check_type_outside_the_closed_set_is_refused():
    assert "check_type" in refused(changed("value_match", check_type="vibes"))


def test_another_record_version_is_refused():
    assert "this reader knows" in refused(changed("value_match", record="repro.check/9"))


def test_a_field_that_is_not_the_right_shape_names_itself():
    assert "checked_at" in refused(changed("value_match", checked_at="yesterday"))


# ----------------------------------------------------------------- unknown stays unknown


def test_an_unknown_address_kind_is_kept_and_its_match_is_read_as_not_checked():
    data = changed("value_match")
    data["reads"][0]["address"] = {"kind": "xpath", "path": "//td[3]", "namespaces": {"a": "b"}}
    record = validate(data)
    assert record.reads[0].address.model_dump() == data["reads"][0]["address"]
    assert as_dict(record)["reads"][0]["address"] == data["reads"][0]["address"]
    assert record.outcome is NormalizedOutcome.MATCH
    assert read_outcome(record) is NormalizedOutcome.NOT_CHECKED


def test_a_native_word_this_version_does_not_know_is_never_a_match():
    data = changed("value_match", native_outcome="confirmed")
    assert "not-checked at best, never a match" in refused(data)
    record = ExportRecord.model_validate(data)
    assert read_outcome(record) is NormalizedOutcome.NOT_CHECKED


def test_a_word_repro_emits_means_nothing_from_a_checker_that_is_not_known():
    data = changed("value_match")
    data["checker"]["name"] = "another-tool"
    assert "never a match" in refused(data)
    assert read_outcome(ExportRecord.model_validate(data)) is NormalizedOutcome.NOT_CHECKED


def test_a_check_type_that_is_other_is_never_read_as_a_match():
    record = ExportRecord.model_validate(
        changed("passage_present", check_type="other", printed=None, reads__0__address=None)
    )
    assert read_outcome(record) is NormalizedOutcome.NOT_CHECKED


def test_a_finding_that_is_not_understood_is_passed_on_as_it_is():
    data = changed("value_mismatch", native_outcome="disagrees")
    data["checker"]["name"] = "another-tool"
    data.pop("stages")
    assert read_outcome(validate(data)) is NormalizedOutcome.MISMATCH


# ----------------------------------------------------------- lines, and the commands upstream


def write(path, text):
    path.write_text(text)
    return Digest.of_file(path)


@pytest.fixture
def project(tmp_path):
    """A command `sum` writes totals.json from counts.json, and a paper quotes the total."""
    counts = write(tmp_path / "counts.json", '{"a": 20, "b": 15}\n')
    totals = write(tmp_path / "totals.json", '{"responders": 35}\n')
    paper = write(
        tmp_path / "paper.md",
        "# Results\n\nOf those invited,\nthirty-five participants\nresponded (35 of 60).\n",
    )
    (tmp_path / "repro.yaml").write_text(
        "schema_version: repro/1\n"
        "project: lines\n"
        "artifacts:\n"
        f"- {{id: counts, path: counts.json, digest: {{algorithm: sha256, value: {counts.value}}}}}\n"
        f"- {{id: totals, path: totals.json, digest: {{algorithm: sha256, value: {totals.value}}}}}\n"
        f"- {{id: paper, path: paper.md, media_type: text/markdown, digest: {{algorithm: sha256, value: {paper.value}}}}}\n"
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
        "regenerations:\n"
        "- id: sum\n"
        "  command: [python3, totals.py]\n"
        "  inputs:\n"
        f"  - {{artifact: counts, digest: {{algorithm: sha256, value: {counts.value}}}}}\n"
        f"  output: {{artifact: totals, digest: {{algorithm: sha256, value: {totals.value}}}}}\n"
    )
    return tmp_path


def rerun(root, state=Regeneration.REPRODUCED):
    manifest = load(root / "repro.yaml")
    (made,) = manifest.regenerations
    written = Digest.of_file(root / "totals.json").value
    append(
        ReproductionReport(
            started_at="2026-10-01T09:00:00+00:00",
            ended_at="2026-10-01T09:00:05+00:00",
            tool_version="0.5.5",
            regenerations=(
                RegenerationState(
                    regeneration_id=made.id,
                    artifact_id="totals",
                    state=state,
                    reason=RegenerationReason.OUTPUT_MATCHES,
                    expected=written,
                    actual=written,
                    executed=True,
                    command=made.command,
                    exit_code=0,
                    duration_seconds=1.5,
                    inputs=(
                        InputReading(
                            artifact_id="counts",
                            path="counts.json",
                            pinned=made.inputs[0].digest.value,
                            observed=Digest.of_file(root / "counts.json").value,
                        ),
                    ),
                ),
            ),
        ),
        root,
    )


def test_a_claim_and_each_assertion_name_their_line_in_the_manifest(project):
    quote, metric = check_records(load(project / "repro.yaml"), WHEN)
    lines = (project / "repro.yaml").read_text().splitlines()
    assert lines[quote.claim.line - 1] == "- id: responders"
    assert lines[quote.assertion.line - 1] == "  - kind: quote"
    assert lines[metric.assertion.line - 1] == "  - kind: metric"
    assert (quote.assertion.index, metric.assertion.index) == (0, 1)
    assert (quote.assertion.position, metric.assertion.position) == (0, 0)


def test_position_counts_among_assertions_of_one_kind_and_name(project):
    """The identity `.repro/checks.jsonl` keeps a history under: claim id, kind, name, and the
    position among the claim's assertions of that kind and name."""
    manifest = project / "repro.yaml"
    manifest.write_text(
        manifest.read_text().replace(
            "  - kind: metric\n",
            "  - kind: quote\n    artifact: paper\n    text: Of those invited\n  - kind: metric\n",
        )
    )
    records = check_records(load(manifest), WHEN)
    assert [
        (r.claim.id, r.assertion.kind, r.assertion.name, r.assertion.position) for r in records
    ] == [
        ("responders", "quote", "", 0),
        ("responders", "quote", "", 1),
        ("responders", "metric", "responders", 0),
    ]
    assert [r.assertion.index for r in records] == [0, 1, 2]


def test_history_is_reserved_and_nothing_writes_it(project):
    quote, metric = check_records(load(project / "repro.yaml"), WHEN)
    assert quote.history is None and metric.history is None
    assert not (project / ".repro").exists(), "an export stores nothing"
    data = as_dict(metric) | {
        "history": {"states": 2, "last_changed_at": "2026-10-13T21:03:22+00:00"}
    }
    assert validate(data).history.states == 2


def test_a_passage_in_a_text_file_names_the_line_it_starts_on(project):
    quote, metric = check_records(load(project / "repro.yaml"), WHEN)
    # The passage runs over a line break in the file, and starts on line 4.
    (passage,) = quote.claim.passages
    assert (passage.assertion, passage.path, passage.line) == (0, "paper.md", 4)
    assert metric.claim.passages == quote.claim.passages


def test_a_passage_that_occurs_twice_gets_no_line(project):
    paper = project / "paper.md"
    paper.write_text(paper.read_text() + "\nAgain: thirty-five participants responded.\n")
    quote, _ = check_records(load(project / "repro.yaml"), WHEN)
    assert quote.claim.passages[0].line is None


def test_no_execution_block_where_no_command_writes_what_is_read(project):
    quote, _ = check_records(load(project / "repro.yaml"), WHEN)
    assert quote.execution is None
    assert "execution" not in as_dict(quote)


def test_a_command_with_no_recorded_rerun_is_named_and_never_rerun(project):
    _, metric = check_records(load(project / "repro.yaml"), WHEN)
    (command,) = metric.execution.commands
    assert (command.id, command.command, command.steps) == ("sum", ("python3", "totals.py"), 0)
    assert command.state.value == metric.execution.state.value == "never_rerun"
    assert command.last_rerun is None
    assert (command.output.artifact, [i.artifact for i in command.inputs]) == ("totals", ["counts"])
    assert command.inputs[0].pinned == Digest.of_file(project / "counts.json").value


def test_a_recorded_rerun_is_carried_with_its_time_and_what_it_found(project):
    rerun(project)
    _, metric = check_records(load(project / "repro.yaml"), WHEN)
    (command,) = metric.execution.commands
    assert command.state.value == "current"
    assert command.last_rerun.model_dump(mode="json") == {
        "started_at": "2026-10-01T09:00:00+00:00",
        "ended_at": "2026-10-01T09:00:05+00:00",
        "state": "reproduced",
        "reason": "output_matches",
        "checker_version": "0.5.5",
        "exit_code": 0,
        "duration_seconds": 1.5,
        "output_digest": Digest.of_file(project / "totals.json").value,
    }
    assert problems(metric) == ()
    assert validate(as_dict(metric)) == metric


def test_an_input_edited_after_the_rerun_leaves_the_assertion_stale(project):
    rerun(project)
    (project / "counts.json").write_text('{"a": 21, "b": 15}\n')
    _, metric = check_records(load(project / "repro.yaml"), WHEN)
    assert metric.execution.state.value == "stale"
    assert metric.execution.commands[0].causes == ("input_changed",)
    assert metric.execution.commands[0].inputs[0].validity.value == "broken_pin"
    assert metric.native_outcome == "verified", "staleness is not an outcome"


def test_a_manifest_built_in_memory_has_no_path_and_no_lines(tmp_path):
    results = tmp_path / "r.json"
    results.write_text('{"x": 3.2}')
    manifest = Manifest(
        artifacts=(ArtifactRef(id="r", path=results, digest=Digest.of_file(results)),),
        claims=(
            Claim(
                id="c",
                text="t",
                evidence=(MetricEvidence(artifact="r", name="x", reported="3.2", pointer="/x"),),
            ),
        ),
        regenerations=(
            RegenerationRecord(id="g", command=("true",), output=RunOutput(artifact="r")),
        ),
    )
    (record,) = check_records(manifest, WHEN)
    assert (record.manifest.path, record.manifest.digest) == ("", None)
    assert record.claim.line is None and record.assertion.line is None
    assert problems(record) == ()


# ------------------------------------------------------------------------------- the command


def snapshot(root):
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def test_export_prints_one_line_per_assertion_and_writes_nothing(project, capsys):
    before = snapshot(project)
    assert main(["export", "record", str(project / "repro.yaml")]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert [json.loads(line)["assertion"]["kind"] for line in lines] == ["quote", "metric"]
    assert snapshot(project) == before


def test_export_writes_the_file_it_is_asked_for_and_no_other(project, tmp_path_factory, capsys):
    out = tmp_path_factory.mktemp("out") / "checks.jsonl"
    before = snapshot(project)
    assert main(["export", "record", str(project / "repro.yaml"), "-o", str(out)]) == 0
    assert capsys.readouterr().out == ""
    assert [validate(json.loads(line)).claim.id for line in out.read_text().splitlines()] == [
        "responders",
        "responders",
    ]
    assert snapshot(project) == before
    assert [p.name for p in out.parent.iterdir()] == ["checks.jsonl"]


def test_export_exits_0_on_a_mismatch_that_verify_exits_1_on(capsys):
    manifest = str(CASES[0].parent / "value_mismatch" / "repro.yaml")
    assert main(["export", "record", manifest]) == 0
    assert json.loads(capsys.readouterr().out)["outcome"] == "mismatch"
    assert main(["verify", manifest]) == 1
    assert "MISS" in capsys.readouterr().out
    assert main(["verify", str(CASES[0].parent / "value_match" / "repro.yaml")]) == 0


def test_export_with_no_manifest_exits_2(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert main(["export", "record"]) == 2
    assert "no repro.yaml here or above" in capsys.readouterr().out


def test_the_record_and_the_report_agree_on_every_fixture():
    for path in CASES:
        manifest = load(path / "repro.yaml")
        decisions = verify(manifest).decisions
        records = check_records(manifest, WHEN)
        assert [r.native_outcome for r in records] == [d.outcome.value for d in decisions]
        assert [r.detail for r in records] == [d.detail for d in decisions]


def test_this_repository_s_own_manifest_yields_one_record_per_assertion():
    manifest = load(ROOT / "repro.yaml")
    records = check_records(manifest, WHEN)
    assert len(records) == sum(len(claim.evidence) for claim in manifest.claims)
    assert all(problems(record) == () for record in records)
    assert all(record.claim.line and record.assertion.line for record in records)
