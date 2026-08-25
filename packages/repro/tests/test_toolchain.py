"""The extractor is identified, and what it produced is hashed.

An artifact digest establishes that the bytes did not change. It establishes nothing about
whether the extractor read them the same way, and `pdftotext` resolving a ligature differently
after an upgrade changes an extracted passage with every pin in the manifest intact. Two
fields close that: the toolchain's own version, which says why a reading changed, and a digest
over what the toolchain produced, which says that one did.
"""

from __future__ import annotations

import json
import subprocess

import pytest
from repro.models import (
    ArtifactRef,
    Claim,
    ComparisonStatus,
    Decision,
    Digest,
    ExecutionStatus,
    ExtractionStatus,
    Manifest,
    MetricEvidence,
    Outcome,
    QuoteEvidence,
    Reason,
    TableCellEvidence,
)
from repro.policy import PUBLICATION, STRICT
from repro.renderers import to_sarif
from repro.toolchain import UNKNOWN, binary_version, distribution_version
from repro.verify import MetricBackend, QuoteBackend, TableBackend, verify

SOURCE = "The measured angle matches the Haar expectation for this ensemble.\n"
PASSAGE = "matches the Haar expectation for this ensemble"

# A name no executable can have, so `binary_version` reaches its unobtainable branch without
# a monkeypatch standing in for the condition under test.
ABSENT_BINARY = "repro-no-such-extractor-on-any-path"


@pytest.fixture(autouse=True)
def _forget_interrogated_versions():
    # Each answer is cached for the life of the process, which is what a run wants and what
    # one test must not inherit from another.
    binary_version.cache_clear()
    distribution_version.cache_clear()
    yield
    binary_version.cache_clear()
    distribution_version.cache_clear()


def quote_manifest(tmp_path, text: str = SOURCE, assertions: int = 1) -> Manifest:
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "source.txt"
    path.write_text(text)
    return Manifest(
        project="p",
        artifacts=(ArtifactRef(id="src", path=path, digest=Digest.of_file(path)),),
        claims=(
            Claim(
                id="c",
                text="t",
                evidence=tuple(
                    QuoteEvidence(artifact="src", text=PASSAGE) for _ in range(assertions)
                ),
            ),
        ),
    )


def metric_manifest(tmp_path, payload: dict, reported: str, pointer: str = "/delta") -> Manifest:
    path = tmp_path / "results.json"
    path.write_text(json.dumps(payload))
    return Manifest(
        project="p",
        artifacts=(ArtifactRef(id="res", path=path, digest=Digest.of_file(path)),),
        claims=(
            Claim(
                id="c",
                text="t",
                evidence=(
                    MetricEvidence(artifact="res", name="m", reported=reported, pointer=pointer),
                ),
            ),
        ),
    )


def table_manifest(tmp_path, stored: str, reported: str) -> Manifest:
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "table.csv"
    path.write_text(f"model,accuracy\nLASSO-Cox,{stored}\n")
    return Manifest(
        project="p",
        artifacts=(ArtifactRef(id="tab", path=path, digest=Digest.of_file(path)),),
        claims=(
            Claim(
                id="c",
                text="t",
                evidence=(
                    TableCellEvidence(
                        artifact="tab",
                        name="acc",
                        reported=reported,
                        column="accuracy",
                        where={"model": "LASSO-Cox"},
                    ),
                ),
            ),
        ),
    )


# -- the toolchain is named, and named separately from the protocol -------------------------


def test_a_quote_decision_names_the_program_that_read_the_artifact(tmp_path):
    decision = verify(quote_manifest(tmp_path)).decisions[0]
    assert decision.tool == "pdftotext"
    assert decision.tool_version


def test_a_value_decision_names_the_distribution_that_read_the_artifact(tmp_path):
    decision = verify(metric_manifest(tmp_path, {"delta": 3.2}, "3.2")).decisions[0]
    assert decision.tool == "reproducible-science"
    assert decision.tool_version


class StubbedExtractor(MetricBackend):
    tool = "stub-extractor"

    @property
    def tool_version(self) -> str:
        return "77.7"


def test_the_protocol_version_and_the_tool_version_are_separate_fields(tmp_path):
    manifest = metric_manifest(tmp_path, {"delta": 3.2}, "3.2")
    decision = verify(manifest, backends=(StubbedExtractor(),)).decisions[0]
    # One field cannot hold both answers, so a report that conflated them would lose one of
    # these. `version` identifies the interface the backend implements; `tool_version`
    # identifies the program that turned bytes into a number.
    assert decision.backend_version == MetricBackend.version
    assert decision.tool == "stub-extractor"
    assert decision.tool_version == "77.7"


def test_every_decision_in_a_report_carries_both_versions(tmp_path):
    manifest = metric_manifest(tmp_path, {"delta": 3.2, "other": 1}, "3.2")
    for decision in verify(manifest).decisions:
        assert decision.backend_version
        assert decision.tool_version


# -- a tool that cannot answer is recorded as unknown ---------------------------------------


def test_the_version_of_a_binary_that_is_not_installed_is_unknown():
    assert binary_version(ABSENT_BINARY) == UNKNOWN


def test_the_version_of_a_distribution_that_is_not_installed_is_unknown():
    assert distribution_version("repro-no-such-distribution") == UNKNOWN


class UninterrogableExtractor(QuoteBackend):
    tool = ABSENT_BINARY


def test_an_unobtainable_version_is_recorded_rather_than_omitted(tmp_path):
    decision = verify(quote_manifest(tmp_path), backends=(UninterrogableExtractor(),)).decisions[0]
    assert decision.tool_version == UNKNOWN
    assert decision.tool_version != "", (
        "a field that disappears when a tool declines to answer makes an uninterrogated "
        "toolchain indistinguishable from an absent one"
    )


def test_a_tool_that_cannot_be_interrogated_changes_no_outcome(tmp_path):
    manifest = quote_manifest(tmp_path)
    named = verify(manifest).decisions[0]
    unnamed = verify(manifest, backends=(UninterrogableExtractor(),)).decisions[0]
    assert named.outcome is Outcome.VERIFIED
    assert unnamed.outcome is named.outcome
    assert (unnamed.execution, unnamed.extraction, unnamed.comparison, unnamed.reason) == (
        named.execution,
        named.extraction,
        named.comparison,
        named.reason,
    )


def test_a_decision_no_backend_produced_carries_no_version_at_all():
    # Empty is the third state, and it is what distinguishes a version that was never sought
    # from one that was sought and not obtained.
    bare = Decision(
        claim_id="c",
        claim_digest="0" * 64,
        kind="metric",
        execution=ExecutionStatus.UNAVAILABLE,
        extraction=ExtractionStatus.NOT_ATTEMPTED,
        comparison=ComparisonStatus.NOT_APPLICABLE,
        reason=Reason.EXTRACTOR_MISSING,
    )
    assert bare.tool_version == ""
    assert bare.tool_version != UNKNOWN


# -- interrogating the binary costs one subprocess per run ----------------------------------


def test_the_binary_is_interrogated_once_however_many_assertions(tmp_path, monkeypatch):
    calls: list[list[str]] = []

    def counted(cmd, **_):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="pdftotext version 9.9.9\n")

    monkeypatch.setattr("repro.toolchain.subprocess.run", counted)
    report = verify(quote_manifest(tmp_path, assertions=6))

    assert len(report.decisions) == 6
    assert calls == [["pdftotext", "-v"]], (
        "a subprocess per assertion would run pdftotext once per quotation in a manuscript"
    )
    assert {d.tool_version for d in report.decisions} == {"pdftotext version 9.9.9"}


def test_the_version_is_the_line_the_tool_prints_on_whichever_stream(monkeypatch):
    # `pdftotext -v` writes to stderr and exits zero; other extractors write to stdout. A
    # helper that read one stream would record `unknown` for a tool that answered.
    def on_stderr(cmd, **_):
        return subprocess.CompletedProcess(cmd, 99, stdout="", stderr="poppler 24.02.0\nmore\n")

    monkeypatch.setattr("repro.toolchain.subprocess.run", on_stderr)
    assert binary_version("anything") == "poppler 24.02.0"


def test_a_tool_that_prints_nothing_is_unknown(monkeypatch):
    monkeypatch.setattr(
        "repro.toolchain.subprocess.run",
        lambda cmd, **_: subprocess.CompletedProcess(cmd, 0, stdout=" \n", stderr=""),
    )
    assert binary_version("silent") == UNKNOWN


def test_a_tool_that_hangs_is_unknown_rather_than_a_stalled_run(monkeypatch):
    def timed_out(cmd, **_):
        raise subprocess.TimeoutExpired(cmd, 10)

    monkeypatch.setattr("repro.toolchain.subprocess.run", timed_out)
    assert binary_version("slow") == UNKNOWN


# -- the digest of what the extractor produced ----------------------------------------------


def test_a_quote_decision_hashes_the_text_the_extractor_produced(tmp_path):
    decision = verify(quote_manifest(tmp_path)).decisions[0]
    assert decision.extraction_digest == Digest.of_text(SOURCE).value


def test_the_quote_digest_moves_when_the_document_changes_outside_the_passage(tmp_path):
    # Both sources contain the passage verbatim and differ everywhere else. A digest over the
    # matched region alone would be identical for the two, and would say nothing about an
    # extractor that changed how it reads the rest of the document.
    first = verify(quote_manifest(tmp_path / "a", SOURCE + "Table 3 reports the residuals.\n"))
    second = verify(quote_manifest(tmp_path / "b", SOURCE + "Table 3 reports the deviances.\n"))
    assert first.decisions[0].outcome is second.decisions[0].outcome is Outcome.VERIFIED
    assert first.decisions[0].extraction_digest != second.decisions[0].extraction_digest


def test_a_value_decision_hashes_the_value_the_adapter_extracted(tmp_path):
    decision = verify(metric_manifest(tmp_path, {"delta": 3.2}, "3.2")).decisions[0]
    assert decision.extraction_digest == Digest.of_text("3.2").value


def test_representation_drift_the_comparison_tolerates_still_moves_the_digest(tmp_path):
    # Both cells agree with a manuscript printing 0.648, so the comparison cannot tell them
    # apart. What the extractor read is different, and the digest says so. This is the drift a
    # version string misses entirely when the version has not changed.
    verbose = verify(table_manifest(tmp_path / "a", "0.6478999999999999", "0.648"))
    rounded = verify(table_manifest(tmp_path / "b", "0.6479", "0.648"))
    assert verbose.decisions[0].outcome is rounded.decisions[0].outcome is Outcome.VERIFIED
    assert verbose.decisions[0].extraction_digest != rounded.decisions[0].extraction_digest


def test_an_extraction_that_produced_nothing_records_unknown(tmp_path):
    decision = verify(metric_manifest(tmp_path, {"delta": 3.2}, "1", "/no/such/key")).decisions[0]
    assert decision.outcome is Outcome.NOT_FOUND
    assert decision.extraction_digest == UNKNOWN


def test_a_value_that_is_not_a_number_still_records_what_was_read(tmp_path):
    # The comparison could make nothing of it and the extractor still produced something, so
    # there is an extraction to hash. Recording `unknown` here would lose the one fact the
    # decision has about the extractor.
    decision = verify(metric_manifest(tmp_path, {"delta": "primary"}, "1")).decisions[0]
    assert decision.outcome is Outcome.NOT_FOUND
    assert decision.extraction_digest == Digest.of_text("primary").value


def test_a_check_that_never_ran_records_unknown(tmp_path):
    manifest = Manifest(
        project="p",
        artifacts=(ArtifactRef(id="res", path=tmp_path / "never_written.json"),),
        claims=(
            Claim(
                id="c",
                text="t",
                evidence=(MetricEvidence(artifact="res", name="m", reported="1", pointer="/x"),),
            ),
        ),
    )
    decision = verify(manifest).decisions[0]
    assert decision.outcome is Outcome.UNCHECKED
    assert decision.extraction_digest == UNKNOWN


def test_recording_the_extraction_digest_changes_no_verdict(tmp_path):
    # Whether a changed extraction should invalidate a stored decision is a policy question
    # and is deliberately not one this engine answers. The field is provenance.
    report = verify(quote_manifest(tmp_path))
    assert report.decisions[0].extraction_digest
    assert PUBLICATION.assess(report).passed
    assert STRICT.assess(report).passed


# -- the renderer does not hide what the engine recorded ------------------------------------


def test_the_sarif_renderer_reports_the_extractor_beside_the_backend(tmp_path):
    report = verify(quote_manifest(tmp_path))
    sarif = to_sarif(report, PUBLICATION.assess(report), version="0")
    properties = sarif["runs"][0]["results"][0]["properties"]
    assert properties["backend"] == "quote/1"
    assert properties["extractor"].startswith("pdftotext/")
    assert properties["extractionDigest"] == report.decisions[0].extraction_digest


def test_the_table_backend_reports_the_same_toolchain_as_the_value_backend():
    # `metric` and `table` are spellings of one implementation, so a manifest never buys a
    # different extractor by choosing a different word for the same address.
    assert TableBackend.tool == MetricBackend.tool
    assert TableBackend().tool_version == MetricBackend().tool_version
