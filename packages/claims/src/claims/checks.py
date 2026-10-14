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
`provenance_core.chain.append_event` appends under a lock held across reading the last entry and
writing the next, so two checks running at once write two entries in a row and not two
claiming one position.

**An index, so a check does not read the record.** A check needs the last state recorded for
each assertion it found, to append only what changed. `checks.index.sqlite`, beside the local
record, holds that state per assertion and where each entry starts, with the head, length and
size of the record it describes. Where those are the record's now and the last entry hashes to
the head file's head, `record` reads nothing else of the record, and its time does not grow
with the record. Otherwise it reads both records whole, checks their chains, refuses to append
to one that does not verify, and writes the index again. The tracked record has no index; it
is a copy, and the entries it lacks are copied as bytes from the local one.

Reading is done here and not by `provenance_core.chain.verify`, which takes a lock by creating a file
beside the record: `repro verify` and `repro why` must leave the working tree as it is.

**What the chain shows, and what it does not.** An entry edited, removed from the middle or
moved is found, with its number, where a record is read whole: by `repro why`, by `repro verify
--set-aside-record`, and by the first check whose index no longer describes the record. The
entries from there on are shown as the record holds them and marked unverifiable. A check whose
index describes the record appends after such an edit, and the edit stays where it was, since
the append rewrites no entry and the `prev_hash` after the edit still names the entry as it was
written. An entry edited at the end is found by every check. Entries cut from the end are found
while the head file is as it was. A record and its head file cut back together, or deleted together and grown again, look
like a shorter or a new record: nothing inside the two files can show it. The local record has
no witness outside its directory. The tracked record's head file is committed with it, so the
repository's history holds every earlier head, and that is what makes a truncation visible to
someone who has the history. Nothing here is signed or timestamped by anyone else, and whoever
can write both files and rewrite the history can rewrite the record.
"""

from __future__ import annotations

import collections
import datetime
import functools
import json
import os
import pathlib
import sqlite3
from collections.abc import Iterable
from typing import Literal

from provenance_core import ZERO, exclusive_lock, sha256_of_text, try_run
from provenance_core.chain import (
    ANCHOR,
    ChainStatus,
    append_event,
    read_anchor,
    tail_agrees,
    write_anchor,
)
from pydantic import ValidationError

from claims.exceptions import ReproError
from claims.models import (
    AggregateEvidence,
    CheckedAssertion,
    CheckRecord,
    Claim,
    CorrespondenceEvidence,
    Decision,
    Evidence,
    Locator,
    Manifest,
    QuoteEvidence,
    RecordSetAside,
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

#: The flag that sets a damaged record aside. Named in the line that reports one.
SET_ASIDE = "--set-aside-record"

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

    def __init__(self, state: RecordState, program: str = "repro") -> None:
        self.state = state
        super().__init__(
            f"{state.path}: refusing to append to a chain reported as {state.status}: "
            f"{'; '.join(state.problems)}; `{program} verify {SET_ASIDE}` keeps it and starts anew"
        )


class RecordIntactError(ReproError):
    """Nothing was set aside: every record there is verifies, and the two agree."""

    def __init__(self, root: pathlib.Path) -> None:
        self.root = root
        super().__init__(f"{root}: no record here is damaged, so none is set aside")


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
    if isinstance(evidence, AggregateEvidence):
        return "; ".join(
            f"{member.artifact} at {address(member.locator)}" for member in evidence.members
        )
    if isinstance(evidence, TableCellEvidence) and not evidence.addresses_one_row:
        # Neither `row` nor `where`, or both: there is no one address to record.
        return ""
    return address(evidence.locator)


def _conversion(evidence: Evidence) -> str:
    if isinstance(evidence, CorrespondenceEvidence):
        return "; ".join(
            f"{side.name}: {side.conversion.value}" for side in evidence.sides if side.conversion
        )
    declared = getattr(evidence, "conversion", None)
    return declared.value if declared else ""


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
                conversion=_conversion(evidence),
                digests={side.artifact_id: side.artifact_digest for side in decision.sides}
                or {member.artifact_id: member.artifact_digest for member in decision.members}
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
    # Line feeds only, as `provenance_core.chain` reads a chain: `str.splitlines` also breaks at
    # U+2028 and U+2029, which a quoted passage can hold.
    return [line.strip() for line in path.read_text(encoding="utf-8").split("\n") if line.strip()]


def _parsed(raw: str) -> CheckRecord | None:
    try:
        return CheckRecord.model_validate_json(raw)
    except ValidationError:
        return None


def _chain(
    path: pathlib.Path,
    kind: Kind,
    lines: list[str],
    parsed: dict[str, CheckRecord | None] | None = None,
) -> RecordState:
    """Whether each entry follows from the one before it, and whether the head file agrees.

    The status is the first fault's, as in the `results` ledger: a chain edited and then cut
    is edited. `parsed` holds entries already read, by line, so a line is parsed once.
    """
    parsed = {} if parsed is None else parsed
    status, problems, first = ChainStatus.INTACT, [], None

    def fault(found: ChainStatus, entry: int, said: str) -> None:
        nonlocal status, first
        problems.append(said)
        if status is ChainStatus.INTACT:
            status = found
        first = entry if first is None else min(first, entry)

    prev = ZERO
    for number, raw in enumerate(lines, start=1):
        if raw not in parsed:
            parsed[raw] = _parsed(raw)
        entry = parsed[raw]
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
        # Each line parsed once, here and in `_chain`: a record shared by a repository's
        # projects grows to megabytes, and its entries are the largest lines it holds.
        parsed: dict[str, CheckRecord | None] = {}
        for kind, path, lines in (("local", self.local, here), ("tracked", self.tracked, there)):
            if path is None or not (lines or read_anchor(path)):
                continue
            state = _chain(path, kind, lines, parsed)
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
        read = {
            raw: entry
            for raw in (*here, *there)
            if (entry := parsed[raw] if raw in parsed else _parsed(raw)) is not None
        }
        beyond = sorted(
            (raw for raw in dict.fromkeys(here[shared:] + there[shared:]) if raw in read),
            key=lambda raw: read[raw].timestamp,
        )
        self._read = read
        self._vouched = vouched
        self._order = (*(raw for raw in here[:shared] if raw in read), *beyond)
        # The last way an entry holds each assertion, as stored: what `record` compares a
        # check with. `history` is built from the same entries only where it is asked for.
        self.latest: dict[Identity, CheckedAssertion] = {
            assertion.identity: assertion
            for raw in self._order
            for assertion in read[raw].assertions
        }
        self.set_aside = tuple(
            note.model_copy(update={"at": read[raw].timestamp})
            for raw in self._order
            if (note := read[raw].set_aside) is not None
        )

    @functools.cached_property
    def history(self) -> dict[Identity, tuple[CheckedAssertion, ...]]:
        """Each way an entry holds each assertion, oldest first, with when it was checked and
        whether the chain vouches for the entry."""
        found: dict[Identity, list[CheckedAssertion]] = collections.defaultdict(list)
        for raw in self._order:
            entry = self._read[raw]
            for assertion in entry.assertions:
                found[assertion.identity].append(
                    assertion.model_copy(
                        update={"checked_at": entry.timestamp, "verifiable": self._vouched[raw]}
                    )
                )
        return {identity: tuple(states) for identity, states in found.items()}

    def state(self, kind: Kind) -> RecordState | None:
        return next((state for state in self.states if state.kind == kind), None)


#: The index of the local record, beside it in the git directory. A cache, rebuilt from the
#: record whenever it does not describe the record's current head, and never committed.
INDEX = "checks.index.sqlite"
#: Bumped when what the index holds changes, so an index of another layout is rebuilt.
INDEX_VERSION = "1"


def _identity(identity: Identity) -> str:
    return json.dumps(list(identity), ensure_ascii=False)


def _entries(path: pathlib.Path) -> list[tuple[int, str]]:
    """Each entry of a record as `_raw` gives it, with the byte offset its line starts at."""
    found, at = [], 0
    for piece in path.read_bytes().split(b"\n") if path.is_file() else []:
        if raw := piece.decode("utf-8").strip():
            found.append((at, raw))
        at += len(piece) + 1
    return found


class Index:
    """What `record` needs from the local record without reading it: the last stored state of
    each assertion, and where each entry starts and what it hashes to.

    Held in SQLite beside the record, with the record's head, length and size in bytes at the
    time it was written. It is used only where those are the record's now and the record's last
    entry hashes to the head its head file records; otherwise the record is read whole, its
    chain checked, and the index written again from it. It is written whole only from a record
    whose chain verifies, and then advanced only by the entries `record` appends. An entry
    edited later is found by the check of the last entry where it is the last, and by a whole
    read, as the module says, where it is not. Every write to it is one transaction, made after
    the record's own write, so a crash between the two leaves an index describing an older
    head, which is then rebuilt.
    """

    def __init__(self, record_path: pathlib.Path) -> None:
        self.record = record_path
        self.path = record_path.with_name(INDEX)
        self.db = sqlite3.connect(self.path, isolation_level=None)
        self.db.executescript(
            "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);"
            "CREATE TABLE IF NOT EXISTS lines "
            "(seq INTEGER PRIMARY KEY, start INTEGER NOT NULL, hash TEXT NOT NULL);"
            "CREATE TABLE IF NOT EXISTS latest (identity TEXT PRIMARY KEY, assertion TEXT NOT NULL);"
        )

    @classmethod
    def open(cls, record_path: pathlib.Path) -> Index | None:
        """The index, or None where it cannot be opened: then the record is read whole."""
        try:
            record_path.parent.mkdir(parents=True, exist_ok=True)
            return cls(record_path)
        except (sqlite3.Error, OSError):
            return None

    def close(self) -> None:
        self.db.close()

    def _meta(self) -> dict[str, str]:
        return dict(self.db.execute("SELECT key, value FROM meta"))

    def _size(self) -> int:
        return self.record.stat().st_size if self.record.is_file() else 0

    def current(self, tracked: pathlib.Path) -> bool:
        """Whether the index describes the record as it is now, and the tracked record, if
        there is one, holds no entry the local one does not: then nothing needs reading.

        The record's head, length and size must be the index's, and its last entry must hash
        to the head its head file records and hold the position the count gives it. The tracked
        record must be absent, or have a head file whose count is no more than the local
        record's and whose head is the local entry at that position.
        """
        try:
            meta = self._meta()
            if meta.get("version") != INDEX_VERSION or meta.get("size") != str(self._size()):
                return False
            count = int(meta.get("count", "-1"))
            if count == 0:
                if self.record.is_file() and self._size():
                    return False
            else:
                agreed = tail_agrees(self.record)
                if agreed is None or agreed != (count, meta.get("head")):
                    return False
            return self._follows(tracked, count) is not None
        except (sqlite3.Error, OSError, ValueError):
            return False

    def _follows(self, tracked: pathlib.Path, count: int) -> int | None:
        """How many entries the tracked record holds, where it is the beginning of the local
        one by its head file; None where that cannot be told from the two head files."""
        anchor = read_anchor(tracked)
        if anchor is None:
            return 0 if not tracked.is_file() or not tracked.stat().st_size else None
        held = anchor.get("count")
        if not isinstance(held, int) or held > count:
            return None
        if held == 0:
            return 0
        found = self.db.execute("SELECT hash FROM lines WHERE seq = ?", (held - 1,)).fetchone()
        return held if found is not None and found[0] == anchor.get("head") else None

    def latest(self, identities: Iterable[Identity]) -> dict[Identity, CheckedAssertion]:
        """The last stored state of each of these assertions that the record holds."""
        wanted = {_identity(identity): identity for identity in identities}
        keys, found = list(wanted), {}
        for start in range(0, len(keys), 500):
            chunk = keys[start : start + 500]
            marks = ",".join("?" * len(chunk))
            rows = self.db.execute(
                f"SELECT identity, assertion FROM latest WHERE identity IN ({marks})", chunk
            )
            for key, assertion in rows:
                found[wanted[key]] = CheckedAssertion.model_validate_json(assertion)
        return found

    def rebuild(self, parsed: dict[str, CheckRecord]) -> None:
        """Write the index again from the record as it is now. `parsed` holds the entries the
        caller has read, by line; any other line is parsed here."""
        entries = _entries(self.record)
        anchor = read_anchor(self.record) or {}
        latest: dict[str, str] = {}
        rows = []
        for seq, (start, raw) in enumerate(entries):
            rows.append((seq, start, sha256_of_text(raw)))
            entry = parsed.get(raw) or _parsed(raw)
            for assertion in entry.assertions if entry is not None else ():
                latest[_identity(assertion.identity)] = assertion.model_dump_json()
        self.db.execute("BEGIN IMMEDIATE")
        self.db.execute("DELETE FROM meta")
        self.db.execute("DELETE FROM lines")
        self.db.execute("DELETE FROM latest")
        self.db.executemany("INSERT INTO lines VALUES (?, ?, ?)", rows)
        self.db.executemany("INSERT INTO latest VALUES (?, ?)", latest.items())
        self._set_meta(
            count=anchor.get("count", len(rows)) if anchor else len(rows),
            head=anchor.get("head", rows[-1][2] if rows else ZERO),
        )
        self.db.execute("COMMIT")

    def advance(self, start: int, written: dict, changed: list[CheckedAssertion]) -> None:
        """Add the entry just appended at byte `start`, which the record's head file now names."""
        anchor = read_anchor(self.record) or {}
        self.db.execute("BEGIN IMMEDIATE")
        self.db.execute(
            "INSERT OR REPLACE INTO lines VALUES (?, ?, ?)",
            (written["seq"], start, anchor.get("head", "")),
        )
        self.db.executemany(
            "INSERT OR REPLACE INTO latest VALUES (?, ?)",
            [(_identity(assertion.identity), assertion.model_dump_json()) for assertion in changed],
        )
        self._set_meta(count=anchor.get("count", 0), head=anchor.get("head", ""))
        self.db.execute("COMMIT")

    def start_of(self, seq: int) -> int | None:
        found = self.db.execute("SELECT start FROM lines WHERE seq = ?", (seq,)).fetchone()
        return found[0] if found else None

    def _set_meta(self, count: int, head: str) -> None:
        self.db.executemany(
            "INSERT OR REPLACE INTO meta VALUES (?, ?)",
            [
                ("version", INDEX_VERSION),
                ("count", str(count)),
                ("head", head),
                ("size", str(self._size())),
            ],
        )


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
    manifest: Manifest,
    report: VerificationReport,
    local: bool = True,
    tracked: bool = False,
    program: str = "repro",
) -> None:
    """Append what one `repro verify` found to the project's records of checks.

    To the local record where `local` and the project is in a git repository, and to the
    tracked one as well where `tracked`. Nothing is written where every assertion is as it
    was last recorded and the tracked record, if asked for, already holds every local entry.

    Where the local record's `Index` describes it as it is now, nothing else of the record is
    read: the last entry is checked against the head file, the assertions this check found are
    compared with the states the index holds for them, and the tracked record is brought up to
    the local one by copying the entries it lacks. Otherwise both records are read whole, their
    chains checked, and the index written again. A chain edited at its end is refused either
    way. An entry edited further back is found where the records are read whole, by `repro why`
    and `repro verify --set-aside-record`, and by the first check after the index stops
    describing the record.

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

    index = Index.open(kept) if kept is not None else None
    try:
        _record(manifest, report, root, kept, carried, written, index, program)
        if tracked and kept is not None:
            with exclusive_lock(carried):
                if not _carry(index, kept, carried):
                    _carry_reading_both(kept, carried, program)
    finally:
        if index is not None:
            index.close()


def _record(
    manifest: Manifest,
    report: VerificationReport,
    root: pathlib.Path,
    kept: pathlib.Path | None,
    carried: pathlib.Path,
    written: pathlib.Path,
    index: Index | None,
    program: str,
) -> None:
    # One lock across reading the last entries and writing the next, so two checks at once
    # append one after the other and the second finds what the first wrote.
    with exclusive_lock(written):
        found = [
            assertion
            for claim, assessed in zip(manifest.claims, report.claims, strict=True)
            for assertion in checked(claim, assessed.decisions)
        ]
        if index is not None and index.current(carried):
            latest = index.latest(assertion.identity for assertion in found)
            ready = True
        else:
            records = _read_whole(root, kept, program)
            latest, ready = records.latest, False
            if index is not None:
                try:
                    index.rebuild(records._read)
                    ready = True
                except (sqlite3.Error, OSError):
                    ready = False
        changed = [
            assertion
            for assertion in found
            if assertion.identity not in latest or not assertion.same_as(latest[assertion.identity])
        ]
        if not changed:
            return
        start = written.stat().st_size if written.is_file() else 0
        # The chain has been checked above, whole or at its end against the head file, so the
        # append checks only that the last entry is the one the head file records.
        appended = append_event(
            written,
            {
                "schema_version": CheckRecord.model_fields["schema_version"].default,
                "assertions": [
                    assertion.model_dump(mode="json", exclude={"checked_at", "verifiable"})
                    for assertion in changed
                ],
            },
            whole_chain=False,
        )
        if ready and index is not None:
            try:
                index.advance(start, appended, changed)
            except sqlite3.Error:
                # The index now describes an older head, and the next check rebuilds it.
                pass


def _read_whole(root: pathlib.Path, kept: pathlib.Path | None, program: str) -> Records:
    """Both records read whole, the entries the tracked one holds beyond the local one taken,
    and the chain to append to checked. Raises `RecordBrokenError` where it does not verify."""
    found = Records(root, kept is not None)
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
        found = Records(root, True)
    state = found.state("local" if kept is not None else "tracked")
    if state is not None and ChainStatus(state.status) not in _SOUND:
        raise RecordBrokenError(state, program)
    return found


def _carry(index: Index | None, kept: pathlib.Path, carried: pathlib.Path) -> bool:
    """Bring the tracked record up to the local one from the index, copying the bytes of the
    entries it lacks. False, having written nothing, where the index cannot say that the
    tracked record is the local one's beginning with an intact end."""
    if index is None or not index.current(carried):
        return False
    meta = index._meta()
    count, head = int(meta["count"]), meta["head"]
    held = index._follows(carried, count)
    if held is None or held == count:
        return held == count
    if held and (tail_agrees(carried) is None or not _ends_a_line(carried)):
        return False
    start = index.start_of(held)
    if start is None:
        return False
    with kept.open("rb") as source:
        source.seek(start)
        missing = source.read()
    carried.parent.mkdir(parents=True, exist_ok=True)
    with carried.open("ab") as handle:
        handle.write(missing)
        handle.flush()
        os.fsync(handle.fileno())
    write_anchor(carried, count, head)
    return True


def _ends_a_line(path: pathlib.Path) -> bool:
    """Whether a file's last byte is a line feed, read without reading the rest."""
    with path.open("rb") as handle:
        if not handle.seek(0, os.SEEK_END):
            return False
        handle.seek(-1, os.SEEK_END)
        return handle.read(1) == b"\n"


def _carry_reading_both(kept: pathlib.Path, carried: pathlib.Path, program: str) -> None:
    here, there = _raw(kept), _raw(carried)
    shared = _prefix(here, there)
    if shared < len(there):
        raise RecordDivergedError(carried, shared + 1)
    state = _chain(carried, "tracked", there)
    if there and ChainStatus(state.status) not in _SOUND:
        raise RecordBrokenError(state, program)
    if len(here) > len(there):
        _take(carried, here, len(there))


def _move_aside(path: pathlib.Path, state: RecordState, lines: list[str]) -> RecordSetAside:
    """Rename a record and its head file to names that say when they were set aside, and say
    what was found in it. Nothing is deleted, and a name already taken is not written over."""
    stamp = datetime.datetime.now(datetime.UTC).strftime("%Y%m%dT%H%M%SZ")
    vouched = len(lines) if state.unverifiable_from is None else state.unverifiable_from - 1
    for name in (path.name, ANCHOR):
        source, target = path.with_name(name), path.with_name(f"{name}.set-aside-{stamp}")
        if target.exists():
            raise FileExistsError(17, "File exists", str(target))
        if source.exists():
            os.replace(source, target)
    problems = state.problems + (
        (f"diverges from the local record at entry {state.diverges_at}",)
        if state.diverges_at is not None
        else ()
    )
    return RecordSetAside(
        kind=state.kind,
        kept_as=f"{path.name}.set-aside-{stamp}",
        entries=len(lines),
        head=sha256_of_text(lines[vouched - 1]) if vouched else ZERO,
        status=state.status,
        problems=problems,
    )


def set_aside(
    manifest: Manifest, local: bool = True, tracked: bool = False
) -> tuple[RecordSetAside, ...]:
    """Move a damaged record of checks aside and say so in the chain that goes on.

    The record `repro verify` appends to, where its chain does not verify: the next entry is
    the first of a new chain and names the old one, the hash of its last entry that verified
    and what was found. With `tracked`, the tracked record as well, where it does not verify or
    is not the beginning of the local one; it is then copied afresh by the check that follows.
    The files are renamed and kept.

    Raises `RecordIntactError` where no record qualifies. Never called except by name.
    """
    root = manifest.path.parent if manifest.path else pathlib.Path.cwd()
    at = git_dir(root) if local else None
    kept = at / LOCAL if at is not None else None
    carried = root / RECORD
    written = kept or carried
    with exclusive_lock(written):
        found = Records(root, local)
        moved = []
        for kind, path in (("local", kept), ("tracked", carried)):
            state = found.state(kind)
            if path is None or state is None or (path != written and not tracked):
                continue
            broken = ChainStatus(state.status) not in _SOUND
            # A tracked record cannot follow a local one that starts again.
            orphaned = path != written and (state.diverges_at is not None or bool(moved))
            if broken or orphaned:
                moved.append(_move_aside(path, state, found.lines[kind]))
        if not moved:
            raise RecordIntactError(root)
        for note in moved:
            append_event(
                written,
                {
                    "schema_version": CheckRecord.model_fields["schema_version"].default,
                    "assertions": [],
                    "set_aside": note.model_dump(mode="json", exclude={"at"}),
                },
            )
    return tuple(moved)


__all__ = [
    "INDEX",
    "LOCAL",
    "NOT_A_REPOSITORY",
    "RECORD",
    "Identity",
    "Index",
    "RecordBrokenError",
    "RecordDivergedError",
    "RecordIntactError",
    "Records",
    "address",
    "checked",
    "git_dir",
    "record",
    "set_aside",
]
