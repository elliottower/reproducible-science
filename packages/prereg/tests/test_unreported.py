"""A plan can pass every freeze check and never reach the paper it was written for."""

from __future__ import annotations

import subprocess
import sys

import pytest
from prereg.plan import hypotheses_of, unreported
from provenance_core.gitref import clean_env

TEMPLATE_STYLE = """# Does it?

**H1.** The first thing.

**H2b.** The second thing.

**H10.** The tenth thing.
"""

HEADING_STYLE = """# Does it?

## H1: the first thing

### HP3: a Perturb-seq thing

## H_tissue1: a tissue thing
"""


def test_both_label_styles_are_found():
    assert hypotheses_of(TEMPLATE_STYLE) == ["H1", "H2b", "H10"]
    assert hypotheses_of(HEADING_STYLE) == ["H1", "HP3", "H_tissue1"]


def test_a_label_repeated_in_the_plan_is_listed_once():
    assert hypotheses_of(TEMPLATE_STYLE + "\n**H1.** restated\n") == ["H1", "H2b", "H10"]


def test_every_hypothesis_mentioned_is_nothing_to_report():
    assert unreported(TEMPLATE_STYLE, "we tested H1, H2b and H10 and here is what happened") == []


def test_the_one_the_manuscript_never_mentions_is_named():
    assert unreported(TEMPLATE_STYLE, "we tested H1 and H2b") == ["H10"]


def test_a_longer_label_does_not_report_a_shorter_one_as_present():
    # `H1` is a substring of `H10`, so a naive search passes a manuscript that
    # mentions only the tenth hypothesis and never the first.
    assert "H1" in unreported(TEMPLATE_STYLE, "we tested H10 and H2b")


def test_a_plan_declared_out_of_scope_reports_nothing():
    out_of_scope = TEMPLATE_STYLE + "\n**Manuscript:** none\n"
    assert unreported(out_of_scope, "this manuscript mentions no hypothesis at all") == []


def test_the_log_is_not_searched_for_hypotheses():
    # `plan_of` cuts the log, so a label quoted in a deviation entry is not a
    # registered hypothesis and must not be demanded of the manuscript.
    with_log = TEMPLATE_STYLE + "\n---\n\n## Log\n\n**H99.** quoted in a deviation\n"
    assert "H99" not in hypotheses_of(with_log)


def git(repo, *args) -> None:
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
        cwd=repo,
        env=clean_env(),
        capture_output=True,
        text=True,
        check=True,
    )


def run(args, cwd):
    return subprocess.run(
        [sys.executable, "-m", "prereg.cli", *args],
        cwd=cwd,
        env=clean_env(),
        capture_output=True,
        text=True,
    )


@pytest.fixture
def frozen_study(tmp_path):
    git(tmp_path, "init", "-q")
    assert run(["new", "study"], tmp_path).returncode == 0
    study = tmp_path / "study"
    plan = study / "PREREG.md"
    plan.write_text(
        plan.read_text() + "\n**H71.** The first thing.\n\n**H72.** The second thing.\n"
    )
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-q", "-m", "plan")
    assert run(["freeze"], study).returncode == 0
    return study


def test_check_fails_an_unchanged_plan_when_the_manuscript_omits_a_hypothesis(frozen_study):
    labels = hypotheses_of((frozen_study / "PREREG.md").read_text())
    assert {"H71", "H72"} <= set(labels)

    (frozen_study / "all.tex").write_text("We tested " + ", ".join(labels) + ".")
    reported = run(["check", "--manuscript", "all.tex"], frozen_study)
    assert reported.returncode == 0, reported.stdout + reported.stderr
    assert "UNREPORTED" not in reported.stdout

    (frozen_study / "some.tex").write_text(
        "We tested " + ", ".join(h for h in labels if h != "H72") + "."
    )
    omitted = run(["check", "--manuscript", "some.tex"], frozen_study)
    assert omitted.returncode == 1
    assert "UNREPORTED" in omitted.stdout
    assert "H72 is registered here" in omitted.stdout
    assert "H71 is registered here" not in omitted.stdout


def test_check_without_the_flag_does_not_read_any_manuscript(frozen_study):
    done = run(["check"], frozen_study)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "UNREPORTED" not in done.stdout


def test_a_manuscript_that_is_not_there_is_reported_and_nothing_is_checked(frozen_study):
    done = run(["check", "--manuscript", "absent.tex"], frozen_study)
    assert done.returncode == 2
    assert "no manuscript at absent.tex" in done.stdout
