"""`claims.export.sarif`, under the name it had in this package.

The code that checks what a manifest declares is the `claims` package. This module is that
one's `sarif` for anything that imports it from here: every name, private ones included,
reads as the same object. Writing is another matter. An assignment here, or a monkeypatch of a
name here, rebinds it in this module and not in `claims.export.sarif`, whose code goes on using its own,
so a patch meant to reach that code targets `claims.export.sarif`.
"""

import importlib

from claims.export.sarif import *  # noqa: F403

# By name: `claims` exports functions called `verify` and `resolve`, which as attributes
# of the package hide the modules of the same names.
_home = importlib.import_module("claims.export.sarif")


def __getattr__(name: str) -> object:
    return getattr(_home, name)


def __dir__() -> list[str]:
    return dir(_home)
