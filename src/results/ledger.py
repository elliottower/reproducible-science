"""Append-only JSONL ledger: every event is one line, hash-chained to the previous."""
from __future__ import annotations

import datetime
import hashlib
import json
import pathlib


LEDGER = "ledger.jsonl"


def sha256_of_file(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_of_str(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def last_hash(ledger: pathlib.Path) -> str:
    """The hash of the last line as stored, or a zero hash if the ledger is empty."""
    if not ledger.exists() or ledger.stat().st_size == 0:
        return "0" * 64
    with open(ledger, "rb") as f:
        last = b""
        for line in f:
            if line.strip():
                last = line
    return sha256_of_str(last.decode().strip())


def append_event(ledger: pathlib.Path, event: dict) -> dict:
    """Write one event to the ledger. Returns the event with chain fields added."""
    event["timestamp"] = now_iso()
    event["prev_hash"] = last_hash(ledger)
    line = json.dumps(event, separators=(",", ":"), sort_keys=True)
    with open(ledger, "a") as f:
        f.write(line + "\n")
    return event


def read_ledger(ledger: pathlib.Path) -> list[dict]:
    if not ledger.exists():
        return []
    events = []
    for line in ledger.read_text().splitlines():
        line = line.strip()
        if line:
            events.append(json.loads(line))
    return events


def verify_chain(ledger: pathlib.Path) -> tuple[bool, list[str]]:
    """Check that every line's prev_hash matches the hash of the previous line as stored."""
    if not ledger.exists():
        return True, []
    lines = [ln.strip() for ln in ledger.read_text().splitlines() if ln.strip()]
    if not lines:
        return True, []
    problems = []
    prev = "0" * 64
    for i, raw in enumerate(lines):
        ev = json.loads(raw)
        if ev.get("prev_hash") != prev:
            problems.append(
                f"line {i + 1}: prev_hash mismatch — expected {prev[:16]}…, "
                f"got {ev.get('prev_hash', '???')[:16]}…")
        prev = sha256_of_str(raw)
    return len(problems) == 0, problems
