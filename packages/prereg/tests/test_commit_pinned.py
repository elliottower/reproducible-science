"""A registration frozen by a commit line is only checked if `check` finds it and reads history."""

from __future__ import annotations

import subprocess

import pytest
from prereg import cli
from provenance_core.gitref import clean_env

PLAN = """\
# Does the rule hold?

**Status:** FROZEN (pending commit SHA)
**Parent document:** OTHER.md (commit SHA: 0123abc)

**Commit SHA:** _pending_

## Hypotheses

**H1.** The effect exceeds 0.10 in every family.

## Deviations

Append only.

```
2026-07-06  drafted                      nothing run
```
"""

NO_PLAN = "no PREREG.md here, above, or below.\n"


def git(repo, *args) -> str:
    # `clean_env` for the reason `test_freeze._run` gives: an inherited `GIT_INDEX_FILE` would
    # send these commits into the repository running the suite.
    done = subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
        cwd=repo,
        env=clean_env(),
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout.strip()


def commit(repo, message="commit") -> str:
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)
    return git(repo, "rev-parse", "HEAD")


def freeze(repo, name="PREREGISTRATION.md", text=PLAN, placeholder="_pending_") -> str:
    """Commit the document, then record that commit in it in the commit that follows."""
    doc = repo / name
    doc.write_text(text)
    sha = commit(repo, "register")
    doc.write_text(text.replace(placeholder, sha[:7]))
    commit(repo, "record the freeze commit")
    return sha


@pytest.fixture
def repo(tmp_path, monkeypatch):
    git(tmp_path, "init", "-q")
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def check(capsys):
    def run() -> tuple[int, str]:
        code = cli.main(["check"])
        return code, capsys.readouterr().out

    return run


def test_a_document_equal_to_its_commit_but_for_the_commit_line_is_unchanged(repo, check):
    sha = freeze(repo)
    code, out = check()
    assert code == 0
    assert f"unchanged    PREREGISTRATION.md  at {sha[:7]}" in out
    assert "1 commit-pinned: 1 unchanged, 0 appended, 0 changed, 0 pending, 0 unknown commit" in out


def test_editing_one_word_of_the_frozen_text_is_a_finding(repo, check):
    freeze(repo)
    doc = repo / "PREREGISTRATION.md"
    doc.write_text(doc.read_text().replace("exceeds 0.10", "exceeds 0.05"))
    code, out = check()
    assert code == 1
    assert "CHANGED      PREREGISTRATION.md" in out
    assert "1 line added, 1 removed" in out
    assert "first difference at line 10:" in out
    assert "- **H1.** The effect exceeds 0.10 in every family." in out
    assert "+ **H1.** The effect exceeds 0.05 in every family." in out


def test_removing_frozen_text_is_a_finding(repo, check):
    freeze(repo)
    doc = repo / "PREREGISTRATION.md"
    doc.write_text(
        doc.read_text().replace("**H1.** The effect exceeds 0.10 in every family.\n", "")
    )
    code, out = check()
    assert code == 1
    assert "0 lines added, 1 removed" in out


def test_lines_added_to_the_log_are_appended_and_counted(repo, check):
    freeze(repo)
    doc = repo / "PREREGISTRATION.md"
    entries = "2026-07-07  ran                          results not opened\n2026-07-08  H1 held\n"
    doc.write_text(doc.read_text().removesuffix("```\n") + entries + "```\n")
    code, out = check()
    assert code == 0
    assert "appended     PREREGISTRATION.md" in out
    assert "2 lines added after the frozen text" in out

    doc.write_text(doc.read_text() + "\n## Amendment\n\nOne more family.\n")
    code, out = check()
    assert code == 1, "text added below a log that also grew is not one appended block"
    doc.write_text(doc.read_text().replace(entries, ""))
    code, out = check()
    assert code == 0
    assert "4 lines added after the frozen text" in out


def test_a_line_inserted_above_the_end_is_not_appended(repo, check):
    freeze(repo)
    doc = repo / "PREREGISTRATION.md"
    doc.write_text(doc.read_text().replace("## Deviations", "**H2.** Also 0.05.\n\n## Deviations"))
    code, out = check()
    assert code == 1
    assert "2 lines added, 0 removed" in out


def test_a_commit_under_its_own_heading_is_read_from_the_next_line(repo, check):
    text = "# Protocol\n\nS1 is the primary analysis.\n\n## Commit SHA\n\n**[TO BE FILLED AFTER COMMIT]**\n"
    doc = repo / "ANALYSIS_PROTOCOL.md"
    doc.write_text(text)
    sha = commit(repo)
    doc.write_text(text.replace("**[TO BE FILLED AFTER COMMIT]**", f"**{sha}**"))
    commit(repo)
    code, out = check()
    assert code == 0
    assert f"unchanged    ANALYSIS_PROTOCOL.md  at {sha}" in out

    doc.write_text(doc.read_text().replace("primary", "secondary"))
    assert check()[0] == 1


def test_a_placeholder_is_pending_and_not_a_pass(repo, check):
    (repo / "PREREGISTRATION.md").write_text(PLAN)
    commit(repo)
    code, out = check()
    assert code == 2
    assert "pending      PREREGISTRATION.md" in out
    assert "the commit line names no commit: _pending_" in out
    assert "0 unchanged, 0 appended, 0 changed, 1 pending" in out


def test_a_commit_the_repository_does_not_hold_is_unknown_not_changed(repo, check):
    (repo / "PREREGISTRATION.md").write_text(PLAN.replace("_pending_", "`0123abc`"))
    commit(repo)
    code, out = check()
    assert code == 2
    assert "unknown commit PREREGISTRATION.md  at 0123abc" in out
    assert "0123abc is not a commit in this repository" in out
    assert "CHANGED" not in out
    assert "0 changed, 0 pending, 1 unknown commit" in out


def test_a_commit_that_predates_the_document_is_unknown_not_changed(repo, check):
    (repo / "README.md").write_text("# study\n")
    before = commit(repo)
    (repo / "PREREGISTRATION.md").write_text(PLAN.replace("_pending_", before))
    commit(repo)
    code, out = check()
    assert code == 2
    assert f"PREREGISTRATION.md is not in commit {before}" in out
    assert "CHANGED" not in out


def test_one_changed_document_fails_a_check_that_others_pass(repo, check):
    freeze(repo, "A.md")
    (repo / "sub").mkdir()
    freeze(repo, "sub/B.md")
    b = repo / "sub" / "B.md"
    b.write_text(b.read_text().replace("every family", "most families"))
    code, out = check()
    assert code == 1
    assert "unchanged    A.md" in out
    assert "CHANGED      sub/B.md" in out
    assert "2 commit-pinned: 1 unchanged, 0 appended, 1 changed" in out


def test_a_repository_with_no_registration_exits_as_before(repo, check):
    (repo / "README.md").write_text("# study\n\nNothing registered.\n")
    commit(repo)
    assert check() == (2, NO_PLAN)


def test_a_mention_of_a_commit_is_not_a_registration(repo, check):
    (repo / "NOTES.md").write_text(
        "# Notes\n\n"
        "**Parent document:** PREREGISTRATION.md (commit SHA: 0123abc)\n"
        "The registration was frozen at commit `0123abc`.\n"
        "Commit SHA of this file serves as the timestamp.\n\n"
        "```\n**Commit SHA:** 0123abc\n```\n"
    )
    commit(repo)
    assert check() == (2, NO_PLAN)


def test_a_directory_outside_any_repository_exits_as_before(tmp_path, monkeypatch, check):
    (tmp_path / "PREREGISTRATION.md").write_text(PLAN)
    monkeypatch.chdir(tmp_path)
    assert check() == (2, NO_PLAN)


def test_commit_pinned_documents_are_listed_apart_from_frozen_plans(repo, check):
    cli.main(["new", "study"])
    commit(repo)
    freeze(repo)
    code, out = check()
    plans, _, documents = out.partition("registrations frozen by a commit line:")
    assert "not frozen" in plans and "PREREG.md" in plans
    assert "unchanged    PREREGISTRATION.md" in documents
    assert "1 plans: 0 unchanged, 0 changed, 1 not frozen" in plans
    assert code == 1, "an unfrozen plan fails a root check, whatever the documents beside it say"


STATUS_NOTE = "the status line was updated after the freeze"


def test_updating_the_header_status_line_after_the_freeze_is_reported_and_not_an_edit(repo, check):
    sha = freeze(repo)
    doc = repo / "PREREGISTRATION.md"
    doc.write_text(doc.read_text().replace("FROZEN (pending commit SHA)", f"FROZEN at `{sha[:7]}`"))
    code, out = check()
    assert code == 0
    assert "unchanged    PREREGISTRATION.md" in out
    assert STATUS_NOTE in out
    assert "CHANGED" not in out


def test_an_untouched_status_line_is_not_reported_as_updated(repo, check):
    freeze(repo)
    assert STATUS_NOTE not in check()[1]


def test_a_status_update_does_not_cover_an_edit_to_the_frozen_text(repo, check):
    freeze(repo)
    doc = repo / "PREREGISTRATION.md"
    doc.write_text(
        doc.read_text()
        .replace("FROZEN (pending commit SHA)", "FROZEN")
        .replace("exceeds 0.10", "exceeds 0.05")
    )
    code, out = check()
    assert code == 1
    assert "CHANGED      PREREGISTRATION.md" in out
    assert "1 line added, 1 removed" in out
    assert "first difference at line 10:" in out
    assert STATUS_NOTE in out


def test_a_status_line_in_the_body_is_frozen_text(repo, check):
    body_status = "**Status:** H1 is confirmatory.\n"
    freeze(repo, text=PLAN.replace("## Deviations", body_status + "\n## Deviations"))
    assert check()[0] == 0
    doc = repo / "PREREGISTRATION.md"
    doc.write_text(doc.read_text().replace("H1 is confirmatory", "H1 is exploratory"))
    code, out = check()
    assert code == 1
    assert "- **Status:** H1 is confirmatory." in out
    assert STATUS_NOTE not in out


def test_another_header_key_is_frozen_text(repo, check):
    dated = PLAN.replace("**Parent document:**", "**Date:** 2026-07-06\n**Parent document:**")
    freeze(repo, text=dated)
    assert check()[0] == 0
    doc = repo / "PREREGISTRATION.md"
    doc.write_text(doc.read_text().replace("**Date:** 2026-07-06", "**Date:** 2026-07-09"))
    code, out = check()
    assert code == 1
    assert "- **Date:** 2026-07-06" in out
