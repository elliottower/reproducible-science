"""A pull-request bot for the reproducible-science toolkit.

On a pull request it comments once for each claim in `repro.yaml` that fails or went stale,
and records the answer someone with write access gives: the paper should change, the result
file is wrong, ignore it, or it is not a claim. It runs from GitHub Actions workflows in the
author's own repository. `repro_pr_bot.cli` is the command.
"""

from __future__ import annotations

import importlib.metadata

try:
    __version__ = importlib.metadata.version("reproducible-science-pr-bot")
except importlib.metadata.PackageNotFoundError:
    __version__ = "0+unknown"

__all__ = ["__version__"]
