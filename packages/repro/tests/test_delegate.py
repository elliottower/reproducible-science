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


def test_a_data_directory_with_nothing_in_it_is_not_evidence_of_use(tmp_path):
    """An empty `preregistrations/` was read as "this project preregisters", and `prereg
    check` then failed it for having no plan -- the detector inventing the failure."""
    (tmp_path / "preregistrations").mkdir()
    assert not BY_NAME["prereg"].used_by(tmp_path)
    (tmp_path / "preregistrations" / "PREREG.md").write_text("# plan\n")
    assert BY_NAME["prereg"].used_by(tmp_path)


def test_claims_are_found_below_the_root_where_papers_actually_keep_them(tmp_path):
    """This library's own registry points at `paper/prior_art/claims`. A root-only search
    told a project with 61 pinned quotations that no tool applied to it."""
    nested = tmp_path / "paper" / "prior_art" / "claims"
    nested.mkdir(parents=True)
    (nested / "a.yaml").write_text("source: {}\n")
    assert BY_NAME["citations"].used_by(tmp_path)
    assert BY_NAME["citations"].data_dir(tmp_path) == nested


def test_the_check_is_told_where_the_claims_are(tmp_path):
    """`citations verify` reports "nothing to check" and exits 2 when given no claims
    directory, so running it without one turned every citations project into a failure."""
    claims = tmp_path / "claims"
    claims.mkdir()
    (claims / "a.yaml").write_text("source: {}\n")
    argv = BY_NAME["citations"].argv_for(tmp_path)
    assert argv == ("verify", "--claims", str(claims))


def test_a_tool_that_must_be_pointed_somewhere_is_unused_when_there_is_nowhere(tmp_path):
    """A library with no claims is not a project whose quotations failed. It is one with
    none, and running the check against it manufactures an exit 2."""
    (tmp_path / ".citations").mkdir()
    assert not BY_NAME["citations"].used_by(tmp_path)
    assert BY_NAME["citations"].argv_for(tmp_path) == ("verify",)


def test_a_data_directory_is_not_looked_for_inside_a_virtualenv(tmp_path):
    buried = tmp_path / ".venv" / "lib" / "claims"
    buried.mkdir(parents=True)
    (buried / "a.yaml").write_text("source: {}\n")
    assert not BY_NAME["citations"].used_by(tmp_path)
