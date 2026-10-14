"""What `prereg check` decides about a plan frozen in place, read from its text alone.

A plan frozen in place carries its digest, its status lines and its log inside the file, and
`prereg log` rewrites the file on every entry: it appends a line to the log and recounts the
`**Log:**` line in the header. `check` decided between unchanged, changed, uncovered and an
altered log inside the command that printed the verdict, so a tool that hashes the file -- the
`results` ledger seals plans by their bytes -- had no way to ask whether two versions of a plan
differ only by what `prereg log` writes. Both questions are answered here, by one rule.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from prereg.log import log_lines, log_problems
from prereg.plan import MARK, plan_of, sha256_of, unhashed_content

UNCHANGED = "unchanged"
CHANGED = "changed"
UNCOVERED = "uncovered"
LOG_ALTERED = "log altered"
NOT_FROZEN = "not frozen"

#: The digest a freeze wrote into the plan.
FROZEN_DIGEST = re.compile(r"\*\*Plan sha256:\*\* `([0-9a-f]{64})`")

#: The whole line `set_log_anchor` writes and rewrites. `prereg log` inserts it beneath the plan
#: digest where a plan frozen before the log was chained has none, so the line goes with it.
LOG_ANCHOR_LINE = re.compile(r"^\*\*Log:\*\* \d+ entries, head `[0-9a-f]{8}`\n", re.M)


@dataclass(frozen=True)
class InPlace:
    """One reading of a plan frozen in place.

    `frozen` is the digest the freeze wrote, empty where there is none; `now` is the digest of
    the plan as it reads now, empty where the plan is not frozen; `problems` says what an
    uncovered plan hides or how its log was altered.
    """

    state: str
    frozen: str = ""
    now: str = ""
    problems: tuple[str, ...] = ()


def in_place(text: str) -> InPlace:
    """What `prereg check` finds for a plan frozen in place whose text is `text`.

    The order is the order `check` reports in: a plan edited after freezing is changed whatever
    else is wrong with it, then content the hash skips, then the log.
    """
    m = FROZEN_DIGEST.search(text)
    if not m:
        return InPlace(NOT_FROZEN)
    now = sha256_of(plan_of(text))
    if now != m.group(1):
        return InPlace(CHANGED, m.group(1), now)
    if hidden := unhashed_content(text):
        return InPlace(UNCOVERED, m.group(1), now, tuple(hidden))
    if log := log_problems(text):
        return InPlace(LOG_ALTERED, m.group(1), now, tuple(log))
    return InPlace(UNCHANGED, m.group(1), now)


def _outside_log(text: str) -> str:
    """The text with the log's entries and its `**Log:**` line taken out, the fence kept.

    The entries are what `log_lines` reads: everything between the first fence after the log
    marker and the last.
    """
    head, mark, tail = text.partition(MARK)
    before, fence, inside = tail.partition("```")
    _, closing, after = inside.rpartition("```")
    return LOG_ANCHOR_LINE.sub("", head) + mark + before + fence + closing + after


def entries_appended(earlier: str, now: str) -> int:
    """How many log entries `now` holds beyond `earlier`, where that is all that separates them.

    Nonzero only where `prereg check` finds `now` unchanged, the entries of `earlier` begin the
    log of `now`, and the two texts are otherwise the same but for the `**Log:**` line, which
    `prereg log` rewrites on every entry. Any other difference, above the log or inside it,
    answers 0.
    """
    if in_place(now).state != UNCHANGED:
        return 0
    before, after = log_lines(earlier), log_lines(now)
    if len(after) <= len(before) or after[: len(before)] != before:
        return 0
    if _outside_log(earlier) != _outside_log(now):
        return 0
    return len(after) - len(before)
