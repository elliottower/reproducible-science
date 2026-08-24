"""Tests for the append-only hash-chained ledger."""

from __future__ import annotations

import json

from results import ledger


def test_empty_ledger_has_zero_hash(tmp_path):
    lp = tmp_path / "ledger.jsonl"
    lp.touch()
    assert ledger.last_hash(lp) == "0" * 64


def test_append_and_read_round_trips(tmp_path):
    lp = tmp_path / "ledger.jsonl"
    lp.touch()
    ledger.append_event(lp, {"event": "init"})
    ledger.append_event(lp, {"event": "seal", "files": [{"path": "x.py", "sha256": "abc"}]})
    events = ledger.read_ledger(lp)
    assert len(events) == 2
    assert events[0]["event"] == "init"
    assert events[1]["event"] == "seal"


def test_chain_verification_passes_on_clean_ledger(tmp_path):
    lp = tmp_path / "ledger.jsonl"
    lp.touch()
    for i in range(5):
        ledger.append_event(lp, {"event": "test", "i": i})
    ok, problems = ledger.verify_chain(lp)
    assert ok
    assert problems == []


def test_chain_verification_catches_tampering(tmp_path):
    lp = tmp_path / "ledger.jsonl"
    lp.touch()
    ledger.append_event(lp, {"event": "init"})
    ledger.append_event(lp, {"event": "seal"})
    ledger.append_event(lp, {"event": "run"})

    lines = lp.read_text().splitlines()
    tampered = json.loads(lines[1])
    tampered["event"] = "TAMPERED"
    lines[1] = json.dumps(tampered, separators=(",", ":"), sort_keys=True)
    lp.write_text("\n".join(lines) + "\n")

    ok, problems = ledger.verify_chain(lp)
    assert not ok
    # `len(problems) >= 1` said nothing about which line, so a report naming the wrong event
    # satisfied it. The edited line is the second, and the break shows on the third, whose
    # prev_hash no longer matches.
    assert any("line 3" in p for p in problems), problems
    assert ledger.verify(lp)[0] is ledger.ChainStatus.EDITED


def test_sha256_of_file_is_deterministic(tmp_path):
    f = tmp_path / "data.txt"
    f.write_text("hello world\n")
    h1 = ledger.sha256_of_file(f)
    h2 = ledger.sha256_of_file(f)
    assert h1 == h2
    assert len(h1) == 64


def test_first_event_prev_hash_is_zero(tmp_path):
    lp = tmp_path / "ledger.jsonl"
    lp.touch()
    ev = ledger.append_event(lp, {"event": "init"})
    assert ev["prev_hash"] == "0" * 64


def test_second_event_prev_hash_chains_to_first(tmp_path):
    lp = tmp_path / "ledger.jsonl"
    lp.touch()
    ledger.append_event(lp, {"event": "first"})
    ev2 = ledger.append_event(lp, {"event": "second"})
    first_line = lp.read_text().splitlines()[0].strip()
    assert ev2["prev_hash"] == ledger.sha256_of_str(first_line)


def test_verify_catches_inserted_line(tmp_path):
    lp = tmp_path / "ledger.jsonl"
    lp.touch()
    ledger.append_event(lp, {"event": "first"})
    ledger.append_event(lp, {"event": "second"})
    lines = lp.read_text().splitlines()
    injected = '{"event":"injected","prev_hash":"fake","timestamp":"2026-01-01T00:00:00+00:00"}'
    lines.insert(1, injected)
    lp.write_text("\n".join(lines) + "\n")
    ok, _problems = ledger.verify_chain(lp)
    assert not ok
