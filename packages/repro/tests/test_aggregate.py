"""A printed value that is a statistic over several stored ones.

Ten runs exist, the manifest binds one of them, and the sentence says "mean over ten seeds".
The assertion here reads every member it declares and is checked only where all of them hold a
number. The tests are about a member that is gone or is not a number, a list that is not the
length the manuscript states, and a mean that is rounded once.
"""

from __future__ import annotations

import decimal
import fractions
import json
import random

import pytest
import yaml
from pydantic import ValidationError
from repro.cli import main
from repro.exceptions import ManifestError
from repro.manifest import load
from repro.models import (
    AggregateEvidence,
    AggregateMember,
    ArtifactRef,
    Claim,
    ComparisonMode,
    ComparisonStatus,
    Digest,
    ExecutionStatus,
    ExtractionStatus,
    Freshness,
    InputReading,
    Manifest,
    Outcome,
    Reading,
    Reason,
    Regeneration,
    RegenerationReason,
    RegenerationRecord,
    RegenerationState,
    ReproductionReport,
    RunOutput,
    Statistic,
    TreeLocator,
    Validity,
    Warning_,
)
from repro.policy import PUBLICATION
from repro.renderers import to_sarif
from repro.reproduce import _reading, append
from repro.stale import stale
from repro.toolchain import UNKNOWN
from repro.verify import (
    DEFAULT_BACKENDS,
    SHOWN_PLACES,
    _agree,
    _agree_exact,
    _shown,
    artifact_states,
    verify,
)
from repro.why import why

#: Ten seeds. Their mean is 0.9137, their median 0.9135, and the best of them is 0.921.
SEEDS = ["0.912", "0.915", "0.909", "0.921", "0.913", "0.911", "0.917", "0.914", "0.908", "0.917"]


def project(tmp_path, values=SEEDS, reported="0.914", statistic="mean", members=None, **kw):
    """A manifest with one aggregate over `seed-N.json`, each holding one value at `/accuracy`."""
    for number, value in enumerate(values):
        # Written as text, so a stored value keeps the digits the test gives it.
        (tmp_path / f"seed-{number}.json").write_text(f'{{"accuracy": {value}}}')
    manifest = {
        "schema_version": "repro/1",
        "project": "t",
        "artifacts": [
            {
                "id": f"seed-{number}",
                "path": f"seed-{number}.json",
                "digest": {
                    "algorithm": "sha256",
                    "value": Digest.of_file(tmp_path / f"seed-{number}.json").value,
                },
            }
            for number in range(len(values))
        ],
        "claims": [
            {
                "id": "c",
                "text": "Mean accuracy over ten seeds was as printed.",
                "evidence": [
                    {
                        "kind": "aggregate",
                        "name": "accuracy",
                        "reported": reported,
                        "statistic": statistic,
                        "count": len(values),
                        "members": members
                        if members is not None
                        else [member(number) for number in range(len(values))],
                        **kw,
                    }
                ],
            }
        ],
    }
    path = tmp_path / "repro.yaml"
    path.write_text(yaml.safe_dump(manifest, sort_keys=False))
    return path


def member(number, pointer="/accuracy"):
    return {"artifact": f"seed-{number}", "locator": {"kind": "tree", "pointer": pointer}}


def only(path):
    (decision,) = verify(load(path)).decisions
    return decision


def evidence(**kw):
    fields = {
        "name": "n",
        "reported": "1",
        "statistic": Statistic.MEAN,
        "count": 2,
        "members": (
            AggregateMember(artifact="a", locator=TreeLocator(pointer="/x")),
            AggregateMember(artifact="b", locator=TreeLocator(pointer="/x")),
        ),
        **kw,
    }
    return AggregateEvidence(**fields)


# -- the statistic is over every member ------------------------------------------------------


def test_the_mean_of_ten_members_is_what_the_manuscript_prints(tmp_path):
    decision = only(project(tmp_path))
    assert (decision.outcome, decision.reason) == (Outcome.VERIFIED, Reason.VALUE_MATCH)
    assert (decision.statistic, decision.computed) == (Statistic.MEAN, "0.9137")
    assert [m.extracted for m in decision.members] == SEEDS
    assert [m.artifact_id for m in decision.members] == [f"seed-{n}" for n in range(10)]
    assert decision.detail == "accuracy: mean of 10 = 0.9137"


def test_the_best_run_printed_as_the_mean_is_a_mismatch(tmp_path):
    best = max(SEEDS)
    decision = only(project(tmp_path, reported=best))
    assert (decision.outcome, decision.reason) == (Outcome.MISMATCH, Reason.VALUE_MISMATCH)
    assert decision.detail == ("accuracy: manuscript prints 0.921, mean of 10 is 0.9137")
    assert only(project(tmp_path, reported=best, statistic="max")).outcome is Outcome.VERIFIED


def test_one_member_edited_moves_the_mean(tmp_path):
    path = project(tmp_path)
    assert only(path).outcome is Outcome.VERIFIED
    (tmp_path / "seed-4.json").write_text('{"accuracy": 0.813}')
    decision = only(path)
    assert decision.outcome is Outcome.MISMATCH
    assert decision.computed == "0.9037"
    assert decision.validity is Validity.BROKEN_PIN
    assert [m.validity for m in decision.members].count(Validity.BROKEN_PIN) == 1
    assert decision.members[4].validity is Validity.BROKEN_PIN


@pytest.mark.parametrize(
    ("statistic", "reported", "computed"),
    [
        ("mean", "3.75", "3.75"),
        ("median", "3", "3"),
        ("min", "1", "1"),
        ("max", "9.25", "9.25"),
        ("sum", "18.75", "18.75"),
        ("count", "5", "5"),
    ],
)
def test_each_statistic_is_computed_over_the_members(tmp_path, statistic, reported, computed):
    values = ["3", "1", "4", "1.5", "9.25"]
    decision = only(project(tmp_path, values, reported, statistic))
    assert (decision.outcome, decision.computed) == (Outcome.VERIFIED, computed)
    # No two of the six agree on these values, so a statistic computed as another is caught.
    for other in ("3.75", "3", "1", "9.25", "18.75", "5"):
        if other != reported:
            assert only(project(tmp_path, values, other, statistic)).outcome is Outcome.MISMATCH


def test_the_median_of_an_even_number_is_the_mean_of_the_middle_two(tmp_path):
    values = ["4", "1", "3", "2"]
    assert only(project(tmp_path, values, "2.5", "median")).outcome is Outcome.VERIFIED
    assert only(project(tmp_path, values, "2", "median", mode="absolute")).outcome is (
        Outcome.MISMATCH
    )
    assert only(project(tmp_path, values, "3", "median", mode="absolute")).outcome is (
        Outcome.MISMATCH
    )


# -- every member must resolve ---------------------------------------------------------------


def test_a_member_file_that_is_gone_leaves_the_assertion_unchecked_and_is_named(tmp_path):
    path = project(tmp_path)
    (tmp_path / "seed-3.json").unlink()
    report = verify(load(path))
    (decision,) = report.decisions
    assert (decision.outcome, decision.reason) == (Outcome.UNCHECKED, Reason.ARTIFACT_MISSING)
    assert decision.comparison is ComparisonStatus.NOT_APPLICABLE
    assert "seed-3.json does not exist" in decision.detail
    assert "seed-2.json" not in decision.detail
    assert report.artifacts_with(Validity.ARTIFACT_ABSENT) == ("seed-3",)
    assert not PUBLICATION.assess(report).passed


def test_the_mean_of_the_members_that_remain_is_never_taken(tmp_path):
    """Nine of the ten values have a mean of their own, 0.91289, which is 0.913 as printed.
    A manifest printing that must not verify against a list that still declares ten."""
    path = project(tmp_path, reported="0.913")
    (tmp_path / "seed-3.json").unlink()
    assert only(path).outcome is Outcome.UNCHECKED

    path = project(tmp_path, reported="0.913")
    (tmp_path / "seed-3.json").write_text('{"loss": 0.2}')
    assert only(path).outcome is Outcome.NOT_FOUND

    path = project(tmp_path, reported="0.913")
    (tmp_path / "seed-3.json").write_text('{"accuracy": "diverged"}')
    assert only(path).outcome is Outcome.NOT_FOUND


def test_a_member_whose_address_does_not_resolve_is_not_found_and_is_named(tmp_path):
    path = project(tmp_path)
    (tmp_path / "seed-3.json").write_text('{"loss": 0.2}')
    (tmp_path / "seed-7.json").write_text('{"loss": 0.3}')
    decision = only(path)
    assert (decision.outcome, decision.reason) == (Outcome.NOT_FOUND, Reason.POINTER_ABSENT)
    assert (decision.execution, decision.extraction, decision.comparison) == (
        ExecutionStatus.COMPLETED,
        ExtractionStatus.ABSENT,
        ComparisonStatus.NOT_APPLICABLE,
    )
    assert decision.detail == (
        "member 4 of 10 (seed-3): /accuracy does not resolve in seed-3.json; "
        "member 8 of 10 (seed-7): /accuracy does not resolve in seed-7.json"
    )
    assert decision.computed is None
    assert [m.extracted for m in decision.members] == [
        None if n in (3, 7) else SEEDS[n] for n in range(10)
    ]
    assert decision.members[3].extraction_digest == UNKNOWN


@pytest.mark.parametrize("stored", ['"diverged"', "NaN", "Infinity", "true"])
def test_a_member_that_holds_no_number_is_not_numeric_and_is_named(tmp_path, stored):
    path = project(tmp_path)
    (tmp_path / "seed-5.json").write_text(f'{{"accuracy": {stored}}}')
    decision = only(path)
    assert (decision.outcome, decision.reason) == (Outcome.NOT_FOUND, Reason.VALUE_NOT_NUMERIC)
    assert decision.extraction is ExtractionStatus.INVALID
    assert decision.detail.startswith("member 6 of 10 (seed-5) holds ")
    assert decision.computed is None


def test_a_member_file_that_cannot_be_parsed_leaves_the_assertion_unchecked_and_is_named(
    tmp_path,
):
    path = project(tmp_path)
    (tmp_path / "seed-8.json").write_text('{"accuracy": 0.9')
    decision = only(path)
    assert (decision.outcome, decision.reason) == (Outcome.UNCHECKED, Reason.ARTIFACT_UNREADABLE)
    assert decision.detail.startswith("member 9 of 10 (seed-8): not valid JSON")


def test_a_member_in_a_format_with_no_adapter_leaves_the_assertion_unchecked(tmp_path):
    members = [member(number) for number in range(10)]
    path = project(tmp_path, members=members)
    manifest = yaml.safe_load(path.read_text())
    (tmp_path / "seed-9.mat").write_bytes(b"MATLAB")
    manifest["artifacts"][9] = {"id": "seed-9", "path": "seed-9.mat"}
    path.write_text(yaml.safe_dump(manifest, sort_keys=False))
    decision = only(path)
    assert (decision.outcome, decision.reason) == (Outcome.UNCHECKED, Reason.FORMAT_UNSUPPORTED)
    assert decision.detail.startswith("member 10 of 10 (seed-9): ")


def test_a_member_the_manifest_does_not_declare_leaves_the_assertion_unchecked(tmp_path):
    members = [*(member(number) for number in range(9)), member(99)]
    decision = only(project(tmp_path, members=members))
    assert (decision.outcome, decision.reason) == (Outcome.UNCHECKED, Reason.ARTIFACT_UNDECLARED)
    assert "'seed-99'" in decision.detail


# -- the list is the length the manuscript states --------------------------------------------


def test_a_count_that_is_not_the_number_of_members_is_a_manifest_that_does_not_load(tmp_path):
    nine = [member(number) for number in range(9)]
    path = project(tmp_path, members=nine)
    with pytest.raises(ManifestError, match="`count` is 10 and 9 members are listed"):
        load(path)
    assert main(["verify", str(path)]) == 2

    with pytest.raises(ValidationError, match="`count` is 3 and 2 members are listed"):
        evidence(count=3)
    with pytest.raises(ValidationError, match="`count` is 1 and 2 members are listed"):
        evidence(count=1)


def test_count_is_required_and_the_list_is_not_empty():
    fields = evidence().model_dump()
    del fields["count"]
    with pytest.raises(ValidationError, match="count"):
        AggregateEvidence.model_validate(fields)
    with pytest.raises(ValidationError):
        evidence(count=0, members=())
    with pytest.raises(ValidationError):
        evidence(count=1, members=())


def test_a_member_listed_twice_is_a_manifest_that_does_not_load(tmp_path):
    twice = [*(member(number) for number in range(9)), member(0)]
    with pytest.raises(ManifestError, match="member 10 addresses a value in 'seed-0'"):
        load(project(tmp_path, members=twice))

    same = AggregateMember(artifact="a", locator=TreeLocator(pointer="/x"))
    with pytest.raises(ValidationError, match="counted twice"):
        evidence(members=(same, same))
    # One file at two addresses is two values.
    other = AggregateMember(artifact="a", locator=TreeLocator(pointer="/y"))
    assert evidence(members=(same, other)).artifacts == ("a",)


@pytest.mark.parametrize("statistic", ["sd", "std", "average", "variance", "MEAN", ""])
def test_a_statistic_the_set_does_not_name_is_a_manifest_that_does_not_load(tmp_path, statistic):
    with pytest.raises(ManifestError, match=r"aggregate\.statistic"):
        load(project(tmp_path, statistic=statistic))


def test_the_statistics_are_a_closed_set():
    assert [s.value for s in Statistic] == ["mean", "median", "min", "max", "sum", "count"]


# -- exact arithmetic ------------------------------------------------------------------------

TEN_ON_A_BOUNDARY = ["0.024", "0.005", "0.075", "0.056", "0.009"]
TEN_ON_A_BOUNDARY += ["0.191", "0.178", "0.130", "0.376", "0.121"]


@pytest.mark.parametrize(
    ("values", "printed", "float_prints"),
    [
        (["0.264", "0.099"], "0.182", "0.181"),
        (["0.305", "0.016"], "0.160", "0.161"),
        (["0.394", "0.127", "0.020", "0.081"], "0.156", "0.155"),
        (
            TEN_ON_A_BOUNDARY,
            "0.116",
            "0.117",
        ),
    ],
)
def test_a_mean_on_a_rounding_boundary_does_not_depend_on_binary_error(
    tmp_path, values, printed, float_prints
):
    """Each mean is exactly halfway between two printed values, and goes to the even one. The
    same mean in binary floating point sits a hair to one side and rounds the other way."""
    as_float = sum(float(v) for v in values) / len(values)
    assert f"{round(as_float, 3):.3f}" == float_prints
    assert only(project(tmp_path, values, printed)).outcome is Outcome.VERIFIED
    assert only(project(tmp_path, values, float_prints)).outcome is Outcome.MISMATCH


def test_a_mean_with_no_finite_expansion_is_rounded_once(tmp_path):
    thirds = ["1", "1", "2"]
    decision = only(project(tmp_path, thirds, "1.33"))
    assert decision.outcome is Outcome.VERIFIED
    assert decision.computed == "1." + "3" * (2 + SHOWN_PLACES)
    assert only(project(tmp_path, thirds, "1.34")).outcome is Outcome.MISMATCH
    assert only(project(tmp_path, thirds, "1.3333333333333333333333333333333333")).outcome is (
        Outcome.VERIFIED
    )
    assert only(project(tmp_path, thirds, "1.3333333333333333333333333333333334")).outcome is (
        Outcome.MISMATCH
    )
    # 2/3 rounds up at every precision, and a quotient cut short at any digit rounds down.
    assert only(project(tmp_path, ["0", "1", "1"], "0.67")).outcome is Outcome.VERIFIED
    assert only(project(tmp_path, ["0", "1", "1"], "0.66")).outcome is Outcome.MISMATCH


def test_a_sum_keeps_every_digit_of_values_longer_than_the_decimal_context(tmp_path):
    """Thirty-one significant digits each, where the default context carries twenty-eight and
    would add them to 2.000000000000000000000000000."""
    (tmp_path / "cells.csv").write_text(
        "run,value\na,1.000000000000000000000000000001\nb,1.000000000000000000000000000002\n"
    )
    assert decimal.Decimal("1.000000000000000000000000000001") + decimal.Decimal(
        "1.000000000000000000000000000002"
    ) != decimal.Decimal("2.000000000000000000000000000003")

    def over(reported):
        return AggregateEvidence(
            name="n",
            reported=reported,
            statistic=Statistic.SUM,
            count=2,
            members=tuple(
                AggregateMember(
                    artifact="cells",
                    locator={"kind": "table", "column": "value", "where": {"run": run}},
                )
                for run in ("a", "b")
            ),
        )

    def outcome(reported):
        manifest = Manifest(
            path=tmp_path / "repro.yaml",
            artifacts=(ArtifactRef(id="cells", path=tmp_path / "cells.csv"),),
            claims=(Claim(id="c", text="t", evidence=(over(reported),)),),
        )
        return verify(manifest).decisions[0].outcome

    assert outcome("2.000000000000000000000000000003") is Outcome.VERIFIED
    assert outcome("2.000000000000000000000000000000") is Outcome.MISMATCH


def test_the_exact_comparison_is_the_decimal_one_on_every_decimal():
    """`_agree_exact` exists for a value no decimal holds. On a value a decimal does hold it
    must be `_agree`, or an aggregate and a metric would be held to two rules."""
    modes = list(ComparisonMode)
    disagreed = []
    agreed = 0
    for _ in range(20000):
        places = random.randint(0, 4)
        reported = decimal.Decimal(random.randint(-2000, 2000)).scaleb(-places)
        # Half the stored values sit within a few quanta of the printed one, ties included.
        near = reported + decimal.Decimal(random.randint(-30, 30)).scaleb(-places - 1)
        far = decimal.Decimal(random.randint(-(10**6), 10**6)).scaleb(-random.randint(0, 6))
        stored = random.choice([near, far])
        tolerance = decimal.Decimal(random.randint(0, 50)).scaleb(-random.randint(0, 3))
        for mode in modes:
            decimal_says = _agree(stored, reported, mode, tolerance)
            exact_says = _agree_exact(fractions.Fraction(stored), reported, mode, tolerance)
            agreed += decimal_says
            if decimal_says is not exact_says:
                disagreed.append((stored, reported, mode, tolerance))
    assert disagreed == []
    assert agreed > 5000, "the sample must hold agreements as well as disagreements"


def test_a_tie_goes_to_the_even_neighbor_as_it_does_for_a_single_value():
    def exact(value, reported):
        return _agree_exact(
            fractions.Fraction(value),
            decimal.Decimal(reported),
            ComparisonMode.PRINTED_PRECISION,
            decimal.Decimal(0),
        )

    assert exact("0.125", "0.12") and not exact("0.125", "0.13")
    assert exact("0.135", "0.14") and not exact("0.135", "0.13")
    assert exact("-0.125", "-0.12") and not exact("-0.125", "-0.13")
    assert exact("25", "2E+1") and exact("35", "4E+1")


def test_a_tolerance_is_compared_against_the_exact_statistic(tmp_path):
    thirds = ["1", "1", "2"]

    def within(reported, mode, tolerance):
        return only(project(tmp_path, thirds, reported, mode=mode, tolerance=tolerance)).outcome

    assert within("1.3", "absolute", "0.04") is Outcome.VERIFIED
    assert within("1.3", "absolute", "0.03") is Outcome.MISMATCH
    assert within("1.25", "relative", "0.07") is Outcome.VERIFIED
    assert within("1.25", "relative", "0.06") is Outcome.MISMATCH
    # A third is within no finite tolerance of zero short of itself.
    assert within("1.3333333333", "absolute", "0") is Outcome.MISMATCH


def test_a_statistic_is_shown_exactly_where_it_terminates_and_rounded_where_it_does_not():
    printed = decimal.Decimal("0.91")
    assert _shown(fractions.Fraction(9137, 10000), printed) == "0.9137"
    assert _shown(fractions.Fraction(5), printed) == "5"
    assert _shown(fractions.Fraction(-3, 8), printed) == "-0.375"
    assert _shown(fractions.Fraction(0), printed) == "0"
    assert _shown(fractions.Fraction(2, 3), printed) == "0.66667"
    assert _shown(fractions.Fraction(-1, 3), printed) == "-0.33333"
    assert _shown(fractions.Fraction(1000, 7), decimal.Decimal("143")) == "142.857"
    assert _shown(fractions.Fraction(1, 3), decimal.Decimal("3E+2")) == "0.333"


# -- what the record carries -----------------------------------------------------------------


def test_the_decision_binds_every_member_by_artifact_locator_and_extraction(tmp_path):
    path = project(tmp_path)
    decision = only(path)
    assert decision.artifact_id == "" and decision.artifact_digest is None
    assert decision.sides == ()
    for number, recorded in enumerate(decision.members):
        file = tmp_path / f"seed-{number}.json"
        assert recorded.artifact_digest == Digest.of_file(file).value
        assert recorded.locator_digest == TreeLocator(pointer="/accuracy").digest.value
        assert recorded.extraction_digest == Digest.of_text(SEEDS[number]).value
        assert recorded.validity is Validity.AUTHORITATIVE
    assert (
        decision.extraction_digest
        == Digest.of_text("\x00".join(m.extraction_digest for m in decision.members)).value
    )
    assert (decision.backend, decision.tool) == ("aggregate", "reproducible-science")

    # Reordering two members that hold different values changes the record of what was read.
    members = [member(number) for number in range(10)]
    members[0], members[1] = members[1], members[0]
    assert only(project(tmp_path, members=members)).extraction_digest != decision.extraction_digest


def test_members_of_one_file_are_read_at_their_own_addresses(tmp_path):
    scores = {"scores": [float(v) for v in SEEDS]}
    (tmp_path / "all.json").write_text(json.dumps(scores))
    aggregate = AggregateEvidence(
        name="accuracy",
        reported="0.914",
        statistic=Statistic.MEAN,
        count=10,
        members=tuple(
            AggregateMember(artifact="all", locator=TreeLocator(pointer=f"/scores/{n}"))
            for n in range(10)
        ),
    )
    assert aggregate.artifacts == ("all",)
    manifest = Manifest(
        path=tmp_path / "repro.yaml",
        artifacts=(
            ArtifactRef(
                id="all", path=tmp_path / "all.json", digest=Digest.of_file(tmp_path / "all.json")
            ),
        ),
        claims=(Claim(id="c", text="t", evidence=(aggregate,)),),
    )
    (decision,) = verify(manifest).decisions
    assert (decision.outcome, decision.computed) == (Outcome.VERIFIED, "0.9137")
    assert decision.artifact_id == "all"
    assert decision.artifact_digest == Digest.of_file(tmp_path / "all.json").value

    # The whole array is not a member: a locator resolves to one scalar.
    whole = aggregate.model_copy(
        update={
            "count": 1,
            "members": (AggregateMember(artifact="all", locator=TreeLocator(pointer="/scores")),),
        }
    )
    (decision,) = verify(
        manifest.model_copy(update={"claims": (Claim(id="c", text="t", evidence=(whole,)),)})
    ).decisions
    assert (decision.outcome, decision.reason) == (Outcome.NOT_FOUND, Reason.SELECTOR_NOT_SCALAR)


def test_a_member_addressed_by_row_index_carries_the_positional_warning(tmp_path):
    (tmp_path / "runs.csv").write_text("seed,accuracy\n0,0.5\n1,0.7\n")
    aggregate = AggregateEvidence(
        name="accuracy",
        reported="0.6",
        statistic=Statistic.MEAN,
        count=2,
        members=tuple(
            AggregateMember(
                artifact="runs",
                locator={"kind": "table_position", "column": "accuracy", "row": row},
            )
            for row in (0, 1)
        ),
    )
    manifest = Manifest(
        path=tmp_path / "repro.yaml",
        artifacts=(ArtifactRef(id="runs", path=tmp_path / "runs.csv"),),
        claims=(Claim(id="c", text="t", evidence=(aggregate,)),),
    )
    (decision,) = verify(manifest).decisions
    assert decision.outcome is Outcome.VERIFIED
    assert decision.warnings == (Warning_.POSITIONAL_ADDRESS,)


def test_sarif_locates_an_aggregate_at_every_file_a_member_reads(tmp_path):
    report = verify(load(project(tmp_path, reported="0.921")))
    document = to_sarif(report, PUBLICATION.assess(report), version="0")
    (result,) = [r for r in document["runs"][0]["results"] if r["ruleId"] == "repro/mismatch"]
    located = [
        location["physicalLocation"]["artifactLocation"]["uri"] for location in result["locations"]
    ]
    assert located == [f"seed-{n}" for n in range(10)]


# -- `repro verify`, `repro why` and `repro stale` -------------------------------------------


def test_verify_prints_the_statistic_and_how_many_members_it_is_over(tmp_path, capsys):
    assert main(["verify", str(project(tmp_path)), "--policy", "exploratory"]) == 0
    assert "aggregate accuracy: mean of 10 = 0.9137" in capsys.readouterr().out


def test_why_lists_the_members_and_the_computed_statistic(tmp_path, capsys):
    path = project(tmp_path)
    (assertion,) = why(load(path), "c").assertions
    assert (assertion.kind, assertion.name, assertion.printed) == ("aggregate", "accuracy", "0.914")
    assert (assertion.statistic, assertion.computed) == (Statistic.MEAN, "0.9137")
    assert [(r.artifact, r.address, r.stored) for r in assertion.reads] == [
        (f"seed-{n}", "/accuracy", SEEDS[n]) for n in range(10)
    ]

    assert main(["why", "c", str(path)]) == 0
    shown = capsys.readouterr().out
    for number, value in enumerate(SEEDS):
        assert f"    seed-{number} (seed-{number}.json): matches its pinned digest " in shown
        assert f"    seed-{number} at /accuracy: holds {value}\n" in shown
    assert (
        "    seed-9 at /accuracy: holds 0.917\n"
        "    the mean of the 10 values: 0.9137\n"
        "    the manuscript prints 0.914: verified\n"
    ) in shown

    assert main(["why", "c", str(path), "--format", "json"]) == 0
    (assertion,) = json.loads(capsys.readouterr().out)["assertions"]
    assert (assertion["statistic"], assertion["computed"]) == ("mean", "0.9137")
    assert [read["stored"] for read in assertion["reads"]] == SEEDS


def test_why_shows_a_mismatch_beside_the_statistic(tmp_path, capsys):
    path = project(tmp_path, reported="0.921")
    assert main(["why", "c", str(path)]) == 0
    shown = capsys.readouterr().out
    assert (
        "    the mean of the 10 values: 0.9137\n    the manuscript prints 0.921: mismatch\n"
    ) in shown


def test_why_names_the_member_that_is_gone_and_shows_no_statistic(tmp_path, capsys):
    path = project(tmp_path)
    (tmp_path / "seed-3.json").unlink()
    (assertion,) = why(load(path), "c").assertions
    assert (assertion.outcome, assertion.computed) == (Outcome.UNCHECKED, None)
    assert [read.stored for read in assertion.reads] == [None] * 10

    assert main(["why", "c", str(path)]) == 0
    shown = capsys.readouterr().out
    assert "    seed-3 (seed-3.json): nothing at the declared path\n" in shown
    assert "    seed-2 (seed-2.json): matches its pinned digest " in shown
    assert "of the 10 values" not in shown
    assert "    the manuscript prints 0.914: unchecked (artifact missing)\n" in shown


def test_why_shows_the_values_that_were_read_where_one_member_holds_no_number(tmp_path, capsys):
    path = project(tmp_path)
    (tmp_path / "seed-5.json").write_text('{"accuracy": "diverged"}')
    assert main(["why", "c", str(path)]) == 0
    shown = capsys.readouterr().out
    assert "    seed-4 at /accuracy: holds 0.913\n" in shown
    assert "    seed-5 at /accuracy: holds diverged\n" in shown
    assert "of the 10 values" not in shown
    assert "    the manuscript prints 0.914: not found (value not numeric)\n" in shown


def rerun(root, record):
    written = Digest.of_file(root / f"{record.output.artifact}.json").value
    return RegenerationState(
        regeneration_id=record.id,
        artifact_id=record.output.artifact,
        state=Regeneration.REPRODUCED,
        reason=RegenerationReason.OUTPUT_MATCHES,
        expected=written,
        actual=written,
        executed=True,
        bytes_identical=True,
        command=record.command,
        inputs=tuple(
            InputReading(
                artifact_id=wanted.artifact,
                path=wanted.artifact,
                pinned=wanted.digest.value,
                observed=Digest.of_file(root / wanted.artifact).value,
            )
            for wanted in record.inputs
        ),
    )


def produced(tmp_path):
    """The ten-seed project, with each seed's file written by its own command from `train.py`,
    and one re-run of every command recorded."""
    loaded = load(project(tmp_path))
    (tmp_path / "train.py").write_text("print('train')\n")
    script = Digest.of_file(tmp_path / "train.py")
    records = tuple(
        RegenerationRecord(
            id=f"train-{n}",
            command=("python", "train.py", "--seed", str(n)),
            inputs=(RunOutput(artifact="train.py", digest=script),),
            output=RunOutput(
                artifact=f"seed-{n}", digest=Digest.of_file(tmp_path / f"seed-{n}.json")
            ),
        )
        for n in range(10)
    )
    manifest = Manifest(
        project="t",
        path=tmp_path / "repro.yaml",
        artifacts=(
            *loaded.artifacts,
            ArtifactRef(id="train.py", path=tmp_path / "train.py", digest=script),
        ),
        claims=loaded.claims,
        regenerations=records,
    )
    append(
        ReproductionReport(
            started_at="2026-01-01T00:00:00+00:00",
            regenerations=tuple(rerun(tmp_path, record) for record in records),
        ),
        tmp_path,
    )
    return manifest


def test_stale_treats_every_member_file_as_read_by_the_assertion(tmp_path):
    manifest = produced(tmp_path)
    report = stale(manifest)
    (claim,) = report.claims
    (assertion,) = claim.assertions
    assert assertion.kind == "aggregate"
    assert assertion.artifacts == tuple(f"seed-{n}" for n in range(10))
    assert [edge.target for edge in report.edges if edge.kind == "reads"] == [
        f"seed-{n}" for n in range(10)
    ]
    assert (assertion.state, claim.state) == (Freshness.CURRENT, Freshness.CURRENT)


@pytest.mark.parametrize("edited", [0, 6, 9])
def test_one_member_file_edited_after_its_rerun_makes_the_claim_stale(tmp_path, edited):
    manifest = produced(tmp_path)
    (tmp_path / f"seed-{edited}.json").write_text('{"accuracy": 0.9}')
    report = stale(manifest)
    (claim,) = report.claims
    assert claim.state is Freshness.STALE
    assert [node.id for node in report.regenerations if node.state is Freshness.STALE] == [
        f"train-{edited}"
    ]
    assert [found.artifact for found in report.findings] == [f"seed-{edited}"]


def test_a_member_file_with_no_producer_leaves_the_claim_partly_outside_the_record(tmp_path):
    manifest = produced(tmp_path)
    fewer = manifest.model_copy(update={"regenerations": manifest.regenerations[:9]})
    (claim,) = stale(fewer).claims
    assert claim.state is Freshness.PARTLY_OUTSIDE


def test_a_rerun_that_rewrites_one_member_is_read_against_the_statistic(tmp_path):
    """`repro reproduce` puts each assertion reading a record's output to the file the re-run
    wrote. For an aggregate that is one member's file, with the others as pinned."""
    manifest = load(project(tmp_path))
    (claim,) = manifest.claims
    (aggregate,) = claim.evidence
    states, paths = artifact_states(manifest)
    registry = {backend.kind: backend for backend in DEFAULT_BACKENDS}

    def reading(text):
        fresh = tmp_path / "fresh.json"
        fresh.write_text(text)
        return _reading(claim, aggregate, manifest, "seed-4", fresh, paths, states, registry)

    # Other bytes, the same value: the mean is the one printed.
    assert reading('{"accuracy": 0.913, "epochs": 30}').reading is Reading.HOLDS
    moved = reading('{"accuracy": 0.813}')
    assert moved.reading is Reading.CHANGED
    assert moved.printed == "0.914"
    assert moved.detail == "accuracy: manuscript prints 0.914, mean of 10 is 0.9037"
    assert reading('{"loss": 0.2}').reading is Reading.UNREADABLE
