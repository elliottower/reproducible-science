"""Reading a manifest off disk.

Validation happens once, here, at the edge. A malformed file names itself and the field at
fault rather than raising a `KeyError` from inside the engine, because the person who has to
fix it is looking at the file, not at the traceback.
"""

from __future__ import annotations

import pathlib
from typing import Any

import yaml
from pydantic import ValidationError

from repro.exceptions import ManifestError
from repro.models import Manifest

DEFAULT_NAME = "repro.yaml"

#: libyaml's loader where PyYAML was built with it, which every published wheel is. It reads the
#: same documents as the Python loader and reads a manifest of a thousand claims in a tenth of
#: the time, which was most of what verifying one took.
_LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)


def load(path: pathlib.Path | str) -> Manifest:
    """Read one manifest, or raise `ManifestError` naming the file and the field."""
    path = pathlib.Path(path)
    try:
        raw: Any = yaml.load(path.read_text(), Loader=_LOADER) or {}
    except yaml.YAMLError as e:
        raise ManifestError(path, f"not valid YAML: {e}") from e
    except OSError as e:
        raise ManifestError(path, f"could not be read: {e}") from e
    if not isinstance(raw, dict):
        raise ManifestError(
            path, f"expected a mapping at the top level, found {type(raw).__name__}"
        )
    # `path` is set at construction because a Manifest is frozen: where it was read from is
    # part of what it is, and an object that can be repointed afterwards resolves relative
    # artifact paths against whichever directory was assigned last.
    raw["path"] = path
    try:
        return Manifest.model_validate(raw)
    except ValidationError as e:
        first = e.errors()[0]
        where = ".".join(str(x) for x in first["loc"]) or "(top level)"
        raise ManifestError(path, f"{where}: {first['msg']}") from e


def find(start: pathlib.Path | None = None) -> pathlib.Path | None:
    """The manifest governing `start`, found by walking up the way git finds `.git`."""
    here = (start or pathlib.Path.cwd()).resolve()
    for directory in [here, *here.parents]:
        candidate = directory / DEFAULT_NAME
        if candidate.is_file():
            return candidate
    return None
