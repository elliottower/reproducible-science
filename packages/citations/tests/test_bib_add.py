"""A repeated key must never reach a `.bib`, and a write is not verified until it is read back.

Appending an entry by hand put a duplicate key in one paper's bibliography twice in one session.
BibTeX's answer to a duplicate is non-fatal -- `Repeated entry`, then it skips that copy and
writes a `.bbl` without it -- so the failure surfaces somewhere else entirely, as
`Citation undefined` warnings that name nothing. The fixtures below are real registry payloads:
the reading of a payload is checked against a payload, with no network and nothing standing in
for one.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest
from citations import add, bibtex, lint
from citations.exceptions import BibFileError, MetadataError

ENTRY = (
    "@misc{{{cite},\n"
    "  author = {{{author}}},\n"
    "  title  = {{Something Measurable}},\n"
    "  year   = {{2026}}\n"
    "}}\n"
)

#: Entry starts land on lines 1, 7, 13 -- five lines each and a blank line between.
FIRST_LINES = (1, 7, 13)


def bib(tmp_path, *keys):
    path = tmp_path / "refs.bib"
    path.write_text("\n".join(ENTRY.format(cite=k, author="Alpha, Ann") for k in keys))
    return path


def entry_file(tmp_path, cite, author="Gamma, Gil"):
    path = tmp_path / "entry.bib"
    path.write_text(ENTRY.format(cite=cite, author=author))
    return path


# --- the repeat, which is the whole point ------------------------------------------------------


def test_a_repeated_key_is_refused_and_the_file_is_left_exactly_as_it_was(tmp_path, capsys):
    target = bib(tmp_path, "alpha2026one", "beta2026two")
    before = target.read_bytes()

    code = add.main(
        [
            str(target),
            "--key",
            "alpha2026one",
            "--entry-file",
            str(entry_file(tmp_path, "alpha2026one", author="Delta, Dee")),
        ]
    )

    assert code != 0
    assert target.read_bytes() == before
    out = capsys.readouterr().out
    assert f"line {FIRST_LINES[0]}" in out
    assert "Alpha, Ann" in out and "Delta, Dee" in out, "both entries, so they can be compared"


def test_a_key_differing_only_in_case_is_the_same_key(tmp_path):
    # BibTeX 0.99d over a file holding both `beta2026two` and `Beta2026Two` reports
    # `Repeated entry`, skips the second and writes a .bbl without it, and reads a \cite of the
    # second as a `Case mismatch error`. Accepting it here would write that defect.
    target = bib(tmp_path, "beta2026two")
    before = target.read_bytes()

    assert add.main([str(target), "--entry-file", str(entry_file(tmp_path, "Beta2026Two"))]) != 0
    assert target.read_bytes() == before


def test_a_new_key_is_appended_and_every_entry_the_file_starts_still_closes(tmp_path):
    target = bib(tmp_path, "alpha2026one")

    assert add.main([str(target), "--entry-file", str(entry_file(tmp_path, "gamma2026three"))]) == 0

    text = bibtex.read(target)
    started = [key for key, _line in bibtex.key_lines(text)]
    closed = [key for _kind, key, _body in bibtex.entries(text)]
    assert started == ["alpha2026one", "gamma2026three"]
    assert closed == started, "an entry that starts and never closes swallows the next one"


def test_check_reports_the_addition_and_writes_nothing(tmp_path, capsys):
    target = bib(tmp_path, "alpha2026one")
    before = target.read_bytes()

    code = add.main(
        [str(target), "--entry-file", str(entry_file(tmp_path, "gamma2026three")), "--check"]
    )

    assert code == 0
    assert target.read_bytes() == before
    assert "gamma2026three" in capsys.readouterr().out


def test_a_write_landing_on_a_key_already_there_is_rolled_back(tmp_path):
    # `append` is the last check between the duplicate report and the file: `main` reads the
    # bibliography, decides the key is free, and then writes, and the file can change in
    # between. Without the read-back the duplicate is in the file and the command reported
    # success.
    target = bib(tmp_path, "alpha2026one")
    before = target.read_bytes()
    entry = add.one_entry(ENTRY.format(cite="alpha2026one", author="Delta, Dee"), target)

    with pytest.raises(BibFileError):
        add.append(target, entry)

    assert target.read_bytes() == before


def test_a_file_holding_an_entry_that_never_closes_is_not_appended_to(tmp_path):
    target = tmp_path / "refs.bib"
    target.write_text("@misc{alpha2026one,\n  title = {First Work}\n")
    before = target.read_bytes()

    with pytest.raises(BibFileError) as caught:
        add.main([str(target), "--entry-file", str(entry_file(tmp_path, "gamma2026three"))])

    assert "alpha2026one" in str(caught.value)
    assert target.read_bytes() == before


def test_an_entry_is_separated_from_the_one_above_it(tmp_path):
    # A file people hand-edit, and the last entry of one is often written without a trailing
    # newline.
    target = tmp_path / "refs.bib"
    target.write_text("@misc{alpha2026one,\n  title = {First Work}\n}")

    assert add.main([str(target), "--entry-file", str(entry_file(tmp_path, "gamma2026three"))]) == 0
    assert "}\n\n@misc{gamma2026three," in bibtex.read(target)


# --- what counts as an entry -------------------------------------------------------------------


def test_text_holding_two_entries_is_refused(tmp_path):
    target = bib(tmp_path, "alpha2026one")
    before = target.read_bytes()
    both = tmp_path / "two.bib"
    both.write_text(
        ENTRY.format(cite="gamma2026three", author="Gamma, Gil")
        + ENTRY.format(cite="delta2026four", author="Delta, Dee")
    )

    with pytest.raises(BibFileError) as caught:
        add.main([str(target), "--entry-file", str(both)])

    assert "gamma2026three" in str(caught.value) and "delta2026four" in str(caught.value)
    assert target.read_bytes() == before


def test_a_key_that_disagrees_with_the_entry_is_refused(tmp_path):
    target = bib(tmp_path, "alpha2026one")

    with pytest.raises(BibFileError) as caught:
        add.main(
            [
                str(target),
                "--key",
                "gamma2026three",
                "--entry-file",
                str(entry_file(tmp_path, "delta2026four")),
            ]
        )

    assert "gamma2026three" in str(caught.value) and "delta2026four" in str(caught.value)


def test_the_entry_can_arrive_on_standard_input(tmp_path):
    target = bib(tmp_path, "alpha2026one")
    env = {"PATH": "/usr/bin:/bin:/usr/local/bin", "HOME": str(tmp_path)}
    env.update(
        {
            k: os.environ[k]
            for k in ("COVERAGE_FILE", "COVERAGE_PROCESS_START", "PYTHONPATH")
            if k in os.environ
        }
    )

    proc = subprocess.run(
        [sys.executable, "-m", "citations.cli", "add", str(target), "--key", "gamma2026three"],
        input=ENTRY.format(cite="gamma2026three", author="Gamma, Gil"),
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env=env,
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert [key for _kind, key, _body in bibtex.entries(bibtex.read(target))] == [
        "alpha2026one",
        "gamma2026three",
    ]


# --- fetched metadata: every author, and nothing invented --------------------------------------


#: Crossref's record for 10.1145/3287560.3287596, trimmed to the fields the reader uses.
MODEL_CARDS = {
    "type": "proceedings-article",
    "title": ["Model Cards for Model Reporting"],
    "container-title": [
        "Proceedings of the Conference on Fairness, Accountability, and Transparency"
    ],
    "publisher": "ACM",
    "page": "220-229",
    "author": [
        {"family": "Mitchell", "given": "Margaret"},
        {"family": "Wu", "given": "Simone"},
        {"family": "Zaldivar", "given": "Andrew"},
        {"family": "Barnes", "given": "Parker"},
        {"family": "Vasserman", "given": "Lucy"},
        {"family": "Hutchinson", "given": "Ben"},
        {"family": "Spitzer", "given": "Elena"},
        {"family": "Raji", "given": "Inioluwa Deborah"},
        {"family": "Gebru", "given": "Timnit"},
    ],
    "published-print": {"date-parts": [[2019, 1, 29]]},
    "issued": {"date-parts": [[2019, 1, 29]]},
    "DOI": "10.1145/3287560.3287596",
}

#: arXiv's Atom feed for 1706.03762, with the summary and the links dropped.
ATTENTION = """<?xml version='1.0' encoding='UTF-8'?>
<feed xmlns:arxiv="http://arxiv.org/schemas/atom" xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/1706.03762v7</id>
    <title>Attention Is All You Need</title>
    <published>2017-06-12T17:57:34Z</published>
    <arxiv:primary_category term="cs.CL"/>
    <author><name>Ashish Vaswani</name></author>
    <author><name>Noam Shazeer</name></author>
    <author><name>Niki Parmar</name></author>
    <author><name>Jakob Uszkoreit</name></author>
    <author><name>Llion Jones</name></author>
    <author><name>Aidan N. Gomez</name></author>
    <author><name>Lukasz Kaiser</name></author>
    <author><name>Illia Polosukhin</name></author>
  </entry>
</feed>
"""

#: What arXiv answers for an identifier it cannot parse: HTTP 400, and a feed holding one entry
#: titled `Error`, written by `arXiv api core`.
ARXIV_ERROR = """<?xml version='1.0' encoding='UTF-8'?>
<feed xmlns:arxiv="http://arxiv.org/schemas/atom" xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>https://arxiv.org/api/errors#incorrect_id_format_for_notanid</id>
    <title>Error</title>
    <updated>2026-08-28T04:11:14Z</updated>
    <summary>incorrect id format for notanid</summary>
    <author><name>arXiv api core</name></author>
  </entry>
</feed>
"""


def test_every_author_crossref_lists_reaches_the_entry():
    work = add.crossref_work(MODEL_CARDS, "10.1145/3287560.3287596")

    assert len(work.authors) == 9
    assert work.authors[0] == "Mitchell, Margaret" and work.authors[-1] == "Gebru, Timnit"

    text = add.render(work, add.suggest_key(work))
    entries = bibtex.entries(text)
    assert len(entries) == 1
    kind, key, body = entries[0]
    assert (kind, key) == ("inproceedings", "mitchell2019model")
    author = next(line for line in body.splitlines() if line.strip().startswith("author"))
    assert author.count(" and ") == 8, "eight separators for nine names, and no `and others`"
    assert "others" not in author and "et al" not in author
    assert "booktitle = {Proceedings of the Conference on Fairness" in body
    assert "year      = {2019}" in body


def test_every_author_arxiv_lists_reaches_the_entry_and_the_id_loses_its_version():
    work = add.arxiv_work(ATTENTION, "1706.03762")

    assert work is not None
    assert len(work.authors) == 8
    assert work.authors[0] == "Ashish Vaswani" and work.authors[-1] == "Illia Polosukhin"
    assert work.arxiv == "1706.03762", "the feed says 1706.03762v7; a citation is not to a version"
    assert work.year == "2017"
    assert add.suggest_key(work) == "vaswani2017attention"

    body = bibtex.entries(add.render(work, "vaswani2017attention"))[0][2]
    author = next(line for line in body.splitlines() if line.strip().startswith("author"))
    assert author.count(" and ") == 7
    assert "eprint        = {1706.03762}" in body and "primaryClass  = {cs.CL}" in body


def test_the_feed_arxiv_returns_for_an_unreadable_identifier_is_not_a_paper():
    # Without this the entry written is `@misc{core2026error, author = {arXiv api core},
    # title = {{Error}}}`, which cites the error message.
    assert add.arxiv_work(ARXIV_ERROR, "notanid") is None


def test_an_author_list_that_ends_in_others_is_refused():
    with pytest.raises(MetadataError) as caught:
        add.crossref_work(
            {
                "title": ["A Work With More Authors Than Were Deposited"],
                "author": [{"family": "Alpha", "given": "Ann"}, {"name": "others"}],
            },
            "10.0000/x",
        )

    assert "not complete" in str(caught.value)


def test_a_payload_with_neither_a_title_nor_an_author_is_not_an_entry():
    with pytest.raises(MetadataError):
        add.crossref_work({"type": "journal-article"}, "10.0000/x")


def test_a_title_arrives_as_text_and_not_as_the_markup_it_was_deposited_in():
    work = add.crossref_work(
        {"title": ["Cost &amp; benefit of <i>in vivo</i> assays"], "author": []},
        "10.0000/x",
    )
    body = bibtex.entries(add.render(work, "k"))[0][2]
    assert "<i>" not in body and "&amp;" not in body
    assert r"Cost \& benefit of in vivo assays" in body


# --- the parser the duplicate check rests on ---------------------------------------------------


def test_key_lines_counts_an_entry_whose_braces_never_close_and_entries_does_not():
    text = "@misc{closed,\n  title = {x}\n}\n\n@misc{open,\n  title = {y}\n"

    assert [key for key, _line in bibtex.key_lines(text)] == ["closed", "open"]
    assert [line for _key, line in bibtex.key_lines(text)] == [1, 5]
    assert [key for _kind, key, _body in bibtex.entries(text)] == ["closed"]


def test_duplicate_keys_folds_case_and_reports_every_line():
    text = "\n".join(
        ENTRY.format(cite=k, author="A") for k in ("alpha2026one", "beta2026two", "Alpha2026One")
    )

    dups = bibtex.duplicate_keys(text)

    assert list(dups) == ["alpha2026one"]
    assert dups["alpha2026one"] == [
        ("alpha2026one", FIRST_LINES[0]),
        ("Alpha2026One", FIRST_LINES[2]),
    ]


# --- lint --bib --------------------------------------------------------------------------------


def test_lint_bib_names_the_repeated_key_and_every_line_it_sits_on(tmp_path, capsys):
    target = bib(tmp_path, "alpha2026one", "beta2026two", "alpha2026one")

    assert lint.main(["--bib", str(target)]) == 1
    out = capsys.readouterr().out
    assert "alpha2026one" in out
    assert f"lines {FIRST_LINES[0]}, {FIRST_LINES[2]}" in out


def test_lint_bib_exits_zero_when_no_key_repeats(tmp_path):
    # The negative half: a --bib mode hardwired to fail would pass the test above.
    assert lint.main(["--bib", str(bib(tmp_path, "alpha2026one", "beta2026two"))]) == 0


def test_lint_bib_consults_neither_papis_nor_a_library(tmp_path, monkeypatch):
    # The records mode needs both, a bibliography needs neither, and continuous integration
    # usually has neither.
    monkeypatch.setattr(lint, "find_papis", lambda: pytest.fail("--bib must not need papis"))
    monkeypatch.setenv("CITATIONS_HOME", str(tmp_path / "nowhere"))

    assert lint.main(["--bib", str(bib(tmp_path, "alpha2026one"))]) == 0


def test_lint_bib_exits_nonzero_under_json_too(tmp_path, capsys):
    # A machine-readable mode that prints findings and exits 0 is a check that cannot fail.
    target = bib(tmp_path, "alpha2026one", "alpha2026one")

    assert lint.main(["--bib", str(target), "--json"]) == 1

    payload = json.loads(capsys.readouterr().out)
    assert payload[0]["lines"] == [FIRST_LINES[0], FIRST_LINES[1]]
