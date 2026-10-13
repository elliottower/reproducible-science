"""A declared number of decimal places, and a value exactly halfway between two printed ones.

`places` is the author's statement of how many decimal places the manuscript reports a value
to. It must agree with the value as printed, and the stored value must round to it. A tie is
the one case where two correct rounding rules print different numbers, so either is accepted
and the record says that it was a tie.
"""

from __future__ import annotations

import decimal
import json
import random

import pytest
import yaml
from pydantic import ValidationError
from repro.cli import main
from repro.exceptions import ManifestError
from repro.manifest import load
from repro.models import (
    ComparisonMode,
    ComparisonStatus,
    ExtractionStatus,
    MetricEvidence,
    Outcome,
    Reason,
    TableCellEvidence,
    Tie,
    ValueEvidence,
)
from repro.verify import _agree, _tie, verify
from repro.why import why

D = decimal.Decimal


def project(tmp_path, stored, evidence):
    """A manifest with one claim over `results.json`, which holds `stored` at `/x`."""
    # Written as text, so a stored value keeps the digits the test gives it.
    (tmp_path / "results.json").write_text(f'{{"x": {stored}}}')
    (tmp_path / "cells.csv").write_text(f"row,x\na,{stored}\n")
    manifest = {
        "schema_version": "repro/1",
        "project": "t",
        "artifacts": [
            {"id": "results", "path": "results.json"},
            {"id": "cells", "path": "cells.csv"},
        ],
        "claims": [{"id": "c", "text": "The value was as printed.", "evidence": [evidence]}],
    }
    path = tmp_path / "repro.yaml"
    path.write_text(yaml.safe_dump(manifest, sort_keys=False))
    return path


def metric(reported, **kw):
    return {
        "kind": "metric",
        "artifact": "results",
        "name": "x",
        "reported": reported,
        "pointer": "/x",
        **kw,
    }


def cell(reported, **kw):
    return {
        "kind": "table",
        "artifact": "cells",
        "name": "x",
        "reported": reported,
        "column": "x",
        "where": {"row": "a"},
        **kw,
    }


def only(path):
    (decision,) = verify(load(path)).decisions
    return decision


def check(tmp_path, stored, reported, **kw):
    return only(project(tmp_path, stored, metric(reported, **kw)))


# -- a declared number of decimal places -----------------------------------------------------


def test_a_value_printed_to_the_declared_places_and_rounding_to_it_verifies(tmp_path):
    decision = check(tmp_path, "4.2051", "4.2", places=1)
    assert (decision.outcome, decision.reason) == (Outcome.VERIFIED, Reason.VALUE_MATCH)
    assert decision.detail == "/x = 4.2051"


def test_a_value_printed_to_more_places_than_declared_does_not_verify(tmp_path):
    """`4.20` is what 4.2011 rounds to at two places, so the file agrees with the print. What
    disagrees is the declaration of one place, and rounding to it and leaving the last printed
    digit unread would pass a table that prints a precision it was not declared to have."""
    assert check(tmp_path, "4.2011", "4.20").outcome is Outcome.VERIFIED
    assert check(tmp_path, "4.2051", "4.20", places=1).reason is Reason.PLACES_MISMATCH
    decision = check(tmp_path, "4.2011", "4.20", places=1)
    assert (decision.outcome, decision.reason) == (Outcome.MISMATCH, Reason.PLACES_MISMATCH)
    assert (decision.extraction, decision.comparison) == (
        ExtractionStatus.EXTRACTED,
        ComparisonStatus.MISMATCH,
    )
    assert decision.detail == (
        "x: manuscript prints 4.20, which is 2 decimal places, and 1 decimal place is declared"
    )
    assert decision.extracted == "4.2011"


def test_a_value_printed_to_fewer_places_than_declared_does_not_verify(tmp_path):
    assert check(tmp_path, "3.14159", "3.1").outcome is Outcome.VERIFIED
    decision = check(tmp_path, "3.14159", "3.1", places=2)
    assert (decision.outcome, decision.reason) == (Outcome.MISMATCH, Reason.PLACES_MISMATCH)
    assert decision.detail == (
        "x: manuscript prints 3.1, which is 1 decimal place, and 2 decimal places is declared"
    )
    assert check(tmp_path, "3.14159", "3.14", places=2).outcome is Outcome.VERIFIED


def test_the_stored_value_must_still_round_to_the_printed_one(tmp_path):
    decision = check(tmp_path, "4.2651", "4.2", places=1)
    assert (decision.outcome, decision.reason) == (Outcome.MISMATCH, Reason.VALUE_MISMATCH)
    assert check(tmp_path, "4.2651", "4.3", places=1).outcome is Outcome.VERIFIED


@pytest.mark.parametrize(
    ("reported", "places", "outcome"),
    [
        ("42", 0, Outcome.VERIFIED),
        ("42.0", 0, Outcome.MISMATCH),
        ("42", 1, Outcome.MISMATCH),
        ("42.0", 1, Outcome.VERIFIED),
        # Printed to the tens, which is no number of decimal places.
        ("4E+1", 0, Outcome.MISMATCH),
    ],
)
def test_no_places_is_a_whole_number_as_printed(tmp_path, reported, places, outcome):
    assert check(tmp_path, "42.04", reported, places=places).outcome is outcome


def test_places_are_counted_after_a_declared_conversion(tmp_path):
    def converted(reported, places):
        return check(tmp_path, "0.04205", reported, conversion="percent", places=places)

    assert converted("4.2", 1).outcome is Outcome.VERIFIED
    assert converted("4.20", 1).reason is Reason.PLACES_MISMATCH
    # 0.04205 is 4.205, an exact tie at two places.
    assert converted("4.21", 2).outcome is Outcome.VERIFIED
    assert converted("4.205", 3).outcome is Outcome.VERIFIED


def test_a_value_that_is_absent_or_not_a_number_is_reported_before_the_places(tmp_path):
    decision = check(tmp_path, '"n/a"', "4.20", places=1)
    assert (decision.outcome, decision.reason) == (Outcome.NOT_FOUND, Reason.VALUE_NOT_NUMERIC)
    path = project(tmp_path, "4.2", metric("4.20", places=1, pointer="/y"))
    assert only(path).reason is Reason.POINTER_ABSENT


@pytest.mark.parametrize("mode", ["absolute", "relative"])
def test_places_with_a_tolerance_is_a_manifest_that_does_not_load(tmp_path, mode):
    path = project(tmp_path, "4.2", metric("4.2", places=1, mode=mode, tolerance="0.1"))
    with pytest.raises(ManifestError, match="`places` goes with `printed_precision` only"):
        load(path)
    assert main(["verify", str(path)]) == 2
    for model, fields in ((MetricEvidence, metric("4.2")), (TableCellEvidence, cell("4.2"))):
        with pytest.raises(ValidationError):
            model.model_validate({**fields, "places": 1, "mode": mode})
    with pytest.raises(ValidationError):
        ValueEvidence(
            artifact="a",
            name="n",
            reported="1.0",
            locator={"kind": "tree", "pointer": "/x"},
            places=1,
            mode=ComparisonMode(mode),
        )


@pytest.mark.parametrize("places", [-1, 1.5, "one"])
def test_places_is_a_whole_number_that_is_not_negative(tmp_path, places):
    with pytest.raises(ManifestError):
        load(project(tmp_path, "4.2", metric("4.2", places=places)))


def test_a_table_cell_and_a_value_take_places_as_a_metric_does(tmp_path):
    value = {
        "kind": "value",
        "artifact": "results",
        "name": "x",
        "reported": "4.20",
        "locator": {"kind": "tree", "pointer": "/x"},
    }
    for evidence in (cell("4.20"), value):
        assert only(project(tmp_path, "4.2011", evidence)).outcome is Outcome.VERIFIED
        declared = only(project(tmp_path, "4.2011", {**evidence, "places": 1}))
        assert declared.reason is Reason.PLACES_MISMATCH
        assert only(project(tmp_path, "4.2011", {**evidence, "places": 2})).outcome is (
            Outcome.VERIFIED
        )


def test_an_assertion_declaring_no_places_serializes_and_reports_as_it_did(tmp_path):
    bare = MetricEvidence(artifact="a", name="m", reported="1", pointer="/x")
    assert bare.model_dump() == {
        "artifact": "a",
        "kind": "metric",
        "name": "m",
        "reported": "1",
        "pointer": "/x",
        "mode": ComparisonMode.PRINTED_PRECISION,
        "tolerance": "0",
    }
    declared = bare.model_copy(update={"places": 0})
    assert json.loads(declared.model_dump_json())["places"] == 0
    assert MetricEvidence.model_validate_json(declared.model_dump_json()) == declared

    decision = check(tmp_path, "3.2004", "3.20")
    assert (decision.outcome, decision.detail, decision.tie) == (
        Outcome.VERIFIED,
        "/x = 3.2004",
        None,
    )
    wrong = check(tmp_path, "3.2004", "3.21")
    assert wrong.detail == "x: manuscript prints 3.21, results.json holds 3.2004 at /x"


# -- an exact tie ----------------------------------------------------------------------------


@pytest.mark.parametrize("reported", ["4.2", "4.3"])
def test_a_tie_verifies_as_either_neighbor_and_the_record_says_it_was_one(tmp_path, reported):
    decision = check(tmp_path, "4.25", reported)
    assert (decision.outcome, decision.reason) == (Outcome.VERIFIED, Reason.VALUE_MATCH)
    assert decision.tie == Tie(lower="4.2", upper="4.3", printed=reported)
    assert decision.detail == (
        f"/x = 4.25, an exact tie between 4.2 and 4.3; the manuscript prints {reported}"
    )


@pytest.mark.parametrize("reported", ["4.1", "4.4", "4.0", "-4.2", "42.5"])
def test_a_printed_value_that_is_neither_neighbor_of_a_tie_is_a_mismatch(tmp_path, reported):
    decision = check(tmp_path, "4.25", reported)
    assert (decision.outcome, decision.reason) == (Outcome.MISMATCH, Reason.VALUE_MISMATCH)


def test_a_mismatch_at_a_tie_still_records_the_tie(tmp_path):
    decision = check(tmp_path, "4.25", "4.4")
    assert decision.tie == Tie(lower="4.2", upper="4.3", printed="4.4")
    assert decision.detail == (
        "x: manuscript prints 4.4, results.json holds 4.25 at /x, an exact tie between 4.2 and 4.3"
    )


@pytest.mark.parametrize(
    ("stored", "verifies", "mismatches"),
    [
        ("4.2500001", "4.3", "4.2"),
        ("4.2499999", "4.2", "4.3"),
        ("4.25000000000000000000000000000000000001", "4.3", "4.2"),
        ("4.24999999999999999999999999999999999999", "4.2", "4.3"),
    ],
)
def test_a_value_beside_a_tie_is_not_one(tmp_path, stored, verifies, mismatches):
    # Read from a table, which keeps every digit; a JSON number goes through a float.
    near = only(project(tmp_path, stored, cell(verifies)))
    assert (near.outcome, near.tie) == (Outcome.VERIFIED, None)
    assert only(project(tmp_path, stored, cell(mismatches))).outcome is Outcome.MISMATCH


@pytest.mark.parametrize("reported", ["-4.2", "-4.3"])
def test_a_negative_tie_verifies_as_either_neighbor(tmp_path, reported):
    decision = check(tmp_path, "-4.25", reported)
    assert decision.outcome is Outcome.VERIFIED
    assert decision.tie == Tie(lower="-4.3", upper="-4.2", printed=reported)
    assert check(tmp_path, "-4.25", "4.2").outcome is Outcome.MISMATCH
    assert check(tmp_path, "-4.25", "-4.4").outcome is Outcome.MISMATCH


@pytest.mark.parametrize("reported", ["4.2", "4.3"])
def test_a_tie_after_the_percent_conversion_verifies_as_either_neighbor(tmp_path, reported):
    decision = check(tmp_path, "0.0425", reported, conversion="percent")
    assert decision.outcome is Outcome.VERIFIED
    assert decision.tie == Tie(lower="4.2", upper="4.3", printed=reported)
    assert decision.detail == (
        "/x = 0.0425 (4.25 as a percentage), an exact tie between 4.2 and 4.3; "
        f"the manuscript prints {reported}"
    )
    # The stored fraction is no tie at the precision it would be compared at unconverted.
    assert check(tmp_path, "0.0425", reported).tie is None


@pytest.mark.parametrize(
    ("reported", "outcome"), [("4.2", Outcome.VERIFIED), ("4.3", Outcome.VERIFIED)]
)
def test_a_tie_under_declared_places_verifies_as_either_neighbor(tmp_path, reported, outcome):
    decision = check(tmp_path, "4.25", reported, places=1)
    assert decision.outcome is outcome
    assert decision.tie == Tie(lower="4.2", upper="4.3", printed=reported)
    assert check(tmp_path, "4.25", "4.25", places=1).reason is Reason.PLACES_MISMATCH
    assert check(tmp_path, "4.25", "4.4", places=1).reason is Reason.VALUE_MISMATCH


def test_a_tie_is_at_the_precision_the_manuscript_prints(tmp_path):
    assert check(tmp_path, "4.25", "4.25").tie is None
    assert check(tmp_path, "4.250", "4.3").tie == Tie(lower="4.2", upper="4.3", printed="4.3")
    assert check(tmp_path, "0.5", "0").tie == Tie(lower="0", upper="1", printed="0")
    assert check(tmp_path, "0.5", "1").outcome is Outcome.VERIFIED
    assert check(tmp_path, "-0.5", "0").tie == Tie(lower="-1", upper="0", printed="0")
    assert check(tmp_path, "-0.5", "-1").outcome is Outcome.VERIFIED
    assert check(tmp_path, "25", "2E+1").tie == Tie(lower="20", upper="30", printed="20")
    assert check(tmp_path, "25", "3E+1").outcome is Outcome.VERIFIED


@pytest.mark.parametrize("mode", ["absolute", "relative"])
def test_a_tolerance_has_no_tie(tmp_path, mode):
    inside = check(tmp_path, "4.25", "4.2", mode=mode, tolerance="0.1")
    assert (inside.outcome, inside.tie) == (Outcome.VERIFIED, None)
    outside = check(tmp_path, "4.25", "4.3", mode=mode, tolerance="0.001")
    assert (outside.outcome, outside.tie) == (Outcome.MISMATCH, None)


def test_tie_detection_is_exact_on_the_digits():
    assert _tie(D("4.25"), D("4.2")) == (D("4.2"), D("4.3"))
    assert _tie(D("4.35"), D("4.3")) == (D("4.3"), D("4.4"))
    assert _tie(D("9.95"), D("9.9")) == (D("9.9"), D("10.0"))
    assert _tie(D("-9.95"), D("9.9")) == (D("-10.0"), D("-9.9"))
    assert _tie(D("4.2"), D("4.2")) is None
    assert _tie(D("4.26"), D("4.2")) is None
    assert _tie(D("4.5"), D("4.25")) is None
    assert _tie(D("1E+30"), D("3.20")) is None
    long = "4.25" + "0" * 60
    assert _tie(D(long), D("4.2")) == (D("4.2"), D("4.3"))
    assert _tie(D(long + "1"), D("4.2")) is None
    lower, upper = _tie(D("4.25"), D("4.2"))
    assert (str(lower), str(upper)) == ("4.2", "4.3")


def test_away_from_a_tie_the_comparison_is_the_half_even_rounding_it_was():
    """Half-even and half-up differ only at a tie, so accepting both there must leave every
    other comparison as `quantize` decides it."""
    zero = D(0)
    ties = 0
    for _ in range(20000):
        places = random.randint(0, 4)
        reported = D(random.randint(-2000, 2000)).scaleb(-places)
        stored = reported + D(random.randint(-30, 30)).scaleb(-places - random.randint(1, 3))
        agrees = _agree(stored, reported, ComparisonMode.PRINTED_PRECISION, zero)
        neighbors = _tie(stored, reported)
        if neighbors is None:
            assert agrees is (stored.quantize(reported, decimal.ROUND_HALF_EVEN) == reported)
        else:
            ties += 1
            assert neighbors == (
                stored.quantize(reported, decimal.ROUND_FLOOR),
                stored.quantize(reported, decimal.ROUND_CEILING),
            )
            assert agrees is (reported in neighbors)
            assert neighbors[1] - neighbors[0] == D(1).scaleb(-places)
            assert stored - neighbors[0] == neighbors[1] - stored
    assert ties > 100, "the sample must reach ties"


def sides(tmp_path, stored, stated):
    (tmp_path / "paper.md").write_text(f"The rate was {stated} in the sample.\n")
    path = project(
        tmp_path,
        stored,
        {
            "kind": "correspondence",
            "name": "rate",
            "sides": [
                {
                    "name": "stated",
                    "artifact": "paper",
                    "locator": {"kind": "prose", "before": "rate was", "after": "in"},
                },
                {
                    "name": "computed",
                    "artifact": "results",
                    "locator": {"kind": "tree", "pointer": "/x"},
                },
            ],
        },
    )
    manifest = yaml.safe_load(path.read_text())
    manifest["artifacts"].append({"id": "paper", "path": "paper.md"})
    path.write_text(yaml.safe_dump(manifest, sort_keys=False))
    return path


@pytest.mark.parametrize("stated", ["4.2", "4.3"])
def test_a_correspondence_at_a_tie_agrees_with_either_neighbor_and_says_so(tmp_path, stated):
    decision = only(sides(tmp_path, "4.25", stated))
    assert decision.outcome is Outcome.VERIFIED
    assert decision.tie == Tie(lower="4.2", upper="4.3", printed=stated)
    assert decision.detail == (
        f"rate: stated {stated}, computed 4.25, an exact tie between 4.2 and 4.3"
    )
    assert only(sides(tmp_path, "4.25", "4.4")).outcome is Outcome.MISMATCH
    assert only(sides(tmp_path, "4.26", "4.3")).tie is None


# -- `repro verify` and `repro why` ----------------------------------------------------------


def test_why_shows_the_tie_and_the_neighbor_the_manuscript_prints(tmp_path, capsys):
    path = project(tmp_path, "0.0425", metric("4.3", conversion="percent"))
    (assertion,) = why(load(path), "c").assertions
    assert assertion.tie == Tie(lower="4.2", upper="4.3", printed="4.3")

    assert main(["why", "c", str(path)]) == 0
    shown = capsys.readouterr().out
    assert (
        "    results at /x: holds 0.0425, 4.25 as a percentage\n"
        "    an exact tie between 4.2 and 4.3: rounding half up prints one and half to even "
        "may print the other\n"
        "    the manuscript prints 4.3: verified\n"
    ) in shown

    assert main(["why", "c", str(path), "--format", "json"]) == 0
    (assertion,) = json.loads(capsys.readouterr().out)["assertions"]
    assert assertion["tie"] == {"lower": "4.2", "upper": "4.3", "printed": "4.3"}
    assert assertion["places"] is None


def test_why_shows_no_tie_line_where_there_is_no_tie(tmp_path, capsys):
    path = project(tmp_path, "4.26", metric("4.3"))
    assert main(["why", "c", str(path)]) == 0
    shown = capsys.readouterr().out
    assert "an exact tie" not in shown
    assert "    results at /x: holds 4.26\n    the manuscript prints 4.3: verified\n" in shown


def test_why_shows_the_declared_places_and_names_a_places_mismatch(tmp_path, capsys):
    path = project(tmp_path, "4.2051", metric("4.20", places=1))
    (assertion,) = why(load(path), "c").assertions
    assert (assertion.places, assertion.reason) == (1, Reason.PLACES_MISMATCH)
    assert main(["why", "c", str(path)]) == 0
    shown = capsys.readouterr().out
    assert (
        "    the manuscript prints 4.20, declared to 1 decimal place: mismatch (places mismatch)\n"
    ) in shown

    path = project(tmp_path, "4.2051", metric("4.2", places=1))
    assert main(["why", "c", str(path)]) == 0
    shown = capsys.readouterr().out
    assert "    the manuscript prints 4.2, declared to 1 decimal place: verified\n" in shown

    path = project(tmp_path, "4.2651", metric("4.2", places=1))
    assert main(["why", "c", str(path)]) == 0
    assert "declared to 1 decimal place: mismatch\n" in capsys.readouterr().out


def test_verify_prints_the_tie_and_carries_it_in_json(tmp_path, capsys):
    path = project(tmp_path, "4.25", metric("4.3"))
    assert main(["verify", str(path), "--policy", "exploratory"]) == 0
    shown = capsys.readouterr().out
    assert "/x = 4.25, an exact tie between 4.2 and 4.3" in shown
    (line,) = [line for line in shown.splitlines() if line.startswith("  ok")]
    assert "  [exact tie: 4.2 or 4.3]" in line
    path = project(tmp_path, "0.0425", metric("4.3", conversion="percent"))
    assert main(["verify", str(path), "--policy", "exploratory"]) == 0
    (line,) = [line for line in capsys.readouterr().out.splitlines() if line.startswith("  ok")]
    # The detail is cut at 52 characters, which is why the tie is said beside it.
    assert line.startswith(
        "  ok    c            metric   /x = 0.0425 (4.25 as a percentage), an exact tie bet"
        "  [exact tie: 4.2 or 4.3]"
    )
    assert main(["verify", str(path), "--policy", "exploratory", "--format", "json"]) == 0
    (decision,) = json.loads(capsys.readouterr().out)["report"]["claims"][0]["decisions"]
    assert decision["tie"] == {"lower": "4.2", "upper": "4.3", "printed": "4.3"}


def test_verify_fails_a_places_mismatch_under_every_policy(tmp_path, capsys):
    path = project(tmp_path, "4.2051", metric("4.20", places=1))
    for policy in ("exploratory", "publication", "strict"):
        assert main(["verify", str(path), "--policy", policy]) == 1
        assert "MISS" in capsys.readouterr().out
