"""A Word manuscript, read as the text a quotation, a prose address and `repro numbers` see.

The reader is `citations`' `docx-text` extractor, which `citations.verify.extract` chooses for
a `.docx` and which reads with `python-docx`. It is the one reader of the format here, so a
quotation checked against a `.docx` and a number counted in it are read from the same text.
`claims` depends on `citations` already and `citations` imports nothing of `claims`, so using
it keeps the direction the import contracts enforce.

What is read, in this order, with `docx-text@1` and `python-docx` 1.1 or 1.2:

  1. every body paragraph, in document order, one per line;
  2. then every body table, in document order, one row per line, top to bottom, cells left to
     right joined with ` | `, a merged cell once.

Tables come after all the paragraphs, not where they sit among them, so a passage running
from a paragraph into the table after it is not one passage in this text.

What is not read: headers and footers, footnotes and endnotes (`python-docx` exposes neither),
comments, text boxes, a table nested in a cell, the text of a content control (`w:sdt`) or of
a simple field (`w:fldSimple`), and the text of a tracked change. `python-docx` reads the runs
that are direct children of a paragraph, so an insertion (`w:ins`) and a deletion (`w:del`)
are both left out: the text is neither the accepted view nor the original, and a sentence a
tracked change touches is read with a hole in it. A `.docx` holding a tracked change of text
is therefore refused as unreadable, and the remedy is to accept or reject the changes in Word
and pin the file again.
"""

from __future__ import annotations

import pathlib
import xml.etree.ElementTree as ET
import zipfile

from claims.exceptions import ArtifactUnreadableError

DOCX_SUFFIX = ".docx"

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

#: A tracked change and the element that holds the text it changes. A `w:ins` or `w:del` with
#: no text under it marks a paragraph mark or a table row as changed, which moves no words.
_REVISIONS = {
    f"{_W}ins": f"{_W}t",
    f"{_W}moveTo": f"{_W}t",
    f"{_W}del": f"{_W}delText",
    f"{_W}moveFrom": f"{_W}delText",
}


def tracked_changes(path: pathlib.Path) -> int:
    """How many tracked changes of text the body of a `.docx` holds.

    Read from `word/document.xml` with the standard library, so it answers without
    `python-docx` installed. A file that is not a `.docx` holds none, and is left to the
    extractor to report.
    """
    try:
        with zipfile.ZipFile(path) as archive:
            body = archive.read("word/document.xml")
    except (OSError, KeyError, zipfile.BadZipFile):
        return 0
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return 0
    return sum(
        1
        for tag, text in _REVISIONS.items()
        for change in root.iter(tag)
        if next(change.iter(text), None) is not None
    )


def refuse_tracked_changes(path: pathlib.Path) -> None:
    """Raise `ArtifactUnreadableError` where `path` is a `.docx` holding a tracked change."""
    if path.suffix.lower() != DOCX_SUFFIX:
        return
    if found := tracked_changes(path):
        raise ArtifactUnreadableError(
            path,
            f"holds {found} tracked change{'s' if found != 1 else ''} of text, and python-docx "
            "reads neither the accepted nor the original text of one; accept or reject the "
            "changes in Word and pin the file again",
        )


__all__ = ["DOCX_SUFFIX", "refuse_tracked_changes", "tracked_changes"]
