"""Extracted text kept between runs, and the three ways a kept reading could be the wrong one.

The cache returns text no extractor produced in this run. That is only sound if the entry is
found by what was read and what read it, so the tests change each of those in turn and count
how many times the extractor ran. The extractor is a script named `pdftotext` that prints the
source and adds a line to a tally, so a run that did not happen leaves no line.
"""

from __future__ import annotations

import stat
import unicodedata

import pytest
from citations import extraction_cache
from citations import verify as V
from citations.cli import main
from citations.exceptions import SourceUnreadableError

SCRIPT = """#!/bin/sh
if [ "$1" = "-v" ]; then cat "{version}" >&2; exit 0; fi
echo run >> "{tally}"
source=""; last=""
for argument; do source="$last"; last="$argument"; done
[ "$last" = "-" ] || exit 3
cat "$source"
"""


@pytest.fixture
def extractor(tmp_path, monkeypatch):
    """A stand-in `pdftotext` on PATH. Returns the tally of its runs and its version file."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    tally, version = tmp_path / "tally", tmp_path / "version"
    tally.write_text("")
    version.write_text("pdftotext version 1.0\n")
    script = bin_dir / "pdftotext"
    script.write_text(SCRIPT.format(version=version, tally=tally))
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bin_dir}:/usr/bin:/bin")
    extraction_cache._version.cache_clear()
    yield tally, version
    extraction_cache.use(None)
    extraction_cache._version.cache_clear()


def runs(tally) -> int:
    return len(tally.read_text().splitlines())


def read(source) -> str:
    return V._run(source, ["pdftotext", str(source), "-"])


def source_in(tmp_path, text="The effect was 0.42 in every run.\n"):
    folder = tmp_path / "sources"
    folder.mkdir(exist_ok=True)
    source = folder / "paper.pdf"
    source.write_text(text)
    return source


def test_an_unchanged_source_is_extracted_once(tmp_path, extractor):
    tally, _ = extractor
    source = source_in(tmp_path)
    extraction_cache.use(tmp_path / "cache")

    first, second = read(source), read(source)

    assert first == second == source.read_text()
    assert runs(tally) == 1
    assert extraction_cache.hits() == 1


def test_changed_bytes_are_extracted_again(tmp_path, extractor):
    tally, _ = extractor
    source = source_in(tmp_path)
    extraction_cache.use(tmp_path / "cache")
    read(source)

    # The same length and the same name: only the bytes say the source changed.
    source.write_text("The effect was 0.24 in every run.\n")

    assert read(source) == "The effect was 0.24 in every run.\n"
    assert runs(tally) == 2


def test_a_different_version_of_the_extractor_reads_again(tmp_path, extractor):
    tally, version = extractor
    source = source_in(tmp_path)
    extraction_cache.use(tmp_path / "cache")
    read(source)

    version.write_text("pdftotext version 2.0\n")
    extraction_cache._version.cache_clear()
    read(source)

    assert runs(tally) == 2


def test_different_arguments_read_again(tmp_path, extractor):
    tally, _ = extractor
    source = source_in(tmp_path)
    extraction_cache.use(tmp_path / "cache")

    V._run(source, ["pdftotext", str(source), "-"])
    V._run(source, ["pdftotext", "-layout", str(source), "-"])

    assert runs(tally) == 2


def test_the_same_bytes_under_another_path_are_not_extracted_again(tmp_path, extractor):
    tally, _ = extractor
    source = source_in(tmp_path)
    extraction_cache.use(tmp_path / "cache")
    read(source)
    copy = source.with_name("copy.pdf")
    copy.write_bytes(source.read_bytes())

    assert read(copy) == source.read_text()
    assert runs(tally) == 1


def test_nothing_is_kept_unless_asked_for(tmp_path, extractor):
    tally, _ = extractor
    source = source_in(tmp_path)

    read(source)
    read(source)

    assert runs(tally) == 2
    assert not (tmp_path / "cache").exists()


def test_a_failed_extraction_is_not_kept(tmp_path, extractor):
    tally, _ = extractor
    source = source_in(tmp_path)
    extraction_cache.use(tmp_path / "cache")

    for _ in range(2):
        with pytest.raises(SourceUnreadableError):
            V._run(source, ["pdftotext", str(source)])

    assert runs(tally) == 2


def test_another_program_is_never_kept(tmp_path, extractor):
    source = source_in(tmp_path)
    extraction_cache.use(tmp_path / "cache")

    assert extraction_cache.address("0" * 64, ["cat", str(source)], source) is None


def test_an_entry_that_cannot_be_read_is_extracted_again(tmp_path, extractor):
    tally, _ = extractor
    source = source_in(tmp_path)
    extraction_cache.use(tmp_path / "cache")
    read(source)
    for entry in (tmp_path / "cache").rglob("*.txt"):
        entry.write_bytes(b"\xff\xfe not text")

    assert read(source) == source.read_text()
    assert runs(tally) == 2


def claims_in(tmp_path, source):
    claims = tmp_path / "claims"
    claims.mkdir()
    for name in ("a", "b"):
        (claims / f"{name}.yaml").write_text(
            f"source:\n  citation: {name}\n  local: {source}\n"
            f"claims:\n  c:\n    statement: s\n    quotes:\n    - exact: The effect was 0.42\n"
        )
    return claims


def test_the_command_reads_each_source_once_across_two_runs(
    tmp_path, extractor, monkeypatch, capsys
):
    tally, _ = extractor
    claims = claims_in(tmp_path, source_in(tmp_path))
    monkeypatch.delenv(extraction_cache.DISABLE_ENV)
    monkeypatch.setenv(extraction_cache.DIRECTORY_ENV, str(tmp_path / "cache"))

    assert main(["verify", "--claims", str(claims)]) == 0
    V.clear_caches()
    first = capsys.readouterr().out
    assert main(["verify", "--claims", str(claims)]) == 0
    second = capsys.readouterr().out

    assert runs(tally) == 1
    assert "from the cache" not in first
    assert "1 extraction taken from the cache" in second
    assert [line for line in second.splitlines() if "cache" not in line and line] == [
        line for line in first.splitlines() if line
    ]


def test_no_cache_runs_the_extractor_and_keeps_nothing(tmp_path, extractor, monkeypatch):
    tally, _ = extractor
    claims = claims_in(tmp_path, source_in(tmp_path))
    monkeypatch.delenv(extraction_cache.DISABLE_ENV)
    monkeypatch.setenv(extraction_cache.DIRECTORY_ENV, str(tmp_path / "cache"))

    for _ in range(2):
        assert main(["verify", "--claims", str(claims), "--no-cache"]) == 0
        V.clear_caches()

    assert runs(tally) == 2
    assert not (tmp_path / "cache").exists()


def reference_fold_marks(s: str) -> str:
    """The marks step of `passage_fold` as it was written: one question per character."""
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c))


@pytest.mark.parametrize(
    "text",
    [
        "",
        "plain ascii, nothing to fold",
        "naïve and nai\u0308ve, Krzy\u017cosiak, \ufb01nal \ufb02ow",
        "a\u0301\u0323 stacked marks, \u1e9b\u0323, and \U0001d400 a mathematical bold A",
        "Ελληνικά ά, עִבְרִית, हिन्दी, 한국어, ｆｕｌｌ ｗｉｄｔｈ",
        "".join(chr(point) for point in range(0x80, 0x3000)),
    ],
)
def test_the_marks_are_dropped_as_they_always_were(text):
    V.passage_fold.cache_clear()
    rest = V.passage_fold(reference_fold_marks(text))
    V.passage_fold.cache_clear()
    assert V.passage_fold(text) == rest


def test_siblings_are_the_files_sharing_a_stem(tmp_path):
    names = [
        "paper.pdf",
        "paper.txt",
        "paper",
        "paper.tar.gz",
        "paper2.txt",
        "a.paper.txt",
        ".paper",
        "paper.",
        "PAPER.txt",
    ]
    for name in names:
        (tmp_path / name).write_text("")
    source = tmp_path / "paper.pdf"

    as_written = frozenset(
        q.name for q in tmp_path.iterdir() if q.stem == source.stem and q != source
    )

    assert V._stem_siblings(source) == as_written
    assert "paper.txt" in as_written
