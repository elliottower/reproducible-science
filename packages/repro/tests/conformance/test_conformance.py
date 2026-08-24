"""Every fixture in cases/ produces the outcomes its expected.json records.

These are the executable form of SPEC.md §9. A change that makes one of these differ is a
change to the contract, and has to be argued for rather than absorbed.
"""
from __future__ import annotations

import json
import pathlib

import pytest

from repro import load, verify
from repro.models import Availability, Outcome

CASES = sorted((pathlib.Path(__file__).parent / "cases").iterdir())


def outcomes_of(report) -> list[str]:
    out = []
    for claim in report.claims:
        if claim.availability is Availability.NOT_OFFERED:
            out.append(Outcome.NOT_OFFERED.value)
        out.extend(d.outcome.value for d in claim.decisions)
    return out


@pytest.mark.parametrize("case", CASES, ids=lambda p: p.name)
def test_fixture_produces_its_recorded_outcomes(case):
    expected = json.loads((case / "expected.json").read_text())["outcomes"]
    assert outcomes_of(verify(load(case / "repro.yaml"))) == expected


@pytest.mark.parametrize("case", CASES, ids=lambda p: p.name)
def test_every_decision_names_what_produced_it(case):
    for decision in verify(load(case / "repro.yaml")).decisions:
        assert decision.claim_digest, "a decision must name the claim revision it evaluated"
        assert decision.backend and decision.backend_version, (
            "a decision that does not say which backend produced it cannot be compared "
            "with a later one")


def test_an_absent_pointer_is_not_a_mismatch():
    # Silence is not contradiction: a file with no such key asserts nothing about the value.
    report = verify(load(CASES[[c.name for c in CASES].index("pointer_absent")] / "repro.yaml"))
    decision = report.decisions[0]
    assert decision.extraction.value == "absent"
    assert decision.comparison.value == "not_applicable"
    assert decision.outcome is Outcome.NOT_FOUND


def test_a_backend_defect_is_an_error_and_never_an_abstention():
    from repro.verify import MetricBackend
    from repro.models import Outcome as O

    class Broken(MetricBackend):
        def check(self, claim, evidence, path):
            raise TypeError("a defect, not a scientific finding")

    case = CASES[[c.name for c in CASES].index("value_match")]
    report = verify(load(case / "repro.yaml"), backends=(Broken(),))
    decision = report.decisions[0]
    assert decision.execution.value == "failed"
    assert decision.outcome is O.ERROR, "a TypeError must not read as unchecked"
