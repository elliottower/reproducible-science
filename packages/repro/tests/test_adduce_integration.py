from __future__ import annotations

import dataclasses
import hashlib
import json

import pytest
import yaml

pytest.importorskip("adduce", reason="install the adduce extra to exercise the rule")

from adduce.evidence import collect
from adduce.model import scan_repository
from adduce.rules import Status
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

    for name in ("Rule", "Status", "Category", "Location", "Finding"):
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
    under `.adduce/`, because a Finding cannot carry per-assertion outcomes."""
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
