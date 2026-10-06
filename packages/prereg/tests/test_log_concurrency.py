"""Concurrent entries in one plan's log.

`append` rewrites the whole file, so two callers that read the same text each write a file holding
only their own entry and the second erases the first. The loss is silent: the chain covers the
entries that remain, so what survives verifies cleanly and reports nothing missing. A deviation
that vanishes without a trace is the one failure this log exists to prevent, so these assert every
entry survives contention.
"""

from __future__ import annotations

import os
import threading

from prereg import log

PLAN = """# Does the lock hold?

**Status:** frozen
**Plan sha256:** `{}`

## Hypotheses

**H1.** Every logged entry survives.
""".format("0" * 64)


def _append_from_threads(path, threads: int) -> list[BaseException]:
    failures: list[BaseException] = []
    barrier = threading.Barrier(threads)

    def worker(n: int) -> None:
        barrier.wait(timeout=30)
        try:
            log.append(path, "2026-09-24", f"deviation {n:03d}", "nothing run")
        except BaseException as e:
            failures.append(e)

    workers = [threading.Thread(target=worker, args=(n,)) for n in range(threads)]
    for w in workers:
        w.start()
    for w in workers:
        w.join(timeout=60)
    return failures


def test_concurrent_entries_are_all_recorded(tmp_path):
    path = tmp_path / "PREREG.md"
    path.write_text(PLAN)
    threads = 16

    failures = _append_from_threads(path, threads)

    assert failures == []
    text = path.read_text()
    for n in range(threads):
        assert f"deviation {n:03d}" in text


def test_the_log_chain_verifies_after_contention(tmp_path):
    path = tmp_path / "PREREG.md"
    path.write_text(PLAN)

    _append_from_threads(path, 16)

    assert log.log_problems(path.read_text()) == []


def test_the_log_anchor_counts_every_concurrent_entry(tmp_path):
    path = tmp_path / "PREREG.md"
    path.write_text(PLAN)
    threads = 16

    _append_from_threads(path, threads)

    count, _ = log.log_head(path.read_text())
    assert count == threads


def test_the_plan_above_the_log_is_untouched_by_concurrent_entries(tmp_path):
    path = tmp_path / "PREREG.md"
    path.write_text(PLAN)

    _append_from_threads(path, 16)

    assert "**H1.** Every logged entry survives." in path.read_text()


def _another_thread_can_take(path) -> bool:
    """Whether a thread other than this one can acquire the plan's lock right now.

    Asked from inside a freeze, between its read and its write. A racing end-to-end test answered
    the same question by luck -- it passed against the unlocked code because the freeze happened
    to finish first -- so the exclusion is asserted directly instead.
    """
    import fcntl

    from provenance_core import lock_path

    got: list[bool] = []

    def probe() -> None:
        fd = os.open(lock_path(path), os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            got.append(True)
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            got.append(False)
        finally:
            os.close(fd)

    t = threading.Thread(target=probe)
    t.start()
    t.join(timeout=10)
    return got == [True]


def test_a_freeze_excludes_other_writers_between_its_read_and_its_write(tmp_path, monkeypatch):
    # `cmd_freeze` read the plan, then wrote the whole file back. A `prereg log` landing between
    # the two was erased, and `set_log_anchor` ran over the stale text as well, so the surviving
    # chain and its `**Log:** N entries` anchor agreed and `check` reported nothing missing.
    # Freeze was bypassing the lock that `log.append` itself takes.
    import subprocess

    from prereg import cli, record
    from provenance_core.gitref import clean_env

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True, env=clean_env())
    monkeypatch.chdir(tmp_path)
    assert cli.main(["new", "study"]) == 0
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True, env=clean_env())
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "init"],
        cwd=tmp_path,
        check=True,
        env=clean_env(),
    )
    study = tmp_path / "study"
    monkeypatch.chdir(study)

    observed: list[bool] = []
    real = record.write

    def spy(*args, **kwargs):
        # Called after the plan has been read and before its freeze record is written.
        observed.append(_another_thread_can_take(study / "PREREG.md"))
        return real(*args, **kwargs)

    monkeypatch.setattr(cli.record, "write", spy)
    assert cli.main(["freeze"]) == 0

    assert observed == [False], "another writer could take the plan's lock mid-freeze"
