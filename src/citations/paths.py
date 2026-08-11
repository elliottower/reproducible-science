"""Every path the tool uses, resolved once.

The library lives wherever `CITATIONS_HOME` points, defaulting to the current directory. That
makes the tool usable on someone else's project without them adopting this repository's layout.

This is the only module that computes a location. Everything else imports the name it wants.
"""
from __future__ import annotations

import os
import pathlib


def home() -> pathlib.Path:
    """Where this library lives. `$CITATIONS_HOME`, else the nearest directory holding one."""
    env = os.environ.get("CITATIONS_HOME")
    if env:
        return pathlib.Path(env).expanduser().resolve()
    here = pathlib.Path.cwd().resolve()
    for d in [here, *here.parents]:
        if (d / "records").is_dir() or (d / ".citations").is_file():
            return d
    return here


def records() -> pathlib.Path:
    return home() / "records"


def enrichment() -> pathlib.Path:
    return home() / "enrichment.yaml"


def pdfs() -> pathlib.Path:
    return home() / "pdfs"


def record_file(slug: str) -> pathlib.Path:
    return records() / f"{slug}.yaml"
