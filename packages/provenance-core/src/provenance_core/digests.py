"""Content addresses: hashing a file, and hashing a string.

Four packages hashed independently before this module existed, and the copies had drifted.
Two read the file in 1 MB blocks and one in 64 KB; one encoded a string with a bare
`.encode()` and the others named UTF-8 explicitly. Neither difference changed a digest on the
machines this ran on, which is what made them survive: a divergence that produces the same
answer today is the kind that produces a different one later, on a platform whose default
encoding is not UTF-8, and then two tools disagree about whether a file is the pinned one.
"""

from __future__ import annotations

import hashlib
import pathlib

#: The prev_hash of a chain's first entry: a digest that addresses nothing.
ZERO = "0" * 64

#: Read size. Large enough that hashing a PDF is not dominated by syscalls, small enough that
#: a multi-gigabyte artifact does not have to fit in memory.
_BLOCK = 1 << 20


def sha256_of_file(path: pathlib.Path) -> str:
    """Hash of a file on disk, streamed so a large artifact is never held in memory."""
    h = hashlib.sha256()
    with pathlib.Path(path).open("rb") as fh:
        for block in iter(lambda: fh.read(_BLOCK), b""):
            h.update(block)
    return h.hexdigest()


def sha256_of_text(text: str) -> str:
    """Hash of a string, encoded as UTF-8.

    The encoding is named rather than left to `str.encode()`'s default, because a digest that
    depends on a platform default is not a content address.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


__all__ = ["ZERO", "sha256_of_file", "sha256_of_text"]


#: Names skipped by default when hashing a tree, and recorded on the result so a digest always
#: says what it did not cover. Filesystem and editor droppings, not data: a `.DS_Store` differs
#: between two checkouts of the same dataset, and letting it into the digest means two people
#: sealing the same data disagree for a reason neither can see.
NOISE: frozenset[str] = frozenset(
    {".DS_Store", "Thumbs.db", "__pycache__", ".ipynb_checkpoints"}
)


def sha256_of_tree(
    root: pathlib.Path, skip: frozenset[str] = NOISE
) -> tuple[str, list[tuple[str, str]], list[str]]:
    """Digest of a directory as a unit, with the files it covered and the names it skipped.

    A dataset is a directory, and `sha256_of_file` cannot address one. Enumerating the files by
    hand instead is where this goes wrong in practice: a file added afterwards is simply absent
    from the record, and nothing notices, so the seal looks complete and is not.

    The digest covers **relative paths as well as contents**. Renaming a file, or moving it to
    another directory, changes it -- a set of bytes is not the same dataset when its labels have
    been reshuffled, and hashing contents alone would call the two identical. Paths are sorted
    before hashing, so the order the filesystem happens to return entries in cannot change the
    answer.

    Returns the digest, the `(relative path, file digest)` pairs it covered, and the names it
    skipped. The skipped list is returned rather than discarded because a digest that quietly
    ignored something is a digest whose meaning differs between two machines: the caller records
    it, and a reader can see the seal's own boundary.

    An empty directory contributes nothing. It has no bytes and no reader can tell whether it
    ever existed, so a seal cannot promise it either way.
    """
    root = pathlib.Path(root)
    covered: list[tuple[str, str]] = []
    skipped: list[str] = []
    for path in sorted(p for p in root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        if any(part in skip for part in path.relative_to(root).parts):
            if path.is_file():
                skipped.append(rel)
            continue
        if path.is_symlink() or not path.is_file():
            # A symlink is a name pointing elsewhere, and following it would put bytes from
            # outside the tree under a digest that claims to address the tree.
            if path.is_symlink():
                skipped.append(rel)
            continue
        covered.append((rel, sha256_of_file(path)))

    h = hashlib.sha256()
    for rel, digest in covered:
        # The path and its digest, each length-prefixed, so no two different trees can produce
        # one byte sequence: without a separator, `("ab", d1), ("c", d2)` and `("a", d1),
        # ("bc", d2)` would hash alike.
        h.update(f"{len(rel)}:{rel}\x00{digest}\n".encode())
    return h.hexdigest(), covered, skipped
