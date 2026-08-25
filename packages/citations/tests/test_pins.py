"""A quotation checked against the wrong document resolves perfectly.

`verify` reads the artifact a record names and matches the passage against it. Whether that
artifact is still the one the record pinned was never checked: 355 sources in the corpus carry
a sha256 and nothing compared it to the file on disk. A source edited after being pinned passes
every quotation check in the library.
"""

from __future__ import annotations

import pytest
from citations import readers as R
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
    V.clear_caches()
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


def only_poppler(monkeypatch):
    """Pin the machine to one reader, the way this suite assumed before there were three.

    Both describe an extractor that is selected and then fails when it is run -- a broken
    install, a permissions error -- so poppler is made selectable here rather than left to
    `shutil.which`. Otherwise the two tests answer differently on a machine with poppler and a
    machine without, and CI has neither poppler nor a reason to say so. What they pin is the
    same either way: an extractor that failed raises and never returns empty text, and its
    reason reaches the caller.
    """
    poppler = R.Reader("poppler", R._read_poppler, lambda: True, lambda: "test")
    monkeypatch.setattr(R, "READERS", {"poppler": poppler})
    monkeypatch.setattr(R, "PREFERRED", ("poppler",))


def test_a_missing_extractor_raises_rather_than_reporting_no_text(tmp_path, monkeypatch):
    # Returning "" here makes every PDF quote `unchecked` and the summary read "nothing
    # failed", so a missing binary is indistinguishable from an unreadable document.
    only_poppler(monkeypatch)
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4 not really a pdf")

    def no_such_binary(*a, **kw):
        raise FileNotFoundError("pdftotext")

    monkeypatch.setattr(R.subprocess, "run", no_such_binary)
    V.clear_caches()
    with pytest.raises(SourceUnreadableError) as e:
        V.extract(pdf)
    assert "PATH" in str(e.value)


def test_a_failed_extraction_surfaces_its_reason_in_the_result(tmp_path, monkeypatch):
    only_poppler(monkeypatch)
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    def no_such_binary(*a, **kw):
        raise FileNotFoundError("pdftotext")

    monkeypatch.setattr(R.subprocess, "run", no_such_binary)
    V.clear_caches()
    r = V.check_one("a passage long enough to clear the minimum quote length here", pdf)
    assert r.state == "unchecked"
    assert "pdftotext" in r.detail, "the reason has to reach the report, not just the log"


def test_every_reader_failing_names_each_one_in_the_reason(tmp_path, monkeypatch):
    # The case the two above cannot reach now that a chain exists: no reader answered, and the
    # report has to say what each of them did rather than naming only the first.
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4 not really a pdf")
    V.clear_caches()
    r = V.check_one("a passage long enough to clear the minimum quote length here", pdf)
    assert r.state == "unchecked"
    named = {"poppler": "pdftotext", "pdfplumber": "pdfplumber", "pypdf": "pypdf"}
    for name in R.available():
        assert named[name] in r.detail


def test_a_page_scan_that_hits_its_limit_says_so_rather_than_reporting_absence(tmp_path):
    # Returning None for both "not on any page" and "stopped looking" makes a cap read as a
    # finding.
    p = artifact(tmp_path)
    found, capped = V._find_page(p, "nothing like this appears", limit=3)
    assert found is None and capped is False, "a text file ends, so the scan ran out of document"


# --- what `--strict` adds to `ok` --------------------------------------------------------------


def test_strict_and_ok_disagree_exactly_where_nothing_was_established():
    # `ok` deliberately passes an unchecked quote: a missing extractor says nothing about the
    # paper. `--strict` exists because in CI that reads as a verified build.
    unresolved = V.Report(checked=1, counts={"unchecked": 1})
    assert unresolved.ok, "an unchecked quote is not a quotation failure"
    assert not unresolved.strict_ok

    unpinned = V.Report(checked=1, counts={"found": 1})
    unpinned.unpinned.append("some-source")
    assert unpinned.ok
    assert not unpinned.strict_ok

    unparsed = V.Report(checked=1, counts={"found": 1})
    unparsed.skipped.append(("broken.yaml", "mapping values are not allowed here"))
    assert unparsed.ok
    assert not unparsed.strict_ok


def test_strict_still_passes_a_run_where_every_quote_resolved():
    # A --strict that can never pass would be turned off, so the pass has to be reachable.
    assert V.Report(checked=3, counts={"found": 3}).strict_ok


def test_strict_never_passes_what_ok_already_failed():
    broken = V.Report(checked=1, counts={"found": 1})
    broken.broken_pins.append(("some-source", V.Pin("broken", "aaa", "bbb")))
    assert not broken.strict_ok
    assert not V.Report(checked=0).strict_ok
