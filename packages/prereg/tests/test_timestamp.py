"""A freeze is dated by a party outside the repository: the OpenTimestamps calendars, then Bitcoin."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess

import pytest
from opentimestamps.core.notary import BitcoinBlockHeaderAttestation, PendingAttestation
from opentimestamps.core.op import OpSHA256
from opentimestamps.core.timestamp import Timestamp
from prereg import cli
from provenance_core import anchor
from provenance_core.gitref import clean_env

ALICE = "https://alice.btc.calendar.opentimestamps.org"
BOB = "https://bob.btc.calendar.opentimestamps.org"
BLOCK_TIME = 1_759_500_000  # 2025-10-03 14:00 UTC


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
        return json.dumps({"merkle_root": self.roots[height], "timestamp": BLOCK_TIME}).encode()


@pytest.fixture
def calendars(monkeypatch) -> Calendars:
    fake = Calendars()
    monkeypatch.setenv(anchor.CALENDARS_ENV, f"{ALICE},{BOB}")
    monkeypatch.setattr(anchor, "remote", fake)
    monkeypatch.setattr(anchor, "_get", fake.explorer)
    return fake


def git(*args, cwd):
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
        cwd=cwd,
        env=clean_env(),
        check=True,
        capture_output=True,
    )


@pytest.fixture
def plan(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    git("init", "-q", cwd=tmp_path)
    assert cli.main(["new", "study"]) == 0
    git("add", "-A", cwd=tmp_path)
    git("commit", "-q", "-m", "plan", cwd=tmp_path)
    monkeypatch.chdir(tmp_path / "study")
    return tmp_path / "study" / "PREREG.md"


def frozen_digest(path) -> str:
    return re.search(r"\*\*Plan sha256:\*\* `([0-9a-f]{64})`", path.read_text()).group(1)


def test_a_freeze_leaves_a_pending_proof_of_exactly_the_frozen_digest(plan, calendars, capsys):
    assert cli.main(["freeze"]) == 0

    proof = plan.with_name("PREREG.md.ots").read_bytes()
    found = anchor.status(proof, frozen_digest(plan))
    assert found.pending == (ALICE, BOB)
    assert cli.main(["check"]) == 0
    assert "pending at 2 calendars" in capsys.readouterr().out


def test_timestamp_completes_the_proof_and_dates_it_by_the_block(plan, calendars, capsys):
    cli.main(["freeze"])
    assert cli.main(["timestamp"]) == 2, "nothing is mined yet, so nothing is dated"

    calendars.mine(915_000)
    capsys.readouterr()
    assert cli.main(["timestamp"]) == 0

    out = capsys.readouterr().out
    assert "Bitcoin block 915000, 2025-10-03 14:00 UTC" in out
    assert anchor.status(
        plan.with_name("PREREG.md.ots").read_bytes(), frozen_digest(plan)
    ).blocks == (915_000,)
    cli.main(["check"])
    assert "Bitcoin block 915000" in capsys.readouterr().out


def test_a_proof_belonging_to_another_plan_fails_the_check(plan, calendars, capsys):
    cli.main(["freeze"])
    other = hashlib.sha256(b"some other plan").hexdigest()
    plan.with_name("PREREG.md.ots").write_bytes(anchor.stamp(other))

    assert cli.main(["check"]) == 1
    assert "TIMESTAMP" in capsys.readouterr().out


def test_a_freeze_with_no_calendar_reachable_still_freezes_and_can_be_stamped_later(
    plan, calendars, monkeypatch, capsys
):
    monkeypatch.setenv(anchor.CALENDARS_ENV, "")
    assert cli.main(["freeze"]) == 0
    assert "not timestamped" in capsys.readouterr().out
    assert not plan.with_name("PREREG.md.ots").exists()

    monkeypatch.setenv(anchor.CALENDARS_ENV, f"{ALICE},{BOB}")
    assert cli.main(["timestamp"]) == 2
    assert anchor.status(plan.with_name("PREREG.md.ots").read_bytes(), frozen_digest(plan)).pending


def test_a_forced_refreeze_keeps_the_earlier_proof_under_its_own_digest(plan, calendars):
    cli.main(["freeze"])
    first = frozen_digest(plan)
    plan.write_text(plan.read_text().replace("## Study type", "## Study type\n\nObservational."))
    git("commit", "-q", "-am", "amend", cwd=plan.parent.parent)

    assert cli.main(["freeze", "--force", "--access", "no results seen"]) == 0

    kept = plan.with_name(f"PREREG.md.{first[:16]}.ots").read_bytes()
    assert anchor.status(kept, first).pending
    assert anchor.status(plan.with_name("PREREG.md.ots").read_bytes(), frozen_digest(plan)).pending
    assert frozen_digest(plan) != first


def test_no_timestamp_sends_nothing(plan, calendars, monkeypatch):
    sent: list[str] = []
    monkeypatch.setattr(anchor, "remote", lambda url: sent.append(url))

    assert cli.main(["freeze", "--no-timestamp"]) == 0

    assert sent == []
    assert not plan.with_name("PREREG.md.ots").exists()
