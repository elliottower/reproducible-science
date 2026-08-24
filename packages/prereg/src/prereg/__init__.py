"""Freeze a plan before you run it, and record what changed after."""
from importlib.metadata import PackageNotFoundError, version as _version

try:
    __version__ = _version("prereg")
except PackageNotFoundError:  # a source tree with nothing installed
    __version__ = "0+unknown"
