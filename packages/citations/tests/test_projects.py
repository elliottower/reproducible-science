"""A name the registry does not know is not the same as a name nothing answers to.

Ninety records named `evaluation-scope` hours after the repository was renamed, and nothing
reported it, because `cited_by` is a free-text key that no check compared against the projects
that exist. These pin the distinction that makes such a report worth reading: three of the five
unknown names in that library were simply unregistered and entirely fine, and grouping them with
the two that were dead would put false positives beside every real finding.
"""

from __future__ import annotations

import os
import subprocess

import yaml
from citations.projects import Status, rename, survey, uncommitted


def library(tmp_path, papers=None, records=None):
    (tmp_path / "records").mkdir(parents=True, exist_ok=True)
    if papers is not None:
        (tmp_path / "papers.yaml").write_text(yaml.safe_dump({"papers": papers}))
    for name, body in (records or {}).items():
        (tmp_path / "records" / f"{name}.yaml").write_text(yaml.safe_dump(body))
    return tmp_path


def status_of(found, name):
    return next(p.status for p in found.projects if p.name == name)


def test_a_registered_project_whose_paths_are_here_and_which_records_cite_is_active(tmp_path):
    bib = tmp_path / "refs.bib"
    bib.write_text("@misc{x}")
    lib = library(
        tmp_path / "lib",
        papers={"paper": {"bib": str(bib)}},
        records={"r": {"slug": "r", "cited_by": {"paper": {"key": "x"}}}},
    )
    assert status_of(survey(lib), "paper") is Status.ACTIVE


def test_a_registered_project_no_record_cites_is_uncited_not_a_defect(tmp_path):
    bib = tmp_path / "refs.bib"
    bib.write_text("@misc{x}")
    lib = library(tmp_path / "lib", papers={"paper": {"bib": str(bib)}})
    assert status_of(survey(lib), "paper") is Status.UNCITED


def test_a_registered_project_whose_path_is_gone_is_dangling(tmp_path):
    lib = library(tmp_path / "lib", papers={"paper": {"bib": str(tmp_path / "nope.bib")}})
    found = survey(lib)
    assert status_of(found, "paper") is Status.DANGLING
    assert found.projects[0].missing_paths


def test_an_unregistered_project_whose_directory_is_here_is_not_stale(tmp_path):
    """The false positive this exists to avoid. `papers.yaml` is written by hand."""
    (tmp_path / "sibling").mkdir()
    lib = library(
        tmp_path / "lib", papers={}, records={"r": {"slug": "r", "cited_by": {"sibling": {}}}}
    )
    assert status_of(survey(lib, search=tmp_path), "sibling") is Status.UNREGISTERED


def test_an_unregistered_project_nothing_answers_to_is_orphaned(tmp_path):
    lib = library(
        tmp_path / "lib", papers={}, records={"r": {"slug": "r", "cited_by": {"vanished": {}}}}
    )
    assert status_of(survey(lib, search=tmp_path), "vanished") is Status.ORPHANED


def test_only_the_two_that_cannot_be_settled_here_ask_for_a_person(tmp_path):
    (tmp_path / "sibling").mkdir()
    bib = tmp_path / "refs.bib"
    bib.write_text("@misc{x}")
    lib = library(
        tmp_path / "lib",
        papers={"live": {"bib": str(bib)}, "dead": {"bib": str(tmp_path / "nope.bib")}},
        records={
            "a": {"slug": "a", "cited_by": {"live": {}}},
            "b": {"slug": "b", "cited_by": {"sibling": {}}},
            "c": {"slug": "c", "cited_by": {"vanished": {}}},
        },
    )
    assert {p.name for p in survey(lib, search=tmp_path).unresolved} == {"dead", "vanished"}


def test_rename_moves_every_citing_record_and_reports_which(tmp_path):
    lib = library(
        tmp_path / "lib",
        papers={},
        records={
            "a": {"slug": "a", "cited_by": {"old": {"key": "k1"}}},
            "b": {"slug": "b", "cited_by": {"old": {"key": "k2"}}},
            "c": {"slug": "c", "cited_by": {"other": {"key": "k3"}}},
        },
    )
    changed = rename(lib, "old", "new")
    assert sorted(p.stem for p in changed) == ["a", "b"]
    a = yaml.safe_load((lib / "records" / "a.yaml").read_text())
    assert a["cited_by"] == {"new": {"key": "k1"}}
    c = yaml.safe_load((lib / "records" / "c.yaml").read_text())
    assert c["cited_by"] == {"other": {"key": "k3"}}, "an unrelated project is untouched"


def test_rename_does_not_overwrite_an_entry_the_record_already_has(tmp_path):
    lib = library(
        tmp_path / "lib",
        papers={},
        records={"a": {"slug": "a", "cited_by": {"old": {"key": "k1"}, "new": {"key": "keep"}}}},
    )
    rename(lib, "old", "new")
    a = yaml.safe_load((lib / "records" / "a.yaml").read_text())
    assert a["cited_by"] == {"new": {"key": "keep"}}


def test_rename_leaves_every_other_value_as_it_parsed(tmp_path):
    """The re-dump changes quoting; it must not change what anything means."""
    body = {"slug": "a", "year": "2016", "arxiv": "1606.03137", "cited_by": {"old": {}}}
    lib = library(tmp_path / "lib", papers={}, records={"a": body})
    rename(lib, "old", "new")
    after = yaml.safe_load((lib / "records" / "a.yaml").read_text())
    assert after["year"] == "2016" and after["arxiv"] == "1606.03137"


def test_a_library_that_is_not_a_repository_reports_nothing_uncommitted(tmp_path):
    assert uncommitted(library(tmp_path / "lib")) == 0


def test_an_uncommitted_record_is_counted(tmp_path):
    lib = library(tmp_path / "lib", records={"a": {"slug": "a"}})
    # A clean environment, because a hook sets `GIT_DIR` and it outranks the path given to
    # `git init` -- the repository then lands somewhere else and this reads a directory that is
    # not one. `gitref` neutralises that for its own queries; creating a repository here has to
    # do the same. Found by the pre-push hook, where the test ran inside exactly that.
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    subprocess.run(["git", "init", "-q", str(lib)], check=True, env=env)
    assert (lib / ".git").exists(), "the repository has to be where the library is"
    assert uncommitted(lib) >= 1


def test_every_status_is_reachable(tmp_path):
    """A status nothing can produce is worse than no status: it is documentation that lies.

    All five from one library, so the schema and the survey cannot drift apart.
    """
    (tmp_path / "sibling").mkdir()
    bib = tmp_path / "refs.bib"
    bib.write_text("@misc{x}")
    lib = library(
        tmp_path / "lib",
        papers={
            "active": {"bib": str(bib)},
            "uncited": {"bib": str(bib)},
            "dangling": {"bib": str(tmp_path / "gone.bib")},
        },
        records={
            "a": {"slug": "a", "cited_by": {"active": {}}},
            "b": {"slug": "b", "cited_by": {"dangling": {}}},
            "c": {"slug": "c", "cited_by": {"sibling": {}}},
            "d": {"slug": "d", "cited_by": {"vanished": {}}},
        },
    )
    assert {p.status for p in survey(lib, search=tmp_path).projects} == set(Status)


def test_the_statuses_are_distinct_lowercase_names():
    values = [s.value for s in Status]
    assert len(set(values)) == len(values)
    assert all(v.islower() and " " not in v for v in values)
