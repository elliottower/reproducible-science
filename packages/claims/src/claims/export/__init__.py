"""Other formats for the check records.

An exporter reads `claims.record.ExportRecord` and nothing else: not the manifest, not a
verification report. A fact a format needs that a record lacks is added to the record, so it
reaches every format and is decided once.
"""

from __future__ import annotations

from collections.abc import Callable

from claims.export.rocrate import to_ro_crate
from claims.export.sarif import to_sarif_log
from claims.record import to_jsonl

#: What `repro export <target>` writes, by target.
EXPORTS: dict[str, Callable[..., str]] = {
    "ro-crate": to_ro_crate,
    "record": to_jsonl,
    "sarif": to_sarif_log,
}

__all__ = ["EXPORTS"]
