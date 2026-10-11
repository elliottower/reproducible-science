"""The record of a freeze, kept outside the file it freezes.

A frozen file never changes by one byte, so the freeze cannot be written into it: the digest is
of the whole file, and writing the digest there would change the bytes just hashed. The record
sits in `.prereg/` beside the file, one JSON document per frozen file, named after it:

    PREREG.md
    PREREG_AMENDMENT_1.md
    .prereg/PREREG.md.json
    .prereg/PREREG_AMENDMENT_1.md.json

A record is written once. Nothing here rewrites one, and `freeze` refuses a file that has one.
"""

from __future__ import annotations

import dataclasses
import datetime
import json
import pathlib

from provenance_core import atomic_write

#: The directory holding the records, beside the files they describe.
RECORDS = ".prereg"


class RecordError(Exception):
    """A freeze record exists and cannot be read as one."""

    def __init__(self, path: pathlib.Path, detail: str) -> None:
        self.path = path
        super().__init__(f"{path} is not a freeze record: {detail}")


@dataclasses.dataclass(frozen=True)
class Record:
    """What a freeze fixed: the file's digest, the commit, the time and what had been seen."""

    file: str
    sha256: str
    commit: str
    frozen_at: str
    access: str
    #: An amendment's parent, by digest. None for a plan.
    parent: str | None = None

    @property
    def date(self) -> str:
        return self.frozen_at[:10]


def now() -> str:
    """The current instant in UTC, to the second."""
    return datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds")


def record_path(path: pathlib.Path) -> pathlib.Path:
    return path.parent / RECORDS / f"{path.name}.json"


def read(path: pathlib.Path) -> Record | None:
    """The freeze record of `path`, or None where it was never frozen this way."""
    where = record_path(path)
    if not where.is_file():
        return None
    try:
        return Record(**json.loads(where.read_text()))
    except (ValueError, TypeError) as e:
        raise RecordError(where, str(e)) from e


def write(path: pathlib.Path, record: Record) -> pathlib.Path:
    where = record_path(path)
    where.parent.mkdir(exist_ok=True)
    atomic_write(where, json.dumps(dataclasses.asdict(record), indent=2) + "\n")
    return where
