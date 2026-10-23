"""A passage a PDF carries in its text layer and does not show on the page.

White text on a white page is extracted by every reader and seen by no reader of the page, so
a sentence planted there resolved as `found`. The PDFs are built here, so the bytes are in view.
"""

from __future__ import annotations

import pathlib
import shutil
import zlib

import pytest
from citations import readers as R
from citations import verify as V

pytestmark = pytest.mark.skipif(
    R.pdfplumber is None or R.pypdf is None or shutil.which("pdftotext") is None,
    reason="needs pdfplumber, pypdf and poppler",
)

SHOWN = "The intervention did not improve recall in older adults at any dose tested."
PLANTED = "The intervention reliably improved recall in older adults at every dose."


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    monkeypatch.setenv("CITATIONS_NO_CACHE", "1")
    V.clear_caches()


def pdf(
    path: pathlib.Path, lines: list[tuple[str, str]], box: str = "", x: list[int] | None = None
) -> pathlib.Path:
    """A one-page PDF: each line as (operators setting how it is drawn, text), at `x` points
    from the left edge, 72 where `x` is not given."""
    body = [box] if box else []
    y = 720
    for i, (how, text) in enumerate(lines):
        left = x[i] if x else 72
        body += ["BT", how or "0 g /F1 11 Tf", f"1 0 0 1 {left} {y} Tm", f"({text}) Tj", "ET"]
        y -= 20
    stream = zlib.compress("\n".join(body).encode())
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + obj + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        xref,
    )
    path.write_bytes(bytes(out))
    return path


@pytest.mark.parametrize(
    "how",
    [
        "1 g /F1 11 Tf",  # white, in gray
        "1 1 1 rg /F1 11 Tf",  # white, in RGB
        "0 g /F1 0.2 Tf",  # under a point
    ],
)
def test_a_passage_the_page_does_not_show_is_warned(tmp_path, how):
    p = pdf(tmp_path / "s.pdf", [("", SHOWN), (how, PLANTED)])
    r = V.check_one(PLANTED, p)
    assert r.state == "found"
    assert "invisible" in r.warnings
    assert "invisible" in V.STRICT_WARNINGS


def test_a_passage_set_off_the_page_is_warned(tmp_path):
    p = pdf(tmp_path / "s.pdf", [("", SHOWN), ("", PLANTED)], x=[72, 900])
    r = V.check_one(PLANTED, p)
    if r.state != "found":
        pytest.skip("no reader here extracts text placed off the page")
    assert "invisible" in r.warnings


def test_a_passage_the_page_shows_is_not_warned(tmp_path):
    p = pdf(tmp_path / "s.pdf", [("", SHOWN), ("", PLANTED)])
    r = V.check_one(PLANTED, p)
    assert r.state == "found"
    assert "invisible" not in r.warnings


def test_white_text_on_a_dark_box_is_shown(tmp_path):
    box = "0 0 0.5 rg 60 680 500 60 re f"
    p = pdf(tmp_path / "s.pdf", [("", SHOWN), ("1 g /F1 11 Tf", PLANTED)], box=box)
    r = V.check_one(PLANTED, p)
    assert r.state == "found"
    assert "invisible" not in r.warnings


def test_the_shown_passage_beside_a_hidden_one_is_not_warned(tmp_path):
    p = pdf(tmp_path / "s.pdf", [("", SHOWN), ("1 g /F1 11 Tf", PLANTED)])
    r = V.check_one(SHOWN, p)
    assert r.state == "found"
    assert "invisible" not in r.warnings
