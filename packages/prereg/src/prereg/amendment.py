"""An amendment: a change to a frozen plan, written as a file of its own and frozen like one.

A frozen plan never changes, so a new hypothesis, criterion or experiment is a separate document
that names what it amends by digest. Four fields are required, and `freeze` refuses an amendment
missing one: the parent, the sections replaced or added, the reason, and what had been seen.

What had been seen is not left to memory where a record exists. A results ledger at or above the
plan (`.results/ledger.jsonl`) is read as data, and no freeze, of a plan or of an amendment,
records a lower access level than the ledger shows.
"""

from __future__ import annotations

import dataclasses
import json
import os
import pathlib
import re

from prereg.log import ACCESS
from prereg.record import RECORDS

LEDGER = pathlib.Path(".results") / "ledger.jsonl"

#: The access levels `results access` records, and the level each amounts to here. The ledger
#: grades what was looked at and `prereg` grades what a note was written after, so the two middle
#: levels, which both mean data was examined and no outcome was, map to one.
LEDGER_ACCESS = {
    "nothing seen": "nothing run",
    "metadata only": "no results seen",
    "structure seen": "no results seen",
    "outcomes seen": "results seen",
}

SECTIONS = "Sections replaced or added"
REASON = "Reason"
SEEN = "What had been seen"

HINTS = {
    SECTIONS: "_Name each section of the amended document this replaces, and each it adds._",
    REASON: "_Why the plan changes._",
    SEEN: (
        "_One of: " + ", ".join(ACCESS) + ". Then say what had been run and read when this "
        "was written._"
    ),
}

AMENDS = re.compile(r"^\*\*Amends:\*\* `([0-9a-f]{64})`", re.M)
LEVEL = re.compile(r"^\*\*Access level:\*\*[ \t]*(.*)$", re.M)
NAME = re.compile(r".+_AMENDMENT_(\d+)\.md")


class AmendmentError(Exception):
    """An amendment is missing a required field, or claims less than the ledger records."""


class LedgerError(Exception):
    """A results ledger exists and cannot be read."""


@dataclasses.dataclass(frozen=True)
class Ledger:
    """What a results ledger says had been seen."""

    path: pathlib.Path
    level: str | None
    """The highest access level recorded, in the ledger's own words. None where it records none."""
    runs: int

    @property
    def floor(self) -> str | None:
        """The lowest access level a freeze can record, in this tool's words.

        A recorded run has finished and left outputs, so one or more of them puts the floor at
        `results not opened` whatever was said about access.
        """
        levels = [LEDGER_ACCESS[self.level]] if self.level else []
        if self.runs:
            levels.append("results not opened")
        return max(levels, key=ACCESS.index, default=None)

    @property
    def summary(self) -> str:
        """What the ledger records, as one phrase."""
        recorded = f"`{self.level}`" if self.level else "none"
        runs = f"{self.runs} run{'' if self.runs == 1 else 's'}"
        return f"highest access level recorded {recorded}, {runs} recorded"

    def refuses(self, access: str) -> str | None:
        """Why `access` cannot be recorded: it is lower than this ledger shows. None if it can."""
        if self.floor is None or ACCESS.index(access) >= ACCESS.index(self.floor):
            return None
        return (
            f"it says `{access}`, and the results ledger {self.path} shows more: "
            f"{self.summary}, which is `{self.floor}` here. The level can be raised and "
            f"cannot be lower than the ledger shows"
        )


def read_ledger(start: pathlib.Path) -> Ledger | None:
    """The results ledger at `start` or the nearest one above, or None where there is none.

    The highest level is taken, not the last: an `outcomes seen` followed by a `metadata only`
    for some other dataset has not unseen the outcomes.
    """
    path = next((d / LEDGER for d in [start, *start.parents] if (d / LEDGER).is_file()), None)
    if path is None:
        return None
    try:
        events = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        levels = [e["level"] for e in events if e.get("event") == "access"]
        level = max(levels, key=list(LEDGER_ACCESS).index, default=None)
    except (ValueError, KeyError, AttributeError) as e:
        raise LedgerError(f"{path} cannot be read as a results ledger: {e}") from e
    return Ledger(path, level, sum(e.get("event") == "run" for e in events))


def path_for(plan: pathlib.Path, n: int) -> pathlib.Path:
    """`PREREG_AMENDMENT_1.md` for `PREREG.md`."""
    return plan.with_name(f"{plan.stem}_AMENDMENT_{n}.md")


def number(path: pathlib.Path) -> int:
    """The N of `PREREG_AMENDMENT_N.md`."""
    return int(path.name.removesuffix(".md").rpartition("_")[2])


def beside(plan: pathlib.Path) -> list[pathlib.Path]:
    """Every amendment to `plan` that is on disk or has a freeze record, in number order.

    A record with no file is included: an amendment deleted after its freeze is a finding.
    """
    names = {p.name for p in plan.parent.glob(f"{plan.stem}_AMENDMENT_*.md")}
    names |= {p.name.removesuffix(".json") for p in (plan.parent / RECORDS).glob("*.md.json")}
    found = [plan.with_name(name) for name in names if NAME.fullmatch(name)]
    return sorted((p for p in found if p.name.startswith(f"{plan.stem}_")), key=number)


def render(n: int, title: str, parent: pathlib.Path, digest: str, ledger: Ledger | None) -> str:
    if ledger is None:
        seen = f"**Access level:**\n\n{HINTS[SEEN]}"
    else:
        # `relative_to` refuses a path that is not below the other, and the ledger usually sits
        # above the plan.
        where = pathlib.Path(os.path.relpath(ledger.path, parent.parent)).as_posix()
        seen = (
            f"**Access level:**{' ' + ledger.floor if ledger.floor else ''}\n\n"
            f"Results ledger `{where}`: {ledger.summary}."
        )
    return (
        f"# Amendment {n} to {title}\n\n"
        f"**Amends:** `{digest}` ({parent.name})\n\n"
        f"## {SECTIONS}\n\n{HINTS[SECTIONS]}\n\n"
        f"## {REASON}\n\n{HINTS[REASON]}\n\n"
        f"## {SEEN}\n\n{seen}\n"
    )


def _sections(text: str) -> dict[str, str]:
    found: dict[str, list[str]] = {}
    current: list[str] | None = None
    for line in text.splitlines():
        if line.startswith("## "):
            current = found.setdefault(line[3:].strip(), [])
        elif current is not None:
            current.append(line)
    return {heading: "\n".join(lines).strip() for heading, lines in found.items()}


def read(text: str, ledger: Ledger | None) -> tuple[str, str]:
    """An amendment's parent digest and access level, or `AmendmentError` naming what is missing.

    The access level is refused where it is lower than the ledger records.
    """
    missing = []
    parent = AMENDS.search(text)
    if parent is None:
        missing.append("`**Amends:**` does not name its parent by a sha256 digest")
    sections = _sections(text)
    for heading in (SECTIONS, REASON):
        if sections.get(heading, "") in ("", HINTS[heading]):
            missing.append(f"`## {heading}` is not filled in")
    level = LEVEL.search(sections.get(SEEN, ""))
    access = level.group(1).strip() if level else ""
    if access not in ACCESS:
        missing.append(
            f"`**Access level:**` under `## {SEEN}` is {access!r}, not one of: {', '.join(ACCESS)}"
        )
    elif ledger and (refusal := ledger.refuses(access)):
        missing.append(refusal)
    if missing or parent is None:
        raise AmendmentError("\n".join(f"  - {m}" for m in missing))
    return parent.group(1), access
