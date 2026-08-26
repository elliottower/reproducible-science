"""Every fixture in cases/ produces the outcomes its expected.json records.

These are the executable form of SPEC.md §9. A change that makes one of these differ is a
change to the contract, and has to be argued for rather than absorbed.
"""

from __future__ import annotations

import json
import pathlib

import pytest
from repro import load, verify
from repro.models import Availability, Outcome, Validity

CASES = sorted((pathlib.Path(__file__).parent / "cases").iterdir())


def outcomes_of(report) -> list[str]:
    out = []
    for claim in report.claims:
        if claim.availability is Availability.NOT_OFFERED:
            out.append(Outcome.NOT_OFFERED.value)
        out.extend(d.outcome.value for d in claim.decisions)
    return out


def reasons_of(report) -> list[str | None]:
    out: list[str | None] = []
    for claim in report.claims:
        if claim.availability is Availability.NOT_OFFERED:
            out.append(None)
        out.extend(d.reason.value if d.reason else None for d in claim.decisions)
    return out


@pytest.mark.parametrize("case", CASES, ids=lambda p: p.name)
def test_fixture_produces_its_recorded_outcomes(case):
    expected = json.loads((case / "expected.json").read_text())["outcomes"]
    assert outcomes_of(verify(load(case / "repro.yaml"))) == expected


@pytest.mark.parametrize("case", CASES, ids=lambda p: p.name)
def test_fixture_produces_its_recorded_reasons(case):
    """The outcome alone cannot tell a defect in the tool from a fact about the manuscript.

    Three cases share the outcome `unchecked` and eight share `not_found`; only the reason
    separates "the manifest never declared this artifact" from "the file is not there", an
    absent column from an ambiguous row, or an ambiguous pair of prose anchors from a number
    written as a word. Asserting outcomes and never reasons let those swap.
    """
    expected = json.loads((case / "expected.json").read_text())["reasons"]
    assert reasons_of(verify(load(case / "repro.yaml"))) == expected


@pytest.mark.parametrize("case", CASES, ids=lambda p: p.name)
def test_every_decision_names_what_produced_it(case):
    for decision in verify(load(case / "repro.yaml")).decisions:
        assert decision.claim_digest, "a decision must name the claim revision it evaluated"
        assert decision.backend and decision.backend_version, (
            "a decision that does not say which backend produced it cannot be compared "
            "with a later one"
        )
        assert decision.tool and decision.tool_version, (
            "the backend's protocol version identifies an interface; the program that read "
            "the artifact is a separate fact, and an upgraded extractor moves it while the "
            "protocol version stays where it was"
        )
        assert decision.extraction_digest, (
            "a version string catches drift that announces itself, and a digest over what "
            "the extractor produced catches the rest; a field that disappears records neither"
        )


def test_an_absent_pointer_is_not_a_mismatch():
    # Silence is not contradiction: a file with no such key asserts nothing about the value.
    report = verify(load(CASES[[c.name for c in CASES].index("pointer_absent")] / "repro.yaml"))
    decision = report.decisions[0]
    assert decision.extraction.value == "absent"
    assert decision.comparison.value == "not_applicable"
    assert decision.outcome is Outcome.NOT_FOUND


def test_a_backend_defect_is_an_error_and_never_an_abstention():
    from repro.models import Outcome as O
    from repro.verify import MetricBackend

    class Broken(MetricBackend):
        def check(self, claim, evidence, paths):
            raise TypeError("a defect, not a scientific finding")

    case = CASES[[c.name for c in CASES].index("value_match")]
    report = verify(load(case / "repro.yaml"), backends=(Broken(),))
    decision = report.decisions[0]
    assert decision.execution.value == "failed"
    assert decision.outcome is O.ERROR, "a TypeError must not read as unchecked"


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.name)
def test_a_fixture_artifact_is_the_one_its_manifest_pinned(case):
    """Every fixture's pins hold, except where breaking one is the point of the case.

    Without this the suite checks outcomes and never validity, so a formatting tool that
    rewrites a fixture -- appending a trailing newline is enough -- breaks every pin in the
    corpus while all the outcome assertions keep passing. That is not hypothetical: it
    happened the first time the pre-commit hooks ran here.

    Skipping the three cases that break a pin on purpose left the contract they exist to
    state untested: `unpinned_artifact` recorded only that its quote resolved, so a build
    reporting an unpinned file as authoritative passed. Each case now asserts its own
    validity, and the fixtures that are meant to be intact assert AUTHORITATIVE.
    """
    expected = json.loads((case / "expected.json").read_text())["artifacts"]
    report = verify(load(case / "repro.yaml"))
    found = {state.artifact_id: state.validity.value for state in report.artifacts}
    assert found == expected, (
        f"{case.name}: {found} != {expected} — either the fixture's bytes have changed or "
        f"the validity ladder has"
    )
    for state in report.artifacts:
        if expected[state.artifact_id] == Validity.BROKEN_PIN.value:
            assert state.expected and state.actual and state.expected != state.actual, (
                "a broken pin has to report both digests, or there is nothing to diagnose"
            )
