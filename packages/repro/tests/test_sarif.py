"""SARIF output.

SARIF is what GitHub renders inline on a pull request, so a report in this format arrives
where a reviewer already looks. The property worth testing is that the three-stage outcome
survives the translation: SARIF splits `kind` from `level`, so a check that could not run can
stay `notApplicable` instead of becoming a low-severity failure.
"""
from __future__ import annotations

import pathlib

import pytest

from repro import load, to_sarif, verify
from repro.models import Outcome
from repro.policy import EXPLORATORY, STRICT
from repro.exceptions import BackendUnavailableError
from repro.verify import DEFAULT_BACKENDS, MetricBackend, QuoteBackend

CASES = pathlib.Path(__file__).parent / "conformance" / "cases"


def report_for(case, backends=DEFAULT_BACKENDS):
    return verify(load(f"{CASES}/{case}/repro.yaml"), backends=backends)


def results(sarif):
    return sarif["runs"][0]["results"]


def test_a_run_is_well_formed():
    s = to_sarif(report_for("value_match"), version="9.9")
    assert s["version"] == "2.1.0"
    assert s["$schema"].endswith("sarif-2.1.0.json")
    driver = s["runs"][0]["tool"]["driver"]
    assert driver["name"] == "repro" and driver["version"] == "9.9"
    assert driver["rules"], "every ruleId used must be declared"


def test_every_result_references_a_declared_rule():
    s = to_sarif(report_for("value_mismatch"))
    declared = {r["id"] for r in s["runs"][0]["tool"]["driver"]["rules"]}
    for r in results(s):
        assert r["ruleId"] in declared, r["ruleId"]


def test_a_check_that_could_not_run_is_notApplicable_and_not_a_failure():
    # The distinction the whole package exists to preserve. A missing extractor is not a
    # low-severity failure; it is a check that did not happen.
    class NoExtractor(QuoteBackend):
        def check(self, claim, evidence, path):
            raise BackendUnavailableError("quote", "pdftotext is not on PATH")

    s = to_sarif(report_for("passage_present", backends=(NoExtractor(), MetricBackend())))
    unchecked = [r for r in results(s) if r["ruleId"] == f"repro/{Outcome.UNCHECKED.value}"]
    assert unchecked
    for r in unchecked:
        assert r["kind"] == "notApplicable"
        assert r["level"] == "none"


def test_a_mismatch_is_a_failure():
    s = to_sarif(report_for("value_mismatch"))
    r = next(x for x in results(s) if x["ruleId"] == "repro/mismatch")
    assert r["kind"] == "fail" and r["level"] == "error"


def test_artifacts_carry_their_digest():
    s = to_sarif(report_for("value_match"))
    artifacts = s["runs"][0]["artifacts"]
    assert artifacts
    assert all("sha-256" in a.get("hashes", {}) for a in artifacts), (
        "the digests a report was computed against travel with it")


def test_a_result_fingerprints_the_claim_and_the_bytes():
    s = to_sarif(report_for("value_match"))
    fp = results(s)[0]["partialFingerprints"]
    assert len(fp["claimDigest"]) == 64
    assert len(fp["artifactDigest"]) == 64


def test_stages_survive_the_translation():
    s = to_sarif(report_for("pointer_absent"))
    props = results(s)[0]["properties"]
    assert props["execution"] == "completed"
    assert props["extraction"] == "absent"
    assert props["comparison"] == "not_applicable"


def test_a_policy_raises_the_level_without_changing_the_kind():
    report = report_for("pointer_absent")
    lax = to_sarif(report, EXPLORATORY.assess(report))
    strict = to_sarif(report, STRICT.assess(report))
    lax_r, strict_r = results(lax)[0], results(strict)[0]
    assert lax_r["kind"] == strict_r["kind"], "what happened does not depend on the policy"
    assert lax_r["level"] == "warning" and strict_r["level"] == "error"


def test_a_broken_pin_appears_as_its_own_result(tmp_path):
    import shutil, pathlib

    src = pathlib.Path(CASES) / "value_match"
    d = tmp_path / "case"
    shutil.copytree(src, d)
    (d / "results.json").write_text('{"delta": 9.9, "label": "primary", "nested": {"a/b": 7}}')
    s = to_sarif(verify(load(d / "repro.yaml")))
    pins = [r for r in results(s) if r["ruleId"] == "repro/broken_pin"]
    assert len(pins) == 1
    assert pins[0]["level"] == "error"


def test_a_claim_with_no_evidence_is_informational():
    s = to_sarif(report_for("no_evidence_offered"))
    r = results(s)[0]
    assert r["kind"] == "informational" and r["level"] == "note"


def test_every_rule_a_result_names_is_declared_by_the_driver(tmp_path):
    """A ruleId with no matching rule object is what a strict SARIF consumer rejects, and it
    is invisible in a report that otherwise looks well formed."""
    import pathlib

    from repro.models import ArtifactRef, Claim, Digest, Manifest, MetricEvidence
    from repro.verify import verify

    # An absent artifact and a broken pin are the two artifact-level results; a mismatch and
    # a verified assertion cover the outcome-level ones.
    good = tmp_path / "good.json"
    good.write_text('{"x": 3.2, "y": 9.9}')
    moved = tmp_path / "moved.json"
    moved.write_text('{"x": 1.0}')
    manifest = Manifest(
        project="p",
        artifacts=(
            ArtifactRef(id="good", path=good, digest=Digest.of_file(good)),
            ArtifactRef(id="moved", path=moved,
                        digest=Digest(algorithm="sha256", value="0" * 64)),
            ArtifactRef(id="gone", path=pathlib.Path(tmp_path / "gone.json"),
                        digest=Digest(algorithm="sha256", value="1" * 64)),
        ),
        claims=(
            Claim(id="ok", text="t", evidence=(
                MetricEvidence(artifact="good", name="x", reported="3.2", pointer="/x"),)),
            Claim(id="bad", text="t", evidence=(
                MetricEvidence(artifact="good", name="y", reported="1.1", pointer="/y"),)),
            Claim(id="absent", text="t", evidence=(
                MetricEvidence(artifact="gone", name="z", reported="1.0", pointer="/z"),)),
        ))
    run = to_sarif(verify(manifest))["runs"][0]
    declared = {rule["id"] for rule in run["tool"]["driver"]["rules"]}
    used = {result["ruleId"] for result in run["results"]}
    assert used, "the fixture should produce results"
    assert used <= declared, f"undeclared rule ids: {sorted(used - declared)}"
