"""The append-only log beneath a frozen plan.

The plan's hash deliberately stops at the log, because the log is written after freezing and a
hash covering it would cover its own value. That exemption left the file's only record of what
changed after registration freely deletable, while `check` still reported the plan unchanged.

Each entry therefore carries the chain value of the one before it, and a marker line beside the
plan hash records how many entries there are and which is last. Chaining alone cannot see an
entry removed from the end -- the ones that remain still follow each other -- which is what the
anchor is for.
"""

from __future__ import annotations

import pathlib
import re

from provenance_core import atomic_write, exclusive_lock

from prereg.plan import MARK, sha256_of

ACCESS = ["nothing run", "no results seen", "results not opened", "results seen"]

#: What each level means, kept beside the list so the two cannot drift. The middle pair is the one
#: that gets guessed at, and the difference was stated only in one README example: `no results
#: seen` is before anything has produced an output, `results not opened` is after a run finished
#: and before anyone read it.
ACCESS_MEANING = {
    "nothing run": "no computation has happened for this plan",
    "no results seen": "code has run and this plan has no outputs yet",
    "results not opened": "the run finished and its outputs are unread",
    "results seen": "the outputs have been looked at",
}

#: One sentence per level, for `--help` and for the message a missing `--access` prints.
ACCESS_HELP = (
    "what had been seen when this entry was written -- "
    + "; ".join(f"{level!r}: {why}" for level, why in ACCESS_MEANING.items())
    + ". An entry logged before results is an amendment, one logged after is a deviation."
)


LOG_MARK = "\u00b7"  # separates the entry from its chain value


def log_lines(text: str) -> list[str]:
    """The log entries, in order, without the fence."""
    _, _, tail = text.partition(MARK)
    inside = tail.partition("```")[2].rpartition("```")[0]
    return [ln.rstrip() for ln in inside.splitlines() if ln.strip()]


def chain_value(previous: str, entry: str) -> str:
    """Each entry's link. Short, because it sits in a file people read."""
    return sha256_of(f"{previous}\x00{entry.strip()}")[:8]


LOG_ANCHOR = re.compile(r"^\*\*Log:\*\* (\d+) entries, head `([0-9a-f]{8})`", re.M)


def log_head(text: str) -> tuple[int, str]:
    """Number of entries and the chain value of the last, for the anchor line."""
    previous, count = "", 0
    for line in log_lines(text):
        entry, _, recorded = line.rpartition(LOG_MARK)
        previous = recorded.strip() if entry else chain_value(previous, line)
        count += 1
    return count, previous


def set_log_anchor(text: str) -> str:
    """Record the log's length and head beside the plan hash.

    Chaining alone cannot see an entry removed from the *end*: the entries that remain still
    follow one another. The anchor is the witness to the length, exactly as the ledger's is,
    and it sits on a marker line the plan hash skips, so recording it cannot change the hash.
    """
    count, head = log_head(text)
    line = f"**Log:** {count} entries, head `{head or '00000000'}`"
    if LOG_ANCHOR.search(text):
        return LOG_ANCHOR.sub(line.replace("\\", "\\\\"), text, count=1)
    marker = re.search(r"^\*\*Plan sha256:\*\* .*$", text, re.M)
    if marker:
        return text[: marker.end()] + "\n" + line + text[marker.end() :]
    return text


def log_problems(text: str) -> list[str]:
    """Where the log has been edited, reordered or had an entry removed.

    The plan's hash deliberately stops at the log, since the log is written after freezing and
    including it would make the hash cover itself. That left the record of deviations -- the
    file's only account of what changed after the plan was fixed -- freely deletable with any
    editor, while `check` still reported the plan unchanged. Chaining the entries makes a
    removal visible without bringing them under the plan hash.
    """
    problems: list[str] = []
    previous = ""
    for i, line in enumerate(log_lines(text), start=1):
        entry, _, recorded = line.rpartition(LOG_MARK)
        if not entry:
            # Written before the log was chained, or by hand. Fold it in rather than report
            # it: the chain protects every entry from the first chained one onward, and
            # calling a plain line tampering would flag every plan written under the old
            # format.
            previous = chain_value(previous, line)
            continue
        expected = chain_value(previous, entry)
        if recorded.strip() != expected:
            problems.append(
                f"log entry {i} does not follow the one before it: an entry has been "
                f"edited, reordered or removed"
            )
            return problems
        previous = expected

    anchor = LOG_ANCHOR.search(text)
    if anchor:
        count, head = log_head(text)
        if int(anchor.group(1)) != count:
            problems.append(
                f"the log records {anchor.group(1)} entries and holds {count}: "
                f"an entry has been removed from the end"
            )
        elif anchor.group(2) != (head or "00000000"):
            problems.append("the log's last entry is not the one recorded")
    return problems


def append(path: pathlib.Path, date: str, event: str, access: str) -> None:
    """Add one entry to the plan's log, chained to the entry before it.

    The whole file is rewritten, so two callers that read the same text each write a file holding
    only their own entry and the second erases the first. A lost deviation is worse than a
    detected one: the chain covers the entries that remain, so the file that survives verifies
    cleanly and reports nothing missing. The lock covers the read as well, since reading early is
    what makes the second write wrong.
    """
    with exclusive_lock(path):
        _append_locked(path, date, event, access)


def _append_locked(path: pathlib.Path, date: str, event: str, access: str) -> None:
    """The append itself. Assumes the caller holds the lock for `path`."""
    text = path.read_text()
    if MARK not in text:
        text += MARK.rstrip("\n") + "\n\n```\n```\n"
    head, _, tail = text.partition(MARK)
    # Two spaces, not just padding. `{event:<36}` emits nothing extra once the note passes 36
    # characters, and the access level then runs into the note — losing the boundary of the one
    # field that separates an amendment from a deviation.
    entry = f"{date}  {event:<36}  {access}"
    previous = ""
    for existing in log_lines(text):
        entry_text, _, recorded = existing.rpartition(LOG_MARK)
        # An entry written before the log was chained carries no value; fold it in so the
        # chain still covers it rather than restarting from nothing.
        previous = recorded.strip() if entry_text else chain_value(previous, existing)
    line = f"{entry}  {LOG_MARK}{chain_value(previous, entry)}"
    if "```" in tail:
        before, fence, after = tail.rpartition("```")
        tail = before.rstrip("\n") + f"\n{line}\n" + fence + after
    else:
        tail = tail.rstrip("\n") + f"\n{line}\n"
    # Atomically: this file is the frozen registration, and a truncating write that dies partway
    # through leaves the plan itself half on disk.
    atomic_write(path, set_log_anchor(head + MARK + tail))
