"""Fixtures for this package's tests.

`repro reproduce` holds a pinned output in the user's cache while its command runs. The suite
holds them in a directory of its own, so no test writes to the cache of whoever runs it. Here
and not in `packages/conftest.py`: run from this package, pytest takes this package as its root
and never reads that file.
"""

from __future__ import annotations

import pytest
from repro.regenerate import HELD_ENV


@pytest.fixture(autouse=True)
def held_outputs_in_the_test(monkeypatch, tmp_path_factory):
    monkeypatch.setenv(HELD_ENV, str(tmp_path_factory.mktemp("held")))
