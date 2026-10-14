"""`claims.core.report`, under the name it had in this package.

The code that checks what a manifest declares is the `claims` package. This module is that
one's `report` for anything that imports it from here: every name, private ones included,
is the same object.
"""

import importlib

from claims.core.report import *  # noqa: F403

# By name: `claims` exports functions called `verify` and `resolve`, which as attributes
# of the package hide the modules of the same names.
_home = importlib.import_module("claims.core.report")


def __getattr__(name: str) -> object:
    return getattr(_home, name)


def __dir__() -> list[str]:
    return dir(_home)
