"""A quotation checked against the wrong document resolves perfectly.

`verify` reads the artifact a record names and matches the passage against it. Whether that
artifact is still the one the record pinned was never checked: 355 sources in the corpus carry
a sha256 and nothing compared it to the file on disk. A source edited after being pinned passes
every quotation check in the library.
"""
from __future__ import annotations

import pytest
from citations import verify as V
from citations.exceptions import SourceUnreadableError


def artifact(tmp_path, text="the measured angle matches the Haar expectation for this ensemble"):
    p = tmp_path / "source.txt"
    p.write_text(text)
    return p


def test_an_untouched_artifact_matches_its_pin(tmp_path):
    p = artifact(tmp_path)
    assert V.check_pin(p, V.sha256(p)).state == "ok"


def test_one_changed_byte_breaks_the_pin(tmp_path):
    p = artifact(tmp_path)
    pinned = V.sha256(p)
    V.sha256.cache_clear()
    p.write_text(p.read_text().replace("Haar", "Poisson"))
    pin = V.check_pin(p, pinned)
    assert pin.state == "broken"
    assert pin.expected == pinned and pin.actual != pinned


def test_a_source_with_no_recorded_hash_is_unpinned_not_ok(tmp_path):
    # Reporting an unchecked source as `ok` claims a guarantee the record does not make.
    p = artifact(tmp_path)
    for empty in ("", "   ", None):
        assert V.check_pin(p, empty).state == "unpinned"


def test_a_named_artifact_that_is_not_there_is_missing(tmp_path):
    assert V.check_pin(tmp_path / "absent.txt", "abc123").state == "missing"
    assert V.check_pin(None, "abc123").state == "missing"


def test_a_broken_pin_makes_the_report_fail_even_when_every_quote_resolved(tmp_path):
    rep = V.Report(checked=12, counts={"found": 12})
    assert rep.ok
    rep.broken_pins.append(("some-source", V.Pin("broken", "aaa", "bbb")))
    assert not rep.ok


def test_a_run_that_checked_nothing_is_not_a_pass():
    assert not V.Report(checked=0).ok


# --- an extraction that failed is not a document that is empty ---------------------------------

def test_a_missing_extractor_raises_rather_than_reporting_no_text(tmp_path, monkeypatch):
    # Returning "" here makes every PDF quote `unchecked` and the summary read "nothing
    # failed", so a missing binary is indistinguishable from an unreadable document.
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4 not really a pdf")

    def no_such_binary(*a, **kw):
        raise FileNotFoundError("pdftotext")

    monkeypatch.setattr(V.subprocess, "run", no_such_binary)
    V.extract.cache_clear()
    with pytest.raises(SourceUnreadableError) as e:
        V.extract(pdf)
    assert "PATH" in str(e.value)


def test_a_failed_extraction_surfaces_its_reason_in_the_result(tmp_path, monkeypatch):
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    def no_such_binary(*a, **kw):
        raise FileNotFoundError("pdftotext")

    monkeypatch.setattr(V.subprocess, "run", no_such_binary)
    V.extract.cache_clear()
    r = V.check_one("a passage long enough to clear the minimum quote length here", pdf)
    assert r.state == "unchecked"
    assert "pdftotext" in r.detail, "the reason has to reach the report, not just the log"


def test_a_page_scan_that_hits_its_limit_says_so_rather_than_reporting_absence(tmp_path):
    # Returning None for both "not on any page" and "stopped looking" makes a cap read as a
    # finding.
    p = artifact(tmp_path)
    found, capped = V._find_page(p, "nothing like this appears", limit=3)
    assert found is None and capped is False, "a text file ends, so the scan ran out of document"
