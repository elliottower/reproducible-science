"""Whether a confirmatory claim's evidence was produced after the plan it names.

The outcome is separate from the reason it was reached. Every condition that stops the check
yields `unchecked` with its own reason: an absent record is not evidence that a result
predates its plan, and reporting it as one would manufacture a finding out of a gap.
"""

from __future__ import annotations

import datetime
import json

import pytest
from pydantic import ValidationError
from repro.models import (
    ArtifactRef,
    Claim,
    Digest,
    Manifest,
    MetricEvidence,
    Ordering,
    OrderingReason,
    Registration,
    RegistrationAuthority,
    RunOutput,
    RunRecord,
)
from repro.policy import EXPLORATORY, PUBLICATION, STRICT, Policy, Severity
from repro.verify import verify

UTC = datetime.UTC
REGISTERED = datetime.datetime(2026, 8, 1, 14, 0, tzinfo=UTC)
AFTER = datetime.datetime(2026, 8, 3, 9, 12, tzinfo=UTC)
BEFORE = datetime.datetime(2026, 7, 20, 9, 12, tzinfo=UTC)

RESULTS = json.dumps({"x": 3.2})


def build(
    tmp_path,
    *,
    registration=Registration.CONFIRMATORY,
    note="",
    runs=(),
    pin_plan=True,
    plan_moved=False,
    results=RESULTS,
):
    """A manifest with one metric claim over `results.json`, and an optional pinned plan."""
    path = tmp_path / "results.json"
    path.write_text(results)
    plan = tmp_path / "PREREG.md"
    plan.write_text("# plan\n")

    artifacts = [ArtifactRef(id="results", path=path, digest=Digest.of_file(path))]
    if pin_plan:
        digest = Digest(algorithm="sha256", value="0" * 64) if plan_moved else Digest.of_file(plan)
        artifacts.append(ArtifactRef(id="plan", path=plan, digest=digest))
    return Manifest(
        project="p",
        artifacts=tuple(artifacts),
        runs=tuple(runs),
        claims=(
            Claim(
                id="c",
                text="t",
                registration=registration,
                registration_note=note,
                evidence=(
                    MetricEvidence(artifact="results", name="x", reported="3.2", pointer="/x"),
                ),
            ),
        ),
    )


def digest_of(tmp_path, body=RESULTS) -> Digest:
    scratch = tmp_path / ".probe"
    scratch.write_text(body)
    return Digest.of_file(scratch)


def run(tmp_path, *, plan="plan", bind=True, body=RESULTS, **kw) -> RunRecord:
    outputs = (
        RunOutput(artifact="results", digest=digest_of(tmp_path, body))
        if bind
        else RunOutput(artifact="results"),
    )
    return RunRecord(id="r", registered_plan=plan, outputs=outputs, **kw)


def check(manifest) -> tuple[Ordering, OrderingReason, str]:
    claim = verify(manifest).claims[0]
    return claim.ordering, claim.ordering_reason, claim.ordering_detail


# -- the two verdicts -----------------------------------------------------------------------


def test_a_run_that_started_after_registration_is_ordered(tmp_path):
    manifest = build(tmp_path, runs=[run(tmp_path, registered_at=REGISTERED, started_at=AFTER)])
    ordering, reason, detail = check(manifest)
    assert ordering is Ordering.ORDERED
    assert reason is OrderingReason.RUN_FOLLOWS_REGISTRATION
    assert "pinned plan" in detail and "self_recorded" in detail


def test_a_run_that_started_before_its_registration_is_a_violation(tmp_path):
    manifest = build(tmp_path, runs=[run(tmp_path, registered_at=REGISTERED, started_at=BEFORE)])
    ordering, reason, detail = check(manifest)
    assert ordering is Ordering.VIOLATED
    assert reason is OrderingReason.RUN_PRECEDES_REGISTRATION
    assert "2026-07-20" in detail and "2026-08-01" in detail


def test_ordering_holds_across_timezones(tmp_path):
    # 09:00-05:00 is 14:00Z, one hour after a 13:00Z registration.
    registered = datetime.datetime(2026, 8, 1, 13, 0, tzinfo=UTC)
    started = datetime.datetime(
        2026, 8, 1, 9, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=-5))
    )
    manifest = build(tmp_path, runs=[run(tmp_path, registered_at=registered, started_at=started)])
    assert check(manifest)[0] is Ordering.ORDERED


# -- one reason per condition that stops the check ------------------------------------------


def test_no_run_record(tmp_path):
    assert check(build(tmp_path))[:2] == (Ordering.UNCHECKED, OrderingReason.NO_RUN_RECORD)


def test_a_run_for_other_artifacts_does_not_order_this_claim(tmp_path):
    other = RunRecord(
        id="elsewhere",
        registered_plan="plan",
        outputs=(RunOutput(artifact="something-else"),),
        registered_at=REGISTERED,
        started_at=AFTER,
    )
    assert check(build(tmp_path, runs=[other]))[1] is OrderingReason.NO_RUN_RECORD


def test_a_run_naming_no_plan(tmp_path):
    manifest = build(
        tmp_path, runs=[run(tmp_path, plan="", registered_at=REGISTERED, started_at=AFTER)]
    )
    assert check(manifest)[:2] == (Ordering.UNCHECKED, OrderingReason.NO_REGISTERED_PLAN)


def test_a_run_missing_a_timestamp(tmp_path):
    manifest = build(tmp_path, runs=[run(tmp_path, registered_at=REGISTERED)])
    assert check(manifest)[:2] == (Ordering.UNCHECKED, OrderingReason.TIMESTAMP_MISSING)


def test_a_plan_whose_pin_is_broken_settles_nothing(tmp_path):
    """A plan that is not the document pinned could have been written to match results."""
    manifest = build(
        tmp_path, plan_moved=True, runs=[run(tmp_path, registered_at=REGISTERED, started_at=AFTER)]
    )
    ordering, reason, detail = check(manifest)
    assert (ordering, reason) == (Ordering.UNCHECKED, OrderingReason.REGISTERED_PLAN_CHANGED)
    assert "attests to nothing" in detail


def test_an_output_named_but_not_bound_by_digest(tmp_path):
    """Otherwise a later file at the same path qualifies as an earlier run's output."""
    manifest = build(
        tmp_path, runs=[run(tmp_path, bind=False, registered_at=REGISTERED, started_at=AFTER)]
    )
    ordering, reason, detail = check(manifest)
    assert (ordering, reason) == (Ordering.UNCHECKED, OrderingReason.RUN_OUTPUT_UNLINKED)
    assert "records no digest" in detail


def test_an_output_whose_bytes_are_not_the_ones_the_run_produced(tmp_path):
    manifest = build(
        tmp_path,
        runs=[
            run(tmp_path, body=json.dumps({"x": 9.9}), registered_at=REGISTERED, started_at=AFTER)
        ],
    )
    assert check(manifest)[:2] == (Ordering.UNCHECKED, OrderingReason.RUN_OUTPUT_CHANGED)


def test_two_runs_claiming_the_same_output(tmp_path):
    a = run(tmp_path, registered_at=REGISTERED, started_at=AFTER)
    b = a.model_copy(update={"id": "r2", "registered_at": BEFORE})
    ordering, reason, detail = check(build(tmp_path, runs=[a, b]))
    assert (ordering, reason) == (Ordering.UNCHECKED, OrderingReason.AMBIGUOUS_PRODUCING_RUN)
    assert "2 runs" in detail


# -- what the check declines to apply to ----------------------------------------------------


@pytest.mark.parametrize(
    "registration,note",
    [
        (Registration.EXPLORATORY, ""),
        (Registration.NOT_APPLICABLE, "exhaustive deterministic count"),
    ],
)
def test_only_a_confirmatory_claim_is_ordered_against_a_plan(tmp_path, registration, note):
    manifest = build(
        tmp_path,
        registration=registration,
        note=note,
        runs=[run(tmp_path, registered_at=REGISTERED, started_at=BEFORE)],
    )
    ordering, reason, _ = check(manifest)
    assert ordering is Ordering.NOT_APPLICABLE, (
        "a run predating a plan is only a finding where a plan was claimed"
    )
    assert reason is OrderingReason.NOT_CONFIRMATORY


# -- registration authority -----------------------------------------------------------------


def test_the_weakest_authority_among_producing_runs_is_reported(tmp_path):
    strong = run(
        tmp_path,
        registered_at=REGISTERED,
        started_at=AFTER,
        registration_authority=RegistrationAuthority.ZENODO,
    )
    assert (
        verify(build(tmp_path, runs=[strong])).claims[0].registration_authority
        is RegistrationAuthority.ZENODO
    )


def test_an_unqualified_timestamp_is_self_recorded(tmp_path):
    manifest = build(tmp_path, runs=[run(tmp_path, registered_at=REGISTERED, started_at=AFTER)])
    assert verify(manifest).claims[0].registration_authority is RegistrationAuthority.SELF_RECORDED


def test_a_policy_can_require_more_than_a_self_recorded_timestamp(tmp_path):
    """A hash and two self-recorded timestamps establish internal consistency, not
    chronology: one actor who writes all three after seeing results manufactures the lot."""
    report = verify(
        build(tmp_path, runs=[run(tmp_path, registered_at=REGISTERED, started_at=AFTER)])
    )
    demanding = Policy(
        name="demanding",
        minimum_registration_authority=RegistrationAuthority.OSF,
        weak_registration_authority=Severity.ERROR,
    )
    assessment = demanding.assess(report)
    assert assessment.passed is False
    assert any(v.rule == "claim.registration_authority" for v in assessment.errors)


def test_a_sufficient_authority_raises_no_violation(tmp_path):
    report = verify(
        build(
            tmp_path,
            runs=[
                run(
                    tmp_path,
                    registered_at=REGISTERED,
                    started_at=AFTER,
                    registration_authority=RegistrationAuthority.TRUSTED_TIMESTAMP,
                )
            ],
        )
    )
    demanding = Policy(name="demanding", minimum_registration_authority=RegistrationAuthority.OSF)
    assert not any(
        v.rule == "claim.registration_authority" for v in demanding.assess(report).violations
    )


# -- policy ---------------------------------------------------------------------------------


def test_a_violated_ordering_fails_every_profile(tmp_path):
    report = verify(
        build(tmp_path, runs=[run(tmp_path, registered_at=REGISTERED, started_at=BEFORE)])
    )
    for policy in (EXPLORATORY, PUBLICATION, STRICT):
        assessment = policy.assess(report)
        assert assessment.passed is False, policy.name
        assert any(v.rule == "claim.ordering_violated" for v in assessment.errors)


def test_an_unchecked_ordering_is_graded_by_profile_and_names_its_reason(tmp_path):
    report = verify(build(tmp_path))
    assert EXPLORATORY.assess(report).passed is True
    publication = PUBLICATION.assess(report)
    assert publication.passed is True
    assert any(v.rule == "claim.ordering_unchecked.no_run_record" for v in publication.warnings)
    assert STRICT.assess(report).passed is False


# -- registration is three states, and the third one has to be argued for -------------------


def test_a_claim_says_nothing_about_registration_and_is_exploratory():
    """The default is never `not_applicable`: inapplicability is asserted, not assumed."""
    assert Claim(id="c", text="t").registration is Registration.EXPLORATORY


def test_not_applicable_without_a_reason_is_refused():
    with pytest.raises(ValidationError, match="registration_note"):
        Claim(id="c", text="t", registration=Registration.NOT_APPLICABLE)


def test_not_applicable_with_a_reason_is_accepted():
    claim = Claim(
        id="c",
        text="t",
        registration=Registration.NOT_APPLICABLE,
        registration_note="exhaustive deterministic count",
    )
    assert claim.confirmatory is False


@pytest.mark.parametrize(
    "flag,expected", [(True, Registration.CONFIRMATORY), (False, Registration.EXPLORATORY)]
)
def test_the_boolean_still_parses(flag, expected):
    assert Claim(id="c", text="t", confirmatory=flag).registration is expected


def test_a_false_boolean_does_not_become_not_applicable():
    """A boolean never carried the distinction, so reading one in cannot invent it."""
    assert (
        Claim(id="c", text="t", confirmatory=False).registration is not Registration.NOT_APPLICABLE
    )


def test_a_bare_artifact_id_in_outputs_parses_and_is_reported_unlinked():
    """`outputs: [results]` is accepted, then reported as an unbound output rather than
    rejected, so the weakness is visible instead of blocking the manifest."""
    record = RunRecord(id="r", outputs=("results",))
    assert record.outputs[0].artifact == "results"
    assert record.outputs[0].digest is None


# -- every artifact a claim rests on needs its own run --------------------------------------


def test_a_run_for_one_artifact_does_not_order_a_claim_that_cites_two(tmp_path):
    """Taking the runs producing *any* named artifact meant a run record for one incidental
    file turned an unregistered result into an ordered one, while the artifact carrying the
    number had no run at all."""
    results = tmp_path / "results.json"
    results.write_text(RESULTS)
    extra = tmp_path / "extra.json"
    extra.write_text(json.dumps({"y": 1.0}))
    plan = tmp_path / "PREREG.md"
    plan.write_text("# plan\n")

    manifest = Manifest(
        project="p",
        artifacts=(
            ArtifactRef(id="results", path=results, digest=Digest.of_file(results)),
            ArtifactRef(id="extra", path=extra, digest=Digest.of_file(extra)),
            ArtifactRef(id="plan", path=plan, digest=Digest.of_file(plan)),
        ),
        runs=(
            RunRecord(
                id="r1",
                registered_plan="plan",
                outputs=(RunOutput(artifact="results", digest=Digest.of_file(results)),),
                registered_at=REGISTERED,
                started_at=AFTER,
            ),
        ),
        claims=(
            Claim(
                id="c",
                text="t",
                registration=Registration.CONFIRMATORY,
                evidence=(
                    MetricEvidence(artifact="results", name="x", reported="3.2", pointer="/x"),
                    MetricEvidence(artifact="extra", name="y", reported="1.0", pointer="/y"),
                ),
            ),
        ),
    )
    claim = verify(manifest).claims[0]
    assert claim.ordering is Ordering.UNCHECKED
    assert claim.ordering_reason is OrderingReason.NO_RUN_RECORD
    assert "extra" in claim.ordering_detail


def test_an_undeclared_plan_is_not_a_pinned_plan(tmp_path):
    """Declaring the plan and leaving it unpinned reported `unchecked`, while not declaring it
    at all reported `ordered` -- so the more transparent manifest scored strictly worse."""
    manifest = build(
        tmp_path, pin_plan=False, runs=[run(tmp_path, registered_at=REGISTERED, started_at=AFTER)]
    )
    ordering, reason, detail = check(manifest)
    assert ordering is Ordering.UNCHECKED
    assert reason is OrderingReason.REGISTERED_PLAN_UNPINNED
    assert "nothing pins" in detail
