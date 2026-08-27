"""A source whose text does not come out of `pdftotext` declares the command that produces it.

That command runs on the machine doing the checking, so what is allowed to run, and what the
report says when nothing did, are as much the subject here as whether the passage resolved.
"""

from __future__ import annotations

import pathlib
import re
import subprocess

import pytest
from citations import cli
from citations import verify as V

PASSAGE = "the measured angle matches the Haar expectation for this ensemble of factors"

MANUSCRIPT = (
    r"\documentclass{article}"
    "\n"
    r"\begin{document}"
    "\n"
    r"We report that \textbf{" + PASSAGE + r"}\REVIEW{check this against Table 2}."
    "\n"
    r"\end{document}"
    "\n"
)


@pytest.fixture(autouse=True)
def _no_cache():
    for cached in (V.extract, V.fold, V.skeleton, V._digest):
        cached.cache_clear()


@pytest.fixture
def renderer(tmp_path):
    def make(name: str, body: str) -> pathlib.Path:
        script = tmp_path / name
        script.write_text(f"#!/bin/sh\n{body}\n")
        script.chmod(0o755)
        return script

    return make


@pytest.fixture
def manuscript(tmp_path):
    source = tmp_path / "manuscript.tex"
    source.write_text(MANUSCRIPT)
    return source


def printing(passage: str = PASSAGE) -> str:
    return f"printf '%s\\n' {passage!r}"


# --- a declared renderer is the text quotations resolve against -------------------------------


def test_a_declared_command_supplies_the_text_the_quotation_resolves_against(manuscript, renderer):
    script = renderer("render", printing())
    result = V.check_one(PASSAGE, manuscript, None, str(script), frozenset({str(script)}))
    assert result.state == "found"


def test_the_same_source_without_a_declared_command_reaches_no_verdict(manuscript, monkeypatch):
    def pdf_reader_on_a_tex(*a, **kw):
        return subprocess.CompletedProcess(a[0], 1, "", "Syntax Error: Couldn't read xref table\n")

    monkeypatch.setattr(V.subprocess, "run", pdf_reader_on_a_tex)
    result = V.check_one(PASSAGE, manuscript)
    assert result.state == "unchecked"
    assert ".tex" in result.detail and "extract_cmd" in result.detail


def test_a_declared_command_takes_precedence_over_reading_a_text_file_directly(tmp_path, renderer):
    notes = tmp_path / "notes.md"
    notes.write_text(PASSAGE.replace("angle", "**angle**"))
    script = renderer("render", printing())
    assert V.check_one(PASSAGE, notes).state == "not found"
    assert V.check_one(PASSAGE, notes, None, str(script), frozenset({str(script)})).state == "found"


def test_a_page_claim_does_not_send_a_pdf_reader_at_a_declared_source(manuscript, renderer):
    # `_on_page` would run `pdftotext` over the .tex, fail, and warn that the passage is not on
    # the page the record claims -- a page finding manufactured out of the wrong extractor.
    script = renderer("render", printing())
    result = V.check_one(PASSAGE, manuscript, 3, str(script), frozenset({str(script)}))
    assert result.state == "found"
    assert "page" not in result.warnings


# --- nothing that goes wrong with a command makes the passage absent ---------------------------


def test_a_command_that_is_not_installed_is_unchecked_rather_than_absent(manuscript):
    missing = "no-such-renderer-4d91b2"
    result = V.check_one(PASSAGE, manuscript, None, missing, frozenset({missing}))
    assert result.state == "unchecked", "an uninstalled renderer says nothing about the paper"
    assert "not on PATH" in result.detail


def test_a_command_outside_the_allowlist_is_refused_and_never_runs(
    manuscript, renderer, monkeypatch
):
    def never(*a, **kw):
        raise AssertionError("a refused command must not reach subprocess")

    monkeypatch.setattr(V.subprocess, "run", never)
    script = renderer("render", printing())
    result = V.check_one(PASSAGE, manuscript, None, str(script))
    assert result.state == "unchecked"
    assert "does not allow" in result.detail


def test_a_refusal_and_a_missing_program_send_the_reader_to_different_remedies(manuscript):
    missing = "no-such-renderer-4d91b2"
    refused = V.check_one(PASSAGE, manuscript, None, "pandoc")
    absent = V.check_one(PASSAGE, manuscript, None, missing, frozenset({missing}))
    assert refused.state == absent.state == "unchecked"
    assert "--allow-extractor" in refused.detail
    assert "--allow-extractor" not in absent.detail and "PATH" in absent.detail


def test_a_command_that_exits_nonzero_is_unchecked(manuscript, renderer):
    script = renderer("render", "echo 'no such macro package' >&2\nexit 3")
    result = V.check_one(PASSAGE, manuscript, None, str(script), frozenset({str(script)}))
    assert result.state == "unchecked"
    assert "exited 3" in result.detail and "no such macro package" in result.detail


def test_a_command_that_prints_nothing_is_unchecked(manuscript, renderer):
    script = renderer("render", "exit 0")
    result = V.check_one(PASSAGE, manuscript, None, str(script), frozenset({str(script)}))
    assert result.state == "unchecked"
    # The command succeeding and printing nothing is a fact about the command. It read
    # `no text extracted`, which is what a document holding no text also reads, and the two
    # are the distinction this module exists to keep apart.
    assert "printed nothing" in result.detail


def test_a_command_that_times_out_is_unchecked(manuscript, monkeypatch):
    def hangs(*a, **kw):
        raise subprocess.TimeoutExpired(a[0], V.EXTRACT_TIMEOUT)

    monkeypatch.setattr(V.subprocess, "run", hangs)
    result = V.check_one(PASSAGE, manuscript, None, "detex")
    assert result.state == "unchecked"
    assert "timed out" in result.detail


def test_a_command_that_will_not_parse_is_unchecked(manuscript):
    result = V.check_one(PASSAGE, manuscript, None, 'detex "unclosed', frozenset({"detex"}))
    assert result.state == "unchecked"
    assert "will not parse" in result.detail


# --- the command is argv, never a shell string -------------------------------------------------


def test_shell_operators_reach_the_program_as_arguments(manuscript, renderer, tmp_path):
    seen = tmp_path / "argv.txt"
    sentinel = tmp_path / "executed"
    script = renderer("render", f"printf '%s\\n' \"$@\" > {seen}\n{printing()}")
    declared = f"{script} ; touch {sentinel}"

    result = V.check_one(PASSAGE, manuscript, None, declared, frozenset({str(script)}))

    assert result.state == "found"
    assert not sentinel.exists(), "a shell would have run the second command"
    assert ";" in seen.read_text().splitlines(), "the operator arrived as one argument"


def test_the_source_path_replaces_the_placeholder(manuscript, renderer, tmp_path):
    seen = tmp_path / "argv.txt"
    script = renderer("render", f"printf '%s\\n' \"$@\" > {seen}\n{printing()}")
    declared = f"{script} --from {{}} --to plain"

    V.check_one(PASSAGE, manuscript, None, declared, frozenset({str(script)}))

    assert seen.read_text().splitlines() == ["--from", str(manuscript), "--to", "plain"]


def test_the_source_path_is_appended_when_no_placeholder_says_where(manuscript, renderer, tmp_path):
    seen = tmp_path / "argv.txt"
    script = renderer("render", f"printf '%s\\n' \"$@\" > {seen}\n{printing()}")

    V.check_one(PASSAGE, manuscript, None, f"{script} -n", frozenset({str(script)}))

    assert seen.read_text().splitlines() == ["-n", str(manuscript)]


# --- what the record says about the extraction -------------------------------------------------


def test_a_result_names_what_produced_the_text(tmp_path, manuscript, renderer):
    script = renderer("render", printing())
    declared = V.check_one(PASSAGE, manuscript, None, str(script), frozenset({str(script)}))
    assert declared.extractor == str(script)

    notes = tmp_path / "notes.txt"
    notes.write_text(PASSAGE)
    assert V.check_one(PASSAGE, notes).extractor == V.PLAIN_TEXT


def test_the_default_extractor_is_named_as_explicitly_as_a_declared_one(tmp_path, monkeypatch):
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    monkeypatch.setattr(
        V.subprocess, "run", lambda *a, **kw: subprocess.CompletedProcess(a[0], 0, PASSAGE, "")
    )
    assert V.check_one(PASSAGE, pdf).extractor == V.DEFAULT_EXTRACTOR


def test_two_renderers_over_one_source_leave_one_pin_and_two_digests(manuscript, renderer):
    plain = renderer("plain", printing())
    spaced = renderer("spaced", printing(PASSAGE.replace(" ", "  ")))
    pin = V.sha256(manuscript)

    first = V.check_one(PASSAGE, manuscript, None, str(plain), frozenset({str(plain)}))
    second = V.check_one(PASSAGE, manuscript, None, str(spaced), frozenset({str(spaced)}))

    assert V.check_pin(manuscript, pin).state == "ok", "the bytes did not move"
    assert first.state == second.state == "found"
    assert first.extraction_digest != second.extraction_digest, "the reading of them did"


def test_a_result_that_read_nothing_names_no_extractor(manuscript):
    result = V.check_one(PASSAGE, manuscript, None, "pandoc")
    assert result.extractor == "" and result.extraction_digest == ""


# --- through the command ------------------------------------------------------------------------


def paper(tmp_path, extract_cmd: str) -> pathlib.Path:
    (tmp_path / "reference").mkdir()
    source = tmp_path / "reference" / "manuscript.tex"
    source.write_text(MANUSCRIPT)
    claims = tmp_path / "claims"
    claims.mkdir()
    (claims / "manuscript.yaml").write_text(
        "source:\n"
        "  local: reference/manuscript.tex\n"
        f"  sha256: {V.sha256(source)}\n"
        f"  extract_cmd: {extract_cmd}\n"
        "claims:\n"
        "  angles:\n"
        "    statement: The cores are close to orthogonal.\n"
        "    quotes:\n"
        f"      - exact: {PASSAGE}\n"
    )
    return claims


def test_the_report_says_which_extractor_the_verdicts_rest_on(tmp_path, renderer, capsys):
    script = renderer("render", printing())
    claims = paper(tmp_path, str(script))

    code = cli.main(
        ["verify", "--claims", str(claims), "--strict", "--allow-extractor", str(script)]
    )

    out = capsys.readouterr().out
    assert code == 0
    assert "read by" in out and str(script) in out
    assert "found" in out


def test_the_same_run_without_consent_establishes_nothing_and_strict_says_so(
    tmp_path, renderer, capsys
):
    script = renderer("render", printing())
    claims = paper(tmp_path, str(script))

    code = cli.main(["verify", "--claims", str(claims), "--strict"])

    out = capsys.readouterr().out
    assert code == 1
    assert "unchecked" in out and "does not allow" in out
    # Matched loosely on the padding: the outcome column widens when an outcome is added, and
    # what this pins is the count beside the label, not the spacing between them.
    assert re.search(r"not found\s+0\b", out), "a refused command is not a passage that is absent"


# -- "no extractor" is a declaration, not a program named none -----------------------------------


@pytest.mark.parametrize(
    "declared",
    [
        "none",
        "None",
        " none ",
        "NONE",
        "",
        "none — Markdown is read directly",
        "none -- read directly",
    ],
)
def test_a_source_declaring_no_extractor_is_read_off_disk(declared, tmp_path):
    # `paperclip.source_block` writes `none` for a pinned text artifact, because naming an
    # extractor would claim a step that never ran. `_argv` read it as a program called `none`
    # and refused it, so every source the resolver wrote came back `unchecked`.
    src = tmp_path / "s.txt"
    src.write_text("the model performs well on every held-out split\n")
    V.clear_caches()
    assert V.declared_extractor(declared) is None
    got = V.check_one("performs well on every held-out split", src, extract_cmd=declared)
    assert got.state == "found"
    assert got.extractor == V.PLAIN_TEXT


def test_a_real_command_is_still_declared(tmp_path):
    assert V.declared_extractor("pdftotext -layout") == "pdftotext -layout"
    assert V.declared_extractor(None) is None


def test_a_command_that_merely_starts_with_the_letters_none_is_still_a_command():
    # Matched on the first word, not a prefix: `nonesuch` is a program.
    assert V.declared_extractor("nonesuch --render") == "nonesuch --render"


def test_a_source_declaring_no_extractor_names_no_program_in_the_report(tmp_path):
    # The point of writing `none` is that the report should not claim an extractor ran.
    src = tmp_path / "s.txt"
    src.write_text("the model performs well on every held-out split\n")
    V.clear_caches()
    got = V.check_one("performs well on every held-out split", src, extract_cmd="none")
    assert "none" not in got.extractor


# -- an extractor reads; one that writes has damaged what the pin names ---------------------------


def test_an_extractor_that_overwrites_its_own_source_is_reported(tmp_path):
    # This happened: a renderer whose output filename matched its input was declared on the
    # artifact it had already produced, and it overwrote the bytes the pin names. The pin then
    # failed against a file the checker itself had damaged, and version control recovered it.
    src = tmp_path / "s.txt"
    src.write_text("the model performs well on every held-out split\n")
    writer = tmp_path / "clobber.py"
    writer.write_text(
        "#!/usr/bin/env python3\n"
        "import pathlib, sys\n"
        "pathlib.Path(sys.argv[1]).write_text('something else entirely\\n')\n"
        "print('rendered')\n"
    )
    writer.chmod(0o755)
    V.clear_caches()
    got = V.check_one(
        "performs well",
        src,
        extract_cmd=f"{writer} {{}}",
        allowed=frozenset({str(writer)}),
    )
    assert got.state == "unchecked"
    assert "modified the artifact" in got.detail


def test_an_extractor_that_only_reads_is_not_reported_as_writing(tmp_path):
    # The other half: a check that fires on every extractor would be turned off.
    src = tmp_path / "s.txt"
    src.write_text("the model performs well on every held-out split\n")
    reader = tmp_path / "cat.py"
    reader.write_text(
        "#!/usr/bin/env python3\nimport pathlib, sys\nprint(pathlib.Path(sys.argv[1]).read_text())\n"
    )
    reader.chmod(0o755)
    V.clear_caches()
    got = V.check_one(
        "performs well", src, extract_cmd=f"{reader} {{}}", allowed=frozenset({str(reader)})
    )
    assert got.state == "found", got.detail


# -- a command that printed nothing is not a document with no text --------------------------------


def test_a_declared_command_that_prints_nothing_says_so(tmp_path):
    src = tmp_path / "s.txt"
    src.write_text("some text\n")
    silent = tmp_path / "silent.py"
    silent.write_text("#!/usr/bin/env python3\n")
    silent.chmod(0o755)
    V.clear_caches()
    got = V.check_one(
        "some text", src, extract_cmd=f"{silent} {{}}", allowed=frozenset({str(silent)})
    )
    assert got.state == "unchecked"
    assert "printed nothing" in got.detail
    assert "no text extracted" not in got.detail


def test_pdftotext_without_a_trailing_dash_is_told_what_is_wrong(tmp_path, monkeypatch):
    # `pdftotext FILE` writes FILE.txt and prints nothing. Ten sources in one claim set were
    # declared that way and every passage read `no text extracted`, which is what a document
    # with no text also reads. Driven through a stub rather than a real PDF: the point is
    # which message an empty stdout produces, not whether poppler can open a fixture.
    pdf = tmp_path / "s.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")

    def silent(argv, **kw):
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(V.subprocess, "run", silent)
    V.clear_caches()
    got = V.check_one("anything at all here", pdf, extract_cmd="pdftotext -layout")
    assert got.state == "unchecked"
    assert "pdftotext -layout {} -" in got.detail


def test_pdftotext_given_the_dash_is_not_lectured_about_it(tmp_path, monkeypatch):
    pdf = tmp_path / "s.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")

    def silent(argv, **kw):
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(V.subprocess, "run", silent)
    V.clear_caches()
    got = V.check_one("anything at all here", pdf, extract_cmd="pdftotext -layout {} -")
    assert got.state == "unchecked"
    assert "printed nothing" in got.detail
    assert "unless the last argument" not in got.detail
