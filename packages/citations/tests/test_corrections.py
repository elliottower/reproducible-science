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
import random
import string
import time

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
READS = "the coefficient of eciency was 0.81 across all twelve sites"


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
    f: pathlib.Path,
    quote: str = QUOTE,
    passage: str = PRINTED,
    reads: str = READS,
    page: int = 4,
    check: bool = False,
) -> int:
    return pin.main(
        [
            *(str(f), "--id", "eff", "--quote", quote, "--page", str(page)),
            *("--correct", passage, "--reads", reads, "--cause", "ffi ligature dropped"),
            *(["--check"] if check else []),
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
    assert account["corrected"] == [
        {
            "claim": "smith:eff",
            "quote": QUOTE,
            "note": "",
            "reads": READS,
            "passage": PRINTED,
            "diff": '"eciency" → "efficiency"',
            "flags": [],
        }
    ]
    assert "all found." not in out
    assert "1 corrected" in out
    assert f'smith:eff{" " * 31}{QUOTE[:60]}\n{" " * 53}"eciency" → "efficiency"\n' in out


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
    edit_correction(paper, reads="the coefficient of eciency was 0.31 across all twelve sites")
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
    f = claims_file(
        tmp_path,
        TEXT + "In the pilot the coefficient of eciency was 0.81 across all twelve sites too.\n",
    )
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


def test_a_faithful_correction_with_invented_text_after_it_is_refused_and_not_applied(
    paper, capsys
):
    passage = PRINTED[:-1] + ", and the effect was shown to be causal."
    quote = QUOTE + ", and the effect was shown to be causal"
    before = paper.read_text()
    assert pin_corrected(paper, quote=quote, passage=passage) == 1
    assert paper.read_text() == before
    reach = "the quotation reaches more than 3 characters past the stretch of the passage"
    assert reach in capsys.readouterr().out

    write_by_hand(paper, quote, passage=passage)
    code, account = verify(paper)
    out = capsys.readouterr().out
    assert code == 1
    assert account["counts"]["corrected"] == 0
    assert account["counts"]["not found"] == 1
    assert account["unapplied_corrections"] == 1
    assert reach in out


def test_a_quotation_spanning_the_whole_corrected_stretch_inside_a_longer_passage_applies(
    tmp_path,
):
    f = claims_file(tmp_path, "Results. " + TEXT + "Discussion follows.\n")
    passage = "Results. " + PRINTED + " Discussion follows."
    assert pin_corrected(f, passage=passage) == 0
    code, account = verify(f)
    assert code == 0
    assert account["counts"]["corrected"] == 1


def test_a_misread_first_and_last_letter_at_the_quotations_ends_still_applies(tmp_path):
    f = claims_file(tmp_path, "Here rnodern estimates put the coefficient at 0.8l in total.\n")
    quote = "modern estimates put the coefficient at 0.81"
    passage = "Here modern estimates put the coefficient at 0.81 in total."
    reads = "rnodern estimates put the coefficient at 0.8l"
    assert pin_corrected(f, quote=quote, passage=passage, reads=reads) == 0
    code, account = verify(f)
    assert code == 0
    assert account["counts"]["corrected"] == 1


def test_the_quotation_may_reach_three_characters_past_the_corrected_stretch_and_no_more():
    passage = PRINTED[:-1] + " xqzk."
    assert V.correction_fault(QUOTE + " xqz", passage, READS) == ""
    assert "reaches more than 3 characters" in V.correction_fault(QUOTE + " xqzk", passage, READS)


def test_a_reads_too_short_to_name_a_place_is_refused_and_not_applied(paper, capsys):
    assert pin_corrected(paper, reads="of eciency") == 1
    assert "`reads` is 9 characters with white space removed" in capsys.readouterr().out
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


def test_a_reads_counted_long_only_through_its_spaces_is_refused_and_not_applied(tmp_path, capsys):
    f = claims_file(tmp_path, "The DOI prefix 1 0 . 1 1 4 5 names the publisher.\n")
    before = f.read_text()
    assert pin_corrected(f, quote="10.1146", passage="10.1146", reads="1 0 . 1 1 4 5") == 1
    assert f.read_text() == before
    assert "`reads` is 7 characters with white space removed" in capsys.readouterr().out

    write_by_hand(f, "10.1146", passage="10.1146", reads="1 0 . 1 1 4 5")
    code, account = verify(f)
    assert code == 1
    assert account["counts"]["corrected"] == 0
    assert account["unapplied_corrections"] == 1


def prose(n: int) -> str:
    words = "the of and a to in is was for that with as on by be are this from at or an".split()
    out: list[str] = []
    length = 0
    while length < n:
        out.append(random.choice([*words, "".join(random.choices(string.ascii_lowercase, k=6))]))
        length += len(out[-1]) + 1
    return " ".join(out)[:n]


def test_a_reads_or_passage_longer_than_a_correction_covers_is_refused_and_not_applied(
    tmp_path, capsys
):
    long_reads = "the coefficient of eciency " * 8 + "was 0.81 across all twelve sites"
    f = claims_file(tmp_path, long_reads + "\n")
    long_passage = long_reads.replace("eciency", "efficiency")
    before = f.read_text()
    assert pin_corrected(f, passage=long_passage, reads=long_reads) == 1
    assert f.read_text() == before
    out = capsys.readouterr().out
    assert "a correction covers a misread passage of up to 200 characters" in out
    assert "correct a shorter span" in out

    passage = prose(2 * V.MAX_PASSAGE_CHARS) + " " + PRINTED
    assert "records a passage of up to 400 characters" in V.correction_fault(QUOTE, passage, READS)


def test_an_oversized_record_written_by_hand_is_not_applied_before_anything_is_searched(
    paper, capsys, monkeypatch
):
    def searched(*a, **kw):
        raise AssertionError("searched an oversized correction")

    monkeypatch.setattr(V, "reads_count", searched)
    monkeypatch.setattr(V, "_corrected_stretch", searched)
    reads = "".join(random.choices(string.ascii_lowercase + " ", k=100_000))
    write_by_hand(paper, QUOTE, reads=reads, passage=reads + " " + PRINTED)
    started = time.perf_counter()
    code, account = verify(paper)
    assert time.perf_counter() - started < 2
    assert code == 1
    assert account["unapplied_corrections"] == 1
    assert "correct a shorter span" in capsys.readouterr().out


@pytest.mark.parametrize("shape", ["shuffled", "quotation repeated"])
def test_correction_fault_on_the_slowest_shapes_within_the_bounds_takes_well_under_a_second(
    shape,
):
    # At the bounds with white space removed, as they are counted.
    reads = prose(3 * V.MAX_READS_CHARS).replace(" ", "")[: V.MAX_READS_CHARS]
    if shape == "shuffled":
        letters = reads + prose(3 * V.MAX_READS_CHARS).replace(" ", "")[: V.MAX_READS_CHARS]
        passage = "".join(random.sample(letters, len(letters)))
        quote = passage[5:17]
    else:
        passage = "".join("zq" + prose(20).replace(" ", "")[:10] for _ in range(33))
        quote = "zq"
    assert len(V.skeleton(passage)) <= V.MAX_PASSAGE_CHARS
    started = time.perf_counter()
    fault = V.correction_fault(quote, passage, reads)
    assert time.perf_counter() - started < 0.5
    assert "holds nothing within 0.8 of `reads`" in fault


INCREASES = "Studies find that reproducibility increases impact, visibility, and trust.\n"


def test_a_correction_that_adds_a_negation_is_shown_and_flagged_by_default(tmp_path, capsys):
    f = claims_file(tmp_path, INCREASES)
    quote = "reproducibility does not increase impact"
    passage = "reproducibility does not increase impact, visibility, and"
    reads = "reproducibility increases impact, visibility, and"
    assert pin_corrected(f, quote=quote, passage=passage, reads=reads) == 0
    capsys.readouterr()
    code, account = verify(f)
    out = capsys.readouterr().out
    assert code == 0
    shown = '"increases" → "does not increase"'
    assert account["corrected"][0]["diff"] == shown
    assert account["corrected"][0]["reads"] == reads
    assert account["corrected"][0]["passage"] == passage
    assert f"smith:eff{' ' * 31}{shown}   (correction adds a negation)\n" in out
    assert account["corrected"][0]["flags"] == ["correction adds a negation"]
    assert [w["claim"] for w in account["warnings"]["correction adds a negation"]] == ["smith:eff"]


def test_pin_correct_prints_what_the_correction_changes_under_check_and_when_it_writes(
    tmp_path, capsys
):
    f = claims_file(tmp_path, INCREASES)
    quote = "reproducibility does not increase impact"
    passage = "reproducibility does not increase impact, visibility, and"
    reads = "reproducibility increases impact, visibility, and"
    shown = '  changes   "increases" → "does not increase"   (correction adds a negation)\n'
    before = f.read_text()
    assert pin_corrected(f, quote=quote, passage=passage, reads=reads, check=True) == 0
    assert shown in capsys.readouterr().out
    assert f.read_text() == before
    assert pin_corrected(f, quote=quote, passage=passage, reads=reads) == 0
    out = capsys.readouterr().out
    assert "added     eff to smith.yaml" in out
    assert shown in out


@pytest.mark.parametrize(
    ("reads", "printed", "flags"),
    [
        ("the mean change was 0.42 at all", "the mean change was -0.42 at all", ["number"]),
        ("the mean change was 0.42 at all", "the mean change was \u22120.42 at all", ["number"]),
        ("the mean change was \u22120.42 at all", "the mean change was 0.42 at all", ["number"]),
        ("the mean change was \u22120.42 at all", "the mean change was -0.42 at all", []),
        ("significant with p < 0.05 at all", "significant with p > 0.05 at all", ["comparison"]),
        ("significant with p <= 0.05 at all", "significant with p < 0.05 at all", ["comparison"]),
        ("significant with p = 0.05 at all", "significant with p ≥ 0.05 at all", ["comparison"]),
        ("significant with p <= 0.05 at all", "significant with p ≤ 0.05 at all", []),
        ("measured at all twelve sites", "measured at all twenty sites", ["number"]),
        ("measured at all of the sites", "measured at half of the sites", ["number"]),
        (
            "the rate was as high when treated",
            "the rate was twice as high when treated",
            ["number"],
        ),
        ("the eciency was seventy per cent", "the efficiency was seventy per cent", []),
        ("reproducibility increases impact", "reproducibility decreases impact", []),
        ("it is the case that X does not hold", "it is not the case that X holds", []),
    ],
)
def test_a_correction_is_flagged_for_a_sign_a_comparison_or_a_number_word_and_not_for_meaning(
    reads, printed, flags
):
    _, raised = V.correction_difference(printed, printed, reads)
    assert raised == [f"correction changes a {flag}" for flag in flags]


def test_a_correction_that_changes_a_digit_is_flagged_and_one_that_fixes_a_ligature_is_not(
    tmp_path,
):
    f = claims_file(tmp_path, TEXT)
    quote = QUOTE.replace("0.81", "0.91")
    assert pin_corrected(f, quote=quote, passage=PRINTED.replace("0.81", "0.91")) == 0
    code, account = verify(f)
    assert code == 0
    assert account["corrected"][0]["diff"] == '"eciency" → "efficiency"; "0.81" → "0.91"'
    assert "correction changes a number" in account["warnings"]
    assert V.correction_difference(QUOTE, PRINTED, READS) == ('"eciency" → "efficiency"', [])


def test_a_correction_counted_in_a_declared_readers_whole_text_keeps_page_unchecked(tmp_path):
    f = claims_file(tmp_path, TEXT)
    f.write_text(f.read_text().replace("claims: {}", "  extract_cmd: cat {}\nclaims: {}"))
    assert pin_corrected(f) == 0
    code, account = verify(f)
    assert code == 0
    assert account["counts"]["corrected"] == 1
    assert [w["claim"] for w in account["warnings"]["page unchecked"]] == ["smith:eff"]


def test_a_quotation_carrying_correction_twice_is_refused_naming_the_key(paper, capsys):
    assert pin_corrected(paper) == 0
    lines = paper.read_text().splitlines(keepends=True)
    at = next(i for i, line in enumerate(lines) if line.strip() == "correction:")
    block = [lines[at]]
    for line in lines[at + 1 :]:
        if len(line) - len(line.lstrip()) <= len(lines[at]) - len(lines[at].lstrip()):
            break
        block.append(line)
    paper.write_text("".join(lines[: at + len(block)] + block + lines[at + len(block) :]))
    verify(paper)
    assert "carries `correction` twice" in capsys.readouterr().out


def test_a_correction_carrying_a_key_twice_is_refused_naming_the_key(paper, capsys):
    assert pin_corrected(paper) == 0
    lines = paper.read_text().splitlines(keepends=True)
    at = next(i for i, line in enumerate(lines) if line.strip() == "correction:")
    indent = lines[at + 1][: len(lines[at + 1]) - len(lines[at + 1].lstrip())]
    # Read last-wins, the correction applies through the second `passage` and the first, the
    # one a reader of the file sees, is never compared with anything.
    lines.insert(at + 1, f"{indent}passage: Table 2 reports that the coefficient was 0.18.\n")
    paper.write_text("".join(lines))
    _, account = verify(paper)
    assert account["counts"]["corrected"] == 0
    assert account["skipped_files"] == 1
    assert "a correction carries `passage` twice" in capsys.readouterr().out


def test_a_misspelt_corrections_key_is_reported_and_not_ignored(paper, capsys):
    assert pin_corrected(paper) == 0
    paper.write_text(paper.read_text().replace("correction:", "corrections:"))
    code, account = verify(paper)
    assert code == 1
    assert account["unapplied_corrections"] == 1
    assert "`corrections` is not a field this package reads" in capsys.readouterr().out


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
