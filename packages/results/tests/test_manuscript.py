"""What counts as a number a manuscript owes a run for, and which of them a claim names."""

import json
import pathlib

import pytest

from results import manuscript


def write(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text)
    return path


def printed(records):
    return [r["printed"] for r in records]


def owed(records):
    return [r["printed"] for r in records if r["exempt"] is None]


def test_a_latex_range_yields_two_positive_bounds(tmp_path):
    paper = write(tmp_path, "p.tex", r"\begin{document} OR 1.07 (0.92--1.20) \end{document}")

    assert printed(manuscript.numbers(paper)) == ["1.07", "0.92", "1.20"]


def test_a_genuine_negative_keeps_its_sign(tmp_path):
    paper = write(tmp_path, "p.tex", r"\begin{document} a shift of -1.3 units \end{document}")

    assert "-1.3" in printed(manuscript.numbers(paper))


def test_a_number_ending_a_clause_drops_its_comma(tmp_path):
    paper = write(tmp_path, "p.tex", r"\begin{document} we sampled 7222, then stopped \end{document}")

    assert "7222" in printed(manuscript.numbers(paper))
    assert "7222," not in printed(manuscript.numbers(paper))


def test_preamble_and_comments_are_not_the_manuscript(tmp_path):
    paper = write(tmp_path, "p.tex",
                  "\\documentclass[11pt]{article}\n"
                  "% an aside mentioning 4321\n"
                  "\\begin{document}\naccuracy was 87.65\n\\end{document}\n")

    assert owed(manuscript.numbers(paper)) == ["87.65"]


def test_layout_lengths_and_citation_keys_owe_nothing(tmp_path):
    paper = write(tmp_path, "p.tex",
                  r"\begin{document}\vspace{0.5em}\cite{smith2019} then 87.65\end{document}")

    assert owed(manuscript.numbers(paper)) == ["87.65"]


def test_constants_identifiers_and_hyphenated_names_owe_nothing(tmp_path):
    paper = write(tmp_path, "p.tex",
                  r"\begin{document}"
                  r"at 1.96 on CIFAR-10 see arXiv: 1312.6114 giving 87.65"
                  r"\end{document}")

    assert owed(manuscript.numbers(paper)) == ["87.65"]


def test_a_single_digit_owes_nothing_and_two_digits_do(tmp_path):
    paper = write(tmp_path, "p.tex", r"\begin{document} 7 families across 24 sites \end{document}")

    assert owed(manuscript.numbers(paper)) == ["24"]


def test_a_rendered_pdf_is_refused_rather_than_read(tmp_path):
    paper = write(tmp_path, "paper.pdf", "%PDF-1.7")

    with pytest.raises(manuscript.UnreadableManuscript):
        manuscript.numbers(paper)


def test_claimed_values_reads_the_numbers_inside_a_claim():
    events = [
        {"event": "run", "run_id": "r1"},
        {"event": "claim", "run_id": "r1", "claim": r"MR $d = 0.103$ clears it by 0.003"},
        {"event": "claim", "run_id": "r1", "claim": "across 24 families"},
    ]

    assert manuscript.claimed_values(events) == {"0.103", "0.003", "24"}


def test_claimed_values_ignores_every_other_event():
    events = [{"event": "seal", "digest": "9" * 64}, {"event": "run", "run_id": "0.999"}]

    assert manuscript.claimed_values(events) == set()


def test_constraining_digits_discounts_leading_and_trailing_zeros():
    assert manuscript.constraining_digits("0.9489") == 4
    assert manuscript.constraining_digits("100") == 1
    assert manuscript.constraining_digits("14.38") == 4
    assert manuscript.constraining_digits("0") == 1


def test_includes_are_followed(tmp_path):
    (tmp_path / "text").mkdir()
    (tmp_path / "text" / "results.tex").write_text("accuracy was 87.65\n")
    paper = write(tmp_path, "main.tex",
                  "\\begin{document}\n\\input{text/results}\n\\end{document}\n")

    assert owed(manuscript.numbers(paper)) == ["87.65"]


def test_a_nested_include_resolves_against_the_main_document(tmp_path):
    """LaTeX resolves an include from the root, never from the file doing the including."""
    (tmp_path / "text" / "appendix").mkdir(parents=True)
    (tmp_path / "text" / "appendix" / "tables.tex").write_text("the table gives 43.21\n")
    (tmp_path / "text" / "appendix.tex").write_text("\\input{text/appendix/tables}\n")
    paper = write(tmp_path, "main.tex",
                  "\\begin{document}\n\\input{text/appendix}\n\\end{document}\n")

    assert owed(manuscript.numbers(paper)) == ["43.21"]


def test_a_number_records_the_file_it_came_from(tmp_path):
    (tmp_path / "sections").mkdir()
    (tmp_path / "sections" / "eval.tex").write_text("we reach 87.65\n")
    paper = write(tmp_path, "main.tex",
                  "\\begin{document}\n\\input{sections/eval}\n\\end{document}\n")

    record = [n for n in manuscript.numbers(paper) if n["exempt"] is None][0]
    assert record["source"] == "eval.tex"
    assert record["line"] == 1


def test_an_include_cycle_terminates(tmp_path):
    (tmp_path / "a.tex").write_text("\\input{b}\n87.65\n")
    (tmp_path / "b.tex").write_text("\\input{a}\n43.21\n")
    paper = write(tmp_path, "main.tex", "\\begin{document}\n\\input{a}\n\\end{document}\n")

    assert sorted(owed(manuscript.numbers(paper))) == ["43.21", "87.65"]


def test_a_missing_include_leaves_the_rest_readable(tmp_path):
    paper = write(tmp_path, "main.tex",
                  "\\begin{document}\n\\input{nowhere/absent}\nwe reach 87.65\n\\end{document}\n")

    assert owed(manuscript.numbers(paper)) == ["87.65"]


def test_a_citation_marks_the_line_it_sits_on(tmp_path):
    paper = write(tmp_path, "p.tex",
                  "\\begin{document}\n"
                  "we measured 43.21 ourselves\n"
                  "an earlier trial reported 55.44 \\cite{smith2019}\n"
                  "\\end{document}\n")

    records = {n["printed"]: n["attributed"] for n in manuscript.numbers(paper)}
    assert records["55.44"] is True
    assert records["43.21"] is False
