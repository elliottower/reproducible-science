"""A stamped head catches what the anchor cannot: the ledger and its anchor rewritten together."""

from __future__ import annotations

import json

import pytest
from opentimestamps.core.notary import BitcoinBlockHeaderAttestation, PendingAttestation
from opentimestamps.core.op import OpSHA256
from opentimestamps.core.timestamp import Timestamp
from provenance_core import anchor
from results import cli, ledger

ALICE = "https://alice.btc.calendar.opentimestamps.org"
BOB = "https://bob.btc.calendar.opentimestamps.org"


class Calendars:
    """Both calendars. Each accepts a commitment; `mine(height)` makes them complete it."""

    def __init__(self):
        self.height: int | None = None
        self.roots: dict[int, str] = {}

    def mine(self, height: int) -> None:
        self.height = height

    def __call__(self, url: str):
        calendars = self

        class One:
            def __init__(self):
                self.url = url

            def submit(self, digest, timeout=None):
                timestamp = Timestamp(digest)
                timestamp.attestations.add(PendingAttestation(url))
                return timestamp

            def get_timestamp(self, commitment, timeout=None):
                if calendars.height is None:
                    raise anchor.CommitmentNotFoundError("not yet")
                timestamp = Timestamp(commitment)
                root = timestamp.ops.add(OpSHA256())
                root.attestations.add(BitcoinBlockHeaderAttestation(calendars.height))
                calendars.roots[calendars.height] = root.msg[::-1].hex()
                return timestamp

        return One()

    def explorer(self, url: str) -> bytes:
        if "/block-height/" in url:
            return f"hash{url.rsplit('/', 1)[1]}".encode()
        height = int(url.rsplit("hash", 1)[1])
        return json.dumps({"merkle_root": self.roots[height], "timestamp": 1_759_500_000}).encode()


@pytest.fixture
def calendars(monkeypatch) -> Calendars:
    fake = Calendars()
    monkeypatch.setenv(anchor.CALENDARS_ENV, f"{ALICE},{BOB}")
    monkeypatch.setattr(anchor, "remote", fake)
    monkeypatch.setattr(anchor, "_get", fake.explorer)
    return fake


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data.csv").write_text("a,b\n1,2\n")
    assert cli.main(["init"]) == 0
    assert cli.main(["seal", "data.csv"]) == 0
    return tmp_path / ".results" / "ledger.jsonl"


def test_a_stamp_is_pending_until_mined_and_then_dates_the_whole_chain(project, calendars, capsys):
    assert cli.main(["timestamp"]) == 0
    capsys.readouterr()
    cli.main(["verify"])
    assert "events 1–2 stamped, pending at 2 calendars" in capsys.readouterr().out

    calendars.mine(915_000)
    assert cli.main(["timestamp"]) == 0
    assert "events 1–2 existed by Bitcoin block 915000" in capsys.readouterr().out
    assert cli.main(["verify"]) == 0
    assert "events 1–2 dated by Bitcoin block 915000" in capsys.readouterr().out


def test_stamping_the_same_head_twice_makes_one_proof(project, calendars):
    cli.main(["timestamp"])
    cli.main(["timestamp"])

    assert len(list((project.parent / "timestamps").glob("*.ots"))) == 1


def test_a_ledger_rewritten_with_its_anchor_after_a_stamp_is_reported(project, calendars, capsys):
    cli.main(["timestamp"])
    # The owner's rewrite: same length, a different second event, chain and anchor both
    # consistent. `results verify` alone passes this.
    project.unlink()
    ledger.anchor_path(project).unlink()
    (project.parent.parent / "data.csv").write_text("a,b\n9,9\n")
    ledger.append_event(project, {"event": "init"})
    ledger.append_event(project, {"event": "seal", "files": []})
    capsys.readouterr()

    assert cli.main(["verify"]) == 1
    out = capsys.readouterr().out
    assert "TIMESTAMP CONTRADICTS THE CHAIN" in out
    assert "000002-" in out


def test_a_ledger_truncated_and_reanchored_after_a_stamp_is_reported(project, calendars, capsys):
    (project.parent.parent / "more.csv").write_text("x\n")
    cli.main(["seal", "more.csv"])
    cli.main(["timestamp"])
    lines = project.read_text().splitlines(keepends=True)
    project.write_text("".join(lines[:-1]))
    ledger.anchor_path(project).unlink()
    assert cli.main(["reanchor"]) == 0
    capsys.readouterr()

    assert cli.main(["verify"]) == 1
    assert "dates a chain of 3 events, and the ledger holds 2" in capsys.readouterr().out


def test_a_damaged_chain_is_not_stamped(project, calendars, capsys):
    project.write_text(project.read_text().replace('"seal"', '"sealed"'))

    assert cli.main(["timestamp"]) == 2
    assert not (project.parent / "timestamps").exists()


def test_with_no_calendar_reachable_nothing_is_written_and_verify_says_there_is_no_date(
    project, monkeypatch, capsys
):
    monkeypatch.setenv(anchor.CALENDARS_ENV, "")

    assert cli.main(["timestamp"]) == 1
    capsys.readouterr()
    cli.main(["verify"])
    assert "no outside timestamp" in capsys.readouterr().out
