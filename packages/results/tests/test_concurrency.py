"""Concurrent appends to one ledger.

Two callers that read the same tail compute the same `seq` and the same `prev_hash`, so the chain
takes two lines claiming one position. Verification reports `edited`, and `reanchor` refuses an
edited chain, which leaves the ledger permanently unrepairable. An orchestrator running two
analyses at once is enough to cause it, so these assert the chain survives contention rather than
that the lock exists.
"""

from __future__ import annotations

import threading

from results import ledger


def _append_from_threads(lp, threads: int, per_thread: int) -> list[BaseException]:
    failures: list[BaseException] = []
    barrier = threading.Barrier(threads)

    def worker(n: int) -> None:
        barrier.wait(timeout=30)
        for i in range(per_thread):
            try:
                ledger.append_event(lp, {"event": "run", "thread": n, "i": i})
            except BaseException as e:
                failures.append(e)

    workers = [threading.Thread(target=worker, args=(n,)) for n in range(threads)]
    for w in workers:
        w.start()
    for w in workers:
        w.join(timeout=60)
    return failures


def test_concurrent_appends_leave_an_intact_chain(tmp_path):
    lp = tmp_path / "ledger.jsonl"
    lp.touch()
    threads, per_thread = 16, 8

    failures = _append_from_threads(lp, threads, per_thread)

    assert failures == []
    status, problems = ledger.verify(lp)
    assert (status, problems) == (ledger.ChainStatus.INTACT, [])


def test_concurrent_appends_lose_no_event(tmp_path):
    lp = tmp_path / "ledger.jsonl"
    lp.touch()
    threads, per_thread = 16, 8

    _append_from_threads(lp, threads, per_thread)

    events = ledger.read_ledger(lp)
    assert len(events) == threads * per_thread
    assert [e["seq"] for e in events] == list(range(threads * per_thread))


def test_every_concurrent_event_is_recorded_once(tmp_path):
    lp = tmp_path / "ledger.jsonl"
    lp.touch()
    threads, per_thread = 16, 8

    _append_from_threads(lp, threads, per_thread)

    events = ledger.read_ledger(lp)
    written = sorted((e["thread"], e["i"]) for e in events)
    expected = sorted((n, i) for n in range(threads) for i in range(per_thread))
    assert written == expected


def test_the_anchor_matches_the_ledger_after_contention(tmp_path):
    lp = tmp_path / "ledger.jsonl"
    lp.touch()

    _append_from_threads(lp, 12, 6)

    anchor = ledger.read_anchor(lp)
    lines = lp.read_text(encoding="utf-8").splitlines()
    assert anchor["count"] == len(lines)
    assert anchor["head"] == ledger.sha256_of_str(lines[-1])


def test_a_reanchor_racing_appends_leaves_the_chain_verifiable(tmp_path):
    lp = tmp_path / "ledger.jsonl"
    lp.touch()
    ledger.append_event(lp, {"event": "init"})
    stop = threading.Event()

    def reanchor_repeatedly() -> None:
        while not stop.is_set():
            ledger.reanchor(lp)

    spinner = threading.Thread(target=reanchor_repeatedly, daemon=True)
    spinner.start()
    try:
        _append_from_threads(lp, 8, 6)
    finally:
        stop.set()
        spinner.join(timeout=10)

    ledger.reanchor(lp)
    status, problems = ledger.verify(lp)
    assert (status, problems) == (ledger.ChainStatus.INTACT, [])


APPEND_IN_CHILD = """
import sys
from pathlib import Path
from results import ledger

lp, n = Path(sys.argv[1]), int(sys.argv[2])
for i in range(n):
    ledger.append_event(lp, {"event": "run", "proc": sys.argv[3], "i": i})
"""


def test_separate_processes_appending_leave_an_intact_chain(tmp_path):
    # The case this guards against is two processes, not two threads: an orchestrator running two
    # skills, or a rerun started before the last one finished. `flock` is held per open file
    # description, so a threaded test exercises the same exclusion -- but only a process test
    # shows it holding across the interpreter boundary the real failure crosses.
    import subprocess
    import sys

    lp = tmp_path / "ledger.jsonl"
    lp.touch()
    script = tmp_path / "append.py"
    script.write_text(APPEND_IN_CHILD)
    per_process, processes = 6, 6

    running = [
        subprocess.Popen(
            [sys.executable, str(script), str(lp), str(per_process), f"p{n}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        for n in range(processes)
    ]
    for proc in running:
        _, err = proc.communicate(timeout=120)
        assert proc.returncode == 0, err.decode()[-2000:]

    status, problems = ledger.verify(lp)
    assert (status, problems) == (ledger.ChainStatus.INTACT, [])
    assert len(ledger.read_ledger(lp)) == per_process * processes
