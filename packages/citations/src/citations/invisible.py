"""Which pages of a PDF carry text a reader of the page cannot see.

A text layer and a rendered page are two things. Text set in white on a white page, at a size
under a point, or at a position off the page is extracted by every reader and shown by none,
so a passage placed there resolves as `found` in a document whose reader never sees it.

Best effort, in two steps, because the second is slow. `pdfplumber` reads the colour, size and
position of every character, and takes about half a second a page; run over every PDF on every
`verify` it would cost more than the check is worth. So the page's content stream is read
first, with `pypdf`, for the operators that set such text: a white fill (`1 g`, `1 1 1 rg`,
`0 0 0 0 k`), a font size under a point, a text matrix placing text off the page. Only a page
carrying one of those is read character by character. A page whose white text sits on a filled
shape of another colour shows that text, and its characters are counted as shown.

Text a PDF sets with render mode 3 is not looked for. That is how a scanned document carries its
OCR layer, which is the text an honest quotation of a scan comes from.

Where `pypdf` or `pdfplumber` is not installed, nothing is looked for and nothing is reported.
"""

from __future__ import annotations

import functools
import pathlib
import re

from citations import readers

#: Operators in a content stream that set text a page may not show.
_WHITE = re.compile(
    rb"(?:^|[\s\]>)])(?:1(?:\.0*)?\s+1(?:\.0*)?\s+1(?:\.0*)?\s+rg|1(?:\.0*)?\s+g"
    rb"|0(?:\.0*)?\s+0(?:\.0*)?\s+0(?:\.0*)?\s+0(?:\.0*)?\s+k)(?=\s)"
)
_TINY = re.compile(rb"(?:^|\s)(?:0|0?\.\d+)\s+Tf(?=\s)")
_MATRIX = re.compile(
    rb"(-?[\d.]+)\s+(-?[\d.]+)\s+(-?[\d.]+)\s+(-?[\d.]+)\s+(-?[\d.]+)\s+(-?[\d.]+)\s+Tm"
)

#: Below this a character is not read on the page, in points.
MIN_SIZE = 1.0

#: How close to white a fill is to count as white, per component.
WHITE = 0.95


def _suspicious(data: bytes, width: float, height: float) -> bool:
    """Whether a content stream sets anything that may be text the page does not show."""
    if _WHITE.search(data) or _TINY.search(data):
        return True
    for m in _MATRIX.finditer(data):
        try:
            x, y = float(m.group(5)), float(m.group(6))
        except ValueError:
            continue
        if x < 0 or y < 0 or x > width or y > height:
            return True
    return False


def _white(color) -> bool:
    """Whether a pdfplumber colour is white, in gray, RGB or CMYK."""
    if color is None:
        return False
    if isinstance(color, int | float):
        color = (color,)
    try:
        values = [float(c) for c in color]
    except (TypeError, ValueError):
        return False
    if len(values) in (1, 3):
        return all(v >= WHITE for v in values)
    if len(values) == 4:
        return all(v <= 1 - WHITE for v in values)
    return False


def _on_colour(char, shapes) -> bool:
    """Whether a white character sits on a filled shape that is not white."""
    x = (char["x0"] + char["x1"]) / 2
    y = (char["top"] + char["bottom"]) / 2
    for shape in shapes:
        if (
            shape.get("fill")
            and not _white(shape.get("non_stroking_color"))
            and shape["x0"] <= x <= shape["x1"]
            and shape["top"] <= y <= shape["bottom"]
        ):
            return True
    return False


def _hidden(char, width: float, height: float, shapes) -> bool:
    if char.get("size", MIN_SIZE) < MIN_SIZE:
        return True
    if char["x1"] < 0 or char["x0"] > width or char["bottom"] < 0 or char["top"] > height:
        return True
    return _white(char.get("non_stroking_color")) and not _on_colour(char, shapes)


def _shown(page) -> str | None:
    """The text a pdfplumber page shows, or None where it shows every character it holds."""
    width, height, shapes = float(page.width), float(page.height), page.rects
    if not any(_hidden(c, width, height, shapes) for c in page.chars):
        return None
    kept = page.filter(
        lambda o: o.get("object_type") != "char" or not _hidden(o, width, height, shapes)
    )
    return kept.extract_text() or ""


@functools.lru_cache(maxsize=32)
def _pages(pdf: pathlib.Path, stamp: tuple[int, int]) -> dict[int, tuple[str, str]]:
    pypdf, pdfplumber = readers.pypdf, readers.pdfplumber
    if pypdf is None or pdfplumber is None:
        return {}
    try:
        doc = pypdf.PdfReader(str(pdf))
        flagged = []
        for number, page in enumerate(doc.pages, start=1):
            contents = page.get_contents()
            data = contents.get_data() if contents is not None else b""
            box = page.mediabox
            if data and _suspicious(data, float(box.width), float(box.height)):
                flagged.append(number)
    except Exception:  # a document pypdf cannot parse is reported elsewhere, not here
        return {}
    out: dict[int, tuple[str, str]] = {}
    if not flagged:
        return out
    try:
        with pdfplumber.open(pdf) as plumbed:
            for number in flagged:
                page = plumbed.pages[number - 1]
                if (shown := _shown(page)) is not None:
                    out[number] = (page.extract_text() or "", shown)
    except Exception:
        return {}
    return out


def pages(pdf: pathlib.Path) -> dict[int, tuple[str, str]]:
    """Each page carrying text it does not show, as its whole text and the text it shows.

    Empty where every page shows all its text, where the file is not a PDF the two readers can
    open, and where either reader is not installed. Cached on the file's size and modification
    time, so a run reads each document once.
    """
    try:
        st = pdf.stat()
    except OSError:
        return {}
    if pdf.suffix.lower() != ".pdf":
        try:
            with pdf.open("rb") as handle:
                if not handle.read(5).startswith(b"%PDF"):
                    return {}
        except OSError:
            return {}
    return _pages(pdf, (st.st_size, st.st_mtime_ns))


def cache_clear() -> None:
    _pages.cache_clear()
