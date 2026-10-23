"""Coverage reads every form a quotation is written in, and says what an ellipsis leaves out.

Two attacks. A manuscript quoting with straight or curly marks, `\\enquote`, a `quote`
environment or a Markdown block had none of those read, so an unpinned quotation in any of them
was reported as nothing to check. And `did ... improve` was `covered` by a pin reading `did not
improve`, which says the opposite.
"""

from __future__ import annotations

import json
import pathlib

import pytest
from citations import coverage as C
from citations.cli import main

PINNED = "the intervention did not improve recall in older adults at any dose tested"
UNPINNED = "the protocol reliably improves recall in every population it was tried on"


@pytest.fixture(autouse=True)
def _quiet(monkeypatch):
    monkeypatch.setenv("REPRO_NO_HINT", "1")


def claims(tmp_path: pathlib.Path) -> pathlib.Path:
    folder = tmp_path / "claims"
    folder.mkdir()
    (folder / "smith.yaml").write_text(
        json.dumps(
            {"source": {"citation": "smith"}, "claims": {"c1": {"quotes": [{"exact": PINNED}]}}}
        )
    )
    return folder


@pytest.mark.parametrize(
    ("suffix", "written", "form"),
    [
        (".tex", f"As reported, ``{UNPINNED}''.", "latex"),
        (".tex", f"As reported, \\enquote{{{UNPINNED}}}.", "command"),
        (".tex", f"\\begin{{quote}}\n{UNPINNED}\n\\end{{quote}}", "environment"),
        (".tex", f"\\begin{{quotation}}\n{UNPINNED}\n\\end{{quotation}}", "environment"),
        (".md", f"As reported, ``{UNPINNED}''.", "latex"),  # not read as inline code
        (".md", f"As reported, \u201c{UNPINNED}\u201d.", "curly"),
        (".md", f'As reported, "{UNPINNED}".', "straight"),
        (".md", f"As reported:\n\n> {UNPINNED[:40]}\n> {UNPINNED[40:]}\n", "markdown"),
    ],
)
def test_an_unpinned_quotation_in_any_form_is_uncovered(tmp_path, capsys, suffix, written, form):
    (q,) = C.quotations(written, latex=suffix == ".tex")
    assert q.form == form
    assert C.passage_fold(UNPINNED) in q.text
    paper = tmp_path / f"paper{suffix}"
    paper.write_text(written)
    assert main(["coverage", str(paper), "--claims", str(claims(tmp_path))]) == 1
    assert "UNCOVERED" in capsys.readouterr().out


def test_a_quotation_inside_a_quote_environment_is_read_once():
    found = C.quotations(f"\\begin{{quote}}\nshe wrote ``{UNPINNED}'' and left\n\\end{{quote}}")
    assert [q.form for q in found] == ["environment"]


@pytest.mark.parametrize(
    "written",
    [
        'the so-called "alignment tax" is small',  # a term, not a quotation
        "> [!NOTE]\n> this callout is a note and not a quotation of anybody at all",
        '---\ntitle: "a title in the front matter that is long enough to count"\n---\n',
        '```\nprint("a string in a code block that is long enough to count as one")\n```\n',
    ],
)
def test_marks_that_set_off_something_else_are_not_quotations_in_markdown(written):
    assert C.quotations(written, latex=False) == []


def test_a_percent_sign_in_markdown_is_not_a_comment():
    (q,) = C.quotations(f'"{UNPINNED} at 50% of the dose"', latex=False)
    assert "50% of the dose" in q.raw


def status(quote: str, pinned: str) -> C.Finding:
    (q,) = C.quotations(f"``{quote}''")
    pool = [("smith", C.comparable(C.unwrap(pinned)))]
    return C.cover(q, pool)


def test_an_ellipsis_that_drops_a_negation_is_covered_and_says_so():
    f = status("the intervention did ... improve recall in older adults", PINNED)
    assert f.status == "covered"
    assert f.omitted == ("not",)
    assert f.negation == "not"


def test_an_ellipsis_that_drops_no_negation_says_what_it_left_out():
    f = status("the intervention did not improve recall ... at any dose tested", PINNED)
    assert f.status == "covered"
    assert f.omitted == ("in older adults",)
    assert f.negation == ""


def test_a_quotation_with_no_ellipsis_leaves_nothing_out():
    f = status("did not improve recall in older adults", PINNED)
    assert f.omitted == () and f.negation == ""


def test_strict_fails_a_dropped_negation_and_the_default_reports_it(tmp_path, capsys):
    paper = tmp_path / "paper.tex"
    paper.write_text(
        "They found ``the intervention did \\ldots{} improve recall in older adults''."
    )
    folder = claims(tmp_path)
    assert main(["coverage", str(paper), "--claims", str(folder)]) == 0
    out = capsys.readouterr().out
    assert "DROPS A NEGATION" in out and "left out: [[not]]" in out
    assert main(["coverage", str(paper), "--claims", str(folder), "--strict"]) == 1
