"""What the repository's history says about a freeze record, which the files on disk cannot.

A freeze record names a digest and a commit, and the file on disk is compared with the digest.
Someone who edits the file and the digest together leaves a pair that agrees, so the disk alone
cannot show it. History can, in two ways:

    the file at the commit the record names     it holds the bytes the record says were frozen,
                                                because `freeze` refuses a file with uncommitted
                                                changes; where it does not, the record or the
                                                file was rewritten afterwards
    the record's own history                    a record is written once and committed once, so
                                                any later version of it, a deletion, or a record
                                                deleted and written again is a freeze that was
                                                made over

Both read only what git holds. A repository with no commit, a shallow clone and a commit this
repository does not hold leave nothing to compare, and say so without failing: none of them is
evidence of an edit. A history rewritten before anyone else fetched it is out of reach of any
local check; an outside timestamp is what dates a freeze against that.
"""

from __future__ import annotations

import hashlib
import pathlib
import re
import subprocess

from provenance_core.gitref import clean_env, try_run

from prereg import record

#: An earlier freeze's timestamp proof, which `freeze` keeps under its digest rather than
#: overwrite: `PREREG.md.0123456789abcdef.ots`.
EARLIER_PROOF = re.compile(r"\.([0-9a-f]{16})\.ots$")


def top_of(directory: pathlib.Path) -> pathlib.Path | None:
    """The top of the repository holding `directory`, or None outside one."""
    found = try_run("rev-parse", "--show-toplevel", cwd=directory)
    return pathlib.Path(found) if found else None


def blob(top: pathlib.Path, spec: str) -> bytes | None:
    """The bytes git holds as `spec` (`<commit>:<path>`), or None where it holds none.

    Bytes, and so not through `gitref`, which returns stripped text: a digest of the whole file
    has to see its last newline.
    """
    done = subprocess.run(
        ["git", "cat-file", "blob", spec],
        cwd=top,
        env=clean_env(),
        capture_output=True,
        check=False,
    )
    return done.stdout if done.returncode == 0 else None


def is_commit(top: pathlib.Path, commit: str) -> bool:
    return try_run("rev-parse", "--verify", "--quiet", f"{commit}^{{commit}}", cwd=top) is not None


def name_in(top: pathlib.Path, path: pathlib.Path) -> str | None:
    """`path` from the top of the repository, or None where it lies outside it."""
    try:
        return path.resolve().relative_to(top.resolve()).as_posix()
    except ValueError:
        return None


def versions(top: pathlib.Path, name: str) -> list[tuple[str, bytes | None]]:
    """Each commit that touched `name`, oldest first, with the bytes it left there: None where
    the commit removed the file."""
    listed = try_run("log", "--format=%H", "--full-history", "--", name, cwd=top)
    if not listed:
        return []
    return [(c, blob(top, f"{c}:{name}")) for c in reversed(listed.split())]


def at_commit(
    path: pathlib.Path, commit: str, digest: str, uncommitted: bool = False
) -> tuple[str | None, str | None]:
    """Compare the file at the commit a freeze record names with the digest it recorded.

    A problem where they differ, which fails the check, and otherwise a note where nothing
    could be compared, which does not: a freeze `--force` made from uncommitted bytes, a commit
    this repository does not hold, a file the commit does not contain.
    """
    if uncommitted:
        return None, f"frozen with --force from bytes that are not those of commit {commit[:12]}"
    top = top_of(path.parent)
    name = name_in(top, path) if top else None
    if top is None or name is None:
        return None, None
    if not is_commit(top, commit):
        return None, f"commit {commit[:12]} is not in this repository, so {name} was not read there"
    held = blob(top, f"{commit}:{name}")
    if held is None:
        return None, f"{name} is not in commit {commit[:12]}, so it was not read there"
    found = hashlib.sha256(held).hexdigest()
    if found == digest:
        return None, None
    return (
        f"{name} at commit {commit[:12]}, the commit the freeze record names, is not the file "
        f"the record says was frozen: {found[:16]}… there, {digest[:16]}… recorded",
        None,
    )


def _made_over(where: pathlib.Path, top: pathlib.Path, name: str) -> list[str]:
    """How the history of the record at `name`, and the record on disk, depart from one
    version committed once.

    A record deleted and later restored byte for byte is the same freeze, and is not reported.
    """
    found: list[str] = []
    last: bytes | None = None
    gone: str | None = None
    for commit, held in versions(top, name):
        if held is None:
            gone = gone or (commit if last is not None else None)
            continue
        if last is not None and held != last:
            how = f"deleted in commit {gone[:12]} and written again" if gone else "rewritten"
            found.append(f"{where.name} was {how} in commit {commit[:12]}")
        last, gone = held, None
    if last is not None and where.is_file() and where.read_bytes() != last:
        found.append(f"{where.name} on disk is not the version last committed")
    return found


def record_problems(path: pathlib.Path, digest: str) -> list[str]:
    """Where the history of `path`'s freeze record shows the freeze was made over, or the
    record on disk differs from the one committed. Empty where it was committed once, or
    never. `digest` is the digest the record holds now.

    A timestamp proof kept beside the file under another digest is the same finding, read
    from the disk: `freeze` keeps an earlier freeze's proof rather than overwrite it, and a
    file frozen whole is frozen once.
    """
    where = record.record_path(path)
    found: list[str] = []
    top = top_of(path.parent)
    name = name_in(top, where) if top else None
    if top is not None and name is not None:
        found += _made_over(where, top, name)
    for proof in sorted(path.parent.glob(f"{path.name}.*.ots")):
        earlier = EARLIER_PROOF.search(proof.name)
        if earlier and not digest.startswith(earlier.group(1)):
            found.append(
                f"{proof.name} is the timestamp of an earlier freeze, of {earlier.group(1)}…: "
                "the file was frozen before under another digest"
            )
    return found


def record_gone(path: pathlib.Path) -> str | None:
    """Why `path` reads as never frozen although history holds a freeze record of it, or None.

    A record removed from disk turns a frozen file back into a draft, and a draft is free to
    change, so a record that history holds and the disk does not is a finding.
    """
    where = record.record_path(path)
    if where.is_file():
        return None
    top = top_of(path.parent)
    name = name_in(top, where) if top else None
    if top is None or name is None:
        return None
    held = versions(top, name)
    committed = [c for c, data in held if data is not None]
    if not committed:
        return None
    if held[-1][1] is not None:
        return f"its freeze record {name}, committed in {committed[0][:12]}, is gone from disk"
    return f"its freeze record {name} was committed in {committed[0][:12]} and deleted since"
