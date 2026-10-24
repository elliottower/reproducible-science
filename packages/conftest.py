"""Fixtures every package's tests share.

A freeze sends its digest to the OpenTimestamps calendars, and most tests freeze a plan in a
subprocess where nothing can be patched. Emptying the calendar list in the environment, which a
subprocess inherits, keeps the suite off the network and off public servers. A test that stamps
names its own calendars.

`citations verify` keeps extracted text in the user's cache directory. The suite turns that off
the same way, so no test reads what an earlier run filed or writes outside its own directory. A
test of the cache names a directory of its own, and so do the outputs `repro reproduce` holds
while a command runs.
"""

from __future__ import annotations

import pytest
from citations.extraction_cache import DISABLE_ENV
from provenance_core.anchor import CALENDARS_ENV
from repro.regenerate import HELD_ENV


@pytest.fixture(autouse=True)
def no_public_calendars(monkeypatch):
    monkeypatch.setenv(CALENDARS_ENV, "")


@pytest.fixture(autouse=True)
def no_extraction_cache(monkeypatch):
    monkeypatch.setenv(DISABLE_ENV, "1")


@pytest.fixture(autouse=True)
def held_outputs_in_the_test(monkeypatch, tmp_path_factory):
    """`repro reproduce` holds pinned outputs in the user's cache while a command runs; the
    suite holds them in a directory of its own."""
    monkeypatch.setenv(HELD_ENV, str(tmp_path_factory.mktemp("held")))
