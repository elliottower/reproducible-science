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


def key_lines(text: str) -> list[tuple[str, int]]:
    """Every entry key in the file, as written, with the 1-based line its `@` sits on.

    Built from `ENTRY_START` rather than from `entries()`, so an entry whose braces never
    balance is counted too. BibTeX reads the key off the `@type{key,` and reports a repeat at
    that position -- `Repeated entry---line 13 of file refs.bib : @misc{alpha2026one` -- so a
    duplicate check that skipped the entries this reader cannot close would be blind in the file
    most likely to hold one. The difference between this count and `entries()` is also what says
    a file has an entry that never closes.
    """
    return [(m.group(2), text.count("\n", 0, m.start()) + 1) for m in ENTRY_START.finditer(text)]


def duplicate_keys(text: str) -> dict[str, list[tuple[str, int]]]:
    """Keys defined more than once: `{folded key: [(key as written, line), ...]}`.

    Case is folded because BibTeX folds it. Running BibTeX 0.99d over a file holding both
    `beta2026two` and `Beta2026Two` reports `Repeated entry---line 19`, skips the second, and
    writes a `.bbl` without it; `\\cite{Beta2026Two}` in the same document is a
    `Case mismatch error` and the citation goes undefined. biblatex/biber read the two as
    different works instead, so a case-only collision is a dropped entry under one engine and a
    split one under the other, and neither is what the file says.
    """
    seen: dict[str, list[tuple[str, int]]] = {}
    for key, line in key_lines(text):
        seen.setdefault(key.lower(), []).append((key, line))
    return {folded: occurrences for folded, occurrences in seen.items() if len(occurrences) > 1}


def read(path) -> str:
    """A `.bib` as text, whatever it is encoded in.

    Bibliographies predate UTF-8 by decades and are still written in latin-1. Reading one
    strictly raised `UnicodeDecodeError` out of the audit rather than reporting anything.
    """
    return path.read_text(encoding="utf-8", errors="replace")
