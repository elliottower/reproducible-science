"""Built-in extractors for the formats a source arrives in that are neither a PDF nor text.

A claims file pins one file by sha256, and `fetch` installs a download only when its bytes are
the pinned ones. That works where the pinned file is the publisher's file. It fails where the
pinned file is a text somebody's script made from one -- a supplementary workbook rendered to
rows, a JATS article with its tags stripped -- because a reader's download is the workbook and
never the text. Measured on one audit's 199 claims files, on an empty checkout: 2 fetched, 156
differ, 41 unavailable. 2,688 of its 4,499 quotations are rows of supplementary spreadsheets.

The remedy is to pin the original and name the extraction, which is what a PDF already gets:
the pin names the publisher's bytes and `pdftotext` is recorded as what read them. These are
the same thing for three more formats.

    sheet-rows   .xlsx, .xls, .csv   one row per line, cells joined with ` | `
    docx-text    .docx               paragraphs in order, then each table one row per line
    jats-text    JATS XML            one block per line, inline markup dropped

Each has a name a claims file can write and a version. The version is of the output, not of
the code: it changes when the same bytes would produce different text, because a quotation
pinned against one rendering says nothing about another. A claims file naming a version this
build does not ship is `unchecked`, with the reason.

They run in this process and execute nothing, so they are outside the `extract_cmd` allowlist:
a claims file naming one names a reader this package ships, not a program on the machine.

`openpyxl`, `xlrd` and `python-docx` are optional, as the PDF readers are. A missing one is
reported and never raised as an `ImportError` out of a check; the quotation is `unchecked`,
which is the outcome for a source nothing here could read.

What every extractor shares: whitespace inside a cell or a block is collapsed, so one row or
one paragraph is one line; an empty cell is dropped unless the source asks to keep them; a row
or block with no text produces no line. Nothing is reordered and nothing is summarized.
"""

from __future__ import annotations

import csv
import dataclasses
import datetime
import pathlib
import shlex
import warnings
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterable

from citations.exceptions import SourceUnreadableError

try:  # optional: `pip install "citations[sheets]"`
    import openpyxl
except ImportError:  # pragma: no cover - exercised by the extras matrix, not the suite
    openpyxl = None

try:  # optional: `pip install "citations[sheets]"`
    import xlrd
except ImportError:  # pragma: no cover
    xlrd = None

try:  # optional: `pip install "citations[docx]"`
    import docx
except ImportError:  # pragma: no cover
    docx = None

#: Between two cells of one row. Spaced, so a cell's last word and the next cell's first never
#: weld into a word that is in neither, and visible, so a quotation spanning two cells shows
#: that it does.
CELL_SEPARATOR = " | "


def _line(text: str) -> str:
    """One line: a cell or a block with every run of whitespace, newlines included, as a space.

    A cell holding a line break would otherwise put half a row on the next line, where it reads
    as a row of its own.
    """
    return " ".join(text.split())


def _cell(value: object) -> str:
    """A cell's value as the text a reader of the sheet sees.

    A spreadsheet stores `46` as the float 46.0 and `0.3` as 0.30000000000000004. Excel shows
    fifteen significant digits, which is what `.15g` keeps, so a quotation typed from the
    sheet matches what is rendered here. A date with no time of day is a date.
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else format(value, ".15g")
    if isinstance(value, datetime.datetime):
        if value.time() == datetime.time():
            return value.date().isoformat()
        return value.isoformat(sep=" ")
    return _line(str(value))


def _rows(rows: Iterable[Iterable[object]], keep_empty: bool) -> list[str]:
    """Rows as lines. An empty cell is dropped, or kept where its position is the content.

    Trailing empty cells are dropped either way: a sheet's used range is as wide as its widest
    row, and keeping them would end every shorter row in a run of separators.
    """
    lines = []
    for row in rows:
        cells = [_cell(value) for value in row]
        while cells and not cells[-1]:
            cells.pop()
        if not keep_empty:
            cells = [c for c in cells if c]
        if any(cells):
            lines.append(CELL_SEPARATOR.join(cells))
    return lines


def _named(path: pathlib.Path, sheet: str | None, names: list[str]) -> list[str]:
    """The sheets to read: the one named, or all of them in workbook order."""
    if sheet is None:
        return names
    if sheet not in names:
        raise SourceUnreadableError(
            path, f"no sheet named {sheet!r}; the workbook holds {', '.join(map(repr, names))}"
        )
    return [sheet]


def _xlsx(path: pathlib.Path, sheet: str | None, keep_empty: bool) -> list[str]:
    if openpyxl is None:
        raise SourceUnreadableError(
            path, 'openpyxl is not installed -- pip install "citations[sheets]"'
        )
    # `data_only`: the value a formula last computed, which is what the sheet shows, and never
    # the formula. `read_only`: a supplementary workbook can be tens of megabytes.
    #
    # openpyxl warns, once per sheet, about workbook features it does not model -- a data
    # validation extension, a conditional format. None of them is a cell's value, and on a
    # publisher's workbook the warning lands in the middle of a report about quotations.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        book = openpyxl.load_workbook(path, read_only=True, data_only=True)
        try:
            lines: list[str] = []
            for name in _named(path, sheet, book.sheetnames):
                ws = book[name]
                # A workbook written by something other than Excel can record a used range of
                # one cell, and a read-only sheet trusts it: every row after the first is not
                # returned and nothing says so. Discarding the recorded range makes it read
                # what is there.
                ws.reset_dimensions()
                lines += _rows(ws.iter_rows(values_only=True), keep_empty)
            return lines
        finally:
            book.close()


def _xls(path: pathlib.Path, sheet: str | None, keep_empty: bool) -> list[str]:
    if xlrd is None:
        raise SourceUnreadableError(
            path, 'xlrd is not installed -- pip install "citations[sheets]"'
        )
    book = xlrd.open_workbook(str(path))

    def value(cell) -> object:
        # The old format has no integer or date type. A date is a float tagged as one, read
        # against the workbook's epoch; a boolean is 0 or 1 tagged as one.
        if cell.ctype == xlrd.XL_CELL_DATE:
            return xlrd.xldate_as_datetime(cell.value, book.datemode)
        if cell.ctype == xlrd.XL_CELL_BOOLEAN:
            return bool(cell.value)
        if cell.ctype == xlrd.XL_CELL_ERROR:
            return xlrd.error_text_from_code.get(cell.value, "")
        return cell.value

    lines: list[str] = []
    for name in _named(path, sheet, book.sheet_names()):
        ws = book.sheet_by_name(name)
        lines += _rows(([value(c) for c in ws.row(r)] for r in range(ws.nrows)), keep_empty)
    return lines


def _csv(path: pathlib.Path, sheet: str | None, keep_empty: bool) -> list[str]:
    if sheet is not None:
        raise SourceUnreadableError(path, f"a .csv has no sheets, and the source names {sheet!r}")
    # `utf-8-sig`: a file exported from Excel begins with a byte-order mark, which would
    # otherwise be the first character of the first cell.
    with path.open(newline="", encoding="utf-8-sig", errors="replace") as handle:
        return _rows(csv.reader(handle), keep_empty)


_SHEET_READERS: dict[str, Callable[[pathlib.Path, str | None, bool], list[str]]] = {
    ".xlsx": _xlsx,
    ".xlsm": _xlsx,
    ".xls": _xls,
    ".csv": _csv,
}


def _sheet_rows(path: pathlib.Path, sheet: str | None, keep_empty: bool) -> str:
    """A workbook's rows, one per line, sheets in workbook order."""
    read = _SHEET_READERS.get(path.suffix.lower())
    if read is None:
        raise SourceUnreadableError(
            path, f"sheet-rows reads {', '.join(_SHEET_READERS)}, and this is {path.suffix!r}"
        )
    return "\n".join(read(path, sheet, keep_empty))


def _docx_text(path: pathlib.Path, sheet: str | None, keep_empty: bool) -> str:
    """Body paragraphs in order, then each table one row per line.

    Tables come after the paragraphs and not where they sit among them, which is the order
    `python-docx` exposes and the order the texts this replaces were made in. Headers, footers,
    footnotes, text boxes and a table nested inside a cell are not read: a quotation taken from
    one of those is `not found`, and the remedy is a different extractor, not a wider match.
    """
    if docx is None:
        raise SourceUnreadableError(
            path, 'python-docx is not installed -- pip install "citations[docx]"'
        )
    document = docx.Document(str(path))
    lines = [_line(p.text) for p in document.paragraphs]
    for table in document.tables:
        for row in table.rows:
            # A merged cell is returned once per column it spans. Without this a row reads
            # `Cohort | Cohort | Cohort | 1,204`, and a quotation of the row as printed fails.
            cells, last = [], None
            for cell in row.cells:
                if cell._tc is not last:
                    cells.append(cell.text)
                last = cell._tc
            lines += _rows([cells], keep_empty)
    return "\n".join(line for line in lines if line)


#: JATS elements that sit inside a sentence. Everything else starts a new line. Listed this way
#: round on purpose: an inline element missing from here splits a sentence across two lines,
#: which the matcher's whitespace folding absorbs, while a block element missing from a list of
#: blocks would have its text dropped, which reads as a passage the source does not contain.
_JATS_INLINE = frozenset(
    {
        "abbrev",
        "bold",
        "email",
        "ext-link",
        "inline-formula",
        "inline-graphic",
        "italic",
        "monospace",
        "named-content",
        "overline",
        "roman",
        "sans-serif",
        "sc",
        "strike",
        "styled-content",
        "sub",
        "sup",
        "underline",
        "uri",
        "xref",
    }
)


def _tag(element: ET.Element) -> str:
    """The element's name without a namespace, which MathML and some deposits carry."""
    return element.tag.rsplit("}", 1)[-1]


def _jats_lines(element: ET.Element, lines: list[str]) -> None:
    """Append the text under `element`, one block per line, in document order."""
    if _tag(element) == "tr":
        cells = ["".join(c.itertext()) for c in element if _tag(c) in ("td", "th")]
        lines += _rows([cells], keep_empty=False)
        return
    run = [element.text or ""]
    for child in element:
        if _tag(child) == "break":
            run.append(" ")
        elif _tag(child) in _JATS_INLINE:
            run.append("".join(child.itertext()))
        else:
            lines.append(_line("".join(run)))
            run = []
            _jats_lines(child, lines)
        run.append(child.tail or "")
    lines.append(_line("".join(run)))


def _jats_text(path: pathlib.Path, sheet: str | None, keep_empty: bool) -> str:
    """A JATS article as text: one block per line, inline markup dropped, entities decoded.

    Read as plain text, the XML keeps its markup, and a quotation crossing `<italic>`, `<sup>`,
    `<xref>` or a character entity does not resolve. Measured on 72 Europe PMC and NCBI
    articles: 194 of 314 quotations resolved in the XML as served, and 308 resolve in this
    text. The other 6 are table rows quoted with spaces between their cells.

    The whole document is read, front matter and reference list included: leaving a part out
    is a decision about what a paper may be quoted on, and that is the claims file's to make.
    A table is one row per line with cells joined by ` | `; spans are not expanded and header
    cells are not repeated beside the body cells.
    """
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as e:
        raise SourceUnreadableError(path, f"not well-formed XML: {e}") from e
    lines: list[str] = []
    _jats_lines(root, lines)
    return "\n".join(line for line in lines if line)


@dataclasses.dataclass(frozen=True)
class Extractor:
    """One built-in extractor: the name a claims file writes, and the version of its output."""

    name: str
    version: int
    read: Callable[[pathlib.Path, str | None, bool], str]

    takes_options: bool = False
    """Whether `--sheet` and `--keep-empty` mean anything to it. Only a workbook has sheets,
    and an option given to an extractor that ignores it is a declaration nothing honoured."""


EXTRACTORS: dict[str, Extractor] = {
    e.name: e
    for e in (
        Extractor("sheet-rows", 1, _sheet_rows, takes_options=True),
        Extractor("docx-text", 1, _docx_text),
        Extractor("jats-text", 1, _jats_text),
    )
}

#: The extractor a format obviously wants, chosen where a source declares nothing. The same
#: rule `verify.BY_SUFFIX` applies to `.tex`: without it a workbook reached the PDF readers and
#: every quotation in it was `unchecked`. `.xml` is not here. An XML source that declares
#: nothing is read as plain text, as it always was, and quotations already pinned against the
#: markup go on resolving; `jats-text` is for a source that names it.
BY_SUFFIX: dict[str, str] = {
    ".xlsx": "sheet-rows",
    ".xlsm": "sheet-rows",
    ".xls": "sheet-rows",
    ".csv": "sheet-rows",
    ".docx": "docx-text",
}


@dataclasses.dataclass(frozen=True)
class Declared:
    """A built-in extractor as one source declared it, options included."""

    extractor: Extractor
    sheet: str | None = None
    keep_empty: bool = False

    @property
    def name(self) -> str:
        """What a result records: the extractor, its version, and the options that shaped it.

        Always with the version, whether or not the claims file wrote one. Two versions of one
        extractor are two readings of the same bytes, and a result that does not say which
        cannot be compared with a later one.
        """
        words = [f"{self.extractor.name}@{self.extractor.version}"]
        if self.sheet is not None:
            words += ["--sheet", self.sheet]
        if self.keep_empty:
            words.append("--keep-empty")
        return shlex.join(words)

    def read(self, path: pathlib.Path) -> str:
        """The text this extractor produces from `path`, or `SourceUnreadableError` saying why.

        Any failure to parse is the document's and is reported as a source that could not be
        read. It is never an empty text, which would say the document holds no words.
        """
        try:
            return self.extractor.read(path, self.sheet, self.keep_empty)
        except SourceUnreadableError:
            raise
        except Exception as e:
            raise SourceUnreadableError(
                path, f"{self.extractor.name} could not read it: {e}"
            ) from e


def is_builtin(extractor: str) -> bool:
    """Whether a declared reading, or the name recorded on a result, is one of `EXTRACTORS`."""
    words = extractor.split()
    return bool(words) and words[0].partition("@")[0] in EXTRACTORS


def declared(path: pathlib.Path, text: str) -> Declared | None:
    """The built-in extractor `text` names, or None where it names a program instead.

    `text` is `name`, or `name@version`, then `--sheet NAME` and `--keep-empty` where the
    extractor takes them: the form `ClaimSource.reader` writes from a source's `extractor`,
    `extractor_version`, `sheet` and `empty_cells` fields.

    Raises `SourceUnreadableError`, so the quotation is `unchecked`, where the version is not
    the one shipped here or an option is not one the extractor takes. Reading with a different
    version, or ignoring the option, would produce a text the claims file did not ask for and
    report a verdict against it.
    """
    try:
        words = shlex.split(text)
    except ValueError:
        return None  # not ours to report: `verify._argv` says why it will not parse
    if not words:
        return None
    name, _, version = words[0].partition("@")
    extractor = EXTRACTORS.get(name)
    if extractor is None:
        return None
    if version and version != str(extractor.version):
        raise SourceUnreadableError(
            path,
            f"the source names {name} version {version} and this build ships version "
            f"{extractor.version}. The two produce different text from the same bytes, so "
            f"nothing was read: install the citations release that ships version {version}, "
            f"or pin the quotations again under version {extractor.version}",
        )
    sheet, keep_empty, rest = None, False, words[1:]
    while rest:
        word = rest.pop(0)
        if extractor.takes_options and word == "--sheet" and rest:
            sheet = rest.pop(0)
        elif extractor.takes_options and word == "--keep-empty":
            keep_empty = True
        else:
            raise SourceUnreadableError(path, f"{name} does not take {word!r}")
    return Declared(extractor, sheet, keep_empty)


__all__ = [
    "BY_SUFFIX",
    "CELL_SEPARATOR",
    "EXTRACTORS",
    "Declared",
    "Extractor",
    "declared",
    "is_builtin",
]
