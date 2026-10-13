"""Other formats for the check records.

An exporter reads `repro.record.ExportRecord` and nothing else: not the manifest, not a
verification report. A fact a format needs that a record lacks is added to the record, so it
reaches every format and is decided once.
"""

from __future__ import annotations

from collections.abc import Callable

from repro.export.sarif import to_sarif_log
from repro.record import to_jsonl

#: What `repro export <target>` writes, by target.
EXPORTS: dict[str, Callable[..., str]] = {
    "record": to_jsonl,
    "sarif": to_sarif_log,
}

__all__ = ["EXPORTS"]
