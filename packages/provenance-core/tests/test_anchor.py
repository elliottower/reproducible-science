import hashlib
import json

import pytest
from opentimestamps.core.notary import BitcoinBlockHeaderAttestation, PendingAttestation
from opentimestamps.core.op import OpSHA256
from opentimestamps.core.timestamp import Timestamp

from provenance_core import anchor

DIGEST = hashlib.sha256(b"the plan, as frozen").hexdigest()
CALENDAR = "https://alice.btc.calendar.opentimestamps.org"


class FakeCalendar:
    """Accepts a commitment, then completes it into block `height` once asked."""

    def __init__(
        self, url: str = CALENDAR, height: int | None = None, fails: bool = False
    ):
        self.url, self.height, self.fails = url, height, fails
        self.submitted: list[bytes] = []
        self.asked: list[bytes] = []

    def submit(self, digest: bytes, timeout=None) -> Timestamp:
        if self.fails:
            raise OSError("calendar unreachable")
        self.submitted.append(digest)
        timestamp = Timestamp(digest)
        timestamp.attestations.add(PendingAttestation(self.url))
        return timestamp

    def get_timestamp(self, commitment: bytes, timeout=None) -> Timestamp:
        self.asked.append(commitment)
        if self.height is None:
            raise anchor.CommitmentNotFoundError("not yet")
        timestamp = Timestamp(commitment)
        root = timestamp.ops.add(OpSHA256())
        root.attestations.add(BitcoinBlockHeaderAttestation(self.height))
        return timestamp


def explorer(roots: dict[int, str], time: int = 1_759_500_000):
    """A fetch that answers Esplora's two calls from `roots`, height to displayed merkle root."""

    def fetch(url: str) -> bytes:
        if "/block-height/" in url:
            return f"hash{url.rsplit('/', 1)[1]}".encode()
        height = int(url.rsplit("hash", 1)[1])
        return json.dumps({"merkle_root": roots[height], "timestamp": time}).encode()

    return fetch


def completed(height: int = 915_000) -> tuple[bytes, str]:
    """A proof of DIGEST reaching block `height`, and the merkle root an honest explorer shows."""
    calendar = FakeCalendar(height=height)
    waiting = FakeCalendar("https://bob.btc.calendar.opentimestamps.org")
    pending = anchor.stamp(DIGEST, [calendar, waiting])
    by_url = {calendar.url: calendar, waiting.url: waiting}
    proof = anchor.upgrade(pending, DIGEST, calendar=by_url.__getitem__)
    root = hashlib.sha256(calendar.asked[0]).digest()[::-1].hex()
    return proof, root


def test_stamp_is_pending_at_every_calendar_that_accepted_it():
    calendars = [
        FakeCalendar(),
        FakeCalendar("https://bob.btc.calendar.opentimestamps.org"),
    ]

    found = anchor.status(anchor.stamp(DIGEST, calendars), DIGEST)

    assert found.pending == (CALENDAR, "https://bob.btc.calendar.opentimestamps.org")
    assert found.blocks == ()
    assert not found.is_complete


def test_calendars_never_receive_the_digest_and_each_stamp_hides_it_differently():
    first, second = FakeCalendar(), FakeCalendar()

    anchor.stamp(DIGEST, [first, FakeCalendar()])
    anchor.stamp(DIGEST, [second, FakeCalendar()])

    assert bytes.fromhex(DIGEST) not in first.submitted + second.submitted
    assert first.submitted != second.submitted


def test_stamp_refuses_when_fewer_than_two_calendars_accept():
    with pytest.raises(anchor.AnchorError, match="1 of 3 calendars"):
        anchor.stamp(
            DIGEST, [FakeCalendar(), FakeCalendar(fails=True), FakeCalendar(fails=True)]
        )


def test_upgrade_completes_the_proof_and_leaves_a_calendar_with_no_answer_pending():
    proof, _root = completed(height=915_000)

    found = anchor.status(proof, DIGEST)

    assert found.blocks == (915_000,)
    assert found.pending == ("https://bob.btc.calendar.opentimestamps.org",)
    assert found.is_complete


def test_upgrade_never_contacts_a_calendar_off_the_whitelist():
    pending = anchor.stamp(
        DIGEST,
        [
            FakeCalendar("https://calendar.example.org"),
            FakeCalendar("https://other.example.org"),
        ],
    )
    contacted: list[str] = []

    anchor.upgrade(
        pending, DIGEST, calendar=lambda url: contacted.append(url) or FakeCalendar(url)
    )

    assert contacted == []


def test_confirm_dates_the_proof_by_the_block_the_explorers_agree_on():
    proof, root = completed(height=915_000)

    found = anchor.confirm(
        proof, DIGEST, explorers=["a", "b"], fetch=explorer({915_000: root})
    )

    assert found is not None
    assert found.height == 915_000
    assert found.time.timestamp() == 1_759_500_000


def test_confirm_refuses_a_block_whose_merkle_root_differs_from_the_proof():
    proof, root = completed(height=915_000)
    wrong = ("0" if root[0] != "0" else "1") + root[1:]

    with pytest.raises(anchor.AnchorError, match="merkle root"):
        anchor.confirm(proof, DIGEST, explorers=["a"], fetch=explorer({915_000: wrong}))


def test_confirm_refuses_when_two_explorers_disagree():
    proof, root = completed(height=915_000)
    honest, lying = explorer({915_000: root}), explorer({915_000: "f" * 64})

    with pytest.raises(anchor.AnchorError, match="lying"):
        anchor.confirm(
            proof,
            DIGEST,
            explorers=["honest", "lying"],
            fetch=lambda url: (lying if url.startswith("lying") else honest)(url),
        )


def test_confirm_of_a_pending_proof_is_none():
    pending = anchor.stamp(DIGEST, [FakeCalendar(), FakeCalendar()])

    assert anchor.confirm(pending, DIGEST, explorers=["a"], fetch=explorer({})) is None


def test_a_proof_of_another_digest_is_refused_rather_than_read():
    proof, _root = completed()
    other = hashlib.sha256(b"a different plan").hexdigest()

    with pytest.raises(anchor.AnchorError, match="not of"):
        anchor.status(proof, other)


def test_bytes_that_are_not_a_proof_are_refused():
    with pytest.raises(anchor.AnchorError, match="not an OpenTimestamps proof"):
        anchor.status(b"not a proof", DIGEST)
