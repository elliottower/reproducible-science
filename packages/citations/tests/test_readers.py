"""A single extractor is an unverifiable oracle.

The pin establishes that the bytes did not change. Nothing establishes that the extractor
turned them into the right text, and a mangled extraction produces a confident `not found`
that accuses a manuscript of misquoting a source it quotes correctly. These pin the properties
that follow: extractors disagreeing must never surface as a quotation failure, one standing in
for another must never do so silently, and a declared command must not be quietly replaced by
a reader its author did not name.
"""

from __future__ import annotations

import pathlib
import shutil
import zlib

import pytest
from citations import readers as R
from citations import verify as V
from citations.exceptions import SourceUnreadableError

PASSAGE = "the measured angle matches the Haar expectation for this ensemble of unitaries"
OTHER = "an entirely different sentence about something else that is nowhere near the first"
POPPLER = V.DEFAULT_EXTRACTOR


@pytest.fixture(autouse=True)
def _no_cache():
    V.clear_caches()


@pytest.fixture
def renderer(tmp_path):
    """A script standing in for a declared renderer, as `test_extract_cmd.py` uses one."""

    def make(name: str, body: str) -> pathlib.Path:
        script = tmp_path / name
        script.write_text(f"#!/bin/sh\n{body}\n")
        script.chmod(0o755)
        return script

    return make


@pytest.fixture
def pdf(tmp_path):
    p = tmp_path / "source.pdf"
    p.write_bytes(b"%PDF-1.4 a file that exists")
    return p


def answer(value):
    """A reader that returns `value`, or raises it when it is an exception."""

    def read(path, page=None):
        if isinstance(value, Exception):
            raise value
        return value

    return read


ABSENT = SourceUnreadableError(pathlib.Path("x"), "pdftotext is not on PATH")


def stub_extractors(monkeypatch, poppler=None, flow=None, pure=None):
    """Replace the extractors with ones that answer from the arguments.

    `poppler=None` means the binary is not there at all; an exception means it is there and
    failed on this document. Those are different facts and every test below turns on the
    difference between one of them and "read it, and the passage is not in it".

    `flow` is poppler's reading order -- the same binary with `-layout` removed. It defaults to
    whatever `-layout` answered, since one document usually reads the same both ways; a test
    passes it separately to make the two modes disagree.
    """
    pure = pure or {}
    layout_answer = ABSENT if poppler is None else poppler
    flow_answer = layout_answer if flow is None else flow

    def poppler_read(path, page=None, layout=True):
        return answer(layout_answer if layout else flow_answer)(path, page)

    monkeypatch.setattr(V, "_poppler", poppler_read)
    monkeypatch.setattr(
        R, "READERS", {n: R.Reader(n, answer(v), lambda: True) for n, v in pure.items()}
    )
    monkeypatch.setattr(R, "PREFERRED", tuple(pure))
    monkeypatch.setattr(V.shutil, "which", lambda name: None if poppler is None else f"/x/{name}")


# --- disagreement is not a mismatch -------------------------------------------------------------


def test_extractors_that_disagree_are_indeterminate_and_never_not_found(pdf, monkeypatch):
    # The whole point. `not found` says the source was read and the passage is not in it,
    # which is an accusation against the manuscript; two extractors disagreeing says they do
    # not settle it, which accuses nothing.
    stub_extractors(monkeypatch, poppler=PASSAGE, pure={"pypdf": OTHER, "pdfplumber": OTHER})
    r = V.check_one(PASSAGE, pdf, triangulate=True)
    assert r.state == "indeterminate"
    assert r.state != "not found"
    assert r.agreement == {
        POPPLER: "found",
        V.READING_ORDER: "found",
        "pypdf": "not found",
        "pdfplumber": "not found",
    }


def test_the_disagreement_names_which_extractor_said_what(pdf, monkeypatch):
    stub_extractors(monkeypatch, poppler=PASSAGE, pure={"pypdf": OTHER})
    r = V.check_one(PASSAGE, pdf, triangulate=True)
    assert f"{POPPLER} found" in r.detail and "pypdf not found" in r.detail


def test_extractors_that_agree_the_passage_is_absent_still_say_not_found(pdf, monkeypatch):
    # Triangulation must not turn every negative into an abstention, or it would be a way of
    # never failing a quotation.
    stub_extractors(monkeypatch, poppler=OTHER, pure={"pypdf": OTHER, "pdfplumber": OTHER})
    assert V.check_one(PASSAGE, pdf, triangulate=True).state == "not found"


def test_extractors_that_agree_the_passage_is_present_say_found(pdf, monkeypatch):
    stub_extractors(monkeypatch, poppler=PASSAGE, pure={"pypdf": PASSAGE, "pdfplumber": PASSAGE})
    r = V.check_one(PASSAGE, pdf, triangulate=True)
    assert r.state == "found"
    assert len(r.agreement) == 4


def test_an_extractor_that_could_not_open_the_file_casts_no_vote(pdf, monkeypatch):
    # A failure to open is not a verdict of absence. Counting it as one would make an
    # uninstallable parser look like a disagreement about the document.
    stub_extractors(
        monkeypatch,
        poppler=PASSAGE,
        pure={"pypdf": PASSAGE, "pdfplumber": SourceUnreadableError(pdf, "could not read it")},
    )
    r = V.check_one(PASSAGE, pdf, triangulate=True)
    assert r.state == "found"
    assert set(r.agreement) == {POPPLER, V.READING_ORDER, "pypdf"}


def test_the_two_poppler_modes_disagreeing_is_reported_rather_than_resolved(pdf, monkeypatch):
    """Measured, not hypothetical: over 1,593 passage checks in `research/pdf-readers/`,
    reading order resolved 59 passages `-layout` missed and missed 29 it resolved. A sentence
    spanning two columns is the first case and a subscript beside it is the second, so
    consulting either mode alone hides whichever failure the document has. Neither is right in
    general, which is why this is `indeterminate` rather than a preference between them."""
    stub_extractors(monkeypatch, poppler=OTHER, flow=PASSAGE, pure={"pypdf": PASSAGE})
    r = V.check_one(PASSAGE, pdf, triangulate=True)
    assert r.state == "indeterminate"
    assert r.agreement[POPPLER] == "not found"
    assert r.agreement[V.READING_ORDER] == "found"


def test_a_passage_the_default_reader_misses_is_rescued_and_the_rescue_is_named(pdf, monkeypatch):
    # Reading order was a triangulation participant and not a second chance, on the reasoning
    # that the default path costs one extraction per document. Measured against a real corpus
    # that cost 110 false accusations on a single two-column paper, where `-layout` interleaves
    # the columns and shreds every sentence spanning the gutter. `not found` is an accusation,
    # so it now takes more than one reader to make it -- and the reader that made it is named,
    # because a rescued passage must not read like one the default reader found itself.
    stub_extractors(monkeypatch, poppler=OTHER, flow=PASSAGE, pure={"pypdf": PASSAGE})
    r = V.check_one(PASSAGE, pdf)
    assert r.state == "found"
    assert r.extractor != POPPLER
    assert r.fallback
    assert POPPLER in r.fallback_reason


def test_a_passage_no_reader_finds_stays_not_found_and_says_who_looked(pdf, monkeypatch):
    stub_extractors(monkeypatch, poppler=OTHER, flow=OTHER, pure={"pypdf": OTHER})
    r = V.check_one(PASSAGE, pdf)
    assert r.state == "not found"
    assert "pypdf" in r.detail and POPPLER in r.detail


def test_the_default_path_still_reads_one_reader_when_the_passage_is_there(pdf, monkeypatch):
    # The escalation is on the failure path alone. A passage the first reader resolves must
    # not pay for the others.
    stub_extractors(monkeypatch, poppler=PASSAGE, flow=PASSAGE, pure={"pypdf": PASSAGE})
    r = V.check_one(PASSAGE, pdf)
    assert (r.state, r.extractor, r.fallback) == ("found", POPPLER, False)


def test_indeterminate_is_not_a_quotation_failure_but_is_not_a_strict_pass():
    rep = V.Report(checked=1, counts={"indeterminate": 1})
    assert rep.ok, "the passage may well be there; failing the paper for it would be the bug"
    assert not rep.strict_ok, "and nothing was established, so --strict must refuse it"
    assert rep.unresolved == 1


# --- availability is not agreement ---------------------------------------------------------------


def test_triangulating_with_one_extractor_establishes_no_agreement(pdf, monkeypatch):
    # A fallback answers "something could read it". Triangulation answers "do they agree".
    # One extractor answers the first and cannot answer the second.
    stub_extractors(monkeypatch, poppler=None, pure={"pypdf": PASSAGE})
    r = V.check_one(PASSAGE, pdf, triangulate=True)
    assert r.state == "found"
    assert list(r.agreement) == ["pypdf"], "one extractor is not a consensus"


def test_a_lone_extractor_can_never_produce_indeterminate(pdf, monkeypatch):
    # `indeterminate` is reached by comparing extractors. With one there is nothing to
    # compare, and a single-entry agreement must not read as disagreement -- that would stop a
    # one-reader machine verifying anything at all.
    stub_extractors(monkeypatch, poppler=None, pure={"pypdf": PASSAGE})
    for triangulate in (False, True):
        assert V.check_one(PASSAGE, pdf, triangulate=triangulate).state == "found"
        assert V.check_one(OTHER, pdf, triangulate=triangulate).state == "not found"


def test_a_single_extractor_check_records_no_agreement_at_all(pdf, monkeypatch):
    # An empty mapping means agreement was never measured. Were it to default to "everyone
    # agreed", every default check would claim a triangulation it never performed.
    stub_extractors(monkeypatch, poppler=PASSAGE, pure={"pypdf": OTHER})
    r = V.check_one(PASSAGE, pdf)
    assert r.state == "found"
    assert r.agreement == {}


# --- a declared command is the author naming the extractor ---------------------------------------


def test_a_declared_command_is_never_triangulated(tmp_path, renderer):
    # One declared extractor, nothing to disagree with. Asking the readers as well would
    # compare a renderer's output against a PDF reader's over a source whose author said is
    # not a PDF, and report the difference as the document being indeterminate.
    source = tmp_path / "manuscript.tex"
    source.write_text("irrelevant")
    script = renderer("render", f"printf '%s\\n' {PASSAGE!r}")
    r = V.check_one(PASSAGE, source, None, str(script), frozenset({str(script)}), triangulate=True)
    assert r.state == "found"
    assert r.agreement == {}
    assert r.extractor == str(script)


def test_a_declared_command_that_fails_does_not_fall_through_to_a_reader(tmp_path, monkeypatch):
    # Falling through would run a PDF reader over a source the author said is not one, and
    # record an extractor nobody asked for on a result the author cannot account for.
    source = tmp_path / "manuscript.tex"
    source.write_text("irrelevant")
    stub_extractors(monkeypatch, poppler=PASSAGE, pure={"pypdf": PASSAGE})
    missing = "no-such-renderer-4d91b2"
    r = V.check_one(PASSAGE, source, None, missing, frozenset({missing}))
    assert r.state == "unchecked"
    assert r.extractor == "", "nothing read it, so nothing is named"
    assert "PATH" in r.detail


# --- a fallback is never silent -------------------------------------------------------------------


def test_the_extractor_is_recorded_on_every_result(pdf, monkeypatch):
    stub_extractors(monkeypatch, poppler=PASSAGE)
    assert V.check_one(PASSAGE, pdf).extractor == POPPLER


def test_standing_in_for_an_absent_poppler_is_recorded_as_a_fallback(pdf, monkeypatch):
    stub_extractors(monkeypatch, poppler=None, pure={"pypdf": PASSAGE})
    r = V.check_one(PASSAGE, pdf)
    assert r.state == "found"
    assert r.extractor == "pypdf"
    assert r.fallback is True
    assert "PATH" in r.fallback_reason


def test_standing_in_for_a_poppler_that_failed_is_also_recorded(pdf, monkeypatch):
    # Installed-and-broken is a different fact from absent, and both are substitutions. A
    # report that shows one and hides the other cannot be compared with a later run.
    stub_extractors(
        monkeypatch,
        poppler=SourceUnreadableError(pdf, "pdftotext exited 1"),
        pure={"pypdf": PASSAGE},
    )
    r = V.check_one(PASSAGE, pdf)
    assert r.extractor == "pypdf"
    assert r.fallback is True
    assert "pdftotext exited 1" in r.fallback_reason


def test_poppler_answering_is_not_a_fallback(pdf, monkeypatch):
    stub_extractors(monkeypatch, poppler=PASSAGE, pure={"pypdf": PASSAGE})
    r = V.check_one(PASSAGE, pdf)
    assert r.extractor == POPPLER
    assert r.fallback is False
    assert r.fallback_reason == ""


def test_a_fallback_reaches_the_report_rather_than_only_the_result(pdf, monkeypatch):
    import collections

    from citations import cli

    stub_extractors(
        monkeypatch, poppler=SourceUnreadableError(pdf, "no such binary"), pure={"pypdf": PASSAGE}
    )
    rep = V.Report()
    counted: collections.Counter = collections.Counter()
    cli._record_extractor(rep, counted, V.check_one(PASSAGE, pdf))
    assert counted == {"pypdf": 1}
    assert "no such binary" in rep.fallback_reasons["pypdf"]


# --- unchecked only where nothing could read it ----------------------------------------------------


def test_unchecked_only_when_nothing_can_read_the_source(pdf, monkeypatch):
    stub_extractors(monkeypatch, poppler=None, pure={})
    r = V.check_one(PASSAGE, pdf)
    assert r.state == "unchecked"
    assert "PATH" in r.detail


def test_a_missing_extra_is_reported_and_never_raised(pdf, monkeypatch):
    # The failure mode this replaces is a traceback out of `citations verify` on a machine
    # where an optional dependency is not installed.
    monkeypatch.setattr(R, "pdfplumber", None)
    monkeypatch.setattr(V, "_poppler", answer(SourceUnreadableError(pdf, "pdftotext absent")))
    monkeypatch.setattr(
        R, "READERS", {"pdfplumber": R.Reader("pdfplumber", R._read_pdfplumber, lambda: True)}
    )
    monkeypatch.setattr(R, "PREFERRED", ("pdfplumber",))
    r = V.check_one(PASSAGE, pdf)
    assert r.state == "unchecked"
    assert "pdfplumber is not installed" in r.detail


def test_every_extractor_failing_is_unchecked_not_not_found(pdf, monkeypatch):
    stub_extractors(
        monkeypatch,
        poppler=SourceUnreadableError(pdf, "pdftotext exited 1"),
        pure={"pypdf": SourceUnreadableError(pdf, "pypdf could not read it")},
    )
    r = V.check_one(PASSAGE, pdf, triangulate=True)
    assert r.state == "unchecked"
    assert "pdftotext" in r.detail and "pypdf" in r.detail


def test_naming_an_extractor_never_falls_through_to_another(pdf, monkeypatch):
    # A caller naming one extractor is comparing it with a second. Substituting silently would
    # make two look like one and turn a disagreement into an agreement.
    stub_extractors(
        monkeypatch,
        poppler=SourceUnreadableError(pdf, "pdftotext exited 1"),
        pure={"pypdf": PASSAGE},
    )
    with pytest.raises(SourceUnreadableError):
        V.reading_with(pdf, extractor=POPPLER)


# --- the seam other packages stand in for ------------------------------------------------------


def test_replacing_extract_replaces_the_text_the_default_check_sees(pdf, monkeypatch):
    """`repro`'s quote backend calls `check_one`, and its regression suite replaces `extract`.
    Routing the default check around it left those tests measuring 42 bytes of stand-in PDF:
    every extractor failed on it, the decision became `unchecked` instead of `mismatch`, and
    `publication` warns on unchecked rather than failing -- so a wrong-page misquote passed an
    assessment it had been failing."""
    monkeypatch.setattr(V, "extract", lambda path, page=None, cmd=None, allowed=None: PASSAGE)
    r = V.check_one(PASSAGE, pdf)
    assert r.state == "found"
    assert r.extractor == V.SUBSTITUTED, "the text did not come from an extractor, and says so"


def test_a_per_page_stub_still_decides_the_page_warning(pdf, monkeypatch):
    # The wrong-page check reads each page through the same seam. Reading page 1 with a real
    # extractor while the document text came from a stub compares two different documents.
    monkeypatch.setattr(
        V,
        "extract",
        lambda path, page=None, cmd=None, allowed=None: PASSAGE if page in (None, 2) else OTHER,
    )
    assert "page" not in V.check_one(PASSAGE, pdf, page=2).warnings
    r = V.check_one(PASSAGE, pdf, page=1)
    assert r.state == "found"
    assert "page" in r.warnings


def test_clearing_extract_alone_leaves_the_second_opinion_cache_stale(pdf, monkeypatch):
    # `clear_caches` exists because clearing four of five leaves a stale answer that looks
    # fresh. The not-found path widened that surface: it consults `reading_with`, so any
    # check that escalated has populated a second cache the default path never touched.
    # Clear only `extract` afterwards and the rescue is re-served from text nothing on disk
    # holds any more.
    stub_extractors(monkeypatch, poppler=OTHER, flow=OTHER, pure={"pypdf": PASSAGE})
    assert V.check_one(PASSAGE, pdf).fallback, "this check must escalate to populate the cache"

    V.extract.cache_clear()
    stub_extractors(monkeypatch, poppler=OTHER, flow=OTHER, pure={"pypdf": OTHER})
    assert V.check_one(PASSAGE, pdf).state == "found", "the stale reading_with entry answered"


def test_clear_caches_clears_the_extraction_behind_it(pdf, monkeypatch):
    # The documented entry point clears every one of them, which is what it is for.
    stub_extractors(monkeypatch, poppler=PASSAGE)
    assert V.check_one(PASSAGE, pdf).state == "found"
    V.clear_caches()
    stub_extractors(monkeypatch, poppler=OTHER)
    assert V.check_one(PASSAGE, pdf).state == "not found"


# --- the real readers, on a real PDF ----------------------------------------------------------


def one_page_pdf(path: pathlib.Path, lines: list[str]) -> pathlib.Path:
    """A minimal single-page PDF carrying `lines` as Helvetica text.

    Built here rather than committed as a fixture so the bytes are visible to anyone reading
    the test: a binary fixture would make "every reader agrees" a claim about a file nobody
    can inspect.
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
def test_every_installed_extractor_opens_a_well_formed_pdf(tmp_path):
    source = one_page_pdf(tmp_path / "prose.pdf", PROSE)
    for name in V.available_extractors():
        assert V.reading_with(source, extractor=name).text.strip(), f"{name} extracted nothing"


@pytest.mark.integration
def test_the_installed_extractors_agree_on_a_passage_that_is_there(tmp_path):
    source = one_page_pdf(tmp_path / "prose.pdf", PROSE)
    if len(V.available_extractors()) < 2:
        pytest.skip("triangulation needs two extractors")
    r = V.check_one(PROSE[0], source, triangulate=True)
    assert r.state == "found"
    assert len(set(r.agreement.values())) == 1


@pytest.mark.integration
def test_the_installed_extractors_agree_on_a_passage_that_is_not_there(tmp_path):
    source = one_page_pdf(tmp_path / "prose.pdf", PROSE)
    if len(V.available_extractors()) < 2:
        pytest.skip("triangulation needs two extractors")
    absent = "a sentence that appears nowhere in this document at any point whatsoever"
    assert V.check_one(absent, source, triangulate=True).state == "not found"


@pytest.mark.integration
def test_an_extraction_names_the_extractor_that_produced_it(tmp_path):
    source = one_page_pdf(tmp_path / "prose.pdf", PROSE)
    for name in V.available_extractors():
        assert V.reading_with(source, extractor=name).extractor == name


@pytest.mark.integration
def test_the_two_poppler_modes_are_both_consulted_and_are_not_the_same_reading(tmp_path):
    # One binary and one flag between them, and they fail in opposite directions: `-layout`
    # breaks a sentence that spans two columns, reading order misplaces the subscripts beside
    # it. Consulting only one hides whichever failure that document has.
    if shutil.which("pdftotext") is None:
        pytest.skip("poppler is not installed")
    assert {V.DEFAULT_EXTRACTOR, V.READING_ORDER} <= set(V.available_extractors())
    source = one_page_pdf(tmp_path / "prose.pdf", PROSE)
    layout = V.reading_with(source, extractor=V.DEFAULT_EXTRACTOR)
    flow = V.reading_with(source, extractor=V.READING_ORDER)
    assert layout.extractor != flow.extractor
    assert PROSE[0].lower() in V.fold(layout.text)
    assert PROSE[0].lower() in V.fold(flow.text)


# --- a failure is an answer, and answers are cached -------------------------------------------


def test_an_unreadable_source_is_attempted_once_not_once_per_quotation(pdf, monkeypatch):
    # `lru_cache` stores only on a normal return, so a cache around a raising function memoized
    # nothing: 2,210 poppler invocations for 14 artifacts, 158x the necessary work, and 95% of
    # a 21-minute run. The failure is per-document and is not a different failure the second
    # time it is asked for.
    attempts = {"n": 0}

    def counted(path, page=None, layout=True):
        attempts["n"] += 1
        raise V.SourceUnreadableError(path, "cannot be read")

    monkeypatch.setattr(V, "_poppler", counted)
    monkeypatch.setattr(R, "READERS", {})
    monkeypatch.setattr(R, "PREFERRED", ())

    for _ in range(20):
        assert V.check_one(PASSAGE, pdf).state == "unchecked"
    assert attempts["n"] == 1, f"one document, one attempt, got {attempts['n']}"


def test_clearing_the_cache_allows_a_repaired_source_to_be_read_again(pdf, monkeypatch):
    # The other half: a cached failure must not outlive the thing that caused it.
    stub_extractors(monkeypatch, poppler=None)
    assert V.check_one(PASSAGE, pdf).state == "unchecked"
    V.clear_caches()
    stub_extractors(monkeypatch, poppler=PASSAGE)
    assert V.check_one(PASSAGE, pdf).state == "found"


def test_a_cached_failure_reports_the_same_reason_every_time(pdf, monkeypatch):
    stub_extractors(monkeypatch, poppler=None)
    first = V.check_one(PASSAGE, pdf)
    again = V.check_one(PASSAGE, pdf)
    assert first.state == again.state == "unchecked"
    assert first.detail == again.detail


def test_every_registered_reader_is_reachable():
    """`available()` walks `PREFERRED`, so a reader only in `READERS` is never consulted.

    Nothing reports that: it is installed, it can read the document, and `_chain` and
    `_triangulate` both go through `available_extractors`, which goes through `available`. The
    two keysets are the same today and there is no mechanism keeping them so.
    """
    assert set(R.PREFERRED) == set(R.READERS), (
        f"registered but unreachable: {set(R.READERS) - set(R.PREFERRED)}; "
        f"named but unregistered: {set(R.PREFERRED) - set(R.READERS)}"
    )


def test_source_code_is_read_as_text_not_handed_to_a_pdf_reader(tmp_path):
    """A pinned .py is text, and pdftotext answers `Couldn't read xref table` on one.

    Pinning a module is how a claim about another project's behaviour names its source when
    that behaviour is absent from the project's prose. Sending it to a PDF extractor graded
    every quotation in it `unchecked`, which reads as "we could not check" rather than
    "nothing here needed a PDF reader".
    """
    src = tmp_path / "scoring.py"
    src.write_text('"""Not-applicable and unknown findings are excluded entirely."""\n')
    assert V._extractor_name(src, None) == V.PLAIN_TEXT
    assert V._extractor_name(src, None) != V.DEFAULT_EXTRACTOR
    assert "excluded entirely" in V.extract_uncached(src, None, None, frozenset())
