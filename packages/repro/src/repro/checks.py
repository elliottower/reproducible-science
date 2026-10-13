"""A record of what each assertion said when it was checked.

`repro verify` reports on a manifest as it is now. After a check does not verify, the
`reported` value, the address or the claim's text can be edited until it does, and the report
of the last run shows none of that. Every `repro verify` therefore appends, for each assertion
whose declaration, artifact digest or outcome differs from the last entry recorded for it, what
it found.

**Two records, one format.** The local record is `repro/checks.jsonl` in the repository's git
directory, the one `git rev-parse --absolute-git-dir` names, so a linked worktree keeps its
own. It is written by every check, belongs to this clone and is never committed, as git's
reflog is, and the working tree is not touched. The tracked record is `.repro/checks.jsonl` in
the working tree, written where `repro verify --record` asks, for a project whose history
should travel. The tracked record is a copy of the local one, line for line, up to the last
time it was asked for; a clone that finds a tracked record longer than its local one takes
the entries it lacks. Outside a git repository there is no local record, and `--record`
appends to the tracked one directly.

**A chain.** Each entry carries its position, `seq`, and the SHA-256 of the entry before it as
stored, `prev_hash`, and a head file beside the record, `ledger.head`, holds the number of
entries and the hash of the last. These are the `results` ledger's fields and its writer:
`results.ledger.append_event` appends under a lock held across reading the last entry and
writing the next, so two checks running at once write two entries in a row and not two
claiming one position, and it refuses to append to a chain that does not verify.

Reading is done here and not by `results.ledger.verify`, which takes a lock by creating a file
beside the record: `repro verify` and `repro why` must leave the working tree as it is.

**What the chain shows, and what it does not.** An entry edited, removed from the middle or
moved is found, with its number, and the entries from there on are shown as the record holds
them and marked unverifiable. Entries cut from the end are found while the head file is as it
was. A record and its head file cut back together, or deleted together and grown again, look
like a shorter or a new record: nothing inside the two files can show it. The local record has
no witness outside its directory. The tracked record's head file is committed with it, so the
repository's history holds every earlier head, and that is what makes a truncation visible to
someone who has the history. Nothing here is signed or timestamped by anyone else, and whoever
can write both files and rewrite the history can rewrite the record.
"""

from __future__ import annotations

import collections
import json
import os
import pathlib
from typing import Literal

from provenance_core import ZERO, exclusive_lock, sha256_of_text, try_run
from pydantic import ValidationError
from results.ledger import ChainStatus, append_event, read_anchor, write_anchor

from repro.exceptions import ReproError
from repro.models import (
    CheckedAssertion,
    CheckRecord,
    Claim,
    CorrespondenceEvidence,
    Decision,
    Evidence,
    Locator,
    Manifest,
    QuoteEvidence,
    RecordState,
    TableCellEvidence,
    TreeLocator,
    VerificationReport,
)

#: The tracked record, beside the manifest.
RECORD = pathlib.Path(".repro") / "checks.jsonl"

#: The local record, inside the git directory.
LOCAL = pathlib.Path("repro") / "checks.jsonl"

#: Why no local record is kept, where none is.
NOT_A_REPOSITORY = "not in a git repository"

#: Which assertion an entry is about: the claim's id, the kind, the name and the position.
Identity = tuple[str, str, str, int]

#: Which of the two records.
Kind = Literal["local", "tracked"]

#: The states of a chain whose every entry follows from the one before it.
_SOUND = (ChainStatus.INTACT, ChainStatus.EXTENDED, ChainStatus.NO_ANCHOR)


class RecordDivergedError(ReproError):
    """The tracked record is not the beginning of the local one, so it cannot be brought up
    to it by appending."""

    def __init__(self, path: pathlib.Path, entry: int) -> None:
        self.path = path
        self.entry = entry
        super().__init__(f"{path}: diverges from the local record at entry {entry}")


class RecordBrokenError(ReproError):
    """A record's chain does not verify, so nothing is appended to it."""

    def __init__(self, state: RecordState) -> None:
        self.state = state
        super().__init__(
            f"{state.path}: refusing to append to a chain reported as {state.status}: "
            f"{'; '.join(state.problems)}"
        )


def address(locator: Locator) -> str:
    """A locator as a reader would write it: a JSON Pointer bare, any other by its fields."""
    if isinstance(locator, TreeLocator):
        return locator.pointer
    fields = locator.model_dump(mode="json", exclude={"contract", "kind"}, exclude_defaults=True)
    return ", ".join(
        f"{key} {json.dumps(value, ensure_ascii=False)}" for key, value in fields.items()
    )


def _address(evidence: Evidence) -> str:
    if isinstance(evidence, QuoteEvidence):
        return ""
    if isinstance(evidence, CorrespondenceEvidence):
        return "; ".join(
            f"{side.name}: {side.artifact} at {address(side.locator)}" for side in evidence.sides
        )
    if isinstance(evidence, TableCellEvidence) and not evidence.addresses_one_row:
        # Neither `row` nor `where`, or both: there is no one address to record.
        return ""
    return address(evidence.locator)


def checked(
    claim: Claim, decisions: tuple[Decision, ...], at: str = ""
) -> tuple[CheckedAssertion, ...]:
    """Each assertion of one claim as a check found it, in the order declared."""
    seen: collections.Counter[tuple[str, str]] = collections.Counter()
    found = []
    for evidence, decision in zip(claim.evidence, decisions, strict=True):
        name = getattr(evidence, "name", "")
        found.append(
            CheckedAssertion(
                claim_id=claim.id,
                kind=evidence.kind,
                name=name,
                position=seen[evidence.kind, name],
                claim_digest=claim.digest.value,
                printed=evidence.text
                if isinstance(evidence, QuoteEvidence)
                else getattr(evidence, "reported", None),
                address=_address(evidence),
                digests={side.artifact_id: side.artifact_digest for side in decision.sides}
                or dict.fromkeys(evidence.artifacts, decision.artifact_digest),
                outcome=decision.outcome,
                reason=decision.reason,
                checked_at=at,
            )
        )
        seen[evidence.kind, name] += 1
    return tuple(found)


def git_dir(root: pathlib.Path) -> pathlib.Path | None:
    """The git directory of the repository `root` is in, as git resolves it: a linked
    worktree's own, and a submodule's. None outside a repository."""
    found = try_run("rev-parse", "--absolute-git-dir", cwd=root)
    return pathlib.Path(found) if found else None


def _raw(path: pathlib.Path) -> list[str]:
    """A record's entries as stored, one per line."""
    if not path.is_file():
        return []
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _parsed(raw: str) -> CheckRecord | None:
    try:
        return CheckRecord.model_validate_json(raw)
    except ValidationError:
        return None


def _chain(path: pathlib.Path, kind: Kind, lines: list[str]) -> RecordState:
    """Whether each entry follows from the one before it, and whether the head file agrees.

    The status is the first fault's, as in the `results` ledger: a chain edited and then cut
    is edited.
    """
    status, problems, first = ChainStatus.INTACT, [], None

    def fault(found: ChainStatus, entry: int, said: str) -> None:
        nonlocal status, first
        problems.append(said)
        if status is ChainStatus.INTACT:
            status = found
        first = entry if first is None else min(first, entry)

    prev = ZERO
    for number, raw in enumerate(lines, start=1):
        entry = _parsed(raw)
        if entry is None:
            fault(ChainStatus.CORRUPT, number, f"entry {number} is not one `repro verify` wrote")
        else:
            if entry.prev_hash != prev:
                fault(
                    ChainStatus.EDITED,
                    max(number - 1, 1),
                    f"entry {number - 1} does not hash to what entry {number} recorded for the "
                    "entry before it"
                    if number > 1
                    else "entry 1 records an entry before it",
                )
            if entry.seq != number - 1:
                fault(
                    ChainStatus.REORDERED,
                    number,
                    f"entry {number} is numbered {entry.seq + 1} of the chain",
                )
        prev = sha256_of_text(raw)

    anchor = read_anchor(path)
    if anchor is None:
        if status is ChainStatus.INTACT:
            status = ChainStatus.NO_ANCHOR
        problems.append("no head file, so entries cut from the end would not be found")
    elif anchor.get("count") != len(lines):
        longer = len(lines) > anchor.get("count", 0)
        if status is ChainStatus.INTACT:
            status = ChainStatus.EXTENDED if longer else ChainStatus.TRUNCATED
        problems.append(
            f"the head file records {anchor.get('count')} entries, the record holds {len(lines)}"
        )
    elif anchor.get("head") != prev:
        fault(
            ChainStatus.EDITED,
            max(len(lines), 1),
            f"entry {len(lines)} does not hash to what the head file records",
        )
    return RecordState(
        kind=kind,
        path=str(path),
        entries=len(lines),
        status=status.value,
        problems=tuple(problems),
        unverifiable_from=first,
    )


def _prefix(one: list[str], other: list[str]) -> int:
    """How many entries two records share from the start."""
    shared = 0
    while shared < min(len(one), len(other)) and one[shared] == other[shared]:
        shared += 1
    return shared


class Records:
    """The project's records of checks, read once: each one's state, and per assertion each
    way an entry holds it, oldest first."""

    def __init__(self, root: pathlib.Path, local: bool = True) -> None:
        at = git_dir(root) if local else None
        self.no_local_record = NOT_A_REPOSITORY if local and at is None else ""
        self.local = at / LOCAL if at is not None else None
        self.tracked = root / RECORD
        here = _raw(self.local) if self.local is not None else []
        there = _raw(self.tracked)
        shared = _prefix(here, there)

        states = []
        vouched: dict[str, bool] = {}
        for kind, path, lines in (("local", self.local, here), ("tracked", self.tracked, there)):
            if path is None or not (lines or read_anchor(path)):
                continue
            state = _chain(path, kind, lines)
            if kind == "tracked" and here and shared < min(len(here), len(there)):
                state = state.model_copy(update={"diverges_at": shared + 1})
            states.append(state)
            for number, raw in enumerate(lines, start=1):
                sound = state.unverifiable_from is None or number < state.unverifiable_from
                vouched[raw] = vouched.get(raw, False) or sound
        self.states = tuple(states)
        self.lines = {"local": here, "tracked": there}

        # What the two share, then what each holds beyond it, in the order appended.
        # An entry that does not parse is counted as a fault above and holds nothing to show.
        read = {raw: entry for raw in (*here, *there) if (entry := _parsed(raw)) is not None}
        beyond = sorted(
            (raw for raw in dict.fromkeys(here[shared:] + there[shared:]) if raw in read),
            key=lambda raw: read[raw].timestamp,
        )
        found: dict[Identity, list[CheckedAssertion]] = collections.defaultdict(list)
        for raw in (*(raw for raw in here[:shared] if raw in read), *beyond):
            entry = read[raw]
            for assertion in entry.assertions:
                found[assertion.identity].append(
                    assertion.model_copy(
                        update={"checked_at": entry.timestamp, "verifiable": vouched[raw]}
                    )
                )
        self.history = {identity: tuple(states) for identity, states in found.items()}

    def state(self, kind: Kind) -> RecordState | None:
        return next((state for state in self.states if state.kind == kind), None)


def _take(behind: pathlib.Path, lines: list[str], held: int) -> None:
    """Append to one record the entries another holds beyond it, as stored, and move its head
    file."""
    behind.parent.mkdir(parents=True, exist_ok=True)
    with behind.open("a", encoding="utf-8") as handle:
        handle.write("".join(f"{line}\n" for line in lines[held:]))
        handle.flush()
        os.fsync(handle.fileno())
    write_anchor(behind, len(lines), sha256_of_text(lines[-1]))


def record(
    manifest: Manifest, report: VerificationReport, local: bool = True, tracked: bool = False
) -> None:
    """Append what one `repro verify` found to the project's records of checks.

    To the local record where `local` and the project is in a git repository, and to the
    tracked one as well where `tracked`. Nothing is written where every assertion is as it
    was last recorded and the tracked record, if asked for, already holds every local entry.

    Raises `RecordBrokenError` where the chain to append to does not verify,
    `RecordDivergedError` where the tracked record is not the beginning of the local one, and
    `OSError` where a record cannot be written.
    """
    root = manifest.path.parent if manifest.path else pathlib.Path.cwd()
    at = git_dir(root) if local else None
    kept = at / LOCAL if at is not None else None
    carried = root / RECORD
    written = kept or (carried if tracked else None)
    if written is None:
        return

    # One lock across reading the last entries and writing the next, so two checks at once
    # append one after the other and the second finds what the first wrote.
    with exclusive_lock(written):
        found = Records(root, local)
        here, there = found.lines["local"], found.lines["tracked"]
        carried_state = found.state("tracked")
        if (
            kept is not None
            and _prefix(here, there) == len(here) < len(there)
            and carried_state is not None
            and carried_state.unverifiable_from is None
        ):
            # A clone, or a pull: the tracked record holds entries this clone has not seen.
            _take(kept, there, len(here))
            found = Records(root, local)
        state = found.state("local" if kept is not None else "tracked")
        if state is not None and ChainStatus(state.status) not in _SOUND:
            raise RecordBrokenError(state)
        changed = [
            assertion
            for claim, assessed in zip(manifest.claims, report.claims, strict=True)
            for assertion in checked(claim, assessed.decisions)
            if assertion.identity not in found.history
            or not assertion.same_as(found.history[assertion.identity][-1])
        ]
        if changed:
            append_event(
                written,
                {
                    "schema_version": CheckRecord.model_fields["schema_version"].default,
                    "assertions": [
                        assertion.model_dump(mode="json", exclude={"checked_at", "verifiable"})
                        for assertion in changed
                    ],
                },
            )

    if tracked and kept is not None:
        with exclusive_lock(carried):
            here, there = _raw(kept), _raw(carried)
            shared = _prefix(here, there)
            if shared < len(there):
                raise RecordDivergedError(carried, shared + 1)
            state = _chain(carried, "tracked", there)
            if there and ChainStatus(state.status) not in _SOUND:
                raise RecordBrokenError(state)
            if len(here) > len(there):
                _take(carried, here, len(there))


__all__ = [
    "LOCAL",
    "NOT_A_REPOSITORY",
    "RECORD",
    "Identity",
    "RecordBrokenError",
    "RecordDivergedError",
    "Records",
    "address",
    "checked",
    "git_dir",
    "record",
]
