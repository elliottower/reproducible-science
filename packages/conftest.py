"""Fixtures every package's tests share.

A freeze sends its digest to the OpenTimestamps calendars, and most tests freeze a plan in a
subprocess where nothing can be patched. Emptying the calendar list in the environment, which a
subprocess inherits, keeps the suite off the network and off public servers. A test that stamps
names its own calendars.
"""

from __future__ import annotations

import pytest
from provenance_core.anchor import CALENDARS_ENV


@pytest.fixture(autouse=True)
def no_public_calendars(monkeypatch):
    monkeypatch.setenv(CALENDARS_ENV, "")
