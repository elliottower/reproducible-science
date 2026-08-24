"""Seal a run, record what it produced, and verify the chain."""
from __future__ import annotations
from importlib.metadata import PackageNotFoundError, version as _version

try:
    __version__ = _version("results-cli")
except PackageNotFoundError:  # a source tree with nothing installed
    __version__ = "0+unknown"
