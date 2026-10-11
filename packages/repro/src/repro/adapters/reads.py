"""Reading each artifact once in a verification.

An adapter resolves one locator against one file, and a manifest of a thousand claims over one
table asked for that table to be read and parsed a thousand times. Within `reading_once()` a
load is kept under its key and returned to every later locator that asks for it.

The scope is one verification and nothing longer. The engine hashes every artifact at the start
of a run, and a decision records that digest as describing what was read; a file read once in
the run is read as close to that hash as it can be. Outside the scope nothing is kept, so a
second verification in the same process reads the file again, whatever the first one saw. A
cache keyed on the path alone and living as long as the process returned the first run's text
to the second.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable, Hashable, Iterator
from contextvars import ContextVar
from typing import TypeVar, cast

T = TypeVar("T")

_HELD: ContextVar[dict[Hashable, object] | None] = ContextVar("repro_reads", default=None)


@contextlib.contextmanager
def reading_once() -> Iterator[None]:
    """Keep each load made inside the block until the block ends."""
    token = _HELD.set({})
    try:
        yield
    finally:
        _HELD.reset(token)


def once(key: Hashable, load: Callable[[], T]) -> T:
    """`load()`, or what it returned earlier in this run under the same key.

    A load that raises is not kept: every locator over an unreadable file reports it.
    """
    held = _HELD.get()
    if held is None:
        return load()
    if key not in held:
        held[key] = load()
    return cast(T, held[key])
