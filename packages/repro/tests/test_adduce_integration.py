from __future__ import annotations

import dataclasses
import datetime
import hashlib
import importlib
import json

import claims
import pytest
import yaml

pytest.importorskip("adduce", reason="install the adduce extra to exercise the rule")

from adduce.evidence import collect
from adduce.model import scan_repository
from adduce.rules import Status
from claims.exceptions import ReproError
from claims.record import check_records
from repro.integrations import adduce as adapter
from repro.integrations.adduce import ReproEvidenceRule, candidates
from repro.models import VerificationReport

RULE = ReproEvidenceRule()


def results_json(results: dict) -> str:
    return json.dumps(results, indent=2) + "\n"


def metric_manifest(project: str, results: dict, reported: dict) -> str:
    """One JSON artifact and one metric assertion per key of `reported`."""
    body = results_json(results)
    return yaml.safe_dump(
        {
            "schema_version": "repro/1",
            "project": project,
            "artifacts": [
                {
                    "id": "res",
                    "path": "results.json",
                    "digest": {
                        "algorithm": "sha256",
                        "value": hashlib.sha256(body.encode()).hexdigest(),
                    },
                }
            ],
            "claims": [
                {
                    "id": f"c{i}",
                    "text": f"claim {i}",
                    "evidence": [
                        {
                            "kind": "metric",
                            "artifact": "res",
                            "name": name,
                            "reported": value,
                            "pointer": f"/{name}",
                        }
                    ],
                }
                for i, (name, value) in enumerate(reported.items())
            ],
        },
        sort_keys=False,
    )


GOOD = metric_manifest("p", {"a": 1.0}, {"a": "1.0"})
DATA = results_json({"a": 1.0})


@pytest.fixture
def build(tmp_path):
    """Materialize a repository from a path -> content mapping and scan it as adduce does."""

    def _build(files: dict[str, str]):
        for relative, content in files.items():
            target = tmp_path / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        repo = scan_repository(tmp_path)
        return repo, collect(repo)

    return _build


def two_assertions(reported: dict, data: dict | None = None) -> dict[str, str]:
    """A root manifest asserting `reported`, beside results holding `data`."""
    values = {"a": 1.0, "b": 2.0} if data is None else data
    return {
        "repro.yaml": metric_manifest("p", {"a": 1.0, "b": 2.0}, reported),
        "results.json": results_json(values),
    }


# -- which manifest describes the project ---------------------------------------------------


def test_root_manifest_is_authoritative_over_a_nested_one(build):
    repo, _ = build(
        {
            "repro.yaml": GOOD,
            "results.json": DATA,
            "paper/repro.yaml": GOOD,
            "analysis/repro.yaml": GOOD,
        }
    )
    assert candidates(repo) == ["repro.yaml"]


def test_the_one_project_manifest_is_found_wherever_it_sits(build):
    repo, _ = build({"paper/repro.yaml": GOOD, "paper/results.json": DATA})
    assert candidates(repo) == ["paper/repro.yaml"]


def test_manifests_under_a_fixture_directory_do_not_describe_the_project(build):
    repo, _ = build(
        {
            "tests/conformance/value_match/repro.yaml": GOOD,
            "tests/conformance/value_match/results.json": DATA,
            "examples/demo/repro.yaml": GOOD,
        }
    )
    assert candidates(repo) == []
    assert RULE.applies_to(repo) is False


def test_a_project_manifest_beside_fixtures_is_still_found(build):
    repo, _ = build(
        {
            "paper/repro.yaml": GOOD,
            "paper/results.json": DATA,
            "tests/conformance/a/repro.yaml": GOOD,
        }
    )
    assert candidates(repo) == ["paper/repro.yaml"]


def test_several_project_manifests_are_reported_rather_than_chosen(build):
    repo, ev = build(
        {
            "paper/repro.yaml": GOOD,
            "paper/results.json": DATA,
            "analysis/repro.yaml": GOOD,
            "analysis/results.json": DATA,
        }
    )
    assert candidates(repo) == ["analysis/repro.yaml", "paper/repro.yaml"]
    finding = RULE.evaluate(ev)
    assert finding.status is Status.UNKNOWN
    assert "analysis/repro.yaml" in finding.message
    assert "paper/repro.yaml" in finding.message


def test_a_file_merely_ending_in_the_manifest_name_is_not_one(build):
    repo, _ = build({"other-repro.yaml": GOOD, "docs/my_repro.yaml": GOOD, "repro.yaml.bak": GOOD})
    assert candidates(repo) == []


def test_a_repository_declaring_nothing_is_out_of_scope_not_failing(build):
    repo, _ = build({"README.md": "# p\n"})
    assert RULE.applies_to(repo) is False


# -- what the rule reports ------------------------------------------------------------------


def test_every_assertion_holding_is_a_pass(build):
    finding = RULE.evaluate(build(two_assertions({"a": "1.0", "b": "2.0"}))[1])
    assert finding.status is Status.PASS
    assert finding.confidence == 1.0
    assert "All 2" in finding.message


def test_one_wrong_value_is_partial_and_the_counts_are_reported(build):
    finding = RULE.evaluate(build(two_assertions({"a": "1.0", "b": "9.9"}))[1])
    assert finding.status is Status.PARTIAL
    assert "1 of 2" in finding.message
    assert "1 mismatch" in finding.message


def test_no_assertion_holding_is_a_failure(build):
    finding = RULE.evaluate(build(two_assertions({"a": "8.8", "b": "9.9"}))[1])
    assert finding.status is Status.FAIL
    assert "No declared evidence assertion verifies" in finding.message


def test_a_missing_value_is_not_a_wrong_one(build):
    finding = RULE.evaluate(build(two_assertions({"a": "1.0", "absent": "1.0"}))[1])
    assert finding.status is Status.PARTIAL
    assert "1 not_found" in finding.message
    assert "mismatch" not in finding.message


def test_an_artifact_changed_since_it_was_pinned_is_a_failure_naming_it(build):
    files = two_assertions({"a": "1.0", "b": "2.0"}, data={"a": 1.0, "b": 2.0, "c": 3.0})
    finding = RULE.evaluate(build(files)[1])
    assert finding.status is Status.FAIL
    assert "changed since being declared" in finding.message
    assert "res" in finding.message


def test_a_manifest_declaring_no_assertions_is_out_of_scope(build):
    finding = RULE.evaluate(build({"repro.yaml": metric_manifest("p", {}, {})})[1])
    assert finding.status is Status.NOT_APPLICABLE


def test_an_unreadable_manifest_does_not_blame_the_repository(build):
    finding = RULE.evaluate(build({"repro.yaml": "schema_version: repro/1\nartifacts: [\n"})[1])
    assert finding.status is Status.UNKNOWN


def test_the_sidecar_holds_an_outcome_for_every_assertion(build, tmp_path):
    RULE.evaluate(build(two_assertions({"a": "1.0", "b": "9.9"}))[1])
    report = VerificationReport.model_validate_json(
        (tmp_path / ".adduce" / "repro-report.json").read_text()
    )
    assert sum(len(c.decisions) for c in report.claims) == 2
    assert {d.outcome.value for c in report.claims for d in c.decisions} == {"verified", "mismatch"}


def test_the_finding_points_at_the_manifest_and_the_full_report(build):
    finding = RULE.evaluate(build(two_assertions({"a": "1.0", "b": "9.9"}))[1])
    assert {loc.path for loc in finding.locations} == {"repro.yaml", ".adduce/repro-report.json"}


# -- one item per checked assertion ---------------------------------------------------------


def test_each_assertion_is_an_item_with_the_values_it_compared(build):
    finding = RULE.evaluate(build(two_assertions({"a": "1.0", "b": "9.9"}))[1])
    items = {item.id: item for item in finding.items}
    assert set(items) == {"c0/metric/a/0", "c1/metric/b/0"}
    held, differed = items["c0/metric/a/0"], items["c1/metric/b/0"]
    assert (held.status, differed.status) == (Status.PASS, Status.FAIL)
    assert held.kind == differed.kind == "value-comparison"
    assert dict(differed.attributes) == {
        "outcome": "mismatch",
        "native_outcome": "mismatch",
        "printed": "9.9",
        "mode": "printed_precision",
        "places": None,
        "computed": None,
        "stored": "2.0",
        "converted": None,
        "validity": "authoritative",
    }
    assert held.attributes["stored"] == "1.0"
    assert all(item.confidence == 1.0 for item in finding.items)


def test_the_items_do_not_change_what_the_finding_weighs(build):
    finding = RULE.evaluate(build(two_assertions({"a": "1.0", "b": "9.9"}))[1])
    assert finding.status is Status.PARTIAL
    assert finding.weight == RULE.weight
    assert finding.to_dict()["items"] == [item.to_dict() for item in finding.items]


def test_an_address_holding_no_value_fails_and_reads_nothing(build):
    finding = RULE.evaluate(build(two_assertions({"a": "1.0", "absent": "1.0"}))[1])
    absent = next(item for item in finding.items if item.id == "c1/metric/absent/0")
    assert absent.status is Status.FAIL
    assert absent.attributes["outcome"] == "not-found"
    assert absent.attributes["stored"] is None


def test_an_assertion_on_a_file_that_is_not_there_is_unknown_not_failed(build):
    files = two_assertions({"a": "1.0", "b": "2.0"})
    del files["results.json"]
    finding = RULE.evaluate(build(files)[1])
    assert finding.status is Status.FAIL
    assert {item.status for item in finding.items} == {Status.UNKNOWN}
    assert {item.attributes["validity"] for item in finding.items} == {"artifact_absent"}


def test_an_item_locates_its_manifest_line_and_the_file_it_read_from_the_root(build):
    manifest = metric_manifest("p", {"a": 1.0}, {"a": "7.0"})
    finding = RULE.evaluate(build({"paper/repro.yaml": manifest, "paper/results.json": DATA})[1])
    (item,) = finding.items
    lines = manifest.splitlines()
    declared = next(n for n, line in enumerate(lines, 1) if "- kind: metric" in line)
    assert [(loc.path, loc.line) for loc in item.locations] == [
        ("paper/repro.yaml", declared),
        ("paper/results.json", None),
    ]
    assert item.remediation == "repro why c0 paper/repro.yaml"


def test_an_item_that_held_names_no_remedy(build):
    finding = RULE.evaluate(build(two_assertions({"a": "1.0", "b": "2.0"}))[1])
    assert {item.remediation for item in finding.items} == {""}


def test_a_quotation_is_an_item_of_its_own_check_type(build):
    document = yaml.safe_load(GOOD)
    document["artifacts"].append({"id": "paper", "path": "paper.txt"})
    document["claims"][0]["evidence"].append(
        {"kind": "quote", "artifact": "paper", "text": "accuracy was high"}
    )
    files = {
        "repro.yaml": yaml.safe_dump(document, sort_keys=False),
        "results.json": DATA,
        "paper.txt": "We found the accuracy was high.\n",
    }
    items = {item.id: item for item in RULE.evaluate(build(files)[1]).items}
    quote = items["c0/quote//0"]
    assert quote.kind == "passage-presence"
    assert quote.status is Status.PASS
    assert quote.attributes["printed"] == "accuracy was high"
    assert "mode" not in quote.attributes


def test_a_slash_in_a_claim_id_or_name_cannot_make_two_items_one(build):
    document = yaml.safe_load(metric_manifest("p", {}, {}))
    document["artifacts"][0]["digest"]["value"] = hashlib.sha256(
        results_json({"x/y": {"z": 1}, "x": {"y/z": 1}}).encode()
    ).hexdigest()
    document["claims"] = [
        {
            "id": "c/metric/x",
            "text": "t",
            "evidence": [
                {"kind": "metric", "artifact": "res", "name": "y", "reported": "1",
                 "pointer": "/x~1y/z"}
            ],
        },
        {
            "id": "c",
            "text": "t",
            "evidence": [
                {"kind": "metric", "artifact": "res", "name": "x/metric/y", "reported": "1",
                 "pointer": "/x/y~1z"}
            ],
        },
    ]  # fmt: skip
    files = {
        "repro.yaml": yaml.safe_dump(document, sort_keys=False),
        "results.json": results_json({"x/y": {"z": 1}, "x": {"y/z": 1}}),
    }
    finding = RULE.evaluate(build(files)[1])
    assert sorted(item.id for item in finding.items) == [
        "c/metric/x~1metric~1y/0",
        "c~1metric~1x/metric/y/0",
    ]
    assert {item.status for item in finding.items} == {Status.PASS}


def test_past_the_envelope_the_finding_says_how_many_items_it_left_out(build, monkeypatch):
    monkeypatch.setattr(adapter, "MAX_ITEMS", 2)
    files = {
        "repro.yaml": metric_manifest(
            "p", {"a": 1, "b": 2, "c": 3}, {"a": "1", "b": "2", "c": "3"}
        ),
        "results.json": results_json({"a": 1, "b": 2, "c": 3}),
    }
    finding = RULE.evaluate(build(files)[1])
    assert [item.id for item in finding.items] == ["c0/metric/a/0", "c1/metric/b/0"]
    assert finding.status is Status.PASS
    assert "The first 2 assertions are items; 1 more are in .adduce/repro-report.json." in (
        finding.message
    )


def test_the_rule_checks_each_assertion_once(build, monkeypatch):
    verify_module = importlib.import_module("claims.verify")
    record_module = importlib.import_module("claims.record")
    calls = []
    original = verify_module.check_evidence

    def counted(claim, evidence, *rest):
        calls.append((claim.id, evidence.kind))
        return original(claim, evidence, *rest)

    monkeypatch.setattr(verify_module, "check_evidence", counted)
    monkeypatch.setattr(record_module, "check_evidence", counted)
    finding = RULE.evaluate(build(two_assertions({"a": "1.0", "b": "9.9"}))[1])
    assert sorted(calls) == [("c0", "metric"), ("c1", "metric")]
    assert len(finding.items) == 2


def test_records_built_from_the_report_are_the_records_a_fresh_check_gives(build, tmp_path):
    build(two_assertions({"a": "1.0", "absent": "1.0"}))
    manifest = claims.load(tmp_path / "repro.yaml")
    when = datetime.datetime(2026, 10, 14, tzinfo=datetime.UTC)
    fresh = check_records(manifest, checked_at=when)
    reused = check_records(manifest, checked_at=when, verified=claims.verify(manifest))
    assert [r.to_json() for r in reused] == [r.to_json() for r in fresh]


def test_a_report_of_another_manifest_is_refused(build, tmp_path):
    build(two_assertions({"a": "1.0", "b": "2.0"}))
    manifest = claims.load(tmp_path / "repro.yaml")
    (tmp_path / "other.yaml").write_text(metric_manifest("p", {"a": 1.0}, {"a": "1.0"}))
    other = claims.verify(claims.load(tmp_path / "other.yaml"))
    with pytest.raises(ReproError, match="not verify's report of this manifest"):
        check_records(manifest, verified=other)


def test_within_the_envelope_the_finding_says_nothing_of_one(build):
    finding = RULE.evaluate(build(two_assertions({"a": "1.0", "b": "2.0"}))[1])
    assert "more are in" not in finding.message
    assert len(finding.items) == 2


# -- the interop contract -------------------------------------------------------------------
#
# adduce is a separate project on its own release schedule and is not a runtime dependency of
# repro: it is an optional extra. That makes the surface repro relies on a contract with
# someone else's code, and an upgrade that moves it would otherwise disable the rule quietly —
# the entry point still loads, `applies_to` still returns, and nothing is ever reported.


@pytest.mark.integration
def test_the_adduce_surface_this_rule_depends_on_is_present():
    from adduce import evidence as adduce_evidence
    from adduce import model as adduce_model
    from adduce import rules as adduce_rules

    for name in ("Rule", "Status", "Category", "Location", "Finding", "FindingItem"):
        assert hasattr(adduce_rules, name), f"adduce.rules.{name} is gone"
    for name in ("PASS", "FAIL", "PARTIAL", "UNKNOWN", "NOT_APPLICABLE"):
        assert hasattr(Status, name), f"adduce Status.{name} is gone"
    for name in ("exists", "find_names"):
        assert hasattr(adduce_model.Repo, name), f"adduce Repo.{name} is gone"
    # `root` is a dataclass field, so it is on instances rather than on the class.
    fields = {f.name for f in dataclasses.fields(adduce_model.Repo)}
    assert "root" in fields, "adduce Repo.root is gone"
    assert hasattr(adduce_evidence, "collect")
    assert hasattr(adduce_model, "scan_repository")


@pytest.mark.integration
def test_the_rule_is_discoverable_through_the_entry_point():
    """Installed with the extra, adduce finds the rule without repro doing anything."""
    from importlib.metadata import entry_points

    registered = {e.name: e.value for e in entry_points(group="adduce.rules")}
    assert registered.get("repro") == "repro.integrations.adduce", (
        f"the entry point adduce discovers this rule by is not registered: {registered}"
    )


@pytest.mark.integration
def test_the_finding_helper_still_accepts_what_the_rule_passes(build):
    """`Rule.finding` is called with five arguments; a signature change would break at runtime
    rather than at import, and only on the path that produces a failure."""
    finding = RULE.evaluate(build(two_assertions({"a": "1.0", "b": "9.9"}))[1])
    for field in (
        "items",
        "rule_id",
        "category",
        "status",
        "confidence",
        "message",
        "remediation",
        "locations",
        "severity",
        "weight",
    ):
        assert hasattr(finding, field), f"adduce Finding.{field} is gone"


@pytest.mark.integration
def test_the_rule_never_writes_outside_its_sidecar(build, tmp_path):
    """adduce rules run over other people's repositories. This one writes exactly one file,
    under `.adduce/`: the full report, which holds what the items' envelope leaves out."""
    import hashlib

    def snapshot():
        return {
            str(p.relative_to(tmp_path)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(tmp_path.rglob("*"))
            if p.is_file() and ".adduce" not in p.parts
        }

    _, ev = build(two_assertions({"a": "1.0", "b": "2.0"}))
    before = snapshot()
    RULE.evaluate(ev)
    assert snapshot() == before, "the rule modified the repository it was auditing"
    assert (tmp_path / ".adduce" / "repro-report.json").is_file()
