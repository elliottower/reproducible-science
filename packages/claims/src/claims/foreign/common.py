"""What the readers of other checkers' results share: one rule for giving a time with no UTC
offset its offset, and one rule for where the records are written.

A time is read as ISO 8601, with `Z` for UTC. One that carries an offset keeps it. One that
carries none was written in a local time nothing in the file names, so it is refused unless the
caller states the offset, `+HH:MM` or `-HH:MM`, and UTC is never assumed. On a command line a
negative offset is written `--offset=-05:30`, since a value that starts with `-` is otherwise
read as an option. The offset applies to
every naive time of one reading, so times on either side of a daylight-saving change are read an
hour apart from what the clock said for one side.

Records go to standard output, or to a file that does not exist yet. A reader never overwrites a
file.
"""

from __future__ import annotations

import datetime
import pathlib
import re

from provenance_core import atomic_write

from claims.exceptions import ReproError

_OFFSET = re.compile(r"(?P<sign>[+-])(?P<hours>\d{2}):(?P<minutes>\d{2})")


#: The help every reader's `--offset` gives.
OFFSET_HELP = (
    "the UTC offset, +HH:MM or -HH:MM, of the local times the file holds without one; write a "
    "negative one --offset=-05:30"
)


class ForeignError(ReproError):
    """Another checker's results could not be read into check records, or written."""


def offset(text: str) -> datetime.timezone:
    """A UTC offset written `+HH:MM` or `-HH:MM`, from `-23:59` to `+23:59`."""
    found = _OFFSET.fullmatch(text)
    if found is None or int(found["hours"]) > 23 or int(found["minutes"]) > 59:
        raise ForeignError(f"{text!r} is not an offset; write it +HH:MM or -HH:MM")
    delta = datetime.timedelta(hours=int(found["hours"]), minutes=int(found["minutes"]))
    return datetime.timezone(-delta if found["sign"] == "-" else delta)


def aware(text: str, given: datetime.timezone | None, what: str) -> datetime.datetime:
    """`text` as a time with an offset: its own, or `given` where it has none. `what` names the
    time in a refusal."""
    try:
        when = datetime.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as e:
        raise ForeignError(f"{what} {text!r} is not an ISO 8601 time") from e
    if when.tzinfo is not None:
        return when
    if given is None:
        raise ForeignError(
            f"{what} {text!r} carries no UTC offset, and a check record's time must; give the "
            "offset it was written in with --offset +HH:MM"
        )
    return when.replace(tzinfo=given)


def write(text: str, output: pathlib.Path | None) -> None:
    """`text` to standard output where `output` is None, and otherwise to that new file."""
    if output is None:
        print(text, end="")
        return
    if output.exists():
        raise ForeignError(f"{output} exists, and a reader never overwrites a file")
    try:
        atomic_write(output, text)
    except OSError as e:
        raise ForeignError(f"{output} could not be written: {e}") from e
