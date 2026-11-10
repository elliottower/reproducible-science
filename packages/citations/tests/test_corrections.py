"""A passage the extractor misreads is pinned with a correction, and reported `corrected`.

The correction is a person's record of what the page prints. It sits beside the extractor's
text, which is never modified, and it applies only to the reading it was recorded against.
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


@pytest.fixture
def paper(tmp_path) -> pathlib.Path:
    (tmp_path / "source.txt").write_text(TEXT)
    (tmp_path / "claims").mkdir()
    f = tmp_path / "claims" / "smith.yaml"
    digest = hashlib.sha256(TEXT.encode()).hexdigest()
    f.write_text(
        f"source:\n  citation: smith\n  local: source.txt\n  sha256: {digest}\nclaims: {{}}\n"
    )
    return f


def pin_corrected(f: pathlib.Path, quote: str = QUOTE) -> int:
    return pin.main(
        [
            *(str(f), "--id", "eff", "--quote", quote, "--page", "4"),
            *("--correct", PRINTED, "--reads", READS, "--cause", "ffi ligature dropped"),
        ]
    )


def verify(f: pathlib.Path) -> tuple[int, dict]:
    V.clear_caches()
    wrote = f.parent.parent / "counts.json"
    code = main(["verify", "--claims", str(f.parent), "--json", str(wrote)])
    return code, json.loads(wrote.read_text())


def edit_correction(f: pathlib.Path, **changed) -> None:
    doc = yaml.safe_load(f.read_text())
    doc["claims"]["eff"]["quotes"][0]["correction"].update(changed)
    f.write_text(yaml.safe_dump(doc, sort_keys=False))


def test_a_corrected_quotation_reports_corrected_and_never_found(paper, capsys):
    assert pin_corrected(paper) == 0
    code, account = verify(paper)
    out = capsys.readouterr().out
    assert code == 0
    assert account["counts"]["corrected"] == 1
    assert account["counts"]["found"] == 0
    assert "all found." not in out
    assert "1 corrected" in out


def test_a_changed_derived_sha256_makes_the_correction_stale_and_it_is_not_applied(paper, capsys):
    assert pin_corrected(paper) == 0
    edit_correction(paper, derived_sha256="0" * 64)
    code, account = verify(paper)
    out = capsys.readouterr().out
    assert code == 1
    assert account["counts"]["corrected"] == 0
    assert account["counts"]["not found"] == 1
    assert account["stale_corrections"] == 1
    assert "recorded against another reading, not applied" in out
    assert "the extracted text (recorded 000000000000" in out


def test_a_correction_whose_passage_lacks_the_quotation_reports_not_found(paper, capsys):
    assert pin_corrected(paper) == 0
    edit_correction(paper, passage="Table 2 reports a coefficient of 0.18 at three sites.")
    code, account = verify(paper)
    out = capsys.readouterr().out
    assert code == 1
    assert account["counts"]["not found"] == 1
    assert account["counts"]["corrected"] == 0
    assert account["stale_corrections"] == 0
    assert "the correction does not support this quotation" in out


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


def test_a_correction_recorded_under_another_extractor_version_is_stale(paper, capsys):
    assert pin_corrected(paper) == 0
    edit_correction(paper, extractor_version="7")
    code, account = verify(paper)
    assert code == 1
    assert account["counts"]["corrected"] == 0
    assert account["stale_corrections"] == 1
    assert "the extractor's version (recorded 7, now none)" in capsys.readouterr().out


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
