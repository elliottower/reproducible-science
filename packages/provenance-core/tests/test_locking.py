"""Tests for the exclusive lock and the atomic replace."""

from __future__ import annotations

import os
import pathlib
import stat
import threading

import pytest

from provenance_core import (
    LOCK_SUFFIX,
    TMP_SUFFIX,
    atomic_write,
    exclusive_lock,
    lock_path,
    sha256_of_tree,
    shared_lock,
)


def test_lock_file_sits_beside_the_path_it_governs(tmp_path):
    target = tmp_path / "ledger.jsonl"
    assert lock_path(target) == tmp_path / f"ledger.jsonl{LOCK_SUFFIX}"


def test_lock_is_released_when_the_block_exits(tmp_path):
    target = tmp_path / "record"
    with exclusive_lock(target):
        pass
    acquired = threading.Event()

    def take():
        with exclusive_lock(target):
            acquired.set()

    t = threading.Thread(target=take)
    t.start()
    t.join(timeout=5)
    assert acquired.is_set()


def test_lock_is_released_when_the_block_raises(tmp_path):
    target = tmp_path / "record"
    with pytest.raises(ValueError), exclusive_lock(target):
        raise ValueError("boom")
    acquired = threading.Event()

    def take():
        with exclusive_lock(target):
            acquired.set()

    t = threading.Thread(target=take)
    t.start()
    t.join(timeout=5)
    assert acquired.is_set()


def test_a_second_thread_waits_for_the_holder(tmp_path):
    target = tmp_path / "record"
    order: list[str] = []
    holding = threading.Event()
    may_release = threading.Event()

    def first():
        with exclusive_lock(target):
            order.append("first in")
            holding.set()
            may_release.wait(timeout=5)
            order.append("first out")

    def second():
        holding.wait(timeout=5)
        may_release.set()
        with exclusive_lock(target):
            order.append("second in")

    a, b = threading.Thread(target=first), threading.Thread(target=second)
    a.start()
    b.start()
    a.join(timeout=5)
    b.join(timeout=5)
    assert order == ["first in", "first out", "second in"]


def test_nesting_the_lock_in_one_thread_does_not_deadlock(tmp_path):
    target = tmp_path / "record"
    done = threading.Event()

    def nest():
        # Deliberately nested rather than combined: taking the lock twice in sequence is the
        # thing under test, and one `with` holding two contexts would not exercise re-entry.
        with exclusive_lock(target):  # noqa: SIM117
            with exclusive_lock(target):
                pass
        done.set()

    t = threading.Thread(target=nest, daemon=True)
    t.start()
    t.join(timeout=5)
    assert done.is_set()


def test_the_lock_is_still_held_after_an_inner_block_exits(tmp_path):
    # A re-entrant hold must not be released by the inner block: the count goes back to one, not
    # to zero. Observed from inside the outer hold, because once it exits the other thread is
    # free to acquire and a check after the join would race with it.
    target = tmp_path / "record"
    inner_done = threading.Event()
    other_got_in = threading.Event()
    observed: list[bool] = []

    def outer():
        with exclusive_lock(target):
            with exclusive_lock(target):
                pass
            inner_done.set()
            other_got_in.wait(timeout=0.5)
            observed.append(other_got_in.is_set())

    def other():
        inner_done.wait(timeout=5)
        with exclusive_lock(target):
            other_got_in.set()

    a, b = (
        threading.Thread(target=outer, daemon=True),
        threading.Thread(target=other, daemon=True),
    )
    a.start()
    b.start()
    a.join(timeout=10)
    b.join(timeout=10)
    assert observed == [False]
    assert other_got_in.is_set()


def test_lock_works_when_the_governed_path_does_not_exist(tmp_path):
    target = tmp_path / "not-created-yet.jsonl"
    with exclusive_lock(target):
        pass
    assert not target.exists()


def test_atomic_write_replaces_the_contents(tmp_path):
    p = tmp_path / "plan.md"
    p.write_text("old")
    atomic_write(p, "new")
    assert p.read_text() == "new"


def test_atomic_write_creates_a_missing_file(tmp_path):
    p = tmp_path / "plan.md"
    atomic_write(p, "first")
    assert p.read_text() == "first"


def test_atomic_write_leaves_the_old_contents_when_the_write_fails(
    tmp_path, monkeypatch
):
    p = tmp_path / "plan.md"
    p.write_text("the frozen plan")

    real_replace = os.replace

    def fail_before_replacing(_src, _dst):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(os, "replace", fail_before_replacing)
    with pytest.raises(OSError):
        atomic_write(p, "a replacement that never lands")
    monkeypatch.setattr(os, "replace", real_replace)

    assert p.read_text() == "the frozen plan"


def test_atomic_write_leaves_no_temporary_file_behind_on_failure(tmp_path, monkeypatch):
    p = tmp_path / "plan.md"
    p.write_text("the frozen plan")
    monkeypatch.setattr(
        os, "replace", lambda _src, _dst: (_ for _ in ()).throw(OSError("nope"))
    )
    with pytest.raises(OSError):
        atomic_write(p, "never lands")
    assert [q.name for q in tmp_path.iterdir()] == ["plan.md"]


def test_many_threads_writing_under_the_lock_never_interleave(tmp_path):
    # Each thread appends its own line while holding the lock. Without mutual exclusion the
    # read-modify-write below loses updates, so the count is the assertion.
    target = tmp_path / "counter"
    target.write_text("")
    threads = 24
    per_thread = 20

    def bump():
        for _ in range(per_thread):
            with exclusive_lock(target):
                text = target.read_text()
                atomic_write(target, text + "x")

    workers = [threading.Thread(target=bump) for _ in range(threads)]
    for w in workers:
        w.start()
    for w in workers:
        w.join(timeout=30)
    assert len(target.read_text()) == threads * per_thread


def test_lock_path_of_a_relative_path_stays_relative(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert lock_path(pathlib.Path("x/ledger.jsonl")) == pathlib.Path(
        f"x/ledger.jsonl{LOCK_SUFFIX}"
    )


# --- the suffixes are distinctive on purpose --------------------------------------------------


def test_the_lock_suffix_cannot_collide_with_a_dependency_lockfile():
    # A tree digest has to skip these. `*.lock` would have taken `uv.lock` with it, dropping a
    # file that pins an environment out of a seal without saying so.
    assert not "uv.lock".endswith(LOCK_SUFFIX)
    assert not "conda-lock.yml".endswith(TMP_SUFFIX)


# --- a lock inside a sealed directory does not change its digest -------------------------------


def test_a_lock_taken_inside_a_sealed_directory_leaves_its_digest_alone(tmp_path):
    (tmp_path / "data.csv").write_text("a,b\n1,2\n")
    sealed, _, _ = sha256_of_tree(tmp_path)

    with exclusive_lock(tmp_path / "data.csv"):
        during, _, _ = sha256_of_tree(tmp_path)

    assert during == sealed


def test_the_skipped_sidecar_is_reported_rather_than_hidden(tmp_path):
    (tmp_path / "data.csv").write_text("a,b\n1,2\n")
    with exclusive_lock(tmp_path / "data.csv"):
        _, _, skipped = sha256_of_tree(tmp_path)
    assert [s for s in skipped if s.endswith(LOCK_SUFFIX)]


def test_a_digest_still_covers_a_dependency_lockfile(tmp_path):
    (tmp_path / "uv.lock").write_text("version = 1\n")
    _, covered, _ = sha256_of_tree(tmp_path)
    assert [rel for rel, _ in covered] == ["uv.lock"]


# --- atomic_write keeps what a plain write would have kept --------------------------------------


def test_atomic_write_preserves_the_modes_of_an_existing_file(tmp_path):
    p = tmp_path / "plan.md"
    p.write_text("old")
    p.chmod(0o644)
    atomic_write(p, "new")
    assert stat.S_IMODE(p.stat().st_mode) == 0o644


def test_atomic_write_preserves_a_deliberately_narrow_mode(tmp_path):
    p = tmp_path / "token.env"
    p.write_text("old")
    p.chmod(0o600)
    atomic_write(p, "new")
    assert stat.S_IMODE(p.stat().st_mode) == 0o600


def test_a_new_file_is_not_created_owner_only(tmp_path):
    # `mkstemp` makes its file 0600 and `os.replace` keeps the replacement's mode, so every file
    # written this way was narrowed to owner-only. A reader in CI under another uid then lost
    # access to a record that had been readable.
    p = tmp_path / "fresh.md"
    atomic_write(p, "first")
    assert stat.S_IMODE(p.stat().st_mode) & 0o044


def test_atomic_write_goes_through_a_symlink_to_its_target(tmp_path):
    target = tmp_path / "real.md"
    target.write_text("old")
    link = tmp_path / "PREREG.md"
    link.symlink_to(target)

    atomic_write(link, "new")

    assert target.read_text() == "new"
    assert link.is_symlink()


def test_no_temporary_file_is_left_beside_the_record(tmp_path):
    p = tmp_path / "plan.md"
    atomic_write(p, "text")
    assert [q.name for q in tmp_path.iterdir()] == ["plan.md"]


# --- a fork must not inherit the belief that it holds a lock -----------------------------------


def test_a_forked_child_does_not_believe_it_holds_the_parents_lock(tmp_path):
    target = tmp_path / "record"
    with exclusive_lock(target):
        read_fd, write_fd = os.pipe()
        pid = os.fork()
        if pid == 0:
            # The child inherits the counter dict and the lock's descriptor. If it still thinks
            # it holds the lock at depth 1, it takes the fast path and reports that immediately.
            try:
                from provenance_core.locking import _depths

                os.close(read_fd)
                held = bool(_depths().get(lock_path(target).resolve()))
                os.write(write_fd, b"held" if held else b"free")
                os.close(write_fd)
            finally:
                os._exit(0)
        os.close(write_fd)
        answer = os.read(read_fd, 8)
        os.close(read_fd)
        os.waitpid(pid, 0)

    assert answer == b"free"


# --- a reader does not wait on a writer it is inside of ----------------------------------------


def test_a_shared_lock_inside_an_exclusive_hold_does_not_deadlock(tmp_path):
    target = tmp_path / "record"
    done = threading.Event()

    def nest():
        with exclusive_lock(target), shared_lock(target):
            pass
        done.set()

    t = threading.Thread(target=nest, daemon=True)
    t.start()
    t.join(timeout=5)
    assert done.is_set()


def test_two_readers_do_not_exclude_each_other(tmp_path):
    target = tmp_path / "record"
    target.write_text("x")
    both_in = threading.Barrier(2, timeout=5)
    ok = []

    def read():
        with shared_lock(target):
            both_in.wait()
            ok.append(True)

    a, b = threading.Thread(target=read), threading.Thread(target=read)
    a.start()
    b.start()
    a.join(timeout=10)
    b.join(timeout=10)
    assert ok == [True, True]


def test_atomic_write_bytes_leaves_the_old_contents_when_it_fails(
    tmp_path, monkeypatch
):
    from provenance_core import atomic_write_bytes

    p = tmp_path / "refs.bib"
    p.write_bytes(b"@article{a,\n  title = {A},\n}\n")
    monkeypatch.setattr(
        os, "replace", lambda _src, _dst: (_ for _ in ()).throw(OSError("nope"))
    )
    with pytest.raises(OSError):
        atomic_write_bytes(p, b"@article{a,\n  title = {A},\n}\n@article{b,")
    assert p.read_bytes().endswith(b"}\n")


def test_atomic_write_bytes_preserves_the_mode(tmp_path):
    from provenance_core import atomic_write_bytes

    p = tmp_path / "refs.bib"
    p.write_bytes(b"x")
    p.chmod(0o644)
    atomic_write_bytes(p, b"y")
    assert stat.S_IMODE(p.stat().st_mode) == 0o644
