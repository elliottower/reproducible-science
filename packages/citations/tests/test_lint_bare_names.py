"""Correct family names with no given names beside them, which every other check passes.

    author = {Bhaskar and Wettig and Friedman and Chen}

is arXiv:2406.16778 written without a first name in it, and it prints as "Bhaskar, Wettig,
Friedman, and Chen." in the reference list. Five entries in one paper's bibliography were like
this on the day it was submitted. `--authors` reported none of them: the four family names are
the four the identifier resolves to, in order, and family names are all it compares. The
registry stub below is that paper's own arXiv payload, so the two checks are run over the one
entry and disagree.

Nothing here touches the network. The bare-name check never has a reason to.
"""

from __future__ import annotations

import json
import pathlib
import urllib.parse

import pytest
from citations import lint

#: arXiv for 2406.16778, trimmed to what the reader takes off it.
EDGE_PRUNING = """<?xml version='1.0' encoding='UTF-8'?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2406.16778v2</id>
    <title>Finding Transformer Circuits with Edge Pruning</title>
    <author><name>Adithya Bhaskar</name></author>
    <author><name>Alexander Wettig</name></author>
    <author><name>Dan Friedman</name></author>
    <author><name>Danqi Chen</name></author>
  </entry>
</feed>
"""

#: The five author fields as that bibliography carried them, and the entries they sat in.
AS_SUBMITTED = {
    "palumbo2024validating": (
        r"Palumbo and Mangal and Wang and Vijayakumar and P{\u a}s{\u a}reanu and Jha"
    ),
    "zhang2023towards": "Zhang and Nanda",
    "chhabra2025neuroplasticity": "Chhabra and Zhu and Khalili",
    "oneill2024sparse": "O'Neill and Bui",
    "bhaskar2024finding": "Bhaskar and Wettig and Friedman and Chen",
}

#: From the same file, and none of them a defect. A corporate author is braced, which is how
#: BibTeX is told the name has no given part; the last two carry an ` and ` inside the braces.
CORPORATE = {
    "nasa2008std7009": "{NASA}",
    "osc2015estimating": "{Open Science Collaboration}",
    "nobel2021economic": "{Royal Swedish Academy of Sciences}",
    "fdabioanalytical": "{U.S. Food and Drug Administration}",
    "pcast2016forensic": "{President's Council of Advisors on Science and Technology}",
}


def entry(key: str, author: str, **fields: str) -> str:
    lines = [f"  author = {{{author}}}"] + [f"  {k} = {{{v}}}" for k, v in fields.items()]
    return "@article{" + key + ",\n" + ",\n".join(lines) + "\n}\n"


def bib(tmp_path, *entries: str) -> pathlib.Path:
    path = tmp_path / "refs.bib"
    path.write_text("\n".join(entries))
    return path


def bare(path: pathlib.Path) -> list[lint.BibFinding]:
    _entries, findings = lint.bib_findings(path)
    return [f for f in findings if f.kind == "bare"]


@pytest.fixture
def registry(monkeypatch):
    """arXiv's answer for 2406.16778, so `--authors` can be asked about the same entry."""
    answers: dict[str, object] = {}

    def get(url, as_json=True, tries=4, headers=None):
        for identifier, payload in answers.items():
            if identifier in url or urllib.parse.quote(identifier, safe="") in url:
                return payload
        return None

    monkeypatch.setattr(lint.resolve, "get", get)
    monkeypatch.setattr(lint, "DELAY", 0)
    return answers


# --- the two checks over one entry, disagreeing -------------------------------------------------


def test_a_family_name_with_no_given_name_is_flagged(tmp_path):
    path = bib(tmp_path, entry("bhaskar2024finding", AS_SUBMITTED["bhaskar2024finding"]))

    findings = bare(path)

    assert [f.names for f in findings] == [["Bhaskar", "Wettig", "Friedman", "Chen"]]


def test_the_registry_check_passes_the_entry_the_bare_check_fails(tmp_path, registry):
    """Why this check exists. The family names are right, and they are all `--authors` reads."""
    registry["2406.16778"] = EDGE_PRUNING
    path = bib(
        tmp_path,
        entry(
            "bhaskar2024finding",
            AS_SUBMITTED["bhaskar2024finding"],
            eprint="2406.16778",
            archiveprefix="arXiv",
        ),
    )

    report = lint.check_authors(path)

    assert (report.checked, report.findings) == (1, [])
    assert bare(path), "the offline check is the only one that can see this"


def test_the_five_entries_that_reached_a_submission_are_the_only_findings(tmp_path):
    written = [entry(key, author) for key, author in AS_SUBMITTED.items()]
    written += [entry(key, author) for key, author in CORPORATE.items()]
    written += [
        entry("smith2019mediational", "Smith, Louisa H. and VanderWeele, Tyler J."),
        entry("vaswani2017attention", "Ashish Vaswani and Noam Shazeer"),
    ]

    findings = bare(bib(tmp_path, *written))

    assert [f.keys[0] for f in findings] == list(AS_SUBMITTED)


# --- a name that is written in full ------------------------------------------------------------


@pytest.mark.parametrize(
    "author",
    [
        "Bhaskar, Adithya",
        "Adithya Bhaskar",
        "Bhaskar, A.",
        "Bhaskar, Adithya and Wettig, Alexander",
        "Adithya Bhaskar and Alexander Wettig",
    ],
)
def test_a_name_with_a_given_part_is_not_flagged(tmp_path, author):
    assert bare(bib(tmp_path, entry("k", author))) == []


@pytest.mark.parametrize("author", list(CORPORATE.values()))
def test_a_braced_name_is_not_flagged(tmp_path, author):
    # Braces are how BibTeX is told a name is complete as written. A check that reports {NASA}
    # reports most of the grey literature in a bibliography and is switched off within the week.
    assert bare(bib(tmp_path, entry("k", author))) == []


def test_a_braced_author_carrying_and_stays_one_author(tmp_path):
    # Splitting on ` and ` brace-blind makes this two names, the second reading `Technology}`,
    # which is a family name with no given name and belongs to nobody.
    field = CORPORATE["pcast2016forensic"]

    assert lint.split_authors(field) == ([field], False)


def test_and_others_is_not_reported_as_a_bare_family_name(tmp_path):
    # A shortened list is a real defect and `--authors` reports it as `marker`. Reporting the
    # marker here as well would name `others` as an author with no first name.
    assert bare(bib(tmp_path, entry("k", "Smith, Louisa H. and others"))) == []
    assert bare(bib(tmp_path, entry("k", "Smith, Louisa H. and et al."))) == []


def test_an_entry_with_no_author_field_is_not_a_finding(tmp_path):
    assert bare(bib(tmp_path, "@misc{k,\n  title = {A Standard}\n}\n")) == []


# --- accents, which the fold must not cost the check ---------------------------------------------


@pytest.mark.parametrize("author", ["Krzyżosiak", "Kozłowski", r"P{\u a}s{\u a}reanu", "Munafò"])
def test_an_accented_family_name_alone_is_still_flagged(tmp_path, author):
    # A LaTeX accent carries a space inside its braces, so counting words brace-blind reads
    # `P{\u a}s{\u a}reanu` as three and lets the entry through.
    assert [f.names for f in bare(bib(tmp_path, entry("k", author)))] == [[author]]


@pytest.mark.parametrize(
    "author",
    [
        "Krzyżosiak, Włodzimierz J.",
        "Włodzimierz J. Krzyżosiak",
        r"P{\u a}s{\u a}reanu, Corina S.",
        r"Munaf{\'o}, Marcus",
        r"{\c{S}}ahin, Kerem",
    ],
)
def test_an_accented_name_with_a_given_name_is_not_flagged(tmp_path, author):
    assert bare(bib(tmp_path, entry("k", author))) == []


# --- a list where some names are written in full and some are not ---------------------------------


def test_a_mixed_list_names_the_authors_that_lost_their_given_names(tmp_path):
    path = bib(
        tmp_path,
        entry("mixed", "Bhaskar, Adithya and Wettig and Friedman, Dan and Chen"),
    )

    findings = bare(path)

    assert [f.names for f in findings] == [["Wettig", "Chen"]]


def test_a_mixed_list_is_one_finding_rather_than_one_per_name(tmp_path):
    path = bib(tmp_path, entry("mixed", "Bhaskar, Adithya and Wettig and Friedman, Dan and Chen"))

    assert len(bare(path)) == 1, "one entry, one defect, one line to go and fix"


# --- what the report says -------------------------------------------------------------------------


def test_the_finding_names_the_entry_and_the_line_it_sits_on(tmp_path):
    path = bib(
        tmp_path,
        entry("first", "Smith, Ann"),
        entry("bhaskar2024finding", AS_SUBMITTED["bhaskar2024finding"]),
    )

    finding = bare(path)[0]

    assert (finding.keys, finding.lines) == (["bhaskar2024finding"], [5])
    assert finding.file == str(path)


def test_the_report_prints_the_names_that_have_no_given_name(tmp_path, capsys):
    path = bib(tmp_path, entry("bhaskar2024finding", AS_SUBMITTED["bhaskar2024finding"]))

    assert lint.main(["--bib", str(path)]) == 1

    out = capsys.readouterr().out
    assert "bhaskar2024finding" in out
    assert "'Bhaskar', 'Wettig', 'Friedman', 'Chen'" in out
    assert "1 author list(s) with a bare family name" in out


def test_a_clean_file_says_so_and_exits_zero(tmp_path, capsys):
    # The negative half: a check hardwired to fail would pass the test above.
    path = bib(tmp_path, entry("k", "Bhaskar, Adithya"), entry("j", CORPORATE["nasa2008std7009"]))

    assert lint.main(["--bib", str(path)]) == 0
    assert "every author list carries given names" in capsys.readouterr().out


def test_a_repeated_key_and_a_bare_name_are_both_reported(tmp_path, capsys):
    path = bib(
        tmp_path,
        entry("twice", "Smith, Ann"),
        entry("twice", "Smith, Ann"),
        entry("bhaskar2024finding", AS_SUBMITTED["bhaskar2024finding"]),
    )

    assert lint.main(["--bib", str(path)]) == 1

    out = capsys.readouterr().out
    assert "1 repeated key(s), 1 author list(s)" in out
    assert "repeated" in out and "bare" in out


def test_findings_exit_nonzero_under_json_too(tmp_path, capsys):
    # A machine-readable mode that prints findings and exits 0 is a check that cannot fail.
    path = bib(tmp_path, entry("bhaskar2024finding", AS_SUBMITTED["bhaskar2024finding"]))

    assert lint.main(["--bib", str(path), "--json"]) == 1

    payload = json.loads(capsys.readouterr().out)
    assert [f["kind"] for f in payload] == ["bare"]
    assert payload[0]["names"] == ["Bhaskar", "Wettig", "Friedman", "Chen"]
    assert payload[0]["keys"] == ["bhaskar2024finding"]


def test_the_bare_check_reaches_no_registry(tmp_path, monkeypatch):
    monkeypatch.setattr(
        lint.resolve, "get", lambda *a, **kw: pytest.fail("--bib must not need a network")
    )
    monkeypatch.setattr(lint, "find_papis", lambda: pytest.fail("--bib must not need papis"))
    monkeypatch.setenv("CITATIONS_HOME", str(tmp_path / "nowhere"))
    path = bib(tmp_path, entry("bhaskar2024finding", AS_SUBMITTED["bhaskar2024finding"]))

    assert lint.main(["--bib", str(path)]) == 1


# --- the splitter both `.bib` modes rest on --------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "wrapped"),
    [
        ("{NASA}", True),
        ("{Open Science Collaboration}", True),
        ("{U.S. Food and Drug Administration}", True),
        ("Bhaskar", False),
        (r"Munaf{\'o}", False),
        (r"Gon{\c{c}}alves", False),
        (r"{\c{S}}ahin", False),  # two groups, the first of which closes before the name ends
        ("{Alpha} and {Beta}", False),
    ],
)
def test_a_whole_name_inside_one_pair_of_braces_is_recognized(name, wrapped):
    assert lint.braced(name) is wrapped


def test_a_separator_inside_braces_does_not_split(tmp_path):
    assert lint.split_outside_braces("{a and b} and c", lint.AND) == ["{a and b}", "c"]
    assert lint.split_outside_braces(r"P{\u a}s{\u a}reanu", lint.SPACE) == [r"P{\u a}s{\u a}reanu"]
    assert lint.split_outside_braces("Adithya Bhaskar", lint.SPACE) == ["Adithya", "Bhaskar"]
