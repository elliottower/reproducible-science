"""A project's own result files and manuscript, read into a draft manifest and its open items.

The project is written in the test: a JSON file of metrics, a CSV of two fits and a `paper.md`
that prints numbers some of which the files hold. Every number becomes a claim with no
assertion and an item listing where the files hold it.
"""

from __future__ import annotations

import hashlib
import json

import pytest
import yaml
from claims.manifest import load
from claims.open_items import DRAFT_NAME, ITEMS_NAME, ClaimState, read, tally
from claims.policy import PROFILES
from claims.sources.project import (
    NothingToScaffoldError,
    ScaffoldExistsError,
    from_project,
)
from claims.verify import verify

METRICS = json.dumps(
    {
        "model": "lasso",
        "scores": {"accuracy": 0.9312, "n": 480, "rate": 0.0426},
        "auc": 0.8421,
        "seed": 12345,
    }
)
TABLE = "model,auc,recall\nlasso,0.71,0.6543\nridge,0.8421,0.6543\n"
PAPER = (
    "# Results\n"
    "\n"
    "We fit the lasso to 480 participants with seed 12345.\n"
    "Held-out accuracy was 0.931, and the error rate was 4.3%.\n"
    "The AUC was 0.842 for both fits.\n"
    "Recall of the lasso was 0.6543.\n"
    "We ran 3 seeds; the AUC was 0.71, not 0.55.\n"
)


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "study"
    (root / "results").mkdir(parents=True)
    (root / "results" / "metrics.json").write_text(METRICS)
    (root / "results" / "table.csv").write_text(TABLE)
    (root / "paper.md").write_text(PAPER)
    return root


def items_of(root) -> dict:
    return {item.claim: item for item in read(root / ITEMS_NAME).items}


def places(item) -> list[tuple[str, str]]:
    return [
        (
            c["artifact"],
            c["locator"].get("pointer") or f"{c['locator']['column']}[{c['locator']['row']}]",
        )
        for c in item.candidates
    ]


def test_every_number_is_an_open_claim_with_no_assertion_and_the_files_are_pinned(project):
    made = from_project(project)

    manifest = load(project / DRAFT_NAME)
    assert {a.path.as_posix(): a.digest.value for a in manifest.artifacts} == {
        "results/metrics.json": hashlib.sha256(METRICS.encode()).hexdigest(),
        "results/table.csv": hashlib.sha256(TABLE.encode()).hexdigest(),
        "paper.md": hashlib.sha256(PAPER.encode()).hexdigest(),
    }
    assert [(c.id, c.where) for c in manifest.claims] == [
        ("line-3-1", "paper.md, line 3"),
        ("line-3-2", "paper.md, line 3"),
        ("line-4-1", "paper.md, line 4"),
        ("line-4-2", "paper.md, line 4"),
        ("line-5-1", "paper.md, line 5"),
        ("line-6-1", "paper.md, line 6"),
        ("line-7-1", "paper.md, line 7"),
        ("line-7-2", "paper.md, line 7"),
    ]
    assert manifest.claims[2].text == "Held-out accuracy was 0.931, and the error rate was 4.3%."
    assert all(claim.evidence == () for claim in manifest.claims)
    assert [item.context["printed"] for item in read(project / ITEMS_NAME).items] == [
        "480",
        "12345",
        "0.931",
        "4.3%",
        "0.842",
        "0.6543",
        "0.71",
        "0.55",
    ]
    assert (made.open, made.unique) == (8, 2)
    assert not (project / "repro.yaml").exists()


def test_one_candidate_passing_the_guards_is_unique_and_listed_first(project):
    from_project(project)
    items = items_of(project)

    accuracy = items["line-4-1"]
    assert (accuracy.unique, accuracy.reason) == (True, "")
    assert places(accuracy) == [("metrics", "/scores/accuracy")]
    assert accuracy.candidates[0]["reported"] == "0.931"
    assert accuracy.candidates[0]["basis"] == "inferred"

    # Both fits hold 0.6543; the line names the lasso, so ridge's row fails the label guard.
    recall = items["line-6-1"]
    assert (recall.unique, recall.reason) == (True, "")
    assert places(recall) == [("table", "recall[0]"), ("table", "recall[1]")]


@pytest.mark.parametrize(
    ("claim", "reason", "found"),
    [
        (
            "line-3-1",
            "480 has fewer than 3 significant digits or is an integer below 1000, so a match "
            "of it may be chance",
            [("metrics", "/scores/n")],
        ),
        (
            "line-3-2",
            "every match is in an index-like column or key, or in a file whose labels are not "
            "read, so none is called unique",
            [("metrics", "/seed")],
        ),
        (
            "line-4-2",
            "4.3 has fewer than 3 significant digits or is an integer below 1000, so a match "
            "of it may be chance",
            [("metrics", "/scores/rate")],
        ),
        (
            "line-5-1",
            "2 addresses pass the guards, not one",
            [("metrics", "/auc"), ("table", "auc[1]")],
        ),
        ("line-7-2", "no address in the result files matches", []),
    ],
)
def test_a_number_the_guards_do_not_single_out_is_not_unique(project, claim, reason, found):
    from_project(project)
    item = items_of(project)[claim]
    assert not item.unique
    assert item.reason == reason
    assert places(item) == found


def test_a_percentage_is_offered_as_the_fraction_the_file_stores(project):
    from_project(project)
    rate = items_of(project)["line-4-2"]
    assert rate.candidates[0]["conversion"] == "percent"
    assert rate.context["percent"] is True


def test_the_fresh_draft_fails_strict_and_a_unique_candidate_filled_in_matches(project):
    from_project(project)
    assessment = PROFILES["strict"].assess(verify(load(project / DRAFT_NAME)))
    assert not assessment.passed
    assert {v.rule for v in assessment.violations} == {"claim.no_evidence", "report.empty"}
    assert tally(project / ITEMS_NAME).claims[ClaimState.OPEN] == 8

    # The positive control: the candidate, written in as the item asks, is checked and holds.
    accuracy = items_of(project)["line-4-1"]
    document = yaml.safe_load((project / DRAFT_NAME).read_text())
    document["claims"][2]["evidence"] = [accuracy.candidates[0]]
    (project / DRAFT_NAME).write_text(yaml.safe_dump(document, sort_keys=False))
    found = tally(project / ITEMS_NAME)
    assert found.claims[ClaimState.BOUND] == 1
    assert found.claims[ClaimState.OPEN] == 7
    # Inferred, so strict still fails it until an author accepts the address.
    assessment = PROFILES["strict"].assess(verify(load(project / DRAFT_NAME)))
    assert "evidence.inferred" in {v.rule for v in assessment.violations}


def test_neither_file_is_overwritten_without_overwrite(project):
    from_project(project)
    (project / DRAFT_NAME).write_text("edited by hand\n")
    before = (project / ITEMS_NAME).read_bytes()

    with pytest.raises(ScaffoldExistsError, match=DRAFT_NAME):
        from_project(project)
    assert (project / DRAFT_NAME).read_text() == "edited by hand\n"
    assert (project / ITEMS_NAME).read_bytes() == before

    (project / DRAFT_NAME).unlink()
    with pytest.raises(ScaffoldExistsError, match=ITEMS_NAME):
        from_project(project)
    assert not (project / DRAFT_NAME).exists()

    made = from_project(project, overwrite=True)
    assert made.open == 8
    assert load(project / DRAFT_NAME).claims


@pytest.mark.parametrize("missing", ["paper.md", "results"])
def test_without_a_manuscript_or_a_result_file_nothing_is_written(project, missing):
    target = project / missing
    if target.is_dir():
        for path in target.iterdir():
            path.unlink()
    else:
        target.unlink()
    with pytest.raises(NothingToScaffoldError):
        from_project(project)
    assert not (project / DRAFT_NAME).exists()
    assert not (project / ITEMS_NAME).exists()


def test_an_lfs_pointer_is_declared_without_a_pin_and_not_searched(project):
    (project / "results" / "metrics.json").write_text(
        "version https://git-lfs.github.com/spec/v1\noid sha256:abc\nsize 12\n"
    )
    made = from_project(project)
    pins = {a.path.as_posix(): a.digest for a in load(project / DRAFT_NAME).artifacts}
    assert pins["results/metrics.json"] is None
    assert [p.file for p in made.written.not_checked] == ["results/metrics.json"]
    assert all(
        c["artifact"] != "metrics" for item in items_of(project).values() for c in item.candidates
    )
