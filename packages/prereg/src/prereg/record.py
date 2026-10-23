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
    #: Where the freeze sits in the results ledger at or above the file, where there is one:
    #: `path` from the file's directory, `events` it held, `head` the digest of the last of them,
    #: and `declared_late`, each run `results label` declared as holding no outcome after it was
    #: recorded, which lowered the access floor this freeze was held to. None where no ledger.
    ledger: dict | None = None
    #: Each companion file frozen with the plan, by its path from the file's directory, and its
    #: digest. None where the freeze named none.
    companions: dict[str, str] | None = None
    #: True where `--force` froze bytes that differed from the commit named, so the file at that
    #: commit is not expected to hold them.
    uncommitted: bool = False

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


#: Fields written only where they hold something, so a record that uses none of them has the
#: shape every earlier version wrote and read.
OPTIONAL = ("ledger", "companions", "uncommitted")


def write(path: pathlib.Path, record: Record) -> pathlib.Path:
    where = record_path(path)
    where.parent.mkdir(exist_ok=True)
    held = {
        name: value
        for name, value in dataclasses.asdict(record).items()
        if name not in OPTIONAL or value
    }
    atomic_write(where, json.dumps(held, indent=2) + "\n")
    return where
