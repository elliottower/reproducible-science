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


def draft(
    repo, successor="PREREGISTRATION.md", name="PREREGISTRATION_predraft.md", key="Superseded by"
):
    """A registration that was never frozen and says in its header what became of it."""
    text = PLAN.replace("**Commit SHA:**", f"**{key}:** {successor}\n\n**Commit SHA:**")
    path = repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    commit(repo, "keep the draft")
    return path


def test_a_draft_naming_the_frozen_registration_that_replaced_it_is_superseded(repo, check):
    sha = freeze(repo)
    draft(repo)
    code, out = check()
    assert code == 0
    assert "superseded   PREREGISTRATION_predraft.md" in out
    assert f"superseded by PREREGISTRATION.md, which is unchanged at {sha[:7]}" in out
    assert (
        "2 commit-pinned: 1 unchanged, 0 appended, 0 changed, 0 pending, 0 unknown commit, "
        "1 superseded"
    ) in out


def test_an_edit_to_the_successor_is_still_a_finding_when_a_draft_points_at_it(repo, check):
    freeze(repo)
    draft(repo)
    doc = repo / "PREREGISTRATION.md"
    doc.write_text(doc.read_text().replace("0.10", "0.05"))
    code, out = check()
    assert code == 1
    assert "CHANGED      PREREGISTRATION.md" in out
    assert "superseded by PREREGISTRATION.md, which is changed at" in out


def test_a_plan_whose_latest_draft_is_unfrozen_is_one_pending_plan_not_two(repo, check):
    (repo / "PREREGISTRATION.md").write_text(PLAN)
    commit(repo)
    draft(repo)
    code, out = check()
    assert code == 2
    assert "pending      PREREGISTRATION.md" in out
    assert "superseded by PREREGISTRATION.md, which is pending" in out
    assert "0 changed, 1 pending, 0 unknown commit, 1 superseded" in out


def test_a_chain_of_drafts_is_followed_to_the_document_that_ends_it(repo, check):
    sha = freeze(repo)
    draft(repo, successor="PREREGISTRATION_v1a_DRAFT.md", name="PREREGISTRATION_DRAFT.md")
    draft(repo, name="PREREGISTRATION_v1a_DRAFT.md")
    code, out = check()
    assert code == 0
    assert (
        "superseded by PREREGISTRATION_v1a_DRAFT.md, then PREREGISTRATION.md, "
        f"which is unchanged at {sha[:7]}"
    ) in out
    assert "1 unchanged, 0 appended, 0 changed, 0 pending, 0 unknown commit, 2 superseded" in out


@pytest.mark.parametrize("named", ["MISSING.md", "README.md"])
def test_a_draft_stays_pending_when_what_it_names_is_no_registration(repo, check, named):
    freeze(repo)
    (repo / "README.md").write_text("# A project\n")
    draft(repo, successor=named)
    code, out = check()
    assert code == 2
    assert "pending      PREREGISTRATION_predraft.md" in out
    assert f"says it is superseded by {named}, which is not a registration checked here" in out


def test_drafts_that_name_each_other_both_stay_pending(repo, check):
    draft(repo, successor="B_DRAFT.md", name="A_DRAFT.md")
    draft(repo, successor="A_DRAFT.md", name="B_DRAFT.md")
    code, out = check()
    assert code == 2
    assert "superseded   " not in out
    assert (
        "says it is superseded by B_DRAFT.md, then A_DRAFT.md, a chain that comes back to itself"
        in out
    )
    assert "0 changed, 2 pending" in out


def test_a_draft_that_names_itself_stays_pending(repo, check):
    draft(repo, successor="PREREGISTRATION_predraft.md")
    code, out = check()
    assert code == 2
    assert "a chain that comes back to itself" in out


def test_a_frozen_registration_cannot_declare_itself_superseded_to_cover_an_edit(repo, check):
    freeze(repo)
    freeze(repo, name="PREREGISTRATION_V2.md")
    doc = repo / "PREREGISTRATION.md"
    edited = doc.read_text().replace("0.10", "0.05")
    doc.write_text(
        edited.replace(
            "**Commit SHA:**", "**Superseded by:** PREREGISTRATION_V2.md\n\n**Commit SHA:**"
        )
    )
    code, out = check()
    assert code == 1
    assert "CHANGED      PREREGISTRATION.md" in out
    assert "superseded   " not in out


def test_the_successor_is_read_from_the_drafts_own_directory(repo, check):
    freeze(repo)
    draft(repo, successor="../PREREGISTRATION.md", name="drafts/PREREGISTRATION_predraft.md")
    code, out = check()
    assert code == 0
    assert "superseded   drafts/PREREGISTRATION_predraft.md" in out


@pytest.mark.parametrize(
    "written", ["`PREREGISTRATION.md`", "[the frozen plan](PREREGISTRATION.md)"]
)
def test_the_successor_may_be_written_in_backticks_or_as_a_link(repo, check, written):
    freeze(repo)
    draft(repo, successor=written)
    code, out = check()
    assert code == 0
    assert "superseded   PREREGISTRATION_predraft.md" in out


def test_the_words_below_the_header_do_not_declare_a_successor(repo, check):
    freeze(repo)
    (repo / "PREREGISTRATION_predraft.md").write_text(
        PLAN.replace("## Deviations", "**Superseded by:** PREREGISTRATION.md\n\n## Deviations")
    )
    commit(repo)
    code, out = check()
    assert code == 2
    assert "pending      PREREGISTRATION_predraft.md" in out


def test_a_plan_that_says_it_was_withdrawn_is_listed_with_its_reason_and_is_not_pending(
    repo, check
):
    draft(repo, successor="2026-07-20, the mismatched arm was never run", key="Withdrawn")
    code, out = check()
    assert code == 0
    assert "withdrawn    PREREGISTRATION_predraft.md" in out
    assert (
        "as the document says and not checked: 2026-07-20, the mismatched arm was never run" in out
    )
    assert "0 pending, 0 unknown commit, 1 withdrawn" in out


def test_a_withdrawal_that_gives_no_reason_leaves_the_plan_pending(repo, check):
    draft(repo, successor="", key="Withdrawn")
    code, out = check()
    assert code == 2
    assert "pending      PREREGISTRATION_predraft.md" in out
    assert "withdrawn    " not in out


def test_a_frozen_registration_cannot_declare_itself_withdrawn_to_cover_an_edit(repo, check):
    freeze(repo)
    doc = repo / "PREREGISTRATION.md"
    edited = doc.read_text().replace("0.10", "0.05")
    doc.write_text(
        edited.replace("**Commit SHA:**", "**Withdrawn:** not needed\n\n**Commit SHA:**")
    )
    code, out = check()
    assert code == 1
    assert "CHANGED      PREREGISTRATION.md" in out
    assert "withdrawn    " not in out


def test_a_chain_broken_two_steps_along_says_where_it_breaks(repo, check):
    draft(repo, successor="B_DRAFT.md", name="A_DRAFT.md")
    draft(repo, successor="MISSING.md", name="B_DRAFT.md")
    code, out = check()
    assert code == 2
    assert "superseded   " not in out
    assert (
        "its chain reaches B_DRAFT.md, which says it is superseded by MISSING.md, "
        "which is not a registration checked here"
    ) in out
    assert "0 changed, 2 pending" in out


def test_a_draft_carrying_both_lines_is_followed_to_its_successor_and_not_withdrawn(repo, check):
    (repo / "PREREGISTRATION.md").write_text(PLAN)
    commit(repo)
    both = "**Superseded by:** PREREGISTRATION.md\n**Withdrawn:** the arm was never run\n\n"
    (repo / "PREREGISTRATION_predraft.md").write_text(
        PLAN.replace("**Commit SHA:**", both + "**Commit SHA:**")
    )
    commit(repo)
    code, out = check()
    assert code == 2
    assert "superseded   PREREGISTRATION_predraft.md" in out
    assert "withdrawn    " not in out
    assert "pending      PREREGISTRATION.md" in out


@pytest.mark.parametrize(
    "line", ["**Superseded by:** PREREGISTRATION_V2.md", "**Withdrawn:** not needed"]
)
def test_adding_either_line_alone_to_a_frozen_registration_is_an_edit(repo, check, line):
    freeze(repo)
    freeze(repo, name="PREREGISTRATION_V2.md")
    doc = repo / "PREREGISTRATION.md"
    doc.write_text(doc.read_text().replace("**Commit SHA:**", line + "\n\n**Commit SHA:**"))
    code, out = check()
    assert code == 1
    assert "CHANGED      PREREGISTRATION.md" in out
    assert "0 removed" in out


@pytest.mark.parametrize("value", ["no", "N/A", "TBD", "-", "none", "_pending_", "Yes."])
def test_a_withdrawal_holding_a_placeholder_leaves_the_plan_pending_and_says_so(repo, check, value):
    draft(repo, successor=value, key="Withdrawn")
    code, out = check()
    assert code == 2
    assert "pending      PREREGISTRATION_predraft.md" in out
    assert f"its `Withdrawn` line gives no reason: {value}" in out
    assert "withdrawn    " not in out


def test_an_empty_withdrawal_says_why_the_plan_is_still_pending(repo, check):
    draft(repo, successor="", key="Withdrawn")
    code, out = check()
    assert code == 2
    assert "its `Withdrawn` line gives no reason: (empty)" in out


def test_an_empty_successor_says_why_the_draft_is_still_pending(repo, check):
    draft(repo, successor="")
    code, out = check()
    assert code == 2
    assert "its `Superseded by` line names no document" in out


def test_a_successor_whose_name_opens_with_an_underscore_is_found(repo, check):
    freeze(repo, name="_FROZEN.md")
    draft(repo, successor="_FROZEN.md")
    code, out = check()
    assert code == 0
    assert "superseded   PREREGISTRATION_predraft.md" in out


def withdrawn_elsewhere(repo, text):
    (repo / "PREREGISTRATION_predraft.md").write_text(text)
    commit(repo)


def test_a_withdrawal_written_below_the_header_is_the_plans_own_text(repo, check):
    withdrawn_elsewhere(
        repo, PLAN.replace("## Deviations", "**Withdrawn:** the arm was never run\n\n## Deviations")
    )
    code, out = check()
    assert code == 2
    assert "pending      PREREGISTRATION_predraft.md" in out
    assert "withdrawn    " not in out


def test_a_withdrawal_inside_a_fenced_block_is_an_example(repo, check):
    fenced = "```\n**Withdrawn:** the arm was never run\n```\n\n"
    withdrawn_elsewhere(repo, PLAN.replace("**Commit SHA:**", fenced + "**Commit SHA:**"))
    code, out = check()
    assert code == 2
    assert "pending      PREREGISTRATION_predraft.md" in out
    assert "withdrawn    " not in out


def test_a_chain_ending_on_a_withdrawn_plan_says_so_and_exits_clean(repo, check):
    draft(
        repo, successor="the arm was never run", name="PREREGISTRATION_v2_DRAFT.md", key="Withdrawn"
    )
    draft(repo, successor="PREREGISTRATION_v2_DRAFT.md")
    code, out = check()
    assert code == 0
    assert "withdrawn    PREREGISTRATION_v2_DRAFT.md" in out
    assert "says it is superseded by PREREGISTRATION_v2_DRAFT.md, which is withdrawn" in out
    assert "0 pending, 0 unknown commit, 1 superseded, 1 withdrawn" in out


@pytest.mark.parametrize("named", ["MISSING.md", ""])
def test_a_withdrawal_does_not_rescue_a_draft_whose_successor_cannot_be_followed(
    repo, check, named
):
    both = f"**Superseded by:** {named}\n**Withdrawn:** the arm was never run\n\n"
    withdrawn_elsewhere(repo, PLAN.replace("**Commit SHA:**", both + "**Commit SHA:**"))
    code, out = check()
    assert code == 2
    assert "pending      PREREGISTRATION_predraft.md" in out
    assert "withdrawn    " not in out
    assert ("names no document" if not named else "not a registration checked here") in out


@pytest.mark.parametrize("reason", ["план отменён до запуска", "该计划在运行前被放弃"])
def test_a_reason_in_another_script_is_a_reason(repo, check, reason):
    draft(repo, successor=reason, key="Withdrawn")
    code, out = check()
    assert code == 0
    assert f"not checked: {reason}" in out


@pytest.mark.parametrize("value", ["not applicable", "TBA", "Not Applicable."])
def test_more_template_words_are_not_reasons(repo, check, value):
    draft(repo, successor=value, key="Withdrawn")
    code, out = check()
    assert code == 2
    assert f"its `Withdrawn` line gives no reason: {value}" in out


@pytest.mark.parametrize("successor", ["../PREREGISTRATION.md", "../plans/PREREGISTRATION.md"])
def test_a_successor_above_or_beside_the_folder_checked_gives_the_draft_one_status(
    repo, check, monkeypatch, successor
):
    name = successor.removeprefix("../")
    (repo / name).parent.mkdir(exist_ok=True)
    sha = freeze(repo, name)
    draft(repo, successor=successor, name="exp/DRAFT.md")
    code, out = check()
    assert code == 0
    assert "superseded   exp/DRAFT.md" in out
    assert f"says it is superseded by {name}, which is unchanged at {sha[:7]}" in out

    monkeypatch.chdir(repo / "exp")
    code, out = check()
    assert code == 0
    assert "superseded   DRAFT.md" in out
    assert f"says it is superseded by {successor}, which is unchanged at {sha[:7]}" in out
    assert (
        "1 commit-pinned: 0 unchanged, 0 appended, 0 changed, 0 pending, 0 unknown commit, "
        "1 superseded"
    ) in out


def test_a_successor_outside_the_repository_leaves_the_draft_pending_from_any_folder(
    repo, check, monkeypatch
):
    freeze(repo)
    draft(repo, successor="../../PREREGISTRATION.md", name="exp/DRAFT.md")
    for folder, shown in ((repo, "exp/DRAFT.md"), (repo / "exp", "DRAFT.md")):
        monkeypatch.chdir(folder)
        code, out = check()
        assert code == 2
        assert f"pending      {shown}" in out
        assert (
            "says it is superseded by ../../PREREGISTRATION.md, "
            "which is an absolute path or leaves this repository"
        ) in out
        assert "superseded   " not in out


def tool_plan(repo, monkeypatch, frozen=True):
    """A `PREREG.md` in `study/`, committed, and frozen with `prereg freeze` unless told not to."""
    assert cli.main(["new", "study"]) == 0
    commit(repo, "plan")
    if frozen:
        monkeypatch.chdir(repo / "study")
        assert cli.main(["freeze"]) == 0
        monkeypatch.chdir(repo)
        commit(repo, "freeze")
    return repo / "study" / "PREREG.md"


@pytest.mark.parametrize(
    ("folder", "shown", "plan"),
    [
        (".", "drafts/DRAFT.md", "study/PREREG.md"),
        ("drafts", "DRAFT.md", "../study/PREREG.md"),
    ],
)
def test_a_draft_naming_a_plan_the_tool_froze_is_superseded(
    repo, check, monkeypatch, folder, shown, plan
):
    tool_plan(repo, monkeypatch)
    draft(repo, successor="../study/PREREG.md", name="drafts/DRAFT.md")
    monkeypatch.chdir(repo / folder)
    code, out = check()
    assert code == 0
    assert f"superseded   {shown}" in out
    assert (
        f"says it is superseded by {plan}, a plan `prereg freeze` froze, which is unchanged" in out
    )
    assert "0 pending, 0 unknown commit, 1 superseded" in out


def test_a_draft_naming_a_plan_the_tool_has_not_frozen_stays_pending(repo, check, monkeypatch):
    tool_plan(repo, monkeypatch, frozen=False)
    draft(repo, successor="../study/PREREG.md", name="drafts/DRAFT.md")
    monkeypatch.chdir(repo / "drafts")
    code, out = check()
    assert code == 2
    assert "pending      DRAFT.md" in out
    assert (
        "says it is superseded by ../study/PREREG.md, a plan `prereg check` reports as not frozen"
        in out
    )
    assert "superseded   " not in out


def test_a_draft_naming_a_plan_edited_after_its_freeze_stays_pending(repo, check, monkeypatch):
    plan = tool_plan(repo, monkeypatch)
    draft(repo, successor="../study/PREREG.md", name="drafts/DRAFT.md")
    plan.chmod(0o644)
    plan.write_text(plan.read_text() + "\nOne more hypothesis.\n")
    commit(repo, "edit the frozen plan")
    monkeypatch.chdir(repo / "drafts")
    code, out = check()
    assert code == 2
    assert "pending      DRAFT.md" in out
    assert (
        "says it is superseded by ../study/PREREG.md, a plan `prereg check` reports a finding on"
        in out
    )
    assert "superseded   " not in out
    assert "CHANGED" not in out, "a plan outside the folder checked is read and not listed"


def test_a_withdrawn_line_on_a_plan_the_tool_freezes_is_not_read(repo, check, monkeypatch):
    plan = tool_plan(repo, monkeypatch, frozen=False)
    title, rest = plan.read_text().split("\n", 1)
    plan.write_text(f"{title}\n\n**Withdrawn:** the arm was never run\n{rest}")
    commit(repo, "say the plan was withdrawn")
    code, out = check()
    assert code == 1
    assert "not frozen   " in out
    assert "withdrawn    " not in out
    assert "commit-pinned" not in out


def test_a_withdrawal_names_the_commit_that_added_its_line(repo, check):
    (repo / "PREREGISTRATION_predraft.md").write_text(PLAN)
    commit(repo, "draft")
    draft(repo, successor="the arm was never run", key="Withdrawn")
    added = git(repo, "log", "-1", "--format=%h, committed %cs")
    git(repo, "mv", "PREREGISTRATION_predraft.md", "PREREGISTRATION_ARM_B.md")
    commit(repo, "rename")
    code, out = check()
    assert code == 0
    assert "withdrawn    PREREGISTRATION_ARM_B.md" in out
    assert f"its `Withdrawn` line was added in {added}" in out
    assert "0 pending, 0 unknown commit, 1 withdrawn" in out


def test_a_withdrawal_not_yet_committed_says_so_and_is_still_withdrawn(repo, check):
    doc = repo / "PREREGISTRATION_predraft.md"
    doc.write_text(PLAN)
    commit(repo, "draft")
    doc.write_text(
        PLAN.replace("**Commit SHA:**", "**Withdrawn:** the arm was never run\n\n**Commit SHA:**")
    )
    code, out = check()
    assert code == 0
    assert "withdrawn    PREREGISTRATION_predraft.md" in out
    assert "its `Withdrawn` line is not yet committed" in out
    assert "0 pending, 0 unknown commit, 1 withdrawn" in out
