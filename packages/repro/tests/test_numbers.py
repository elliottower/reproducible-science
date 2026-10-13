"""Every number a text prints, and whether a declared assertion accounts for it.

Each test writes a small text and a manifest over it with the models a manifest is read into,
and asks where each number in the text stands.
"""

from __future__ import annotations

import hashlib
import json

import pytest
from citations.verify import passage_fold
from repro.cli import main
from repro.exceptions import ArtifactMissingError, ManifestError
from repro.manifest import load
from repro.models import (
    ArtifactRef,
    Claim,
    CorrespondenceEvidence,
    CorrespondenceSide,
    Digest,
    Manifest,
    MetricEvidence,
    NumberForm,
    NumberRule,
    NumbersReport,
    ProseLocator,
    QuoteEvidence,
    SetAside,
    Standing,
    TreeLocator,
    ValueEvidence,
)
from repro.numbers import NoTextError, UnknownArtifactError, numbers, texts
from repro.verify import verify

BOUND, UNBOUND = Standing.BOUND, Standing.UNBOUND
BY_RULE, WITH_REASON = Standing.SET_ASIDE_BY_RULE, Standing.SET_ASIDE_WITH_A_REASON


def claim(name, passage, reported, artifact="paper"):
    """A sentence of the text, and the value it prints as a file holds it."""
    return Claim(
        id=name,
        text=passage,
        evidence=(
            QuoteEvidence(artifact=artifact, text=passage),
            MetricEvidence(artifact="results", name=name, reported=reported, pointer=f"/{name}"),
        ),
    )


def project(root, text, claims=(), set_aside=(), **more):
    """A manifest over `paper.txt` holding `text`, `results.json`, and any other text named."""
    (root / "paper.txt").write_text(text)
    (root / "results.json").write_text(json.dumps({"n": 1}))
    for name, body in more.items():
        (root / f"{name}.txt").write_text(body)
    made = Manifest(
        project="p",
        path=root / "repro.yaml",
        artifacts=tuple(
            ArtifactRef(id=p.stem, path=p, digest=Digest.of_file(p))
            for p in sorted(p for p in root.iterdir() if p.suffix in (".json", ".txt"))
        ),
        claims=tuple(claims),
        set_aside=tuple(set_aside),
    )
    made.path.write_text(made.model_dump_json())
    return made


def found(report, artifact="paper"):
    """Each number of one text as it is printed, with where it stands."""
    (text,) = (t for t in report.texts if t.artifact == artifact)
    return [(n.text, n.standing) for n in text.numbers]


def read(root, text):
    """The numbers of a text no claim binds: as printed, the value read, and the rule."""
    report = numbers(project(root, text), only=("paper",))
    return [(n.text, n.value, n.rule) for n in report.numbers]


def snapshot(root):
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def test_a_number_is_bound_only_in_the_passage_of_the_claim_that_reports_it(tmp_path):
    text = "Of 240 values, 146 are located. A later table repeats 146 and adds 7.\n"
    made = project(tmp_path, text, [claim("located", "Of 240 values, 146 are located", "146")])
    report = numbers(made)

    assert found(report) == [("240", UNBOUND), ("146", BOUND), ("146", UNBOUND), ("7", UNBOUND)]
    first, bound, again, other = report.numbers
    assert bound.claims == ("located",)
    # The same digits outside the passage are unbound, and named as the weaker thing they are.
    assert (again.claims, again.reported_elsewhere) == ((), True)
    assert (first.reported_elsewhere, other.reported_elsewhere) == (False, False)
    assert report.counts == {BOUND: 1, UNBOUND: 3}


def test_a_passage_printed_twice_binds_its_number_in_both_places(tmp_path):
    text = "We read 2,364 passages. The appendix says again: we read 2,364 passages.\n"
    made = project(tmp_path, text, [claim("read", "we read 2,364 passages", "2364")])
    assert found(numbers(made)) == [("2,364", BOUND), ("2,364", BOUND)]


@pytest.mark.parametrize(
    ("printed", "reported", "standing"),
    [
        ("2,364", "2364", BOUND),
        ("0.50", "0.50", BOUND),
        ("24.11%", "24.11", BOUND),
        ("-0.42", "-0.42", BOUND),
        ("eighteen", "18", BOUND),
        # At the precision printed: a value reported to another precision is another string.
        ("0.5", "0.50", UNBOUND),
        ("0.42", "-0.42", UNBOUND),
        ("24.11%", "0.2411", UNBOUND),
        ("2,364", "2365", UNBOUND),
    ],
)
def test_a_number_is_bound_by_the_reported_value_it_prints_digit_for_digit(
    tmp_path, printed, reported, standing
):
    passage = f"the estimate was {printed} overall"
    made = project(tmp_path, f"In all, {passage}.\n", [claim("c", passage, reported)])
    assert found(numbers(made)) == [(printed, standing)]


def test_a_quotation_alone_in_its_claim_binds_nothing_and_its_source_is_not_a_text(tmp_path):
    quoted = Claim(
        id="quoted",
        text="The source reports 40 cases.",
        evidence=(QuoteEvidence(artifact="source", text="we observed 40 cases"),),
    )
    stated = claim("stated", "we then counted 12 sites", "12")
    made = project(
        tmp_path, "And we then counted 12 sites.\n", [quoted, stated], source="we observed 40 cases"
    )
    assert texts(made) == ("paper",)
    assert [text.artifact for text in numbers(made).texts] == ["paper"]

    # Read by name, the source is counted, and the quotation alone binds nothing in it.
    assert found(numbers(made, only=("source",)), "source") == [("40", UNBOUND)]


def test_the_value_a_prose_address_selects_is_bound_and_nothing_beside_it(tmp_path):
    text = "The suite holds eighteen fixtures and 3 runners. Recall was 0.61 over 45 capsules.\n"
    counted = Claim(
        id="fixtures",
        text="The suite holds eighteen fixtures.",
        evidence=(
            CorrespondenceEvidence(
                name="fixtures",
                sides=(
                    CorrespondenceSide(
                        name="stated",
                        artifact="paper",
                        locator=ProseLocator(
                            before="suite holds", after="fixtures", form=NumberForm.CARDINAL_WORD
                        ),
                    ),
                    CorrespondenceSide(
                        name="counted", artifact="results", locator=TreeLocator(pointer="/n")
                    ),
                ),
            ),
        ),
    )
    recall = Claim(
        id="recall",
        text="Recall was 0.61.",
        evidence=(
            ValueEvidence(
                artifact="paper",
                name="recall",
                reported="0.61",
                locator=ProseLocator(before="recall was", after="over"),
            ),
        ),
    )
    made = project(tmp_path, text, [counted, recall])
    assert texts(made) == ("paper",)
    report = numbers(made)
    assert found(report) == [
        ("eighteen", BOUND),
        ("3", UNBOUND),
        ("0.61", BOUND),
        ("45", UNBOUND),
    ]
    assert [n.claims for n in report.numbers] == [("fixtures",), (), ("recall",), ()]


def test_a_passage_set_aside_is_counted_with_its_reason_and_never_over_a_binding(tmp_path):
    text = "Timing: 0.53 seconds on 6 cores. We found 12 defects. Nothing here.\n"
    aside = (
        SetAside(artifact="paper", text="0.53 seconds on 6 cores", reason="hardware, not a result"),
        SetAside(artifact="paper", text="We found 12 defects", reason="bound below"),
        SetAside(artifact="paper", text="no such passage", reason="left over from a draft"),
        SetAside(artifact="other", text="0.53", reason="names a text that is not read"),
    )
    made = project(tmp_path, text, [claim("defects", "we found 12 defects", "12")], aside)
    report = numbers(made)

    assert found(report) == [("0.53", WITH_REASON), ("6", WITH_REASON), ("12", BOUND)]
    assert [n.reason for n in report.numbers] == [
        "hardware, not a result",
        "hardware, not a result",
        "",
    ]
    assert [(entry.reason, entry.numbers) for entry in report.set_aside] == [
        ("hardware, not a result", 2),
        ("bound below", 0),
        ("left over from a draft", 0),
        ("names a text that is not read", 0),
    ]


def test_a_set_aside_entry_needs_a_reason(tmp_path):
    made = project(tmp_path, "Timing: 0.53 seconds.\n")
    document = json.loads(made.path.read_text())
    document["set_aside"] = [{"artifact": "paper", "text": "0.53 seconds", "reason": ""}]
    made.path.write_text(json.dumps(document))
    with pytest.raises(ManifestError, match=r"set_aside\.0\.reason"):
        load(made.path)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # Counted as numbers, with the value read.
        ("we ran 12 trials", [("12", "12", None)]),
        ("a mean of 3.20 units", [("3.20", "3.20", None)]),
        ("across 863,878 runs", [("863,878", "863878", None)]),
        ("in 24.11% of runs", [("24.11%", "24.11", None)]),
        ("from 10-12 weeks", [("10", "10", None), ("12", "12", None)]),
        ("a change of -0.42 (p<0.05)", [("-0.42", "-0.42", None), ("0.05", "0.05", None)]),
        ("stored as 9.73e-7 exactly", [("9.73e-7", "9.73e-7", None)]),
        ("thirty-five responded, zero left", [("thirty-five", "35", None), ("zero", "0", None)]),
        ("weighed 5kg each", [("5", "5", None)]),
        ("the interval (0.31,0.52) held", [("0.31", "0.31", None), ("0.52", "0.52", None)]),
        ("rows 3 and 4", [("3", "3", None), ("4", "4", None)]),
        ("[0, 1] is an interval", [("0", "0", None), ("1", "1", None)]),
        ("a count of 1750 cells", [("1750", "1750", None)]),
        ("a two-sided test, one-third done", []),
        # Set aside, each by the rule that says what the digits are.
        (
            "published in 2019 and (Smith, 2020a)",
            [("2019", "2019", "year"), ("2020", "2020", "year")],
        ),
        (
            "frozen on 2026-10-13 at noon",
            [("2026", "2026", "date"), ("10", "10", "date"), ("13", "13", "date")],
        ),
        ("version v15 of sha256", [("15", None, "name"), ("256", None, "name")]),
        ("gpt-4 and covid-19", [("4", None, "name"), ("19", None, "name")]),
        ("digest 6efb0ee8 pinned", [("6", None, "name"), ("0", None, "name"), ("8", None, "name")]),
        ("python 3.13.12 here", [("3.13.12", None, "version_or_section")]),
        ("as shown [12] and [3, 7-9]", [(n, n, "citation") for n in ("12", "3", "7", "9")]),
        ("see table 6 and fig. 2", [("6", "6", "label"), ("2", "2", "label")]),
        (
            "in section 3.2, pp. 14-15",
            [("3.2", "3.2", "label"), ("14", "14", "label"), ("15", "15", "label")],
        ),
        ("eq. (3) holds", [("3", "3", "label")]),
        ("(1) plans, (2) runs", [("1", "1", "list_marker"), ("2", "2", "list_marker")]),
        ("the 95th percentile", [("95", "95", "ordinal")]),
        ("one of the files", [("one", "1", "the_word_one")]),
        ("at https://example.org/v2/2024 now", [("2", None, "link"), ("2024", None, "link")]),
        (
            "doi:10.1000/182 cited",
            [("10.1000", None, "document_identifier"), ("182", None, "document_identifier")],
        ),
        # Lines of a real manuscript's text, each with what leaked before its rule read it.
        (
            "(macbookpro16,1: 6-core intel core i7-9750h at 2.6,ghz, 16,gb of memory",
            [
                ("16,1", None, "name"),
                ("6", "6", None),
                ("7", None, "name"),
                ("9750", None, "name"),
                ("2.6", "2.6", None),
                ("16", "16", None),
            ],
        ),
        (
            "| sha256sum -c 10 | 647 |",
            [("256", None, "name"), ("10", "10", None), ("647", "647", None)],
        ),
        (
            "paper/continuous_verification_v15zw_ai4sci.txt",
            [("15", None, "name"), ("4", None, "name")],
        ),
        (
            "(ubuntu-24.04: amd epyc 9v45, 2 processors",
            [("24.04", None, "name"), ("9", None, "name"), ("45", None, "name"), ("2", "2", None)],
        ),
        ("value here | rfc 6901 json pointer | decimal", [("6901", None, "document_identifier")]),
        (
            "iso 8601 and arxiv 2609.22111",
            [("8601", None, "document_identifier"), ("2609.22111", None, "document_identifier")],
        ),
        (
            "isbn 978-3-16-148410-0 and pep-8",
            [(n, None, "document_identifier") for n in ("978", "3", "16", "148410", "0", "8")],
        ),
        # An em or en dash before a number ends a clause. It joins no name and is no sign.
        ("accuracy\u201492 of 100", [("92", "92", None), ("100", "100", None)]),
        ("we kept three \u20143 of them", [("three", "3", None), ("3", "3", None)]),
        ("weeks 10\u201312", [("10", "10", None), ("12", "12", None)]),
        ("recall---61 in all", [("61", "61", None)]),
        ("a drop of \u22120.42 and gpt\u20104", [("-0.42", "-0.42", None), ("4", None, "name")]),
        # Left counted: a status code is a statement the text makes, and a year rule or a
        # citation rule narrowed by its surroundings would be a judgment.
        ("the run exits 1, and exit code 2", [("1", "1", None), ("2", "2", None)]),
        ("a count of 1950 cells", [("1950", "1950", "year")]),
        (
            "95% ci [12, 18]",
            [("95%", "95", None), ("12", "12", "citation"), ("18", "18", "citation")],
        ),
    ],
)
def test_each_form_of_number_is_read_and_each_rule_names_what_it_sets_aside(
    tmp_path, text, expected
):
    assert read(tmp_path, text + "\n") == [
        (printed, value, NumberRule(rule) if rule else None) for printed, value, rule in expected
    ]


def test_every_number_stands_in_one_place_and_the_counts_add_up(tmp_path, capsys):
    text = (
        "In 2024 we ran 12 trials (table 2) over 3 sites.\n"
        "Of 240 values, 146 are located, a recall of 61%.\n"
        "Timing took 0.53 seconds with v15.\n"
    )
    made = project(
        tmp_path,
        text,
        [claim("located", "Of 240 values, 146 are located", "146")],
        [SetAside(artifact="paper", text="took 0.53 seconds", reason="a timing, not a result")],
        notes="The notes repeat 146 and add 9.",
    )
    report = numbers(made, only=("paper", "notes"))
    assert report.counts == {BOUND: 1, BY_RULE: 3, WITH_REASON: 1, UNBOUND: 6}
    assert sum(report.counts.values()) == len(report.numbers) == 11
    assert report.rules == {NumberRule.NAME: 1, NumberRule.LABEL: 1, NumberRule.YEAR: 1}

    assert main(["numbers", str(made.path), "--text", "paper", "--text", "notes"]) == 0
    out = capsys.readouterr().out
    paper, notes, summary = out.split("\n\n")[1:]
    assert paper.splitlines() == [
        f"  paper ({tmp_path / 'paper.txt'})",
        "    line 1     12   in 2024 we ran 12 trials (table 2) over",
        "    line 1     3    trials (table 2) over 3 sites. of 240 values,",
        "    line 2     240  over 3 sites. of 240 values, 146 are located,",
        "    line 2     61%  located, a recall of 61%. timing took 0.53 seconds",
        "    9 numbers: 1 bound, 3 set aside by rule, 1 set aside with a reason, 4 unbound",
    ]
    assert notes.splitlines() == [
        f"  notes ({tmp_path / 'notes.txt'})",
        "    line 1     146  the notes repeat 146 and add 9.  (reported elsewhere)",
        "    line 1     9    repeat 146 and add 9.",
        "    2 numbers: 0 bound, 0 set aside by rule, 0 set aside with a reason, 2 unbound",
    ]
    assert summary.splitlines() == [
        "  set aside by rule: 1 name, 1 label, 1 year",
        '  set aside with a reason: 1 in paper "took 0.53 seconds": a timing, not a result',
        "  11 numbers in 2 texts: 1 bound, 3 set aside by rule, 1 set aside with a reason, "
        "6 unbound",
        "  6 unbound: 6 numerals, 0 number words",
        "  1 of the 6 unbound print a value an assertion reports, outside the passage it "
        "reports it for; 0 more match on one digit and are not marked",
    ]


def test_a_number_is_on_the_line_of_the_text_it_is_printed_on(tmp_path):
    text = (
        "A first line with 11 in it.\n"
        "\n"
        "   Then 22, split at a hyphen-\n"
        "ated word, and naïve 33.\n"
        "\n"
        "A last line holding 44 —\n"
        "and 55"
    )
    report = numbers(project(tmp_path, text), only=("paper",))
    assert [(n.text, n.line) for n in report.numbers] == [
        ("11", 1),
        ("22", 3),
        ("33", 4),
        ("44", 6),
        ("55", 7),
    ]
    folded = passage_fold(text)
    assert all(folded[n.offset :].startswith(n.text) for n in report.numbers)
    assert report.numbers[2].context == "hyphenated word, and naive 33. a last line holding"


def test_the_json_document_is_the_report_with_every_number_in_it(tmp_path, capsys):
    text = "In 2024 we ran 12 trials. Of 240 values, 146 are located.\n"
    made = project(
        tmp_path,
        text,
        [claim("located", "Of 240 values, 146 are located", "146")],
        [SetAside(artifact="paper", text="ran 12 trials", reason="a design choice")],
    )
    assert main(["numbers", str(made.path), "--format", "json"]) == 0
    document = json.loads(capsys.readouterr().out)
    report = NumbersReport.model_validate(document)
    assert report == numbers(made)
    assert NumbersReport.model_validate_json(report.model_dump_json()) == report
    (paper,) = document["texts"]
    assert [(n["text"], n["standing"], n["rule"]) for n in paper["numbers"]] == [
        ("2024", "set_aside_by_rule", "year"),
        ("12", "set_aside_with_a_reason", None),
        ("240", "unbound", None),
        ("146", "bound", None),
    ]
    assert paper["numbers"][3]["claims"] == ["located"]
    assert document["set_aside"] == [
        {"artifact": "paper", "text": "ran 12 trials", "reason": "a design choice", "numbers": 1}
    ]


def test_the_command_writes_nothing_and_changes_no_other_report(tmp_path, capsys):
    made = project(
        tmp_path,
        "Of 240 values, 146 are located.\n",
        [claim("located", "Of 240 values, 146 are located", "146")],
    )
    before = snapshot(tmp_path), verify(made)
    numbers(made)
    assert main(["numbers", str(made.path)]) == 0
    assert main(["numbers", str(made.path), "--format", "json"]) == 0
    assert (snapshot(tmp_path), verify(made)) == before


def test_with_no_text_to_read_the_command_says_so_and_exits_2(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main(["numbers"]) == 2
    assert "no repro.yaml here or above" in capsys.readouterr().out

    made = project(tmp_path, "We ran 12 trials.\n")
    with pytest.raises(NoTextError):
        numbers(made)
    assert main(["numbers"]) == 2
    assert "Name the text with --text <artifact-id>" in capsys.readouterr().out

    with pytest.raises(
        UnknownArtifactError, match=r"no artifact 'draft'; declared: paper, results"
    ):
        numbers(made, only=("draft",))
    assert main(["numbers", "--text", "draft"]) == 2

    (tmp_path / "paper.txt").unlink()
    with pytest.raises(ArtifactMissingError):
        numbers(made, only=("paper",))
    assert main(["numbers", "--text", "paper"]) == 2


def test_a_value_reported_elsewhere_is_marked_only_where_it_has_two_digits_or_a_point(
    tmp_path, capsys
):
    stated = "We kept 4 sites, 25 fixtures, 0.5 of the rows and four readers"
    text = stated + ". Later: 4 sites, 25 fixtures, 0.5 of the rows, four readers, twenty-five.\n"
    claims = [
        claim(name, stated, reported)
        for name, reported in (("sites", "4"), ("fixtures", "25"), ("rows", "0.5"))
    ]
    made = project(tmp_path, text, claims)
    report = numbers(made)
    later = report.numbers[4:]
    assert [(n.text, n.reported_elsewhere, n.reported_elsewhere_one_digit) for n in later] == [
        ("4", False, True),
        ("25", True, False),
        ("0.5", True, False),
        ("four", False, True),
        ("twenty-five", True, False),
    ]
    # The word in the passage is bound by the claim that reports its value.
    assert [(n.text, n.standing) for n in report.numbers[:4]] == [
        ("4", BOUND),
        ("25", BOUND),
        ("0.5", BOUND),
        ("four", BOUND),
    ]
    assert main(["numbers", str(made.path)]) == 0
    assert capsys.readouterr().out.splitlines()[-2:] == [
        "  5 unbound: 3 numerals, 2 number words",
        "  3 of the 5 unbound print a value an assertion reports, outside the passage it "
        "reports it for; 2 more match on one digit and are not marked",
    ]


def test_a_number_whose_line_cannot_be_placed_is_printed_with_its_offset(
    tmp_path, capsys, monkeypatch
):
    made = project(tmp_path, "First line.\nThen 12 trials.\n")
    assert [n.line for n in numbers(made, only=("paper",)).numbers] == [2]
    monkeypatch.setattr("repro.numbers._line_starts", lambda raw, folded: None)
    (number,) = numbers(made, only=("paper",)).numbers
    assert (number.line, number.offset) == (None, 17)
    assert main(["numbers", str(made.path), "--text", "paper"]) == 0
    assert "    offset 17  12  first line. then 12 trials." in capsys.readouterr().out
