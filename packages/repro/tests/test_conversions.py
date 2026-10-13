"""A file that stores a fraction, and a manuscript that prints the percentage.

The conversion is a name from a closed set, declared on the assertion and applied to the stored
value before the comparison. The tests are about the order of the two steps, converting and then
rounding to what the manuscript prints, and about nothing being converted that was not named.
"""

from __future__ import annotations

import decimal
import json

import pytest
import yaml
from pydantic import ValidationError
from repro.cli import main
from repro.exceptions import ManifestError
from repro.manifest import load
from repro.models import (
    ComparisonMode,
    Conversion,
    CorrespondenceEvidence,
    CorrespondenceSide,
    Digest,
    Manifest,
    MetricEvidence,
    Outcome,
    Reason,
    TableCellEvidence,
    TreeLocator,
    ValueEvidence,
)
from repro.verify import compare_decimal, verify
from repro.why import why


def project(tmp_path, stored, evidence):
    """A manifest with one claim over `results.json`, which holds `stored` at `/rate`."""
    # Written as text, so a stored value keeps the digits the test gives it.
    (tmp_path / "results.json").write_text(f'{{"rate": {stored}}}')
    (tmp_path / "models.csv").write_text(f"model,rate\nlasso,{stored}\n")
    manifest = {
        "schema_version": "repro/1",
        "project": "t",
        "artifacts": [
            {"id": "results", "path": "results.json"},
            {"id": "models", "path": "models.csv"},
        ],
        "claims": [{"id": "c", "text": "The rate was as printed.", "evidence": evidence}],
    }
    path = tmp_path / "repro.yaml"
    path.write_text(yaml.safe_dump(manifest, sort_keys=False))
    return path


def metric(reported, **kw):
    return {
        "kind": "metric",
        "artifact": "results",
        "name": "rate",
        "reported": reported,
        "pointer": "/rate",
        **kw,
    }


def only(path):
    (decision,) = verify(load(path)).decisions
    return decision


def test_a_stored_fraction_agrees_with_the_printed_percentage_only_where_declared(tmp_path):
    declared = only(project(tmp_path, "0.042", [metric("4.2", conversion="percent")]))
    assert (declared.outcome, declared.reason) == (Outcome.VERIFIED, Reason.VALUE_MATCH)
    bare = only(project(tmp_path, "0.042", [metric("4.2")]))
    assert (bare.outcome, bare.reason) == (Outcome.MISMATCH, Reason.VALUE_MISMATCH)


@pytest.mark.parametrize(
    ("stored", "outcome"),
    [
        ("0.0424", Outcome.VERIFIED),
        ("0.0426", Outcome.MISMATCH),
        # Rounding the fraction to the printed precision first would make both of these 0.0,
        # and both would then disagree with 4.2.
        ("0.04249999", Outcome.VERIFIED),
        ("0.04250001", Outcome.MISMATCH),
    ],
)
def test_the_value_is_rounded_to_printed_precision_after_it_is_converted(tmp_path, stored, outcome):
    assert only(project(tmp_path, stored, [metric("4.2", conversion="percent")])).outcome is outcome


@pytest.mark.parametrize(
    ("stored", "outcome"),
    [("4.2", Outcome.VERIFIED), ("4.24", Outcome.VERIFIED), ("4.26", Outcome.MISMATCH)],
)
def test_a_stored_percentage_agrees_with_the_printed_fraction(tmp_path, stored, outcome):
    decision = only(project(tmp_path, stored, [metric("0.042", conversion="fraction")]))
    assert decision.outcome is outcome
    bare = only(project(tmp_path, stored, [metric("0.042")]))
    assert bare.outcome is Outcome.MISMATCH


def test_the_decision_carries_the_stored_value_the_converted_value_and_the_conversion(tmp_path):
    decision = only(project(tmp_path, "0.0424", [metric("4.2", conversion="percent")]))
    assert (decision.extracted, decision.conversion, decision.converted) == (
        "0.0424",
        Conversion.PERCENT,
        "4.24",
    )
    assert "0.0424 (4.24 as a percentage)" in decision.detail

    wrong = only(project(tmp_path, "0.0426", [metric("4.2", conversion="percent")]))
    assert (wrong.extracted, wrong.converted) == ("0.0426", "4.26")
    assert "manuscript prints 4.2" in wrong.detail
    assert "holds 0.0426 (4.26 as a percentage)" in wrong.detail

    other = only(project(tmp_path, "95.76", [metric("0.958", conversion="fraction")]))
    assert (other.conversion, other.converted) == (Conversion.FRACTION, "0.9576")
    assert "95.76 (0.9576 as a fraction)" in other.detail


def test_an_assertion_with_no_conversion_reports_as_it_did(tmp_path):
    decision = only(project(tmp_path, "3.2004", [metric("3.20")]))
    assert decision.outcome is Outcome.VERIFIED
    assert decision.detail == "/rate = 3.2004"
    assert (decision.extracted, decision.conversion, decision.converted) == ("3.2004", None, None)

    wrong = only(project(tmp_path, "3.2004", [metric("3.21")]))
    assert wrong.detail == "rate: manuscript prints 3.21, results.json holds 3.2004 at /rate"


def test_a_manifest_declaring_no_conversion_serializes_without_the_field():
    """The manifest digest is over the serialized manifest, so a field that appeared as
    `null` on every assertion would move the digest of every manifest already written."""
    bare = MetricEvidence(artifact="a", name="m", reported="1", pointer="/x")
    declared = bare.model_copy(update={"conversion": Conversion.PERCENT})
    assert "conversion" not in bare.model_dump()
    assert "conversion" not in json.loads(bare.model_dump_json())
    assert json.loads(declared.model_dump_json())["conversion"] == "percent"
    assert MetricEvidence.model_validate_json(declared.model_dump_json()) == declared

    side = CorrespondenceSide(name="s", artifact="a", locator=TreeLocator(pointer="/x"))
    assert "conversion" not in side.model_dump()

    # Field for field what the model wrote before `conversion` existed.
    written = (
        '{"schema_version":"repro/1","project":"p","provenance":null,"artifacts":[],'
        '"claims":[{"id":"c","text":"t","where":null,"registration":"exploratory",'
        '"registration_note":"","evidence":[{"artifact":"a","kind":"metric","name":"m",'
        '"reported":"1","pointer":"/x","mode":"printed_precision","tolerance":"0"}]}],'
        '"runs":[],"regenerations":[],"set_aside":[]}'
    )
    manifest = Manifest.model_validate_json(written)
    assert Digest.of_text(manifest.model_dump_json()) == Digest.of_text(written)


def test_the_conversion_moves_the_decimal_point_and_changes_no_digit():
    long = decimal.Decimal("0.123456789012345678901234567890123456789")
    assert str(Conversion.PERCENT.apply(long)) == "12.3456789012345678901234567890123456789"
    assert Conversion.FRACTION.apply(Conversion.PERCENT.apply(long)) == long
    # One digit stays one digit: 0.5 is known to the tenth, and so to ten percentage points.
    assert Conversion.PERCENT.apply(decimal.Decimal("0.5")).as_tuple() == (0, (5,), 1)
    assert str(Conversion.PERCENT.apply(decimal.Decimal("-0.042"))) == "-4.2"
    assert str(Conversion.FRACTION.apply(decimal.Decimal("7"))) == "0.07"


def test_a_converted_value_is_written_without_an_exponent(tmp_path):
    decision = only(project(tmp_path, "0.5", [metric("50", conversion="percent")]))
    assert decision.outcome is Outcome.VERIFIED
    assert decision.converted == "50"
    assert decision.detail == "/rate = 0.5 (50 as a percentage)"
    assert only(project(tmp_path, "0.5", [metric("50.0", conversion="percent")])).outcome is (
        Outcome.VERIFIED
    )
    assert only(project(tmp_path, "0.5", [metric("50.1", conversion="percent")])).outcome is (
        Outcome.MISMATCH
    )


def test_a_conversion_is_exact_where_binary_multiplication_is_not(tmp_path):
    """`0.07 * 100` is `7.000000000000001` in binary floating point, so a comparison with no
    tolerance at all agrees only if the arithmetic is decimal."""
    assert 0.07 * 100 != 7
    exact = metric("7", conversion="percent", mode="absolute", tolerance="0")
    assert only(project(tmp_path, "0.07", [exact])).outcome is Outcome.VERIFIED
    printed = metric("7.000000000000000", conversion="percent")
    assert only(project(tmp_path, "0.07", [printed])).outcome is Outcome.VERIFIED


def test_a_tolerance_is_in_the_unit_the_manuscript_prints(tmp_path):
    def within(tolerance, mode):
        evidence = metric("4.2", conversion="percent", mode=mode, tolerance=tolerance)
        return only(project(tmp_path, "0.0426", [evidence])).outcome

    # 4.26 against 4.2 differs by 0.06 percentage points, which is 0.0006 as stored.
    assert within("0.1", "absolute") is Outcome.VERIFIED
    assert within("0.05", "absolute") is Outcome.MISMATCH
    assert within("0.02", "relative") is Outcome.VERIFIED
    assert within("0.01", "relative") is Outcome.MISMATCH


def test_compare_decimal_applies_the_declared_conversion_and_stays_total():
    evidence = MetricEvidence(
        artifact="a", name="m", reported="4.2", pointer="/x", conversion=Conversion.PERCENT
    )
    assert compare_decimal(decimal.Decimal("0.0424"), evidence) is True
    assert compare_decimal(decimal.Decimal("4.2"), evidence) is False
    assert compare_decimal(decimal.Decimal("NaN"), evidence) is False
    assert compare_decimal(decimal.Decimal("Infinity"), evidence) is False


@pytest.mark.parametrize("stored", ['"n/a"', "NaN", "Infinity"])
def test_a_stored_value_that_is_not_a_number_is_not_numeric_under_a_conversion(tmp_path, stored):
    decision = only(project(tmp_path, stored, [metric("4.2", conversion="percent")]))
    assert (decision.outcome, decision.reason) == (Outcome.NOT_FOUND, Reason.VALUE_NOT_NUMERIC)
    assert decision.conversion is Conversion.PERCENT and decision.converted is None


@pytest.mark.parametrize("name", ["percentage", "per_thousand", "x100", "PERCENT", "* 100", ""])
def test_a_conversion_the_set_does_not_name_is_a_manifest_that_does_not_load(tmp_path, name):
    path = project(tmp_path, "0.042", [metric("4.2", conversion=name)])
    with pytest.raises(ManifestError, match=r"claims\.0\.evidence\.0\.metric\.conversion"):
        load(path)
    with pytest.raises(ValidationError):
        MetricEvidence.model_validate(metric("4.2", conversion=name))
    assert main(["verify", str(path)]) == 2


def test_no_assertion_takes_a_multiplier(tmp_path):
    for field in ("multiplier", "scale", "factor"):
        with pytest.raises(ManifestError):
            load(project(tmp_path, "0.042", [metric("4.2", **{field: 100})]))


def test_a_table_cell_and_a_value_take_the_conversion_a_metric_does(tmp_path):
    cell = {
        "kind": "table",
        "artifact": "models",
        "name": "rate",
        "reported": "4.2",
        "column": "rate",
        "where": {"model": "lasso"},
    }
    value = {
        "kind": "value",
        "artifact": "results",
        "name": "rate",
        "reported": "4.2",
        "locator": {"kind": "tree", "pointer": "/rate"},
    }
    for evidence in (cell, value):
        path = project(tmp_path, "0.0424", [{**evidence, "conversion": "percent"}])
        assert only(path).outcome is Outcome.VERIFIED
        assert only(path).converted == "4.24"
        assert only(project(tmp_path, "0.0424", [evidence])).outcome is Outcome.MISMATCH
        path = project(tmp_path, "0.0426", [{**evidence, "conversion": "percent"}])
        assert only(path).outcome is Outcome.MISMATCH
    assert TableCellEvidence.model_fields["conversion"].default is None
    assert ValueEvidence.model_fields["conversion"].default is None


def sides(tmp_path, stored, stated, **kw):
    (tmp_path / "paper.md").write_text(f"Attrition was {stated}% of the enrolled sample.\n")
    path = project(
        tmp_path,
        stored,
        [
            {
                "kind": "correspondence",
                "name": "attrition",
                "sides": [
                    {
                        "name": "stated",
                        "artifact": "paper",
                        "locator": {"kind": "prose", "before": "Attrition was", "after": "%"},
                    },
                    {
                        "name": "computed",
                        "artifact": "results",
                        "locator": {"kind": "tree", "pointer": "/rate"},
                        **kw,
                    },
                ],
            }
        ],
    )
    manifest = yaml.safe_load(path.read_text())
    manifest["artifacts"].append({"id": "paper", "path": "paper.md"})
    path.write_text(yaml.safe_dump(manifest, sort_keys=False))
    return path


def test_a_side_of_a_correspondence_is_compared_as_converted(tmp_path):
    decision = only(sides(tmp_path, "0.0424", "4.2", conversion="percent"))
    assert decision.outcome is Outcome.VERIFIED
    assert [(s.name, s.extracted, s.conversion, s.converted) for s in decision.sides] == [
        ("stated", "4.2", None, None),
        ("computed", "0.0424", Conversion.PERCENT, "4.24"),
    ]
    assert decision.detail == "attrition: stated 4.2, computed 0.0424 (4.24 as a percentage)"

    assert only(sides(tmp_path, "0.0426", "4.2", conversion="percent")).outcome is Outcome.MISMATCH
    assert only(sides(tmp_path, "0.0424", "4.2")).outcome is Outcome.MISMATCH
    # The coarser side is found after converting: 4.2 prints one decimal and 0.04 as a
    # percentage prints none, so the document's 4.2 is the value rounded.
    assert only(sides(tmp_path, "0.04", "4.2", conversion="percent")).outcome is Outcome.VERIFIED
    assert only(sides(tmp_path, "0.05", "4.2", conversion="percent")).outcome is Outcome.MISMATCH


def test_a_correspondence_side_that_is_not_a_number_is_not_converted(tmp_path):
    decision = only(sides(tmp_path, '"n/a"', "4.2", conversion="percent"))
    assert (decision.outcome, decision.reason) == (Outcome.NOT_FOUND, Reason.VALUE_NOT_NUMERIC)
    assert [s.converted for s in decision.sides] == [None, None]


def test_two_sides_at_one_address_are_refused_whatever_conversion_one_declares():
    def side(name, **kw):
        return CorrespondenceSide(name=name, artifact="a", locator=TreeLocator(pointer="/x"), **kw)

    with pytest.raises(ValidationError, match="same value"):
        CorrespondenceEvidence(
            name="n", sides=(side("stored"), side("printed", conversion=Conversion.PERCENT))
        )


def test_why_shows_the_stored_value_and_the_converted_one(tmp_path, capsys):
    path = project(tmp_path, "0.042", [metric("4.2", conversion="percent")])
    (assertion,) = why(load(path), "c").assertions
    (read,) = assertion.reads
    assert (read.stored, read.conversion, read.converted) == ("0.042", Conversion.PERCENT, "4.2")
    assert (assertion.printed, assertion.outcome) == ("4.2", Outcome.VERIFIED)

    assert main(["why", "c", str(path)]) == 0
    shown = capsys.readouterr().out
    assert "    results at /rate: holds 0.042, 4.2 as a percentage\n" in shown
    assert "    the manuscript prints 4.2: verified\n" in shown

    assert main(["why", "c", str(path), "--format", "json"]) == 0
    (read,) = json.loads(capsys.readouterr().out)["assertions"][0]["reads"]
    assert (read["stored"], read["conversion"], read["converted"]) == ("0.042", "percent", "4.2")


def test_why_shows_a_mismatch_after_conversion_with_both_values(tmp_path, capsys):
    path = project(tmp_path, "0.0426", [metric("4.2", conversion="percent")])
    assert main(["why", "c", str(path)]) == 0
    shown = capsys.readouterr().out
    assert "    results at /rate: holds 0.0426, 4.26 as a percentage\n" in shown
    assert "    the manuscript prints 4.2: mismatch\n" in shown


def test_why_shows_a_value_with_no_conversion_as_it_did(tmp_path, capsys):
    path = project(tmp_path, "0.042", [metric("0.042")])
    assert main(["why", "c", str(path)]) == 0
    assert "    results at /rate: holds 0.042\n" in capsys.readouterr().out
    (read,) = why(load(path), "c").assertions[0].reads
    assert (read.conversion, read.converted) == (None, None)


def test_why_shows_each_side_of_a_correspondence_under_its_own_conversion(tmp_path, capsys):
    path = sides(tmp_path, "0.0424", "4.2", conversion="percent")
    assert main(["why", "c", str(path)]) == 0
    shown = capsys.readouterr().out
    assert '    stated: paper at before "Attrition was", after "%": holds 4.2\n' in shown
    assert "    computed: results at /rate: holds 0.0424, 4.24 as a percentage\n" in shown


def test_verify_prints_the_stored_value_beside_the_converted_one(tmp_path, capsys):
    path = project(tmp_path, "0.042", [metric("4.2", conversion="percent")])
    assert main(["verify", str(path), "--policy", "exploratory"]) == 0
    assert "/rate = 0.042 (4.2 as a percentage)" in capsys.readouterr().out


def test_the_modes_are_unchanged_by_the_field():
    assert [mode.value for mode in ComparisonMode] == ["printed_precision", "absolute", "relative"]
    assert [conversion.value for conversion in Conversion] == ["percent", "fraction"]
