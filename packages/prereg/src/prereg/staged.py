"""What a pre-commit hook asks: does the git index hold a change to a frozen file?

Read-only on disk stops an accidental save, and git does not carry that flag to another machine.
A commit is the next place a change to a frozen file can be stopped, so this reads the index and
names every staged path whose frozen content differs from what was frozen, under the rule of the
format it was frozen in:

    a file frozen whole     the staged bytes against the digest in its freeze record
    a freeze record         any change to one already committed
    a log beside a plan     anything but entries added after the committed ones
    a log's anchor          a count lower than the committed one
    a plan frozen in place  the staged plan section against the digest committed in it
    a commit-line document  the staged text against the file at the commit it names

Nothing is installed. `prereg check --staged` is the command a hook runs.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import re
import subprocess

from provenance_core.gitref import try_run

from prereg import pinned, sidelog
from prereg.plan import PREREG, plan_of, sha256_of
from prereg.record import RECORDS

FROZEN_DIGEST = re.compile(r"^\*\*Plan sha256:\*\* `([0-9a-f]{64})`", re.M)


def _blob(spec: str) -> bytes | None:
    """The bytes git holds as `spec` (`:path` is the index, `HEAD:path` the last commit).

    Bytes, and so not through `gitref`, which returns stripped text: a digest of the whole file
    has to see its last newline.

    Git is asked from the working directory with the environment as it is, here and in `changes`.
    `git commit -a` and `git commit <path>` build the commit in a temporary index and name it to
    the hook in `GIT_INDEX_FILE`; a call that dropped the variable would read the index the
    commit is not being made from.
    """
    done = subprocess.run(["git", "cat-file", "blob", spec], capture_output=True, check=False)
    return done.stdout if done.returncode == 0 else None


def _recorded(top: pathlib.Path, name: pathlib.Path) -> str | None:
    """The digest `name` was frozen whole with: from the index, or from disk where git has none."""
    record = name.parent / RECORDS / f"{name.name}.json"
    held = _blob(f":{record.as_posix()}")
    if held is None and (top / record).is_file():
        held = (top / record).read_bytes()
    try:
        return json.loads(held)["sha256"] if held else None
    except (ValueError, KeyError, TypeError):
        return None


def _finding(top: pathlib.Path, name: pathlib.Path) -> str | None:
    """Why the staged `name` is a change to something frozen, or None where it is not."""
    staged = _blob(f":{name.as_posix()}")
    committed = _blob(f"HEAD:{name.as_posix()}")
    if name.parent.name == RECORDS and name.suffix == ".json":
        return "a freeze record already committed" if committed not in (None, staged) else None

    if name.suffix == ".log" and _recorded(top, name.with_suffix(".md")) and committed is not None:
        was = sidelog.lines_of(committed.decode(errors="replace"))
        now = sidelog.lines_of((staged or b"").decode(errors="replace"))
        return (
            None
            if now[: len(was)] == was
            else "a log is append-only, and committed entries are gone"
        )
    if name.name.endswith(".log.head") and committed is not None:
        try:
            shorter = staged is None or (
                sidelog.read_anchor(staged.decode())[0] < sidelog.read_anchor(committed.decode())[0]
            )
        except ValueError:
            shorter = True
        return "a log's anchor, moved backwards" if shorter else None

    digest = _recorded(top, name)
    if digest is not None:
        if staged is None:
            return "frozen, and staged for removal"
        return None if hashlib.sha256(staged).hexdigest() == digest else "frozen whole"

    if name.suffix != ".md":
        return None
    removed = "frozen, and staged for removal"
    was = (committed or b"").decode(errors="replace")
    frozen = FROZEN_DIGEST.search(was)
    if frozen:
        if staged is None:
            return removed
        now = sha256_of(plan_of(staged.decode(errors="replace")))
        return None if now == frozen.group(1) else "frozen above its log line"

    # `check` leaves a `PREREG.md` to its own rule, so this does as well.
    if name.name == PREREG:
        return None
    if staged is None:
        return removed if pinned.split_record(was)[1] else None
    body, values, statuses = pinned.split_record(staged.decode(errors="replace"))
    if values and pinned.check_document(top, name, body, values, statuses).status == pinned.CHANGED:
        return "frozen by a commit line"
    return None


def changes() -> list[tuple[pathlib.Path, str]] | None:
    """Each staged path that changes something frozen, with why. None outside a repository."""
    root = try_run("rev-parse", "--show-toplevel")
    if root is None:
        return None
    top = pathlib.Path(root)
    listed = try_run("diff", "--cached", "--name-only", "--no-renames", "-z") or ""
    found = []
    for name in sorted(filter(None, listed.split("\0"))):
        why = _finding(top, pathlib.Path(name))
        if why:
            found.append((pathlib.Path(name), why))
    return found
