"""Timestamps held outside the repository, so a digest can be shown to have existed by a date.

A digest written into a repository proves only that the repository agrees with itself. Whoever
holds the repository can rewrite its history, delete it and push it again, and every check that
reads the repository passes afterwards. What closes that is a copy of the digest held by someone
else, with a date that party will not change.

OpenTimestamps provides one with no account and no trusted party beyond Bitcoin. A digest is
sent to public calendar servers, which return a proof that is pending; within hours the calendars
commit it into a Bitcoin block, and fetching the proof again completes it. A complete proof needs
no calendar to check: it is a chain of hash operations from the digest to a block's merkle root.

Only the digest leaves the machine, with a random nonce appended first, so a calendar learns
nothing about the file, not even its hash.

Calendars and block explorers are parameters rather than module state, so a caller can name its
own and a test can stand in for both without patching anything.

Requires the `anchor` extra: `provenance-core[anchor]`.
"""

from __future__ import annotations

import datetime
import json
import os
import urllib.request
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from typing import Protocol

from opentimestamps.calendar import (
    DEFAULT_AGGREGATORS,
    DEFAULT_CALENDAR_WHITELIST,
    CommitmentNotFoundError,
    RemoteCalendar,
)
from opentimestamps.core.notary import BitcoinBlockHeaderAttestation, PendingAttestation
from opentimestamps.core.op import OpAppend, OpSHA256
from opentimestamps.core.serialize import (
    BytesDeserializationContext,
    BytesSerializationContext,
    DeserializationError,
)
from opentimestamps.core.timestamp import DetachedTimestampFile, Timestamp

#: Aggregators that forward a submission to the calendars. Four operators run them, so one
#: calendar disappearing leaves the others to complete the proof.
CALENDARS: tuple[str, ...] = tuple(DEFAULT_AGGREGATORS)

#: A stamp is refused unless this many calendars accepted it. One calendar is one operator who
#: could lose the commitment before it reaches a block.
MIN_CALENDARS = 2

#: Esplora block explorers, run by two operators. A block's merkle root is read from both, and a
#: disagreement is an error rather than a vote.
EXPLORERS: tuple[str, ...] = (
    "https://blockstream.info/api",
    "https://mempool.space/api",
)

USER_AGENT = "provenance-core (reproducible-science)"
TIMEOUT = 15


class AnchorError(Exception):
    """A timestamp could not be made, read, completed or checked."""


class Calendar(Protocol):
    url: str

    def submit(self, digest: bytes, timeout: float | None = None) -> Timestamp: ...

    def get_timestamp(
        self, commitment: bytes, timeout: float | None = None
    ) -> Timestamp: ...


#: Names the calendars to submit to, comma-separated, in place of `CALENDARS`. Set and empty, it
#: turns stamping off: a test suite, or a machine that must not reach the network, says so once
#: rather than in every command.
CALENDARS_ENV = "PROVENANCE_CALENDARS"


def configured() -> tuple[str, ...]:
    if CALENDARS_ENV not in os.environ:
        return CALENDARS
    return tuple(
        url.strip() for url in os.environ[CALENDARS_ENV].split(",") if url.strip()
    )


def remote(url: str) -> Calendar:
    return RemoteCalendar(url, user_agent=USER_AGENT)


@dataclass(frozen=True)
class Status:
    """What a proof attests, read from the proof alone, with no network."""

    digest: str
    pending: tuple[str, ...]
    """Calendars holding the commitment that have not yet returned a Bitcoin attestation."""
    blocks: tuple[int, ...]
    """Heights of the Bitcoin blocks the proof reaches. Not checked against Bitcoin here."""

    @property
    def is_complete(self) -> bool:
        return bool(self.blocks)


@dataclass(frozen=True)
class Confirmation:
    """A Bitcoin block whose merkle root the proof reaches, as the explorers report it."""

    height: int
    time: datetime.datetime


def _digest_bytes(digest: str) -> bytes:
    try:
        raw = bytes.fromhex(digest)
    except ValueError as e:
        raise AnchorError(f"{digest!r} is not a hex digest") from e
    if len(raw) != 32:
        raise AnchorError(
            f"a sha256 digest is 32 bytes, and {digest[:16]}… is {len(raw)}"
        )
    return raw


def _dump(proof: DetachedTimestampFile) -> bytes:
    ctx = BytesSerializationContext()
    proof.serialize(ctx)
    return ctx.getbytes()


def _load(data: bytes, digest: str) -> DetachedTimestampFile:
    """The proof in `data`, refused unless it is a proof of `digest`.

    A proof of another digest is not a weaker proof of this one, so it is an error and not a
    status: a proof copied from a different freeze would otherwise date this one.
    """
    try:
        proof = DetachedTimestampFile.deserialize(BytesDeserializationContext(data))
    except DeserializationError as e:
        raise AnchorError(f"not an OpenTimestamps proof: {e}") from e
    if not isinstance(proof.file_hash_op, OpSHA256):
        raise AnchorError("the proof is of a digest other than sha256")
    if proof.file_digest != _digest_bytes(digest):
        raise AnchorError(
            f"the proof is of {proof.file_digest.hex()[:16]}…, not of {digest[:16]}…"
        )
    return proof


def proved_digest(data: bytes) -> str:
    """The digest a proof is of, without checking it against anything."""
    try:
        return DetachedTimestampFile.deserialize(
            BytesDeserializationContext(data)
        ).file_digest.hex()
    except DeserializationError as e:
        raise AnchorError(f"not an OpenTimestamps proof: {e}") from e


def _nodes(timestamp: Timestamp) -> Iterator[Timestamp]:
    yield timestamp
    for child in timestamp.ops.values():
        yield from _nodes(child)


def stamp(
    digest: str,
    calendars: Sequence[Calendar] | None = None,
    timeout: float = TIMEOUT,
) -> bytes:
    """Submit `digest` and return the pending proof, serialized as an `.ots` file holds it."""
    if calendars is None:
        calendars = [remote(url) for url in configured()]
    if not calendars:
        raise AnchorError(
            f"no calendars are configured ({CALENDARS_ENV} is set and empty)"
        )
    proof = DetachedTimestampFile(OpSHA256(), Timestamp(_digest_bytes(digest)))
    # The nonce keeps the digest itself from the calendars, as the reference client does.
    tip = proof.timestamp.ops.add(OpAppend(os.urandom(16))).ops.add(OpSHA256())
    accepted, refused = 0, []
    for calendar in calendars:
        try:
            tip.merge(calendar.submit(tip.msg, timeout=timeout))
            accepted += 1
        # The library raises a bare `Exception` for an unexpected response, beside `OSError` for
        # the network and `DeserializationError` for a malformed reply. Each is one calendar
        # failing, which the count below turns into a decision.
        except Exception as e:  # noqa: BLE001
            refused.append(f"{calendar.url}: {e}")
    if accepted < MIN_CALENDARS:
        raise AnchorError(
            f"{accepted} of {len(calendars)} calendars accepted the digest, and {MIN_CALENDARS} "
            f"are needed: " + "; ".join(refused)
        )
    return _dump(proof)


def status(data: bytes, digest: str) -> Status:
    proof = _load(data, digest)
    pending, blocks = set(), set()
    for _msg, attestation in proof.timestamp.all_attestations():
        if isinstance(attestation, BitcoinBlockHeaderAttestation):
            blocks.add(attestation.height)
        elif isinstance(attestation, PendingAttestation):
            pending.add(attestation.uri)
    return Status(digest, tuple(sorted(pending)), tuple(sorted(blocks)))


def upgrade(
    data: bytes,
    digest: str,
    calendar: Callable[[str], Calendar] | None = None,
    timeout: float = TIMEOUT,
) -> bytes:
    """Ask each pending calendar for the rest of the proof, and return the proof with it merged.

    Only calendars on the reference client's whitelist are asked. The URI comes from the proof
    file, and a proof written by someone else could otherwise make this fetch any address.
    A calendar that has not yet reached a block answers 404, which leaves its branch pending.
    """
    proof = _load(data, digest)
    calendar = remote if calendar is None else calendar
    for node in list(_nodes(proof.timestamp)):
        for attestation in list(node.attestations):
            if not isinstance(attestation, PendingAttestation):
                continue
            if attestation.uri not in DEFAULT_CALENDAR_WHITELIST:
                continue
            try:
                answer = calendar(attestation.uri).get_timestamp(
                    node.msg, timeout=timeout
                )
            # `CommitmentNotFoundError` is the ordinary not-yet answer; anything else is one
            # calendar failing (see `stamp`). Both leave this branch pending for a later try.
            except (CommitmentNotFoundError, Exception):  # noqa: BLE001, S112
                continue
            node.merge(answer)
            # A calendar whose branch now reaches a block is no longer pending. Left in place, the
            # mark would make a complete proof read as still waiting on that calendar.
            if any(
                isinstance(found, BitcoinBlockHeaderAttestation)
                for _msg, found in answer.all_attestations()
            ):
                node.attestations.discard(attestation)
    return _dump(proof)


def _get(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return response.read(100_000)


def _merkle_root(
    api: str, height: int, fetch: Callable[[str], bytes]
) -> tuple[str, int]:
    block_hash = fetch(f"{api}/block-height/{height}").decode().strip()
    block = json.loads(fetch(f"{api}/block/{block_hash}"))
    return block["merkle_root"], block["timestamp"]


def confirm(
    data: bytes,
    digest: str,
    explorers: Sequence[str] = EXPLORERS,
    fetch: Callable[[str], bytes] | None = None,
) -> Confirmation | None:
    """The earliest Bitcoin block the proof reaches, checked against the explorers.

    None when the proof reaches no block yet. Raises `AnchorError` when a block the proof names
    has a different merkle root, which means the proof is false or the explorers are; either way
    nothing here can be trusted, and saying so is the result.

    Explorers are trusted to report block headers honestly. Two operators are asked so that one
    lying is a disagreement and not a pass; a local Bitcoin node removes the trust entirely.
    """
    proof = _load(data, digest)
    fetch = _get if fetch is None else fetch
    found: list[Confirmation] = []
    for msg, attestation in proof.timestamp.all_attestations():
        if not isinstance(attestation, BitcoinBlockHeaderAttestation):
            continue
        # The proof carries the merkle root in Bitcoin's internal byte order; explorers print it
        # reversed.
        expected = msg[::-1].hex()
        answers = []
        for api in explorers:
            try:
                answers.append((api, *_merkle_root(api, attestation.height, fetch)))
            except (OSError, ValueError, KeyError):
                continue
        if not answers:
            raise AnchorError(f"no explorer answered for block {attestation.height}")
        for api, root, _time in answers:
            if root != expected:
                raise AnchorError(
                    f"{api} gives block {attestation.height} the merkle root {root[:16]}…, and "
                    f"the proof reaches {expected[:16]}…"
                )
        when = datetime.datetime.fromtimestamp(answers[0][2], datetime.UTC)
        found.append(Confirmation(attestation.height, when))
    return min(found, key=lambda c: c.height) if found else None
