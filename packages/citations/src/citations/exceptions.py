"""What can go wrong, named.

Library code raises; only `cli.py` catches and turns an exception into an exit code. Nothing
here calls `sys.exit` or raises `SystemExit`, so `citations` can be imported and called from
inside another program -- an agent skill, a test, a notebook -- without taking the host
process down with it.

The hierarchy is shallow on purpose. A caller that wants to handle everything catches
`CitationsError`; a caller that wants to distinguish "your library is missing" from "your
claims file is malformed" catches the specific one.
"""

from __future__ import annotations

import pathlib


class CitationsError(Exception):
    """Base for every error this package raises."""


class LibraryNotFoundError(CitationsError):
    """No library governs this directory, and none was named."""

    def __init__(self, start: pathlib.Path | None = None) -> None:
        self.start = start
        super().__init__(
            "no library here.\n"
            "    citations init            make one in this directory\n"
            "    citations init --user     make one shared across all your projects\n"
            "    CITATIONS_HOME=<path>     use one that already exists"
        )


class ClaimFileError(CitationsError):
    """A claims or record file could not be read as the shape this package expects.

    Carries the path so the message names the file the reader has to open, which a bare
    `KeyError` from inside a comprehension does not.
    """

    def __init__(self, path: pathlib.Path, detail: str) -> None:
        self.path = path
        self.detail = detail
        super().__init__(f"{path}: {detail}")


class SourceUnreadableError(CitationsError):
    """A pinned artifact exists but its text could not be extracted.

    Distinct from a missing file and from a passage that is genuinely absent. Raised where the
    cause is the extraction toolchain rather than the document -- a missing `pdftotext`, a
    timeout, a permission error -- so that an infrastructure failure is never recorded as a
    quotation that simply did not resolve.
    """

    def __init__(self, path: pathlib.Path, detail: str) -> None:
        self.path = path
        self.detail = detail
        super().__init__(f"{path}: {detail}")


class PinBrokenError(CitationsError):
    """The artifact on disk is not the artifact that was pinned.

    The recorded sha256 and the file's actual sha256 disagree, so every quotation checked
    against it is being checked against a document the record does not describe.
    """

    def __init__(self, path: pathlib.Path, expected: str, actual: str) -> None:
        self.path = path
        self.expected = expected
        self.actual = actual
        super().__init__(
            f"{path}: pinned sha256 {expected[:16]}... but the file on disk is "
            f"{actual[:16]}...  the source changed after it was pinned"
        )


class BibFileError(CitationsError):
    """A `.bib`, or the text offered as an entry for one, is not the shape `add` requires.

    Carries the path so the message names the file to open. Covers both halves of one command:
    text that is not exactly one entry, and a file that did not read back after a write as the
    file that was written.
    """

    def __init__(self, path: pathlib.Path, detail: str) -> None:
        self.path = path
        self.detail = detail
        super().__init__(f"{path}: {detail}")


class MetadataError(CitationsError):
    """An identifier could not be turned into the metadata a `.bib` entry needs.

    Distinct from a malformed file: the bibliography is fine and the registry is the problem --
    it holds no record for the identifier, it refused to answer, or what it returned is missing
    something an entry cannot be written without. Writing an entry anyway is how a guessed year
    and a shortened author list get into a bibliography.
    """

    def __init__(self, identifier: str, detail: str) -> None:
        self.identifier = identifier
        self.detail = detail
        super().__init__(f"{identifier}: {detail}")
