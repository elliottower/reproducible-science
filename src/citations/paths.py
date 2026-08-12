"""Where the library lives.

Resolution order, and nothing is written to a directory you did not name:

    $CITATIONS_HOME             if set
    ./.citations/ walking up    this project's own, the way git finds .git
    the user-level library      if one has been created
    nothing                     the caller says to run `citations init`

Project-local is the default because it is the least surprising: run the tool inside a paper
and it works on that paper, with no hidden global state and no wondering which library was
just written to.
"""
from __future__ import annotations

import os
import pathlib

DIRNAME = ".citations"


def user_library() -> pathlib.Path:
    """The per-user library, in the platform's data directory."""
    try:
        import platformdirs
        return pathlib.Path(platformdirs.user_data_dir("citations"))
    except ImportError:
        base = os.environ.get("XDG_DATA_HOME")
        if base:
            return pathlib.Path(base) / "citations"
        if os.uname().sysname == "Darwin":
            return pathlib.Path.home() / "Library" / "Application Support" / "citations"
        return pathlib.Path.home() / ".local" / "share" / "citations"


def find_with_origin(start: pathlib.Path | None = None) -> tuple[pathlib.Path | None, str]:
    """The library governing `start`, and which rule produced it.

    The origin is returned because the surprising case is silent. A directory with no
    `.citations/` of its own does not fail — it walks up, reaches the user library, verifies
    whatever is in there and reports `all found` about a set of records that has nothing to do
    with the work in front of you. Reporting the path turns that into something a reader can
    notice.
    """
    env = os.environ.get("CITATIONS_HOME")
    if env:
        p = pathlib.Path(env).expanduser()
        return (p, "CITATIONS_HOME") if p.is_dir() else (None, "CITATIONS_HOME")

    here = (start or pathlib.Path.cwd()).resolve()
    for d in [here, *here.parents]:
        if (d / DIRNAME).is_dir():
            return d / DIRNAME, "project"
        if (d / "records").is_dir():      # a library that is itself the directory
            return d, "project"

    user = user_library()
    return (user, "user") if (user / "records").is_dir() else (None, "none")


def find(start: pathlib.Path | None = None) -> pathlib.Path | None:
    """The library governing `start`, or None if there is not one."""
    return find_with_origin(start)[0]


def home() -> pathlib.Path:
    """The library, or exit telling the caller how to make one."""
    found = find()
    if found is None:
        raise SystemExit(
            "no library here.\n"
            "    citations init            make one in this directory\n"
            "    citations init --user     make one shared across all your projects\n"
            "    CITATIONS_HOME=<path>     use one that already exists")
    return found


def records() -> pathlib.Path:
    return home() / "records"


def enrichment() -> pathlib.Path:
    return home() / "enrichment.yaml"


def pdfs() -> pathlib.Path:
    return home() / "pdfs"


def record_file(slug: str) -> pathlib.Path:
    return records() / f"{slug}.yaml"
