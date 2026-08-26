"""Which program read the artifact, and what it produced.

`Backend.version` is a protocol version: a hand-written string naming the interface a backend
implements. It is not a version of anything that reads a file, and what a decision says
depends on the program that turns bytes into text or values. A `pdftotext` upgrade that
resolves a ligature differently changes an extracted passage while every digest in the
manifest stays where it was, so a report carrying only the protocol version records the same
provenance before and after.

Two ways a tool is identified:

  * a **binary**, by the version string it prints, kept as printed. Parsing it into fields
    discards the build metadata distributions attach, which is the part that separates two
    installations reporting the same upstream release.
  * an **installed distribution**, by `importlib.metadata`.

A version that cannot be obtained is `UNKNOWN`, never omitted. A field that disappears when a
tool declines to answer makes an uninterrogated toolchain indistinguishable from an absent
one, which is the confusion this package exists to prevent, one level down.

The executable's own digest is not recorded. `pdftotext` is a driver over `libpoppler`, so
hashing it addresses the part that does not do the reading while reading as a pin on the part
that does. `Decision.extraction_digest` covers the same ground without that gap: it hashes
what the extractor produced, which moves whenever the behaviour does.

Each answer is resolved once per process. Interrogating a binary per assertion would run a
subprocess per quotation.
"""

from __future__ import annotations

import functools
import subprocess
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _installed_version

UNKNOWN = "unknown"
"""Recorded where a version or a digest was sought and not obtained. Distinct from an empty
field, which says nothing was sought."""

VERSION_TIMEOUT = 10
"""Seconds to wait for a tool to say what it is. A tool that hangs is not identified, and
blocking a verification run on it would be worse than recording `UNKNOWN`."""


@functools.cache
def binary_version(name: str, flag: str = "-v") -> str:
    """The version string `name` prints, as it prints it, or `UNKNOWN`.

    Both streams are read: `pdftotext -v` writes to stderr and other extractors write to
    stdout, so a helper that picked one would record `unknown` for a tool that answered. The
    exit status is ignored for the same reason -- several builds exit non-zero from `-v` and
    print the version anyway.
    """
    try:
        completed = subprocess.run(
            [name, flag], capture_output=True, text=True, timeout=VERSION_TIMEOUT
        )
    except (OSError, subprocess.SubprocessError):
        return UNKNOWN
    for line in (completed.stdout + "\n" + completed.stderr).splitlines():
        if line.strip():
            return line.strip()
    return UNKNOWN


@functools.cache
def distribution_version(name: str) -> str:
    """The installed version of a distribution, or `UNKNOWN` where nothing provides it."""
    try:
        return _installed_version(name)
    except PackageNotFoundError:
        return UNKNOWN


__all__ = ["UNKNOWN", "VERSION_TIMEOUT", "binary_version", "distribution_version"]
