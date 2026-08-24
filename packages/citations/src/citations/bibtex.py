"""Splitting a `.bib` file into entries.

A regular expression cannot do this. The one that used to
(`@(\\w+)\\s*\\{\\s*([^,\\s]+)\\s*,(.*?)\\n\\}`) required an entry to close with a brace at
column zero, which is one convention among several: JabRef and BibDesk indent it, and plenty
of files end the last field and the entry on one line as `doi = {...}}`.

The consequences were worse than a missed entry. Because the body was non-greedy up to the
next `\\n}`, an entry closing in any other style ran into the one after it, so the later
entry's fields overwrote the earlier one's -- an entry silently vanished from the audit, and
its neighbour was checked against the wrong DOI and the wrong author list. An audit that
reports agreement for a record it never examined is worse than one that reports nothing.

Counting braces is the only thing that works, and it is about fifteen lines.
"""

from __future__ import annotations

import re

ENTRY_START = re.compile(r"@(\w+)\s*\{\s*([^,\s}]+)\s*,")


def entries(text: str) -> list[tuple[str, str, str]]:
    """Every `(kind, key, body)` in the file, in order.

    An entry whose braces never balance is dropped rather than run into its neighbour: a
    truncated file should cost its last entry, not corrupt the one before it.
    """
    found: list[tuple[str, str, str]] = []
    for match in ENTRY_START.finditer(text):
        depth, i = 1, match.end()
        while i < len(text) and depth:
            char = text[i]
            if char == "\\":
                i += 2
                continue
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
            i += 1
        if depth == 0:
            found.append((match.group(1), match.group(2), text[match.end() : i - 1]))
    return found


def read(path) -> str:
    """A `.bib` as text, whatever it is encoded in.

    Bibliographies predate UTF-8 by decades and are still written in latin-1. Reading one
    strictly raised `UnicodeDecodeError` out of the audit rather than reporting anything.
    """
    return path.read_text(encoding="utf-8", errors="replace")
