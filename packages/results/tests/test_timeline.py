"""The instants a ledger records, and the order they are read in."""

from __future__ import annotations

import datetime
import random
import subprocess

from provenance_core.gitref import clean_env
from results.timeline import (
    first_outcomes_seen,
    first_run_timestamp,
    freeze_timestamp,
    precedes,
)

UTC = datetime.UTC


def stamp(text):
    return {"timestamp": text}


# -- which instant came first ----------------------------------------------------------------


def test_a_freeze_precedes_an_exposure_it_predates_in_any_timezone():
    """The freeze comes from git in local time and the ledger writes UTC.

    Compared as strings these ordered correctly only where the local offset happened to make
    the hour smaller. Every pair below names the same ordering of instants and differs only
    in how the offset is written.
    """
    exposure = "2026-08-25T17:09:55.123456+00:00"

    assert precedes("2026-08-25T13:09:55-04:00", exposure)
    assert precedes("2026-08-25T17:09:55+00:00", exposure)
    assert precedes("2026-08-25T17:09:55Z", exposure)
    assert precedes("2026-08-25T19:09:55+02:00", exposure)


def test_a_freeze_after_the_exposure_does_not_precede_it():
    exposure = "2026-08-25T17:09:55.123456+00:00"

    assert not precedes("2026-08-25T17:09:56+00:00", exposure)
    assert not precedes("2026-08-25T13:09:56-04:00", exposure)


def test_a_timestamp_that_cannot_be_parsed_never_protects_a_claim():
    """A freeze that cannot be placed in time cannot protect anything.

    Returning True on a malformed value would grant the protection to a claim whose ordering
    was never established, which is the opposite of what the flag is for.
    """
    exposure = "2026-08-25T17:09:55.123456+00:00"

    assert not precedes("not a timestamp", exposure)
    assert not precedes("", exposure)
    assert not precedes("2026-08-25T17:09:55", exposure)


def test_one_instant_written_in_two_offsets_precedes_itself_in_neither_direction():
    # Read as text, the Boston spelling sorts first, so a string comparison reports that the
    # plan was frozen before an exposure that happened at the very same moment.
    utc = "2026-08-25T17:09:55.123456+00:00"
    boston = "2026-08-25T13:09:55.123456-04:00"

    assert not precedes(utc, boston)
    assert not precedes(boston, utc)


def test_two_naive_timestamps_are_ordered_against_each_other():
    assert precedes("2026-08-25T17:09:55", "2026-08-25T17:09:56")
    assert not precedes("2026-08-25T17:09:56", "2026-08-25T17:09:55")


def test_a_naive_timestamp_and_an_aware_one_are_ordered_in_neither_direction():
    aware = "2026-08-25T17:09:55.123456+00:00"
    naive = "2026-08-25T17:09:55.123456"

    assert not precedes(naive, aware)
    assert not precedes(aware, naive)


def test_the_order_is_of_instants_and_not_of_the_text_they_are_written_in():
    """Every pair below is two instants spelled in two arbitrary offsets.

    A comparison made on the strings agrees with the instants only where the offsets happen to
    line up, so this is the shape of the defect rather than any single pair of it: reintroduce
    a text comparison and the disagreements run to the hundreds.
    """
    offsets = [
        datetime.timezone(datetime.timedelta(hours=h, minutes=m))
        for h in range(-12, 15)
        for m in (0, 30)
    ]
    base = datetime.datetime(2026, 8, 25, 17, 9, 55, 123456, tzinfo=UTC)

    def somewhen():
        return base + datetime.timedelta(
            seconds=random.randint(-21_600, 21_600), microseconds=random.randint(0, 999_999)
        )

    disagreements = []
    for _ in range(2000):
        one, two = somewhen(), somewhen()
        written = (one.astimezone(random.choice(offsets)), two.astimezone(random.choice(offsets)))
        if precedes(written[0].isoformat(), written[1].isoformat()) != (one < two):
            disagreements.append((written[0].isoformat(), written[1].isoformat(), one < two))

    assert not disagreements, f"{len(disagreements)} of 2000: {disagreements[:3]}"


# -- what the ledger's own events say -----------------------------------------------------------


def test_the_exposure_is_the_earliest_time_the_outcomes_were_seen():
    events = [
        {"event": "access", "level": "outcomes seen", **stamp("2026-03-01T00:00:00+00:00")},
        {"event": "access", "level": "metadata only", **stamp("2026-01-01T00:00:00+00:00")},
        {"event": "access", "level": "outcomes seen", **stamp("2026-02-01T00:00:00+00:00")},
    ]

    assert first_outcomes_seen(events) == "2026-02-01T00:00:00+00:00"


def test_a_ledger_with_no_exposure_has_no_exposure_time():
    events = [
        {"event": "access", "level": "structure seen", **stamp("2026-01-01T00:00:00+00:00")},
        {"event": "run", "run_id": "r1", **stamp("2026-02-01T00:00:00+00:00")},
    ]

    assert first_outcomes_seen(events) is None


def test_a_run_id_recorded_twice_resolves_to_the_later_of_the_two():
    # Resolving to the earlier one let a run performed after the exposure be ordered by when
    # its id was first used, and the confirmatory guard passed on it.
    events = [
        {"event": "run", "run_id": "r1", **stamp("2026-01-01T00:00:00+00:00")},
        {"event": "run", "run_id": "r1", **stamp("2026-04-01T00:00:00+00:00")},
        {"event": "run", "run_id": "r2", **stamp("2026-05-01T00:00:00+00:00")},
    ]

    assert first_run_timestamp(events, "r1") == "2026-04-01T00:00:00+00:00"


def test_a_run_id_the_ledger_does_not_hold_has_no_time():
    events = [{"event": "run", "run_id": "r1", **stamp("2026-01-01T00:00:00+00:00")}]

    assert first_run_timestamp(events, "ghost") is None


def test_a_claim_event_naming_a_run_id_is_not_itself_a_run():
    events = [
        {"event": "claim", "run_id": "r1", **stamp("2026-06-01T00:00:00+00:00")},
        {"event": "run", "run_id": "r1", **stamp("2026-01-01T00:00:00+00:00")},
    ]

    assert first_run_timestamp(events, "r1") == "2026-01-01T00:00:00+00:00"


# -- resolving a freeze reference through git ------------------------------------------------


def a_repo_committed_at(tmp_path, when):
    """A repository whose one commit carries `when` as its committer date, offset and all."""
    # `clean_env` keeps the date variables and drops the ones that would send these
    # commands at whatever repository invoked the suite.
    env = clean_env(GIT_COMMITTER_DATE=when, GIT_AUTHOR_DATE=when)
    for args in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"]):
        subprocess.run(["git", *args], cwd=tmp_path, capture_output=True, env=env)
    (tmp_path / "plan.md").write_text("H1. the effect is positive.\n")
    subprocess.run(["git", "add", "plan.md"], cwd=tmp_path, capture_output=True, env=env)
    subprocess.run(
        ["git", "commit", "-q", "-m", "freeze the plan"], cwd=tmp_path, capture_output=True, env=env
    )
    (tmp_path / ".results").mkdir()
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, capture_output=True, text=True, env=env
    ).stdout.strip()


def test_a_freeze_east_of_utc_is_ordered_against_the_ledger_by_its_instant(tmp_path):
    """The whole seam, through git: `%cI` keeps the committer's offset, the ledger writes UTC.

    19:09:55+02:00 is 17:09:55Z. Read as text it sorts after both comparisons below, so a
    string comparison calls the freeze late and drops the protection the claim was recorded
    with.
    """
    sha = a_repo_committed_at(tmp_path, "2026-08-25T19:09:55+02:00")
    frozen = freeze_timestamp(tmp_path / ".results", sha)

    assert frozen is not None
    assert precedes(frozen, "2026-08-25T17:09:56+00:00")
    assert not precedes(frozen, "2026-08-25T17:09:54+00:00")


def test_the_freeze_time_is_read_from_a_subdirectory_of_the_repository(tmp_path):
    # `freeze_timestamp` is handed `.results/`, never the repository root.
    sha = a_repo_committed_at(tmp_path, "2026-08-25T19:09:55+02:00")

    assert freeze_timestamp(tmp_path / ".results", sha) == "2026-08-25T19:09:55+02:00"


def test_a_reference_that_names_no_commit_has_no_freeze_time(tmp_path):
    a_repo_committed_at(tmp_path, "2026-08-25T19:09:55+02:00")

    assert freeze_timestamp(tmp_path / ".results", "deadbeef") is None


def test_a_directory_outside_any_repository_has_no_freeze_time(tmp_path):
    (tmp_path / ".results").mkdir()

    assert freeze_timestamp(tmp_path / ".results", "HEAD") is None
