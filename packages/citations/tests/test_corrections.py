"""A passage the extractor misreads is pinned with a correction, and reported `corrected`.

The correction is a person's record of what the page prints. It sits beside the extractor's
text, which is never modified, and it applies where its `reads` names one place in this run's
reading of the recorded bytes. The extractor, its version and the digest of its text are
recorded and decide nothing; where they differ, the report says so.
"""

from __future__ import annotations

import hashlib
import json
import pathlib

import pytest
import yaml
from citations import pin
from citations import verify as V
from citations.cli import main
from citations.exceptions import SourceUnreadableError

#: What the extractor produced: the `ffi` ligature dropped.
TEXT = "Table 2 reports that the coefficient of eciency was 0.81 across all twelve sites.\n"
QUOTE = "the coefficient of efficiency was 0.81 across all twelve sites"
PRINTED = "Table 2 reports that the coefficient of efficiency was 0.81 across all twelve sites."
READS = "the coefficient of eciency was 0.81"


@pytest.fixture(autouse=True)
def _alone(monkeypatch):
    monkeypatch.setenv("CITATIONS_NO_CACHE", "1")
    monkeypatch.setenv("REPRO_NO_HINT", "1")
    V.clear_caches()


def claims_file(root: pathlib.Path, text: str, name: str = "source.txt") -> pathlib.Path:
    (root / name).write_bytes(text.encode("latin-1") if name.endswith(".pdf") else text.encode())
    (root / "claims").mkdir(exist_ok=True)
    f = root / "claims" / "smith.yaml"
    digest = hashlib.sha256((root / name).read_bytes()).hexdigest()
    f.write_text(f"source:\n  citation: smith\n  local: {name}\n  sha256: {digest}\nclaims: {{}}\n")
    return f


@pytest.fixture
def paper(tmp_path) -> pathlib.Path:
    return claims_file(tmp_path, TEXT)


def pin_corrected(
    f: pathlib.Path, quote: str = QUOTE, passage: str = PRINTED, reads: str = READS, page: int = 4
) -> int:
    return pin.main(
        [
            *(str(f), "--id", "eff", "--quote", quote, "--page", str(page)),
            *("--correct", passage, "--reads", reads, "--cause", "ffi ligature dropped"),
        ]
    )


def verify(f: pathlib.Path, *flags: str) -> tuple[int, dict]:
    V.clear_caches()
    wrote = f.parent.parent / "counts.json"
    code = main(["verify", "--claims", str(f.parent), "--json", str(wrote), *flags])
    return code, json.loads(wrote.read_text())


def edit_correction(f: pathlib.Path, **changed) -> None:
    doc = yaml.safe_load(f.read_text())
    doc["claims"]["eff"]["quotes"][0]["correction"].update(changed)
    f.write_text(yaml.safe_dump(doc, sort_keys=False))


def write_by_hand(f: pathlib.Path, quote: str, **correction) -> None:
    """A correction as someone might type it, past every refusal of `pin --correct`."""
    doc = yaml.safe_load(f.read_text())
    artifact = f.parent.parent / doc["source"]["local"]
    text = V.extract(artifact)
    correction = {
        "passage": PRINTED,
        "page": 4,
        "extractor": "text",
        "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
        "derived_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "reads": READS,
    } | correction
    doc["claims"] = {"eff": {"quotes": [{"exact": quote, "page": 4, "correction": correction}]}}
    f.write_text(yaml.safe_dump(doc, sort_keys=False))


def test_a_corrected_quotation_reports_corrected_never_found_and_is_named(paper, capsys):
    assert pin_corrected(paper) == 0
    code, account = verify(paper, "--verbose")
    out = capsys.readouterr().out
    assert code == 0
    assert account["counts"]["corrected"] == 1
    assert account["counts"]["found"] == 0
    assert account["corrected"] == [{"claim": "smith:eff", "quote": QUOTE, "note": ""}]
    assert "all found." not in out
    assert "1 corrected" in out
    assert f"smith:eff{' ' * 31}{QUOTE[:60]}" in out


def test_a_corrected_quotation_passes_under_strict(paper):
    assert pin_corrected(paper) == 0
    code, account = verify(paper, "--strict")
    assert code == 0
    assert account["counts"]["corrected"] == 1


def test_the_same_text_under_another_reported_version_is_corrected_with_a_note(paper, capsys):
    assert pin_corrected(paper) == 0
    edit_correction(paper, extractor_version="7")
    code, account = verify(paper)
    out = capsys.readouterr().out
    assert code == 0
    assert account["counts"]["corrected"] == 1
    assert account["unapplied_corrections"] == 0
    assert account["corrected"][0]["note"] == "applied under text; recorded under text, 7"
    assert "1 correction applied under another reading than it was recorded under" in out


def test_another_reader_whose_text_holds_reads_once_is_corrected_and_both_are_named(paper):
    assert pin_corrected(paper) == 0
    edit_correction(
        paper,
        extractor="pdftotext -layout",
        extractor_version="pdftotext version 26.04.0",
        derived_sha256="0" * 64,
    )
    code, account = verify(paper)
    assert code == 0
    assert account["counts"]["corrected"] == 1
    digest = hashlib.sha256(TEXT.encode()).hexdigest()
    assert account["corrected"][0]["note"] == (
        "applied under text; recorded under pdftotext -layout, pdftotext version 26.04.0; "
        f"extracted text {digest[:12]}, recorded 000000000000"
    )


def test_a_reading_that_does_not_hold_reads_is_not_corrected_and_says_why(paper, capsys):
    assert pin_corrected(paper) == 0
    edit_correction(paper, reads="the coefficient of eciency was 0.31")
    code, account = verify(paper)
    out = capsys.readouterr().out
    assert code == 1
    assert account["counts"]["not found"] == 1
    assert account["counts"]["corrected"] == 0
    assert account["unapplied_corrections"] == 1
    assert "1 correction not applied" in out
    assert (
        "it does not describe this machine's reading: `reads` does not occur in what text "
        "produced" in out
    )


def test_reads_occurring_twice_is_refused_at_pin_and_not_applied_at_verify(tmp_path, capsys):
    f = claims_file(tmp_path, TEXT + "In the pilot the coefficient of eciency was 0.81 too.\n")
    before = f.read_text()
    assert pin_corrected(f) == 1
    assert f.read_text() == before
    assert "--reads occurs 2 times in what text produced" in capsys.readouterr().out

    write_by_hand(f, QUOTE)
    code, account = verify(f)
    assert code == 1
    assert account["counts"]["not found"] == 1
    assert account["unapplied_corrections"] == 1
    assert "`reads` occurs 2 times in what text produced" in capsys.readouterr().out


def test_reads_unrelated_to_the_passage_is_refused_at_pin_and_not_applied_at_verify(paper, capsys):
    # A real, unique stretch of the extractor's text, beside a passage the page does not print.
    fabricated = "In this paper the authors proved that the effect cannot be replicated."
    quote = "the authors proved that the effect cannot be replicated"
    real = "Table 2 reports that the"
    before = paper.read_text()
    assert pin_corrected(paper, quote=quote, passage=fabricated, reads=real) == 1
    assert paper.read_text() == before
    assert "holds nothing within 0.8 of `reads`" in capsys.readouterr().out

    write_by_hand(paper, quote, passage=fabricated, reads=real)
    code, account = verify(paper)
    out = capsys.readouterr().out
    assert code == 1
    assert account["counts"]["corrected"] == 0
    assert account["counts"]["not found"] == 1
    assert "holds nothing within 0.8 of `reads` where it holds the quotation" in out


def test_a_reads_too_short_to_name_a_place_is_refused_and_not_applied(paper, capsys):
    assert pin_corrected(paper, reads="of eciency") == 1
    assert "`reads` is 10 characters" in capsys.readouterr().out
    write_by_hand(paper, QUOTE, reads="of eciency")
    code, account = verify(paper)
    assert code == 1
    assert account["counts"]["corrected"] == 0


def test_a_correction_for_another_page_than_the_quotation_is_not_applied(paper, capsys):
    write_by_hand(paper, QUOTE, page=5)
    code, account = verify(paper)
    assert code == 1
    assert account["counts"]["corrected"] == 0
    assert "recorded for page 5 and the quotation for page 4" in capsys.readouterr().out


def test_a_correction_whose_passage_lacks_the_quotation_reports_not_found(paper, capsys):
    assert pin_corrected(paper) == 0
    edit_correction(paper, passage="Table 2 reports a coefficient of 0.18 at three sites.")
    code, account = verify(paper)
    assert code == 1
    assert account["counts"]["not found"] == 1
    assert account["counts"]["corrected"] == 0
    assert "the passage does not hold the quotation" in capsys.readouterr().out


def test_a_changed_source_is_not_corrected_even_where_its_text_holds_reads(paper, capsys):
    assert pin_corrected(paper) == 0
    changed = TEXT + "A line added in a later printing.\n"
    source = paper.parent.parent / "source.txt"
    source.write_text(changed)
    doc = yaml.safe_load(paper.read_text())
    doc["source"]["sha256"] = hashlib.sha256(changed.encode()).hexdigest()
    paper.write_text(yaml.safe_dump(doc, sort_keys=False))
    code, account = verify(paper)
    assert code == 1
    assert account["counts"]["corrected"] == 0
    assert account["unapplied_corrections"] == 1
    assert "the source changed: recorded" in capsys.readouterr().out


def test_the_extractors_text_and_digest_are_byte_identical_before_and_after(paper):
    source = paper.parent.parent / "source.txt"
    before_bytes = source.read_bytes()
    before_text = V.extract(source)
    before_block = yaml.safe_load(paper.read_text())["source"]

    assert pin_corrected(paper) == 0
    pinned = paper.read_bytes()
    verify(paper)

    assert source.read_bytes() == before_bytes
    assert V.extract(source) == before_text == TEXT
    assert yaml.safe_load(paper.read_text())["source"] == before_block
    assert paper.read_bytes() == pinned
    recorded = yaml.safe_load(paper.read_text())["claims"]["eff"]["quotes"][0]["correction"]
    assert recorded["derived_sha256"] == hashlib.sha256(before_text.encode()).hexdigest()
    assert recorded["sha256"] == hashlib.sha256(before_bytes).hexdigest()
    assert recorded["reads"] == READS


def test_a_source_whose_text_now_holds_the_quotation_says_the_correction_may_be_unneeded(
    paper, capsys
):
    assert pin_corrected(paper) == 0
    fixed = PRINTED + "\n"
    (paper.parent.parent / "source.txt").write_text(fixed)
    doc = yaml.safe_load(paper.read_text())
    doc["source"]["sha256"] = hashlib.sha256(fixed.encode()).hexdigest()
    paper.write_text(yaml.safe_dump(doc, sort_keys=False))
    code, account = verify(paper)
    assert code == 0
    assert account["counts"]["found"] == 1
    assert account["counts"]["corrected"] == 0
    assert account["unneeded_corrections"] == 1
    assert "may no longer be needed" in capsys.readouterr().out


def test_pin_refuses_a_correction_where_the_extractor_already_reads_the_quotation(paper, capsys):
    before = paper.read_text()
    assert pin_corrected(paper, quote="reports that the coefficient of eciency was 0.81") == 1
    assert paper.read_text() == before
    assert "no correction is needed" in capsys.readouterr().out


def two_page_pdf(first: str, second: str) -> str:
    """A PDF of two pages, each one line of Helvetica, with a correct cross-reference table."""
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R 4 0 R] /Count 2 >>",
        *(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {n} 0 R "
            "/Resources << /Font << /F1 7 0 R >> >> >>"
            for n in (5, 6)
        ),
        *(
            f"<< /Length {len(s := f'BT /F1 10 Tf 40 700 Td ({line}) Tj ET')} >>\n"
            f"stream\n{s}\nendstream"
            for line in (first, second)
        ),
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out, offsets = "%PDF-1.4\n", []
    for i, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{body}\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n"
    out += "".join(f"{o:010d} 00000 n \n" for o in offsets)
    return out + f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n"


def test_a_pdf_read_by_pypdf_applies_a_correction_recorded_under_poppler_on_its_page_only(
    tmp_path, monkeypatch, capsys
):
    pytest.importorskip("pypdf")

    def no_poppler(pdf, page, layout=True):
        raise SourceUnreadableError(pdf, "pdftotext is not installed")

    monkeypatch.setattr(V, "_poppler", no_poppler)
    monkeypatch.setattr(V.shutil, "which", lambda name: None)
    f = claims_file(tmp_path, two_page_pdf("Methods follow.", TEXT.strip()), "smith.pdf")
    assert pin_corrected(f, page=2) == 0
    edit_correction(
        f,
        extractor="pdftotext -layout",
        extractor_version="pdftotext version 26.04.0",
        derived_sha256="0" * 64,
    )
    code, account = verify(f)
    assert code == 0
    assert account["counts"]["corrected"] == 1
    assert account["corrected"][0]["note"].startswith(
        f"applied under pypdf, {V.extractor_version('pypdf')}; recorded under pdftotext -layout, "
        "pdftotext version 26.04.0; extracted text "
    )

    doc = yaml.safe_load(f.read_text())
    doc["claims"]["eff"]["quotes"][0]["page"] = 1
    doc["claims"]["eff"]["quotes"][0]["correction"]["page"] = 1
    f.write_text(yaml.safe_dump(doc, sort_keys=False))
    capsys.readouterr()
    code, account = verify(f)
    assert code == 1
    assert account["counts"]["corrected"] == 0
    assert "`reads` does not occur on page 1 of what pypdf produced" in capsys.readouterr().out
