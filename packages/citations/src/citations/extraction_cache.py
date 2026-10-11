"""Extracted text kept between runs, addressed by the bytes read and the program that read them.

`pdftotext` over a source is most of what `citations verify` costs, and a source that has not
changed gives the same text every time the same `pdftotext` reads it. An entry is filed under a
digest of: the sha256 of the source's bytes, hashed immediately before the lookup; the
program's name and the version it reports; its arguments, with the source's path left out; and
the encoding its output is decoded with. A source whose bytes changed, a different poppler, or
a different flag is a different entry, so nothing is ever looked up by path or by date.

Off unless a caller turns it on. `citations verify` does, and `--no-cache` or `CITATIONS_NO_CACHE`
leaves it off. A library caller, `repro` among them, reads every source every time.

Only a successful, non-empty extraction is stored. A failure is a fact about this run's
toolchain and is found again by running it. An entry that cannot be read or written is treated
as absent: the cache can make a run faster and cannot make one fail.

The directory holds text extracted from the sources, so it belongs to the user and not to a
repository: `$CITATIONS_CACHE_DIR`, else `$XDG_CACHE_HOME/citations/extractions`, else
`~/.cache/citations/extractions`.
"""

from __future__ import annotations

import functools
import hashlib
import locale
import os
import pathlib
import subprocess
import tempfile

DIRECTORY_ENV = "CITATIONS_CACHE_DIR"
DISABLE_ENV = "CITATIONS_NO_CACHE"

#: Changed when the layout of an entry or the make-up of its address changes.
SCHEMA = "1"

#: Programs whose output is kept. A declared extractor this package does not know has no
#: version it can ask for, and without one a changed program would return an old reading.
CACHED_PROGRAMS = frozenset({"pdftotext"})

_VERSION_TIMEOUT = 10


class _State:
    directory: pathlib.Path | None = None
    hits = 0


def default_directory() -> pathlib.Path:
    if named := os.environ.get(DIRECTORY_ENV):
        return pathlib.Path(named).expanduser()
    base = os.environ.get("XDG_CACHE_HOME") or "~/.cache"
    return pathlib.Path(base).expanduser() / "citations" / "extractions"


def use(directory: pathlib.Path | None) -> None:
    """Keep extractions under `directory` from here on, or keep none. Resets the hit count."""
    _State.directory = directory
    _State.hits = 0


def use_default(disabled: bool = False) -> None:
    """What the command line asks for: the default directory unless told otherwise."""
    use(None if disabled or os.environ.get(DISABLE_ENV) else default_directory())


def enabled() -> bool:
    return _State.directory is not None


def hits() -> int:
    """How many extractions were returned from the cache since `use` was last called."""
    return _State.hits


@functools.lru_cache(maxsize=8)
def _version(program: str) -> str | None:
    """What the program says it is, or None where it will not say."""
    try:
        said = subprocess.run(
            [program, "-v"], capture_output=True, text=True, timeout=_VERSION_TIMEOUT
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    lines = (said.stderr or said.stdout).strip().splitlines()
    return lines[0].strip() if lines else None


def address(source_sha256: str, argv: list[str], source: pathlib.Path) -> str | None:
    """Where this extraction is filed, or None where it is not kept at all."""
    if _State.directory is None or not source_sha256:
        return None
    program = pathlib.Path(argv[0]).name
    if program not in CACHED_PROGRAMS:
        return None
    version = _version(argv[0])
    if version is None:
        return None
    arguments = ["{}" if part == str(source) else part for part in argv[1:]]
    described = [
        SCHEMA,
        source_sha256,
        program,
        version,
        locale.getpreferredencoding(False),
        *arguments,
    ]
    return hashlib.sha256("\x00".join(described).encode()).hexdigest()


def _path(key: str) -> pathlib.Path:
    assert _State.directory is not None
    return _State.directory / key[:2] / f"{key}.txt"


def get(key: str) -> str | None:
    try:
        text = _path(key).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    _State.hits += 1
    return text


def put(key: str, text: str) -> None:
    """File one extraction. Written beside its final name and moved, so a reader never sees half."""
    path = _path(key)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, suffix=".part", delete=False
        ) as handle:
            handle.write(text)
        os.replace(handle.name, path)
    except OSError:
        return
