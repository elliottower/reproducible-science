"""Other formats for the check records.

An exporter reads `repro.record.CheckRecord` and nothing else: not the manifest, not a
verification report. A fact a format needs that a record lacks is added to the record, so it
reaches every format and is decided once.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from repro.record import CheckRecord, to_jsonl

#: What `repro export <target>` writes, by target.
EXPORTS: dict[str, Callable[[Sequence[CheckRecord]], str]] = {
    "record": to_jsonl,
}

__all__ = ["EXPORTS"]
