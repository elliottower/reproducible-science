"""SQLite, addressed by table, column and a key predicate."""

from __future__ import annotations

import pathlib
import sqlite3

from repro.adapters.base import Found, Resolution, _no, _ok
from repro.exceptions import ArtifactUnreadableError
from repro.models import (
    SqliteLocator,
)

# ---------------------------------------------------------------------------------- sqlite

_SQLITE_SUFFIXES = {".db", ".sqlite", ".sqlite3"}


def _resolve_sqlite(locator: SqliteLocator, path: pathlib.Path) -> Found:
    if path.suffix.lower() not in _SQLITE_SUFFIXES:
        return _no(
            Resolution.FORMAT_UNSUPPORTED,
            f"a sqlite locator addresses a database file; {path.name} is {path.suffix}",
        )
    try:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error as e:
        raise ArtifactUnreadableError(path, str(e)) from e
    try:
        tables = {
            r[0]
            for r in connection.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
            )
        }
        if locator.table not in tables:
            return _no(
                Resolution.SELECTOR_INVALID,
                f"{path.name} has no table {locator.table!r}; tables are "
                f"{', '.join(sorted(tables)[:8])}",
            )
        # Identifiers cannot be bound as parameters, so they are checked against the schema
        # and then quoted. Values are always bound.
        columns = {r[1] for r in connection.execute(f'PRAGMA table_info("{locator.table}")')}
        unknown = [c for c in (locator.column, *locator.where) if c not in columns]
        if unknown:
            return _no(
                Resolution.SELECTOR_INVALID,
                f"{locator.table} has no column {', '.join(repr(c) for c in unknown)}; "
                f"columns are {', '.join(sorted(columns)[:8])}",
            )
        clause = " AND ".join(f'"{k}" IS ?' for k in locator.where)
        query = f'SELECT "{locator.column}" FROM "{locator.table}"' + (
            f" WHERE {clause}" if clause else ""
        )
        try:
            found = connection.execute(query, tuple(locator.where.values())).fetchall()
        except sqlite3.Error as e:
            raise ArtifactUnreadableError(path, str(e)) from e
    finally:
        connection.close()

    described = ", ".join(f"{k}={v!r}" for k, v in locator.where.items())
    if not found:
        return _no(Resolution.ABSENT, f"no row in {locator.table} where {described}")
    if len(found) > 1:
        return _no(Resolution.AMBIGUOUS, f"{len(found)} rows in {locator.table} where {described}")
    value = found[0][0]
    if value is None:
        return _no(Resolution.ABSENT, f"{locator.column} is NULL where {described}")
    if isinstance(value, (bytes, memoryview)):
        return _no(Resolution.NOT_SCALAR, f"{locator.column} holds a blob")
    return _ok(str(value), type(value).__name__, f"{locator.table}.{locator.column}")
