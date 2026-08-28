"""The hint speaks only where it is a fact, and only once. These pin every bound.

A tool printing advertising is worse for it, and one printing into a CI log is worse still, so
each condition below is a way the note could become noise.
"""

from __future__ import annotations

import io
import pathlib

import pytest

from provenance_core import hint


class Tty(io.StringIO):
    def isatty(self) -> bool:
        return True


@pytest.fixture(autouse=True)
def _cache(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.delenv(hint.OFF, raising=False)


def test_a_project_using_only_this_tool_is_told_nothing(tmp_path):
    (tmp_path / ".citations").mkdir()
    assert hint.note("citations", tmp_path, Tty()) is None


def test_a_project_using_another_tool_is_told_once(tmp_path):
    (tmp_path / ".citations").mkdir()
    (tmp_path / ".prereg").mkdir()
    stream = Tty()
    said = hint.note("citations", tmp_path, stream)
    assert said and "prereg" in said
    assert hint.note("citations", tmp_path, Tty()) is None, (
        "it should speak once, not always"
    )


def test_a_second_project_is_still_told(tmp_path):
    for name in ("one", "two"):
        p = tmp_path / name
        (p / ".citations").mkdir(parents=True)
        (p / ".prereg").mkdir()
        assert hint.note("citations", p, Tty()) is not None, name


def test_nothing_is_printed_when_the_stream_is_not_a_terminal(tmp_path):
    (tmp_path / ".citations").mkdir()
    (tmp_path / ".prereg").mkdir()
    assert hint.note("citations", tmp_path, io.StringIO()) is None


def test_the_environment_variable_silences_it(tmp_path, monkeypatch):
    (tmp_path / ".citations").mkdir()
    (tmp_path / ".prereg").mkdir()
    monkeypatch.setenv(hint.OFF, "1")
    assert hint.note("citations", tmp_path, Tty()) is None


def test_a_data_directory_is_not_mistaken_for_a_tool(tmp_path):
    """`results/` is committed data in this project's convention; `.results/` is the state."""
    (tmp_path / ".citations").mkdir()
    (tmp_path / "results").mkdir()
    assert hint.note("citations", tmp_path, Tty()) is None


def test_an_unwritable_cache_costs_silence_not_a_failure(tmp_path, monkeypatch):
    (tmp_path / ".citations").mkdir()
    (tmp_path / ".prereg").mkdir()
    monkeypatch.setattr(
        pathlib.Path, "mkdir", lambda *a, **k: (_ for _ in ()).throw(OSError())
    )
    assert hint.note("citations", tmp_path, Tty()) is None


def test_it_names_every_other_tool_in_use(tmp_path):
    for m in (".citations", ".prereg", ".results"):
        (tmp_path / m).mkdir()
    said = hint.note("citations", tmp_path, Tty())
    assert (
        said
        and "prereg" in said
        and "results" in said
        and "citations" not in said.split(".")[0]
    )
