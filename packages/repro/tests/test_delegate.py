"""`repro <tool>` is a spelling of the tool; `repro check` is the thing that is not.

The risk in an umbrella is that it reports on work it did not do. These pin the two ways that
could happen: a tool the project does not use being counted as passing, and a tool being run
against a directory other than the one named.
"""

from __future__ import annotations

import pathlib

import pytest
from repro.delegate import BY_NAME, TOOLS, check, run


def test_every_tool_is_reachable_and_takes_argv():
    """All four commands share one signature, which is what lets one call another."""
    for tool in TOOLS:
        entry = tool.entry()
        assert callable(entry)
        assert run(tool, ["--help"]) == 0, tool.name


def test_a_tool_the_project_does_not_use_is_not_reported_as_passing(tmp_path):
    outcomes = {o.tool: o for o in check(tmp_path)}
    assert set(outcomes) == set(BY_NAME)
    for name, o in outcomes.items():
        assert not o.used, name
        assert o.code is None, f"{name} was not run, so it has no exit code to report"
        assert "not used" in o.line


def test_a_project_using_no_tool_is_not_a_pass(tmp_path):
    """Nothing ran, so there is nothing to call clean."""
    assert all(not o.used for o in check(tmp_path))


def test_detection_reads_the_state_directory_not_a_data_directory(tmp_path):
    """`results/` is committed data in this project's convention; `.results/` is the tool's.

    Matching the former reported a demo project as using `results`, then failed it for having
    no `.results/` -- a failure the detector invented.
    """
    (tmp_path / "results").mkdir()
    assert not BY_NAME["results"].used_by(tmp_path)
    (tmp_path / ".results").mkdir()
    assert BY_NAME["results"].used_by(tmp_path)


def test_a_tool_runs_in_the_named_project_not_the_working_directory(tmp_path, monkeypatch):
    """Each tool resolves its configuration from the working directory.

    Without a chdir, `repro check <dir>` ran the tools against whatever directory the shell
    was in and reported the answer as if it were about `<dir>`.
    """
    project = tmp_path / "project"
    (project / ".results").mkdir(parents=True)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    outcome = next(o for o in check(project) if o.tool == "results")
    assert outcome.used
    assert str(project) in outcome.output or outcome.code == 0, outcome.output


@pytest.mark.parametrize("name", sorted(BY_NAME))
def test_each_tool_declares_a_summary_and_a_check(name):
    tool = BY_NAME[name]
    assert tool.summary and not tool.summary.endswith(".")
    assert tool.check_argv
    assert all(not m.endswith("/") for m in tool.markers)


def test_markers_are_relative_names(tmp_path):
    for tool in TOOLS:
        for m in tool.markers:
            assert not pathlib.Path(m).is_absolute()
