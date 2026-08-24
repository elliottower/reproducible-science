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

import platformdirs

from citations.exceptions import LibraryNotFoundError

DIRNAME = ".citations"


def user_library() -> pathlib.Path:
    """The per-user library, in the platform's data directory."""
    return pathlib.Path(platformdirs.user_data_dir("citations"))


def find_with_origin(start: pathlib.Path | None = None) -> tuple[pathlib.Path | None, str]:
    """The library governing `start`, and which rule produced it.

    The origin is returned because the surprising case is silent. A directory with no
    `.citations/` of its own does not fail -- it walks up, reaches the user library, verifies
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
        if (d / "records").is_dir():  # a library that is itself the directory
            return d, "project"

    user = user_library()
    return (user, "user") if (user / "records").is_dir() else (None, "none")


def find(start: pathlib.Path | None = None) -> pathlib.Path | None:
    """The library governing `start`, or None if there is not one."""
    return find_with_origin(start)[0]


def home(start: pathlib.Path | None = None) -> pathlib.Path:
    """The library governing `start`.

    Raises `LibraryNotFoundError` rather than exiting, so that a caller embedding this package
    -- a test, a notebook, an agent skill -- decides for itself what to do about a missing
    library. Only `cli.py` turns that into an exit code.
    """
    found = find(start)
    if found is None:
        raise LibraryNotFoundError(start)
    return found


def records(start: pathlib.Path | None = None) -> pathlib.Path:
    return home(start) / "records"


def enrichment(start: pathlib.Path | None = None) -> pathlib.Path:
    return home(start) / "enrichment.yaml"


def pdfs(start: pathlib.Path | None = None) -> pathlib.Path:
    return home(start) / "pdfs"


def record_file(slug: str, start: pathlib.Path | None = None) -> pathlib.Path:
    return records(start) / f"{slug}.yaml"
