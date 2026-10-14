"""The check records as an RO-Crate metadata document.

Two properties carry the rest. The crate is written from the records and from nothing else, so
it can be read back into them and compared; and it is a document other tools open, so every
reference in it has to lead somewhere.
"""

from __future__ import annotations

import datetime
import json
import pathlib

import pytest
from repro import load
from repro.cli import main
from repro.export.rocrate import (
    METADATA_FILE,
    PROCESS_RUN_CRATE,
    PROFILE,
    RO_CRATE,
    TERMS,
    ConflictingRecordsError,
    NotAClaimCheckCrateError,
    NothingToExportError,
    from_ro_crate,
    to_ro_crate,
)
from repro.models import (
    Digest,
    InputReading,
    Regeneration,
    RegenerationReason,
    RegenerationState,
    ReproductionReport,
)
from repro.record import (
    CheckType,
    ExportRecord,
    History,
    NormalizedOutcome,
    Tie,
    check_records,
    read_outcome,
)
from repro.reproduce import append
from repro.verify import DEFAULT_BACKENDS, MetricBackend

ROOT = pathlib.Path(__file__).resolve().parents[3]
CASES = sorted(
    (
        pathlib.Path(__file__).resolve().parents[2] / "claims" / "tests" / "conformance" / "cases"
    ).iterdir()
)
WHEN = datetime.datetime(2026, 10, 13, 12, 0, tzinfo=datetime.UTC)

#: Every term the crate takes from the RO-Crate 1.3 context, which is schema.org's but for
#: `conformsTo` and `Profile`. Written out so a term cannot come into use unnoticed.
REUSED = {
    "ActionStatusType",
    "CheckAction",
    "Claim",
    "CreateAction",
    "CreativeWork",
    "Dataset",
    "DefinedTerm",
    "File",
    "HowTo",
    "Profile",
    "PropertyValue",
    "SoftwareApplication",
    "about",
    "actionStatus",
    "alternateName",
    "conformsTo",
    "datePublished",
    "description",
    "encodingFormat",
    "endTime",
    "error",
    "hasPart",
    "identifier",
    "instrument",
    "license",
    "mentions",
    "name",
    "object",
    "result",
    "sha256",
    "startTime",
    "termCode",
    "text",
    "url",
    "value",
    "version",
}


class Broken(MetricBackend):
    def check(self, claim, evidence, paths):
        raise TypeError("a defect, not a finding")


def records_of(name, backends=DEFAULT_BACKENDS):
    return check_records(load(CASES[0].parent / name / "repro.yaml"), WHEN, backends)


def graph_of(records):
    return json.loads(to_ro_crate(records))["@graph"]


def by_id(graph):
    return {entity["@id"]: entity for entity in graph}


def of_type(graph, name):
    return [
        e for e in graph if name in (e["@type"] if isinstance(e["@type"], list) else [e["@type"]])
    ]


def references(value):
    """Every `{"@id": ...}` a value holds, at any depth."""
    if isinstance(value, dict):
        if set(value) == {"@id"}:
            yield value["@id"]
        else:
            for key, inner in value.items():
                if key != "@id":
                    yield from references(inner)
    elif isinstance(value, list):
        for inner in value:
            yield from references(inner)


def write(path, text):
    path.write_text(text)
    return Digest.of_file(path)


@pytest.fixture
def project(tmp_path):
    """`sum` writes totals.json from counts.json and `shape` writes counts.json from raw.csv; a
    paper quotes the total, and one assertion compares the paper with the file."""
    raw = write(tmp_path / "raw.csv", "id,arm\n1,a\n2,b\n")
    counts = write(tmp_path / "counts.json", '{"a": 20, "b": 15}\n')
    totals = write(tmp_path / "totals.json", '{"responders": 35, "invited": 60}\n')
    paper = write(tmp_path / "my paper.md", "# Results\n\nIn all 35 participants responded.\n")

    def pin(digest):
        return f"{{algorithm: sha256, value: {digest.value}}}"

    (tmp_path / "repro.yaml").write_text(
        "schema_version: repro/1\n"
        "project: crate\n"
        "artifacts:\n"
        f"- {{id: raw, path: raw.csv, media_type: text/csv, digest: {pin(raw)}}}\n"
        f"- {{id: counts, path: counts.json, media_type: application/json, digest: {pin(counts)}}}\n"
        f"- {{id: totals, path: totals.json, media_type: application/json, digest: {pin(totals)}}}\n"
        f"- {{id: paper, path: my paper.md, media_type: text/markdown, digest: {pin(paper)}}}\n"
        "- {id: gone, path: gone.json}\n"
        "claims:\n"
        "- id: responders\n"
        "  text: Thirty-five participants responded.\n"
        "  where: Results, first paragraph\n"
        "  evidence:\n"
        "  - {kind: quote, artifact: paper, text: 35 participants responded}\n"
        "  - {kind: metric, artifact: totals, name: responders, reported: '35', pointer: /responders}\n"
        "  - kind: correspondence\n"
        "    name: paper-and-file\n"
        "    sides:\n"
        "    - {name: stated, artifact: paper, locator: {kind: prose, before: In all, after: participants}}\n"
        "    - {name: stored, artifact: totals, locator: {kind: tree, pointer: /responders}}\n"
        "- id: invited\n"
        "  text: Sixty were invited.\n"
        "  evidence:\n"
        "  - {kind: metric, artifact: totals, name: invited, reported: '61', pointer: /invited}\n"
        "  - {kind: metric, artifact: gone, name: lost, reported: '1', pointer: /x}\n"
        "  - {kind: metric, artifact: nowhere, name: undeclared, reported: '1', pointer: /x}\n"
        "regenerations:\n"
        "- id: shape\n"
        "  command: [python3, shape.py, --arm, a b]\n"
        f"  inputs: [{{artifact: raw, digest: {pin(raw)}}}]\n"
        f"  output: {{artifact: counts, digest: {pin(counts)}}}\n"
        "- id: sum\n"
        "  command: [python3, totals.py]\n"
        f"  inputs: [{{artifact: counts, digest: {pin(counts)}}}]\n"
        f"  output: {{artifact: totals, digest: {pin(totals)}}}\n"
    )
    return tmp_path


def rerun(root, record_id, output, state=Regeneration.REPRODUCED):
    manifest = load(root / "repro.yaml")
    made = next(r for r in manifest.regenerations if r.id == record_id)
    written = Digest.of_file(root / output).value
    append(
        ReproductionReport(
            started_at="2026-10-01T09:00:00+00:00",
            ended_at="2026-10-01T09:00:05+00:00",
            tool_version="0.5.5",
            regenerations=(
                RegenerationState(
                    regeneration_id=made.id,
                    artifact_id=made.output.artifact,
                    state=state,
                    reason=RegenerationReason.OUTPUT_MATCHES
                    if state is Regeneration.REPRODUCED
                    else RegenerationReason.COMMAND_FAILED,
                    expected=written,
                    actual=written,
                    executed=True,
                    command=made.command,
                    exit_code=0 if state is Regeneration.REPRODUCED else 2,
                    duration_seconds=1.5,
                    inputs=tuple(
                        InputReading(
                            artifact_id=wanted.artifact,
                            pinned=wanted.digest.value,
                            observed=manifest.artifact(wanted.artifact)
                            and Digest.of_file(
                                root / manifest.artifact(wanted.artifact).path
                            ).value,
                        )
                        for wanted in made.inputs
                    ),
                ),
            ),
        ),
        root,
    )


@pytest.fixture
def records(project):
    rerun(project, "sum", "totals.json")
    return check_records(load(project / "repro.yaml"), WHEN)


# ------------------------------------------------------------------------- nothing is lost


@pytest.mark.parametrize("path", CASES, ids=lambda p: p.name)
def test_a_fixture_s_records_survive_the_crate(path):
    found = check_records(load(path / "repro.yaml"), WHEN)
    if not found:
        with pytest.raises(NothingToExportError):
            to_ro_crate(found)
        return
    assert from_ro_crate(to_ro_crate(found)) == found


def test_records_with_commands_reruns_and_absent_files_survive_the_crate(records):
    assert {r.native_outcome for r in records} == {"verified", "mismatch", "unchecked"}
    assert any(r.execution and len(r.execution.commands) == 2 for r in records)
    assert from_ro_crate(to_ro_crate(records)) == records


def test_a_failed_rerun_and_a_never_rerun_command_survive_the_crate(project):
    rerun(project, "shape", "counts.json", Regeneration.FAILED)
    found = check_records(load(project / "repro.yaml"), WHEN)
    assert from_ro_crate(to_ro_crate(found)) == found
    graph = by_id(graph_of(found))
    assert graph["#rerun/shape"]["actionStatus"] == {"@id": "http://schema.org/FailedActionStatus"}
    assert graph["#rerun/shape"]["error"] == "command_failed"
    assert "lastRerun" not in graph["#command/sum"] and "#rerun/sum" not in graph


def test_an_error_survives_the_crate():
    found = records_of("value_match", backends=(Broken(),))
    assert found[0].outcome is NormalizedOutcome.ERROR
    assert from_ro_crate(to_ro_crate(found)) == found


def test_a_history_survives_the_crate_where_a_record_has_one(records):
    held = tuple(
        r.model_copy(update={"history": History(states=3, last_changed_at="2026-09-30T08:00:00Z")})
        for r in records
    )
    assert from_ro_crate(to_ro_crate(held)) == held


def test_the_crate_is_the_same_bytes_for_the_same_records(project):
    rerun(project, "sum", "totals.json")
    manifest = load(project / "repro.yaml")
    first, second = (
        to_ro_crate(check_records(manifest, WHEN)),
        to_ro_crate(check_records(manifest, WHEN)),
    )
    assert first == second
    later = WHEN + datetime.timedelta(days=1)
    assert to_ro_crate(check_records(manifest, later)) != first, "the only time is the records'"
    assert first.replace(WHEN.isoformat(), later.isoformat()) == to_ro_crate(
        check_records(manifest, later)
    )


# ------------------------------------------------------------------------ a document that holds


def test_no_reference_dangles(records):
    graph = graph_of(records)
    known = set(by_id(graph)) | {RO_CRATE}
    for entity in graph:
        for target in references(entity):
            assert target in known, f"{entity['@id']} refers to {target}, which nothing describes"


@pytest.mark.parametrize("path", CASES, ids=lambda p: p.name)
def test_no_reference_dangles_in_any_fixture(path):
    found = check_records(load(path / "repro.yaml"), WHEN)
    if not found:
        return
    graph = graph_of(found)
    known = set(by_id(graph)) | {RO_CRATE}
    assert all(target in known for entity in graph for target in references(entity))


def test_identifiers_are_unique_and_do_not_move(records, project):
    graph = graph_of(records)
    names = [entity["@id"] for entity in graph]
    assert len(names) == len(set(names))
    assert names == [e["@id"] for e in graph_of(check_records(load(project / "repro.yaml"), WHEN))]
    assert {
        "#check/responders/0",
        "#check/responders/0/read/0",
        "#check/responders/2/read/1",
        "#check/invited/2",
        "#claim/responders",
        "#command/sum",
        "#rerun/sum",
        "#artifact/gone",
        "#artifact/nowhere",
        "my%20paper.md",
        "totals.json",
        "repro.yaml",
    } <= set(names)
    assert "ro-crate-metadata.json" == names[0] and "./" == names[1]


def test_every_entity_is_reachable_from_the_root(records):
    graph = by_id(graph_of(records))
    seen, pending = set(), ["./"]
    while pending:
        name = pending.pop()
        if name in seen or name not in graph:
            continue
        seen.add(name)
        pending += list(references(graph[name]))
    assert set(graph) - seen == {METADATA_FILE}


def test_every_file_a_record_names_is_in_the_crate_with_its_digests(records, project):
    graph = by_id(graph_of(records))
    files = {e["identifier"]: e for e in of_type(graph.values(), "File") if "identifier" in e}
    assert set(files) == {"raw", "counts", "totals", "paper", "gone", "nowhere"}
    for artifact, path in (
        ("raw", "raw.csv"),
        ("counts", "counts.json"),
        ("totals", "totals.json"),
    ):
        digest = Digest.of_file(project / path).value
        assert files[artifact]["@id"] == path
        assert (files[artifact]["sha256"], files[artifact]["pinnedDigest"]) == (digest, digest)
        assert files[artifact]["validity"] == "authoritative"
    assert (
        files["paper"]["@id"] == "my%20paper.md"
        and files["paper"]["alternateName"] == "my paper.md"
    )
    assert files["paper"]["encodingFormat"] == "text/markdown"
    # A file that is not there is described and is not a data entity: it has no path in the
    # crate and no digest.
    assert files["gone"]["@id"] == "#artifact/gone" and "sha256" not in files["gone"]
    assert files["gone"]["validity"] == "artifact_absent"
    assert "validity" not in files["nowhere"]
    manifest = graph["repro.yaml"]
    assert manifest["sha256"] == Digest.of_file(project / "repro.yaml").value
    assert {ref["@id"] for ref in graph["./"]["hasPart"]} == {
        e["@id"] for e in of_type(graph.values(), "File")
    }


def test_every_assertion_is_a_check_with_its_outcome(records):
    graph = by_id(graph_of(records))
    checks = of_type(graph.values(), "ClaimCheck")
    assert len(checks) == len(records) == 6
    for record in records:
        check = graph[f"#check/{record.claim.id}/{record.assertion.index}"]
        assert check["@type"] == ["CheckAction", "ClaimCheck"]
        assert check["outcome"] == {"@id": f"{PROFILE}#{record.outcome.value}"}
        assert check["checkType"] == {"@id": f"{PROFILE}#{record.check_type.value}"}
        assert (check["nativeOutcome"], check["nativeReason"]) == (
            record.native_outcome,
            record.native_reason,
        )
        assert graph[check["object"]["@id"]]["@type"] == "Claim"
        assert graph[check["instrument"]["@id"]]["version"] == record.checker.version
        assert check["endTime"] == WHEN.isoformat()
    assert [ref["@id"] for ref in graph["./"]["mentions"]][:6] == [
        f"#check/{r.claim.id}/{r.assertion.index}" for r in records
    ]


def test_a_mismatch_holds_the_stored_value_the_printed_value_and_the_address(records):
    graph = by_id(graph_of(records))
    check = graph["#check/invited/0"]
    read = graph[check["fileRead"]["@id"]]
    assert check["outcome"] == {"@id": f"{PROFILE}#mismatch"}
    assert (read["value"], check["printedValue"]) == ("60", "61")
    assert read["@type"] == ["PropertyValue", "FileRead"]
    assert read["readsFile"] == {"@id": "totals.json"}
    assert read["addressKind"] == "tree"
    assert json.loads(read["canonicalAddress"]) == {
        "contract": 1,
        "kind": "tree",
        "pointer": "/invited",
    }
    assert (check["comparisonMode"], check["tolerance"]) == ("printed_precision", "0")


def test_a_correspondence_reads_two_files_and_prints_no_value(records):
    graph = by_id(graph_of(records))
    check = graph["#check/responders/2"]
    sides = [graph[ref["@id"]] for ref in check["fileRead"]]
    assert [(s["side"], s["readsFile"]["@id"], s["value"]) for s in sides] == [
        ("stated", "my%20paper.md", "35"),
        ("stored", "totals.json", "35"),
    ]
    assert "printedValue" not in check


def test_no_property_is_a_boolean(records):
    def booleans(value):
        if isinstance(value, bool):
            yield value
        elif isinstance(value, dict):
            for inner in value.values():
                yield from booleans(inner)
        elif isinstance(value, list):
            for inner in value:
                yield from booleans(inner)

    assert list(booleans(graph_of(records))) == []


# ------------------------------------------------------------------ what the profiles require


def test_the_descriptor_and_the_root_are_what_ro_crate_1_3_requires(records):
    document = json.loads(to_ro_crate(records))
    assert document["@context"][0] == "https://w3id.org/ro/crate/1.3/context"
    descriptor, root = document["@graph"][:2]
    assert descriptor == {
        "@id": "ro-crate-metadata.json",
        "@type": "CreativeWork",
        "conformsTo": {"@id": "https://w3id.org/ro/crate/1.3"},
        "about": {"@id": "./"},
    }
    assert root["@type"] == "Dataset"
    assert root["name"] and root["description"] and root["license"]
    assert root["datePublished"] == WHEN.isoformat()


def test_every_term_the_profile_adds_is_in_the_context_and_no_other_is_used(records, project):
    rerun(project, "shape", "counts.json", Regeneration.FAILED)
    document = json.loads(to_ro_crate(check_records(load(project / "repro.yaml"), WHEN)))
    added = document["@context"][1]
    assert added == {term: f"{PROFILE}#{term}" for term in TERMS}
    used = set()
    for entity in document["@graph"]:
        used |= {key for key in entity if not key.startswith("@")}
        used |= set(entity["@type"] if isinstance(entity["@type"], list) else [entity["@type"]])
    assert used <= REUSED | set(added), sorted(used - REUSED - set(added))
    assert not set(added) & REUSED, "a profile term must not shadow one RO-Crate defines"


def test_each_profile_conformed_to_has_its_entity(records):
    graph = by_id(graph_of(records))
    conformed = [ref["@id"] for ref in graph["./"]["conformsTo"]]
    assert conformed == [PROFILE, PROCESS_RUN_CRATE]
    for name in conformed:
        assert "Profile" in graph[name]["@type"] and "CreativeWork" in graph[name]["@type"]
    assert graph[PROFILE]["version"] == "0.1-experimental"


def test_process_run_crate_is_declared_only_where_a_rerun_is_recorded(project):
    graph = by_id(graph_of(check_records(load(project / "repro.yaml"), WHEN)))
    assert graph["./"]["conformsTo"] == {"@id": PROFILE}
    assert PROCESS_RUN_CRATE not in graph
    assert not of_type(graph.values(), "CreateAction")
    assert "#command/sum" in graph, "a command with no recorded re-run is still described"


def test_a_recorded_rerun_meets_what_process_run_crate_says_must_hold(records):
    graph = by_id(graph_of(records))
    (action,) = of_type(graph.values(), "CreateAction")
    # MUST: the action has an @id, a @type and an instrument; the tool has an @id and a @type.
    assert action["@id"] == "#rerun/sum"
    tool = graph[action["instrument"]["@id"]]
    assert tool["@id"] == "#command/sum" and tool["@type"]
    # SHOULD and MAY, where the record of re-runs holds the fact.
    assert action["object"] == {"@id": "counts.json"} and action["result"] == {"@id": "totals.json"}
    assert (action["startTime"], action["endTime"]) == (
        "2026-10-01T09:00:00+00:00",
        "2026-10-01T09:00:05+00:00",
    )
    assert action["actionStatus"] == {"@id": "http://schema.org/CompletedActionStatus"}
    assert action["name"] and action["description"] == "python3 totals.py"
    assert {"@id": "#rerun/sum"} in graph["./"]["mentions"]
    assert "agent" not in action, "the tool records no person, so the crate names none"


def test_a_check_points_at_the_commands_upstream_and_does_not_restate_them(records):
    graph = by_id(graph_of(records))
    check = graph["#check/responders/1"]
    assert check["upstream"] == [{"@id": "#command/sum"}, {"@id": "#command/shape"}]
    assert check["freshness"] == "never_rerun"
    assert not {"argv", "declaredInput", "startTime", "rerunState"} & set(check)
    assert json.loads(graph["#command/shape"]["argv"]) == ["python3", "shape.py", "--arm", "a b"]
    assert graph["#command/sum"]["lastRerun"] == {"@id": "#rerun/sum"}


# ----------------------------------------------------------------------- unknown stays unknown


def test_a_match_under_a_word_this_version_does_not_know_leaves_as_not_checked():
    (record,) = records_of("value_match")
    unknown = ExportRecord.model_validate(
        {**json.loads(record.to_json()), "native_outcome": "confirmed"}
    )
    assert unknown.outcome is NormalizedOutcome.MATCH
    graph = by_id(graph_of((unknown,)))
    assert graph["#check/c/0"]["outcome"] == {"@id": f"{PROFILE}#not-checked"}
    assert f"{PROFILE}#match" not in graph
    assert graph["#check/c/0"]["nativeOutcome"] == "confirmed", "the word is kept as written"
    (back,) = from_ro_crate(to_ro_crate((unknown,)))
    assert back.outcome is read_outcome(unknown) is NormalizedOutcome.NOT_CHECKED


def test_a_match_at_an_address_kind_this_version_does_not_know_leaves_as_not_checked():
    (record,) = records_of("value_match")
    data = json.loads(record.to_json())
    data["reads"][0]["address"] = {"kind": "xpath", "path": "//td[3]"}
    graph = by_id(graph_of((ExportRecord.model_validate(data),)))
    assert graph["#check/c/0"]["outcome"] == {"@id": f"{PROFILE}#not-checked"}
    read = graph["#check/c/0/read/0"]
    assert json.loads(read["canonicalAddress"]) == {"kind": "xpath", "path": "//td[3]"}


# -------------------------------------------------------------------------------- refusals


def test_records_that_disagree_about_one_thing_are_refused(records):
    other = records[0].model_copy(
        update={"claim": records[0].claim.model_copy(update={"text": "Something else."})}
    )
    with pytest.raises(ConflictingRecordsError, match="#claim/responders"):
        to_ro_crate((*records, other))


def test_a_document_that_is_not_a_claim_check_crate_is_refused():
    with pytest.raises(NotAClaimCheckCrateError):
        from_ro_crate("{}")
    plain = {"@graph": [{"@id": "./", "@type": "Dataset"}]}
    with pytest.raises(NotAClaimCheckCrateError, match="does not conform"):
        from_ro_crate(json.dumps(plain))


# ------------------------------------------------------------------------------- the command


def test_export_writes_the_metadata_file_into_a_directory(project, tmp_path_factory, capsys):
    out = tmp_path_factory.mktemp("crates") / "new"
    assert main(["export", "ro-crate", str(project / "repro.yaml"), "-o", str(out)]) == 0
    assert capsys.readouterr().out == ""
    assert [p.name for p in out.iterdir()] == [METADATA_FILE]
    assert len(from_ro_crate((out / METADATA_FILE).read_text())) == 6


def test_export_writes_a_named_json_file_or_standard_output(project, tmp_path_factory, capsys):
    out = tmp_path_factory.mktemp("crates") / "checks.json"
    assert main(["export", "ro-crate", str(project / "repro.yaml"), "-o", str(out)]) == 0
    assert json.loads(out.read_text())["@graph"][1]["@id"] == "./"
    assert main(["export", "ro-crate", str(project / "repro.yaml")]) == 0
    assert json.loads(capsys.readouterr().out)["@graph"][0]["@id"] == METADATA_FILE


def test_export_of_a_manifest_with_no_assertion_exits_2(capsys):
    manifest = CASES[0].parent / "no_evidence_offered" / "repro.yaml"
    assert main(["export", "ro-crate", str(manifest)]) == 2
    assert "nothing for an RO-Crate to describe" in capsys.readouterr().out


def test_this_repository_s_own_manifest_survives_the_crate():
    found = check_records(load(ROOT / "repro.yaml"), WHEN)
    assert from_ro_crate(to_ro_crate(found)) == found
    files = of_type(graph_of(found), "File")
    assert {f["identifier"] for f in files if "identifier" in f} == {
        a.id for a in load(ROOT / "repro.yaml").artifacts
    }


def test_the_profile_page_defines_every_term_under_its_own_anchor():
    page = (
        ROOT / "site" / "public" / "ro-crate" / "claim-check" / "0.1" / "index.html"
    ).read_text()
    assert PROFILE.endswith("/ro-crate/claim-check/0.1/")
    for term in (*TERMS, *(o.value for o in NormalizedOutcome), *(t.value for t in CheckType)):
        assert f'<section id="{term}">' in page, f"{term} has no definition on the profile page"
    assert "0.1-experimental" in page and "not a standard" in page


# ------------------------------------------------- conversions, places, ties and aggregates


def test_a_converted_value_is_carried_beside_the_stored_one():
    (record,) = records_of("value_mismatch_converted")
    graph = by_id(graph_of((record,)))
    check, read = graph["#check/c/0"], graph["#check/c/0/read/0"]
    assert (read["value"], read["convertedValue"]) == (
        record.reads[0].stored,
        record.reads[0].converted,
    )
    assert read["value"] != read["convertedValue"]
    assert check["conversion"] == record.comparison.conversion


def test_declared_places_are_carried():
    found = records_of("value_places_mismatch")
    graph = by_id(graph_of(found))
    assert [graph[f"#check/c/{r.assertion.index}"]["declaredPlaces"] for r in found] == [
        r.comparison.places for r in found
    ]
    assert {r.comparison.places for r in found} == {1}


def test_an_aggregate_has_one_file_read_per_member_and_the_value_computed():
    (record,) = records_of("aggregate_mismatch")
    graph = by_id(graph_of((record,)))
    check = graph["#check/c/0"]
    assert len(record.reads) > 1
    assert [graph[ref["@id"]]["value"] for ref in check["fileRead"]] == [
        read.stored for read in record.reads
    ]
    assert (check["statistic"], check["computedValue"]) == (
        record.comparison.statistic,
        record.comparison.computed,
    )
    assert check["checkType"] == {"@id": f"{PROFILE}#aggregate-comparison"}
    assert check["memberCount"] == record.comparison.count == len(record.reads)


def test_a_tie_survives_the_crate():
    (record,) = records_of("value_match")
    tied = record.model_copy(
        update={
            "comparison": record.comparison.model_copy(
                update={"tie": Tie(lower="3.2", upper="3.3", printed="3.2")}
            )
        }
    )
    check = by_id(graph_of((tied,)))["#check/c/0"]
    assert (check["tieLower"], check["tieUpper"], check["tiePrinted"]) == ("3.2", "3.3", "3.2")
    assert from_ro_crate(to_ro_crate((tied,))) == (tied,)
