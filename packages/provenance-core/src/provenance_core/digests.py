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
