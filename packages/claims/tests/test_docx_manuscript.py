"""A Word manuscript is checked as a text manuscript is.

Each test builds its `.docx` with `python-docx` in the test's own directory, so no binary is
committed and the fixture is exactly what the assertions describe.
"""

from __future__ import annotations

import json
from importlib.metadata import version

import docx
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
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

SENTENCE = "Thirty-five participants responded to the survey."


def manuscript(path, *, tracked=False):
    """A `.docx` of two paragraphs and a table of two rows, one cell of which is merged."""
    document = docx.Document()
    document.add_paragraph(SENTENCE)
    paragraph = document.add_paragraph("Responders were older by 4.2 years.")
    if tracked:
        inserted = OxmlElement("w:ins")
        inserted.set(qn("w:id"), "1")
        inserted.set(qn("w:author"), "a")
        run, text = OxmlElement("w:r"), OxmlElement("w:t")
        text.text = " on average"
        run.append(text)
        inserted.append(run)
        paragraph._p.append(inserted)
    table = document.add_table(rows=2, cols=3)
    for column, heading in enumerate(("Arm", "Cohort", "n")):
        table.cell(0, column).text = heading
    table.cell(1, 0).text = "Treated"
    table.cell(1, 1).merge(table.cell(1, 2)).text = "1,204"
    document.sections[0].header.paragraphs[0].text = "Running head 99"
    document.save(path)
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


def test_the_docx_is_read_as_its_paragraphs_then_its_table_rows_and_not_its_header(tmp_path):
    assert extract_uncached(manuscript(tmp_path / "paper.docx")).splitlines() == [
        SENTENCE,
        "Responders were older by 4.2 years.",
        "Arm | Cohort | n",
        "Treated | 1,204",
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
        "header": (Outcome.MISMATCH, Reason.PASSAGE_ABSENT),
    }


def test_a_decision_on_a_docx_names_python_docx_and_its_version_and_hashes_its_text(tmp_path):
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
    assert (quote.tool, quote.tool_version) == ("python-docx", version("python-docx"))
    assert quote.extraction_digest == Digest.of_text(text).value
    assert prose.outcome is Outcome.VERIFIED
    assert (prose.tool, prose.tool_version) == ("python-docx", version("python-docx"))
    # The JSON beside it is read by the adapters, not by the library that reads the docx.
    assert metric.tool != "python-docx"


def test_a_number_in_a_docx_table_is_found_and_bound_by_the_claim_that_quotes_its_row(
    tmp_path, capsys
):
    made = project(tmp_path, [quoted("treated", "Treated | 1,204", "1204", "/treated")])
    (inventory,) = numbers(made).texts
    assert [(n.text, n.standing) for n in inventory.numbers] == [
        ("thirty-five", Standing.UNBOUND),
        ("4.2", Standing.UNBOUND),
        ("1,204", Standing.BOUND),
    ]
    assert inventory.numbers[2].claims == ("treated",)

    assert main(["numbers", str(made.path)]) == 0
    assert (
        "3 numbers: 1 bound, 0 set aside by rule, 0 set aside with a reason, 2 unbound"
        in capsys.readouterr().out
    )


def test_a_docx_holding_a_tracked_change_is_unreadable_and_not_a_mismatch(tmp_path, capsys):
    made = project(
        tmp_path,
        [quoted("older", "older by 4.2 years on average", "35", "/responders")],
        tracked=True,
    )
    decision = verify(made).decisions[0]
    assert (decision.outcome, decision.reason) == (Outcome.UNCHECKED, Reason.ARTIFACT_UNREADABLE)
    assert "1 tracked change of text" in decision.detail
    assert (decision.tool, decision.tool_version) == ("python-docx", version("python-docx"))

    assert main(["numbers", str(made.path)]) != 0
    assert "1 tracked change of text" in capsys.readouterr().out
