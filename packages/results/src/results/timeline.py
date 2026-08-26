"""Ordering the instants a ledger records.

A claim's disposition follows from three moments: when outcomes were seen, when the run behind
the claim was recorded, and when the plan it rests on was frozen. Deciding which of them came
first is all `precedes` does, and it lived in `cli.py` among the argparse handlers, where the
only way to reach it was to run a command.

The comparison was once made on the ISO strings themselves. Git reports a freeze as `%cI`,
which carries the committer's local offset, while the ledger writes UTC, so comparing the text
compares the offsets rather than the instants. That passed on a machine four hours behind UTC,
where the local hour is numerically smaller, and failed on a UTC runner. Two timestamps naming
the same instant in different offsets are the case to test, and testing it through a
subprocess that runs a whole command is not how anyone would find the next one.
"""

from __future__ import annotations

import datetime
import pathlib

from provenance_core.gitref import try_run


def first_outcomes_seen(events: list[dict]) -> str | None:
    """Timestamp of the earliest 'outcomes seen' access event, if there is one."""
    stamps = [
        e["timestamp"]
        for e in events
        if e.get("event") == "access" and e.get("level") == "outcomes seen"
    ]
    return min(stamps) if stamps else None


def first_run_timestamp(events: list[dict], run_id: str) -> str | None:
    """Timestamp of the *latest* run recorded under this id.

    It once returned the earliest, so a second run recorded under an id that already existed
    inherited the first one's timestamp: a run performed after the outcomes were seen was
    ordered by when the id was first used, and the confirmatory guard passed. Duplicate ids
    are refused now, and this takes the latest regardless -- what a claim rests on is the most
    recent run under the id.
    """
    stamps = [
        e["timestamp"] for e in events if e.get("event") == "run" and e.get("run_id") == run_id
    ]
    return max(stamps) if stamps else None


def precedes(earlier: str, later: str) -> bool:
    """Whether one ISO timestamp names an instant before another.

    Both sides must be parsed. The freeze time comes from git as `%cI`, which carries the
    committer's local offset, and the ledger writes UTC; comparing them as strings compares
    the offsets rather than the instants. That comparison passed on a machine four hours
    behind UTC, where the local hour is numerically smaller, and failed on a UTC runner where
    the two agree to the second and the ordering fell to whether `+` or `Z` sorts before `.`.

    An unparseable timestamp is not treated as earlier. A freeze that cannot be placed in time
    cannot protect a claim, and guessing here would grant the protection on a malformed value.
    """
    try:
        first = datetime.datetime.fromisoformat(earlier)
        second = datetime.datetime.fromisoformat(later)
    except (TypeError, ValueError):
        return False
    if (first.tzinfo is None) != (second.tzinfo is None):
        # One naive and one aware cannot be ordered without inventing a zone for the naive one.
        return False
    return first < second


def freeze_timestamp(root: pathlib.Path, ref: str) -> str | None:
    """When the plan named by `ref` was fixed, as an ISO timestamp.

    A freeze reference is a git commit containing the frozen plan. Its commit
    date is the moment the plan stopped being editable, which is the fact that
    matters: a plan already committed cannot be reached by anything a context
    reads afterwards.
    """
    # Through `gitref` rather than a `git -C` of its own, because `-C` is a directory change
    # and `GIT_DIR` outranks it. Read from inside a git hook, a direct call answers with the
    # invoking repository's HEAD, so a freeze in one repository is timed by a commit in another.
    return try_run("show", "-s", "--format=%cI", ref, cwd=root, timeout=15)
