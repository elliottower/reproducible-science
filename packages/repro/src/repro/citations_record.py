"""The record of a citations check made on the author's machine, which a CI job can read.

A clone does not hold the sources a claims directory pins: a cited paper is usually not the
author's to redistribute, so its file is gitignored. A CI job that ran `citations verify`
would find every quotation `unchecked`. What it can do is read what a run on the author's
machine found, and check that the run was made over the claims files the repository holds now.

`write` runs `citations verify` as `repro ci citations` runs it and writes, to
`.repro/citations-verified.json`, the counts it gave, the sha256 of every claims file it read
and the source digest each pins, the version of `citations` and the time. `compare` reads the
record and says whether the claims files are still the ones it covers. A claims file pins its
source by digest, so a source replaced under a pin changes the claims file too.

The record is written by `repro`, not by `citations`: it exists for the badge, and `citations
verify` writes nothing a run did not ask for.
"""

from __future__ import annotations

import datetime
import enum
import json
import pathlib

from citations import __version__ as citations_version
from citations.exceptions import ClaimFileError
from citations.models import load_claim_file
from provenance_core import atomic_write, sha256_of_file
from pydantic import BaseModel, ConfigDict, ValidationError

from repro import audit, ci
from repro.delegate import BY_NAME
from repro.exceptions import ReproError

#: Where the record is kept, from the top of the project. Committed, beside the record of
#: re-runs.
RECORD = pathlib.Path(".repro") / "citations-verified.json"
VERSION = "repro.citations-verified/1"


class NoClaimsError(ReproError):
    """There is no claims directory to check, so there is nothing to record."""

    def __init__(self, root: pathlib.Path) -> None:
        self.root = root
        super().__init__(f"{root}: {ci.NO_RECORD['citations']}; nothing was written.")


class ClaimsFile(BaseModel):
    """One claims file the check read: its bytes, and the digest of the source it pins."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    sha256: str
    source: str = ""
    """The source's pinned sha256, or empty where the file pins none or could not be read."""


class CitationsRecord(BaseModel):
    """What `citations verify` found on the machine it ran on, and what it read."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    record: str = VERSION
    written_at: str
    """UTC, to the second."""
    citations: str
    """The version of `citations` that checked."""
    command: str
    outcome: str
    """The word `repro ci citations` gives the run."""
    quotes: int
    counts: dict[str, int]
    """The counts `citations verify --json` gives, by result."""
    claims: dict[str, ClaimsFile]
    """Every claims file read, by its path from the top of the project."""

    @property
    def run(self) -> ci.ToolRun:
        """The run as `repro.badges.citations_badge` reads one."""
        return ci.ToolRun(
            check="citations",
            outcome=self.outcome,
            account={"quotes": self.quotes, "counts": self.counts},
        )


class Standing(enum.StrEnum):
    """How the record stands against the claims files the project holds now."""

    CURRENT = "current"
    """Every claims file is the one the record covers, and no file was added or removed."""
    STALE = "stale"
    """A claims file differs from the one recorded, or one was added or removed."""
    ABSENT = "absent"
    """No record, or one that cannot be read."""


class Compared(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    standing: Standing
    record: CitationsRecord | None = None
    differing: tuple[str, ...] = ()
    """The claims files added, removed or changed since the record, by path."""


def claims_files(root: pathlib.Path) -> dict[str, ClaimsFile]:
    """Every claims file `citations verify --claims` reads in the project's claims directory,
    which is each `*.yaml` directly in it, by its path from `root`."""
    found = BY_NAME["citations"].data_dir(root)
    if found is None:
        return {}
    files = {}
    for path in sorted(found.glob("*.yaml")):
        try:
            source = load_claim_file(path).source.sha256 or ""
        except ClaimFileError:
            # `citations verify` skips it and says so; its bytes are still covered.
            source = ""
        files[path.relative_to(root).as_posix()] = ClaimsFile(
            sha256=sha256_of_file(path), source=source
        )
    return files


def write(root: pathlib.Path) -> CitationsRecord:
    """Check the project's quotations here and write the record of what was found."""
    run = ci.tool("citations", root)
    if run.outcome == audit.NOTHING:
        raise NoClaimsError(root)
    made = CitationsRecord(
        written_at=datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
        citations=citations_version,
        command=" ".join(run.command),
        outcome=run.outcome,
        quotes=run.account.get("quotes", 0),
        counts=run.account.get("counts", {}),
        claims=claims_files(root),
    )
    (root / RECORD).parent.mkdir(parents=True, exist_ok=True)
    atomic_write(root / RECORD, json.dumps(made.model_dump(), indent=2, sort_keys=True) + "\n")
    return made


def compare(root: pathlib.Path) -> Compared:
    """The record against the claims files the project holds now."""
    path = root / RECORD
    try:
        made = CitationsRecord.model_validate_json(path.read_bytes())
    except (OSError, ValidationError):
        return Compared(standing=Standing.ABSENT)
    now = claims_files(root)
    differing = tuple(
        sorted(
            name
            for name in now.keys() | made.claims.keys()
            if now.get(name) != made.claims.get(name)
        )
    )
    return Compared(
        standing=Standing.STALE if differing else Standing.CURRENT,
        record=made,
        differing=differing,
    )


__all__ = [
    "RECORD",
    "CitationsRecord",
    "ClaimsFile",
    "Compared",
    "Standing",
    "claims_files",
    "compare",
    "write",
]
