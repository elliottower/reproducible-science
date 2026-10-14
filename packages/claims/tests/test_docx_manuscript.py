"""A Word manuscript is checked as a text manuscript is.

Each test writes its `.docx` part by part into a zip in the test's own directory, so no binary
is committed, no library beyond the standard one builds it, and the fixture is exactly the
markup the assertions describe. The text is `citations`' `docx-text` version 2, which needs no
library either, so these run where `claims-cli` is installed alone; its own tests cover each
kind of content it reads.
"""

from __future__ import annotations

import json
import zipfile
from importlib.metadata import version

from citations.verify import extract_uncached
from claims.cli import main
from claims.models import (
    ArtifactRef,
    Claim,
    Digest,
    Manifest,
    MetricEvidence,
    Outcome,
    ProseLocator,
    QuoteEvidence,
    Reason,
    Standing,
    ValueEvidence,
)
from claims.numbers import numbers
from claims.verify import verify

SENTENCE = "Thirty-five participants responded to the survey."

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
RELS = "http://schemas.openxmlformats.org/package/2006/relationships"


def run(text: str, tag: str = "w:t") -> str:
    return f'<w:r><{tag} xml:space="preserve">{text}</{tag}></w:r>'


def paragraph(*runs: str) -> str:
    return f"<w:p>{''.join(runs)}</w:p>"


def cell(text: str, span: int = 1) -> str:
    merged = f'<w:tcPr><w:gridSpan w:val="{span}"/></w:tcPr>' if span > 1 else ""
    return f"<w:tc>{merged}{paragraph(run(text))}</w:tc>"


def manuscript(path, *, tracked=False):
    """A `.docx` of two paragraphs, a table of two rows, one cell of which spans two columns,
    and a header. `tracked` inserts ` on average` and deletes ` in 2020` as tracked changes."""
    changes = (
        f'<w:ins w:id="1" w:author="a">{run(" on average")}</w:ins>'
        f'<w:del w:id="2" w:author="a">{run(" in 2020", "w:delText")}</w:del>'
        if tracked
        else ""
    )
    grid = "<w:tblGrid>" + '<w:gridCol w:w="2000"/>' * 3 + "</w:tblGrid>"
    body = (
        paragraph(run(SENTENCE))
        + paragraph(run("Responders were older by 4.2 years"), changes, run("."))
        + f"<w:tbl>{grid}<w:tr>{cell('Arm')}{cell('Cohort')}{cell('n')}</w:tr>"
        + f"<w:tr>{cell('Treated')}{cell('1,204', span=2)}</w:tr></w:tbl>"
        + '<w:sectPr><w:headerReference w:type="default" r:id="rIdH"/></w:sectPr>'
    )
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(
            "_rels/.rels",
            f'<Relationships xmlns="{RELS}"><Relationship Id="rId1" '
            f'Type="{R}/officeDocument" Target="word/document.xml"/></Relationships>',
        )
        z.writestr(
            "word/document.xml",
            f'<w:document xmlns:w="{W}" xmlns:r="{R}"><w:body>{body}</w:body></w:document>',
        )
        z.writestr(
            "word/_rels/document.xml.rels",
            f'<Relationships xmlns="{RELS}"><Relationship Id="rIdH" Type="{R}/header" '
            'Target="header1.xml"/></Relationships>',
        )
        z.writestr(
            "word/header1.xml", f'<w:hdr xmlns:w="{W}">{paragraph(run("Running head 99"))}</w:hdr>'
        )
    return path


def project(root, claims, *, tracked=False):
    paper = manuscript(root / "paper.docx", tracked=tracked)
    results = root / "results.json"
    results.write_text(json.dumps({"responders": 35, "treated": 1204}))
    made = Manifest(
        project="p",
        path=root / "repro.yaml",
        artifacts=tuple(
            ArtifactRef(id=p.stem, path=p, digest=Digest.of_file(p)) for p in (paper, results)
        ),
        claims=tuple(claims),
    )
    made.path.write_text(made.model_dump_json())
    return made


def quoted(name, passage, reported="", pointer=""):
    evidence = [QuoteEvidence(artifact="paper", text=passage)]
    if reported:
        evidence.append(
            MetricEvidence(artifact="results", name=name, reported=reported, pointer=pointer)
        )
    return Claim(id=name, text=passage, evidence=tuple(evidence))


def test_the_docx_is_read_in_document_order_and_its_header_after_the_body(tmp_path):
    assert extract_uncached(manuscript(tmp_path / "paper.docx")).splitlines() == [
        SENTENCE,
        "Responders were older by 4.2 years.",
        "Arm | Cohort | n",
        "Treated | 1,204",
        "Running head 99",
    ]


def test_a_passage_in_the_docx_verifies_and_one_it_does_not_hold_is_a_mismatch(tmp_path):
    made = project(
        tmp_path,
        [
            quoted("present", "participants responded to the survey"),
            quoted("row", "Treated | 1,204"),
            quoted("absent", "participants declined the survey"),
            quoted("header", "Running head 99"),
        ],
    )
    outcomes = {d.claim_id: (d.outcome, d.reason) for d in verify(made).decisions}
    assert outcomes == {
        "present": (Outcome.VERIFIED, Reason.PASSAGE_PRESENT),
        "row": (Outcome.VERIFIED, Reason.PASSAGE_PRESENT),
        "absent": (Outcome.MISMATCH, Reason.PASSAGE_ABSENT),
        "header": (Outcome.VERIFIED, Reason.PASSAGE_PRESENT),
    }


def test_a_decision_on_a_docx_names_the_reader_and_its_version_and_hashes_its_text(tmp_path):
    made = project(
        tmp_path,
        [
            quoted("present", "participants responded to the survey"),
            Claim(
                id="older",
                text="t",
                evidence=(
                    ValueEvidence(
                        artifact="paper",
                        name="older",
                        reported="4.2",
                        locator=ProseLocator(before="older by", after="years"),
                    ),
                ),
            ),
            quoted("responders", SENTENCE, "35", "/responders"),
        ],
    )
    quote, prose, _, metric = verify(made).decisions
    text = extract_uncached(tmp_path / "paper.docx")
    # `docx-text` is `citations`' own code, so its version is the one that says which reading.
    assert (quote.tool, quote.tool_version) == ("citations", version("citations"))
    assert quote.extraction_digest == Digest.of_text(text).value
    assert prose.outcome is Outcome.VERIFIED
    assert (prose.tool, prose.tool_version) == ("citations", version("citations"))
    # The JSON beside it is read by the adapters, not by what reads the docx.
    assert metric.tool != "citations"


def test_a_number_in_a_docx_table_is_found_and_bound_by_the_claim_that_quotes_its_row(
    tmp_path, capsys
):
    made = project(tmp_path, [quoted("treated", "Treated | 1,204", "1204", "/treated")])
    (inventory,) = numbers(made).texts
    assert [(n.text, n.standing) for n in inventory.numbers] == [
        ("thirty-five", Standing.UNBOUND),
        ("4.2", Standing.UNBOUND),
        ("1,204", Standing.BOUND),
        ("99", Standing.UNBOUND),
    ]
    assert inventory.numbers[2].claims == ("treated",)

    assert main(["numbers", str(made.path)]) == 0
    assert (
        "4 numbers: 1 bound, 0 set aside by rule, 0 set aside with a reason, 3 unbound"
        in capsys.readouterr().out
    )


def test_a_tracked_insertion_is_read_and_a_tracked_deletion_is_not(tmp_path):
    made = project(
        tmp_path,
        [
            quoted("inserted", "older by 4.2 years on average", "35", "/responders"),
            quoted("deleted", "older by 4.2 years in 2020"),
        ],
        tracked=True,
    )
    inserted, _, deleted = verify(made).decisions
    assert (inserted.outcome, deleted.outcome) == (Outcome.VERIFIED, Outcome.MISMATCH)
    (inventory,) = numbers(made).texts
    assert "2020" not in [n.text for n in inventory.numbers]
