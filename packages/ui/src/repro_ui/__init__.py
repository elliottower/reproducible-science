"""A local web page over a project's Reproducible Science records.

`repro ui` (or `repro-ui`) builds the page's data from what `repro verify`, `repro stale`,
`prereg check` and `results verify` report, and from the project's ledger, check history,
record of re-runs, manifest and manuscript, then serves it on localhost.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _version

try:
    __version__ = _version("reproducible-science-ui")
except PackageNotFoundError:  # running from a checkout that was never installed
    __version__ = "0+unknown"

__all__ = ["__version__"]
