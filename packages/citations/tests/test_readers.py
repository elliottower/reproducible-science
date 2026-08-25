"""A single extractor is an unverifiable oracle.

The pin establishes that the bytes did not change. Nothing establishes that the reader turned
those bytes into the right text, and a mangled extraction produces a confident `not found`
that accuses a manuscript of misquoting a source it quotes correctly. These pin the two
properties that follow: readers disagreeing must never surface as a quotation failure, and a
reader standing in for the preferred one must never do so silently.
"""

from __future__ import annotations

import pathlib
import zlib

import pytest
from citations import readers as R
from citations import verify as V
from citations.exceptions import SourceUnreadableError

PASSAGE = "the measured angle matches the Haar expectation for this ensemble of unitaries"
OTHER = "an entirely different sentence about something else that is nowhere near the first"


@pytest.fixture(autouse=True)
def _no_cache():
    V.clear_caches()


@pytest.fixture
def pdf(tmp_path):
    p = tmp_path / "source.pdf"
    p.write_bytes(b"%PDF-1.4 a file that exists")
    return p


def stub_readers(monkeypatch, texts: dict[str, str | Exception]):
    """Replace the reader registry with readers that answer from `texts`.

    A value that is an exception is raised, so "this reader could not open the file" and "this
    reader read it and the passage is not there" are expressible separately -- which is the
    distinction every test below turns on.
    """

    def make(name, answer):
        def read(path, page=None):
            if isinstance(answer, Exception):
                raise answer
            return answer

        return R.Reader(name, read, lambda: True, lambda: "stub")

    monkeypatch.setattr(R, "READERS", {n: make(n, a) for n, a in texts.items()})
    monkeypatch.setattr(R, "PREFERRED", tuple(texts))


# --- disagreement is not a mismatch -----------------------------------------------------------


def test_readers_that_disagree_are_indeterminate_and_never_not_found(pdf, monkeypatch):
    # The whole point. `not found` says the source was read and the passage is not in it,
    # which is an accusation against the manuscript; two readers disagreeing says the readers
    # do not settle it, which accuses nothing.
    stub_readers(monkeypatch, {"poppler": PASSAGE, "pdfplumber": OTHER, "pypdf": OTHER})
    r = V.check_one(PASSAGE, pdf, triangulate=True)
    assert r.state == "indeterminate"
    assert r.state != "not found"
    assert r.agreement == {"poppler": "found", "pdfplumber": "not found", "pypdf": "not found"}


def test_the_disagreement_names_which_reader_said_what(pdf, monkeypatch):
    stub_readers(monkeypatch, {"poppler": PASSAGE, "pypdf": OTHER})
    r = V.check_one(PASSAGE, pdf, triangulate=True)
    assert "poppler found" in r.detail and "pypdf not found" in r.detail


def test_readers_that_agree_the_passage_is_absent_still_say_not_found(pdf, monkeypatch):
    # Triangulation must not turn every negative into an abstention, or it would be a way of
    # never failing a quotation.
    stub_readers(monkeypatch, {"poppler": OTHER, "pdfplumber": OTHER, "pypdf": OTHER})
    assert V.check_one(PASSAGE, pdf, triangulate=True).state == "not found"


def test_readers_that_agree_the_passage_is_present_say_found(pdf, monkeypatch):
    stub_readers(monkeypatch, {"poppler": PASSAGE, "pdfplumber": PASSAGE, "pypdf": PASSAGE})
    r = V.check_one(PASSAGE, pdf, triangulate=True)
    assert r.state == "found"
    assert len(r.agreement) == 3


def test_a_reader_that_could_not_open_the_file_casts_no_vote(pdf, monkeypatch):
    # A failure to open is not a verdict of absence. Counting it as one would make an
    # uninstallable parser look like a disagreement about the document.
    stub_readers(
        monkeypatch,
        {
            "poppler": PASSAGE,
            "pdfplumber": SourceUnreadableError(pdf, "pdfplumber could not read it"),
            "pypdf": PASSAGE,
        },
    )
    r = V.check_one(PASSAGE, pdf, triangulate=True)
    assert r.state == "found"
    assert set(r.agreement) == {"poppler", "pypdf"}


def test_indeterminate_is_not_a_quotation_failure_but_is_not_a_strict_pass():
    rep = V.Report(checked=1, counts={"indeterminate": 1})
    assert rep.ok, "the passage may well be there; failing the paper for it would be the bug"
    assert not rep.strict_ok, "and nothing was established, so --strict must refuse it"
    assert rep.unresolved == 1


# --- availability is not agreement ------------------------------------------------------------


def test_triangulating_with_one_reader_establishes_no_agreement(pdf, monkeypatch):
    # A fallback answers "something could read it". Triangulation answers "do readers agree".
    # One reader answers the first and cannot answer the second, and the result must not read
    # as three readers concurring.
    stub_readers(monkeypatch, {"pypdf": PASSAGE})
    r = V.check_one(PASSAGE, pdf, triangulate=True)
    assert r.state == "found"
    assert list(r.agreement) == ["pypdf"], "one reader is not a consensus"


def test_a_single_reader_check_records_no_agreement_at_all(pdf, monkeypatch):
    # An empty mapping means agreement was never measured. Were it to default to "everyone
    # agreed", every default check would claim a triangulation it never performed.
    stub_readers(monkeypatch, {"poppler": PASSAGE, "pypdf": OTHER})
    r = V.check_one(PASSAGE, pdf)
    assert r.state == "found"
    assert r.agreement == {}


# --- a fallback is never silent ---------------------------------------------------------------


def test_the_reader_is_recorded_on_every_result(pdf, monkeypatch):
    stub_readers(monkeypatch, {"poppler": PASSAGE})
    assert V.check_one(PASSAGE, pdf).reader == "poppler"


def test_standing_in_for_an_absent_preferred_reader_is_recorded_as_a_fallback(pdf, monkeypatch):
    def missing(path, page=None):  # pragma: no cover - never called; poppler is absent
        raise AssertionError("an unavailable reader must not be asked to read")

    monkeypatch.setattr(
        R,
        "READERS",
        {
            "poppler": R.Reader("poppler", missing, lambda: False, lambda: "absent"),
            "pypdf": R.Reader("pypdf", lambda p, page=None: PASSAGE, lambda: True, lambda: "stub"),
        },
    )
    monkeypatch.setattr(R, "PREFERRED", ("poppler", "pypdf"))
    r = V.check_one(PASSAGE, pdf)
    assert r.state == "found"
    assert r.reader == "pypdf"
    assert r.fallback is True
    assert "poppler is not installed" in r.fallback_reason


def test_standing_in_for_a_preferred_reader_that_failed_is_also_recorded(pdf, monkeypatch):
    # Installed-and-broken is a different fact from absent, and both are substitutions. A
    # report that shows one and hides the other cannot be compared with a later run.
    stub_readers(
        monkeypatch,
        {"poppler": SourceUnreadableError(pdf, "pdftotext exited 1"), "pypdf": PASSAGE},
    )
    r = V.check_one(PASSAGE, pdf)
    assert r.reader == "pypdf"
    assert r.fallback is True
    assert "pdftotext exited 1" in r.fallback_reason


def test_the_preferred_reader_answering_is_not_a_fallback(pdf, monkeypatch):
    stub_readers(monkeypatch, {"poppler": PASSAGE, "pypdf": PASSAGE})
    r = V.check_one(PASSAGE, pdf)
    assert r.reader == "poppler"
    assert r.fallback is False
    assert r.fallback_reason == ""


def test_a_fallback_reaches_the_report_rather_than_only_the_result(pdf, monkeypatch):
    from citations import cli

    stub_readers(
        monkeypatch, {"poppler": SourceUnreadableError(pdf, "no such binary"), "pypdf": PASSAGE}
    )
    rep = V.Report()
    cli._record_reader(rep, V.check_one(PASSAGE, pdf))
    assert rep.readers_used == {"pypdf": 1}
    assert "no such binary" in rep.fallback_reasons["pypdf"]


# --- unchecked only where nothing could read it -----------------------------------------------


def test_unchecked_only_when_no_reader_is_available(pdf, monkeypatch):
    monkeypatch.setattr(R, "READERS", {})
    monkeypatch.setattr(R, "PREFERRED", ())
    r = V.check_one(PASSAGE, pdf)
    assert r.state == "unchecked"
    assert "pip install" in r.detail and "poppler" in r.detail


def test_a_missing_extra_is_reported_and_never_raised(pdf, monkeypatch):
    # The failure mode this replaces is a traceback out of `citations verify` on a machine
    # where an optional dependency is not installed.
    monkeypatch.setattr(R, "pdfplumber", None)
    monkeypatch.setattr(
        R,
        "READERS",
        {"pdfplumber": R.Reader("pdfplumber", R._read_pdfplumber, lambda: True, lambda: "absent")},
    )
    monkeypatch.setattr(R, "PREFERRED", ("pdfplumber",))
    r = V.check_one(PASSAGE, pdf)
    assert r.state == "unchecked"
    assert "pdfplumber is not installed" in r.detail


def test_every_reader_failing_is_unchecked_not_not_found(pdf, monkeypatch):
    stub_readers(
        monkeypatch,
        {
            "poppler": SourceUnreadableError(pdf, "pdftotext exited 1"),
            "pypdf": SourceUnreadableError(pdf, "pypdf could not read it"),
        },
    )
    r = V.check_one(PASSAGE, pdf, triangulate=True)
    assert r.state == "unchecked"
    assert "pdftotext" in r.detail and "pypdf" in r.detail


def test_naming_a_reader_never_falls_through_to_another(pdf, monkeypatch):
    # A caller naming one reader is comparing it with a second. Substituting silently would
    # make two readers look like one and turn a disagreement into an agreement.
    stub_readers(
        monkeypatch,
        {"poppler": SourceUnreadableError(pdf, "pdftotext exited 1"), "pypdf": PASSAGE},
    )
    with pytest.raises(SourceUnreadableError):
        R.read(pdf, reader="poppler")


# --- the real readers, on a real PDF ----------------------------------------------------------


def one_page_pdf(path: pathlib.Path, lines: list[str]) -> pathlib.Path:
    """A minimal single-page PDF carrying `lines` as Helvetica text.

    Built here rather than committed as a fixture so the bytes are visible to anyone reading
    the test: a binary fixture would make "all three readers agree" a claim about a file
    nobody can inspect.
    """
    body = ["BT", "/F1 11 Tf", "72 720 Td", "14 TL"]
    for line in lines:
        body.append(f"({line}) Tj T*")
    body.append("ET")
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
    out += b"xref\n0 %d\n" % (len(objects) + 1)
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        xref,
    )
    path.write_bytes(bytes(out))
    return path


PROSE = [
    "The measured angle matches the Haar expectation for this ensemble",
    "of unitaries, and the residual is smaller than the sampling error",
    "we report in the preceding section of this document.",
]


@pytest.mark.integration
def test_every_installed_reader_opens_a_well_formed_pdf(tmp_path):
    source = one_page_pdf(tmp_path / "prose.pdf", PROSE)
    for name in R.available():
        assert R.read(source, reader=name).text.strip(), f"{name} extracted nothing"


@pytest.mark.integration
def test_the_installed_readers_agree_on_a_passage_that_is_there(tmp_path):
    source = one_page_pdf(tmp_path / "prose.pdf", PROSE)
    if len(R.available()) < 2:
        pytest.skip("triangulation needs two readers")
    r = V.check_one(PROSE[0], source, triangulate=True)
    assert r.state == "found"
    assert len(set(r.agreement.values())) == 1


@pytest.mark.integration
def test_the_installed_readers_agree_on_a_passage_that_is_not_there(tmp_path):
    source = one_page_pdf(tmp_path / "prose.pdf", PROSE)
    if len(R.available()) < 2:
        pytest.skip("triangulation needs two readers")
    absent = "a sentence that appears nowhere in this document at any point whatsoever"
    r = V.check_one(absent, source, triangulate=True)
    assert r.state == "not found"


@pytest.mark.integration
def test_a_reader_names_itself_and_its_version(tmp_path):
    source = one_page_pdf(tmp_path / "prose.pdf", PROSE)
    for name in R.available():
        got = R.read(source, reader=name)
        assert got.reader == name
        assert got.version and got.version != "unknown"
