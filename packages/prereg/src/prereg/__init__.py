"""Preregister your plan to prevent p-hacking and unfalsifiable post-hoc analysis."""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _version

try:
    __version__ = _version("prereg")
except PackageNotFoundError:  # a source tree with nothing installed
    __version__ = "0+unknown"
