"""Serializing writes to an append-only record, and replacing a file without a torn window.

Both tools read a record, compute the next entry from what they read, and write it back. Two
callers that read the same state compute the same entry: the ledger takes two lines claiming one
position, and a plan's log takes one entry written over the other. The chain reports the ledger
case as `edited`, and re-anchoring refuses an edited chain, so that damage is permanent; the log
case loses an entry with nothing left to report it, which is worse. Neither case needs an
adversary. Two skills in one pipeline, or a rerun started before the last one finished, is enough.

An advisory lock held across read, compute and write makes the three one step. It lives on a
sidecar file rather than on the record, so taking it neither creates the record nor truncates it,
and the kernel drops it when the holder exits, so a crash leaves no lock to clear by hand.

The limits are the ones the record's threat model already states. An advisory lock binds only
writers that ask for one, and on a network filesystem it may not be honored at all, so this
prevents collision between cooperating writers and nothing else.
"""

from __future__ import annotations

import contextlib
import os
import pathlib
import stat
import tempfile
import threading
import time
from collections.abc import Iterator

try:
    import fcntl

    _msvcrt = None
except ImportError:  # Windows has no fcntl; msvcrt locks a byte range instead.
    fcntl = None  # type: ignore[assignment]
    try:
        import msvcrt as _msvcrt
    except ImportError:
        _msvcrt = None

#: The sidecar suffixes. Deliberately not `.lock` and `.tmp`: a tree digest has to skip these,
#: and skipping `*.lock` would drop `uv.lock` -- a file that pins an environment and belongs in a
#: seal -- out of the digest silently. A suffix nothing else uses cannot take a real record with it.
LOCK_SUFFIX = ".provenance-lock"
TMP_SUFFIX = ".provenance-tmp"

#: What a digest over a directory must ignore, since these appear and vanish around a write and say
#: nothing about the records themselves.
SIDECAR_SUFFIXES: frozenset[str] = frozenset({LOCK_SUFFIX, TMP_SUFFIX})

#: Windows has no indefinitely blocking lock: `LK_LOCK` retries for about ten seconds and then
#: raises. Retrying keeps the call blocking, as it is everywhere else.
_WINDOWS_RETRY_SECONDS = 300.0


class LockUnavailableError(RuntimeError):
    """This interpreter offers no file locking, so serialized writes cannot be guaranteed.

    Raised rather than returning an unlocked context. A lock that silently does nothing turns a
    corrupted record into an unreported one, which is the failure this module exists to prevent.
    """


def lock_path(path: pathlib.Path | str) -> pathlib.Path:
    """The sidecar file whose lock governs writes to `path`.

    A sidecar rather than the record itself, and not as a preference: `atomic_write` replaces the
    record by renaming another file over it, which swaps the inode. A lock taken on the record
    would stay with the old inode, and the next writer would open the new one and find it free.
    """
    path = pathlib.Path(path)
    return path.with_name(path.name + LOCK_SUFFIX)


def _acquire(fd: int) -> None:
    if fcntl is not None:
        fcntl.flock(fd, fcntl.LOCK_EX)
        return
    if _msvcrt is None:
        raise LockUnavailableError(
            "neither fcntl nor msvcrt is available on this interpreter"
        )
    deadline = time.monotonic() + _WINDOWS_RETRY_SECONDS
    while True:
        try:
            _msvcrt.locking(fd, _msvcrt.LK_LOCK, 1)
            return
        except OSError:
            if time.monotonic() >= deadline:
                raise


def _release(fd: int) -> None:
    if fcntl is not None:
        fcntl.flock(fd, fcntl.LOCK_UN)
    elif _msvcrt is not None:
        _msvcrt.locking(fd, _msvcrt.LK_UNLCK, 1)


#: Locks already held by *this thread*, by resolved lock path, with a re-entry count. Per-thread
#: rather than per-process: `flock` is taken on an open file description, so two threads that open
#: the lock file separately do exclude each other, and a process-wide count would let the second
#: skip a lock the first is holding.
_held = threading.local()


def _depths() -> dict[pathlib.Path, int]:
    depths = getattr(_held, "depths", None)
    if depths is None:
        depths = _held.depths = {}
    return depths


def _forget_held_locks() -> None:
    """Drop this thread's re-entrancy counters after a fork.

    A forked child inherits both the counter dict and the lock's open file description, and
    `flock` on an inherited description is genuinely held -- so the child would believe it holds
    a lock at depth 1, and releasing it would release the *parent's* lock. The child starts from
    nothing instead: it then blocks on a fresh descriptor, and a block is visible where a
    silently released lock is not. `multiprocessing` with the fork start method is the reachable
    case; these tools do not fork while holding one today.
    """
    _held.__dict__.clear()


os.register_at_fork(after_in_child=_forget_held_locks)


@contextlib.contextmanager
def exclusive_lock(path: pathlib.Path | str) -> Iterator[pathlib.Path]:
    """Hold the exclusive lock for `path`, blocking until it is free.

    Re-entrant within one thread, so a caller may take the lock and then call a function that
    takes it again to write several entries as one unit. Without that, the outer hold and the
    inner request are two open file descriptions on one file and the thread waits on itself
    forever.

    Yields the lock file's path, so a caller that wants to exclude it from a tree hash or a
    listing can name it rather than reconstruct it.
    """
    lock = lock_path(path)
    lock.parent.mkdir(parents=True, exist_ok=True)
    key = lock.resolve()
    depths = _depths()
    if depths.get(key):
        depths[key] += 1
        try:
            yield lock
        finally:
            depths[key] -= 1
        return

    fd = os.open(lock, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        _acquire(fd)
        depths[key] = 1
        try:
            yield lock
        finally:
            depths[key] = 0
            _release(fd)
    finally:
        os.close(fd)


@contextlib.contextmanager
def shared_lock(path: pathlib.Path | str) -> Iterator[pathlib.Path]:
    """Hold a shared lock for `path`, excluding writers but not other readers.

    An append writes its line and then its anchor, so a reader arriving between the two sees a
    ledger one line longer than the anchor records. Verification reports that as `extended`, which
    is correct about the bytes and wrong about the cause: nothing was damaged, a write was in
    flight. Without this a `results verify` running beside an append fails for a reason that
    disappears when it is run again, which is the worst kind of red.

    Yields without acquiring when this thread already holds the exclusive lock. `flock` conflicts
    between two open file descriptions even inside one process, so a writer that verifies while
    holding its own lock would otherwise wait on itself.
    """
    lock = lock_path(path)
    depths = _depths()
    if lock.exists() and depths.get(lock.resolve()):
        yield lock
        return
    lock.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        if fcntl is not None:
            fcntl.flock(fd, fcntl.LOCK_SH)
        try:
            yield lock
        finally:
            _release(fd)
    finally:
        os.close(fd)


def _mode_for(path: pathlib.Path) -> int:
    """The permissions the replacement should carry.

    `mkstemp` creates its file 0600 and `os.replace` keeps the replacement's mode, so writing this
    way silently narrowed every file it touched -- a registration, a ledger anchor, a records file
    -- from 0644 to owner-only. On a shared machine, or in CI running as another uid, the next
    reader loses access to a record that was readable before it was written.
    """
    if path.exists():
        return stat.S_IMODE(path.stat().st_mode)
    umask = os.umask(0)
    os.umask(umask)
    return 0o666 & ~umask


def atomic_write_bytes(path: pathlib.Path | str, data: bytes) -> None:
    """`atomic_write` for a file whose bytes are the record.

    A `.bib` is appended to by reading it whole and writing it back, and a torn write leaves an
    unclosed entry -- which the parser then blames on a defect that predates the addition, so the
    tool reports a problem in the author's bibliography that the tool itself created.
    """
    path = pathlib.Path(os.path.realpath(path))
    mode = _mode_for(path)
    fd, tmp = tempfile.mkstemp(
        dir=str(path.parent), prefix=path.name, suffix=TMP_SUFFIX
    )
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
        dir_fd = os.open(str(path.parent), os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        except OSError:
            pass
        finally:
            os.close(dir_fd)
    except BaseException:
        pathlib.Path(tmp).unlink(missing_ok=True)
        raise


def atomic_write(
    path: pathlib.Path | str, text: str, *, encoding: str = "utf-8"
) -> None:
    """Replace what `path` holds in one step, or leave the old contents untouched.

    A plain write truncates first and fills after, so a crash, a full disk or a killed process
    between the two leaves a half-written file. Where the file is a frozen registration or the
    anchor attesting a chain's length, that window destroys the record the tool exists to
    protect. Writing a sibling temporary file and renaming it means a reader sees the old
    contents or the new ones.

    The path is resolved first, so a symlinked record is written through to its target. Replacing
    the link would leave a regular file under the link's name while the target kept the old text,
    which is the shape where two readers disagree about what one record says. Hard links do not
    survive a replace: another name for the same inode keeps the old contents, and nothing can
    both swap atomically and preserve them.
    """
    path = pathlib.Path(os.path.realpath(path))
    mode = _mode_for(path)
    fd, tmp = tempfile.mkstemp(
        dir=str(path.parent), prefix=path.name, suffix=TMP_SUFFIX
    )
    try:
        with os.fdopen(fd, "w", encoding=encoding) as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
        # A rename is metadata, and metadata is not durable until the directory holding it is
        # flushed. Without this, a crash just after the replace can leave the old contents, so a
        # freeze that reported success is missing from the file afterwards.
        dir_fd = os.open(str(path.parent), os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        except OSError:
            # Not permitted on every filesystem. The replace has happened either way; only its
            # durability across a power loss is in question.
            pass
        finally:
            os.close(dir_fd)
    except BaseException:
        pathlib.Path(tmp).unlink(missing_ok=True)
        raise
