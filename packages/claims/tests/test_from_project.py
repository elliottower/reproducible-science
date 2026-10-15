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
from claims.open_items import (
    DRAFT_NAME,
    ITEMS_NAME,
    ClaimState,
    OpenItemsError,
    Source,
    read,
    tally,
    write_draft,
)
from claims.policy import PROFILES
from claims.sources.project import (
    NothingToScaffoldError,
    ScaffoldExistsError,
    ScaffoldRefusedError,
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


def test_a_dangling_link_at_an_output_path_is_refused_and_nothing_is_written(tmp_path, project):
    outside = tmp_path / "outside"
    outside.mkdir()
    (project / DRAFT_NAME).symlink_to("../outside/planted.yaml")

    for overwrite in (False, True):
        with pytest.raises(ScaffoldRefusedError, match="symbolic link"):
            from_project(project, overwrite=overwrite)
    assert not (outside / "planted.yaml").exists()
    assert not (project / ITEMS_NAME).exists()


def test_write_draft_refuses_a_link_whatever_reader_calls_it(tmp_path, project):
    (tmp_path / "outside").mkdir()
    (project / ITEMS_NAME).symlink_to("../outside/planted.json")
    source = Source(reader="test", reader_version="0", format="none", path="x", digest="0" * 64)
    document = {"schema_version": "repro/1", "project": "p", "artifacts": [], "claims": []}
    with pytest.raises(OpenItemsError, match="symbolic link"):
        write_draft(project, document, source, (), overwrite=True)
    assert not (tmp_path / "outside" / "planted.json").exists()
    assert not (project / DRAFT_NAME).exists()


def test_the_words_before_each_number_and_not_the_whole_line_meet_the_label_guard(project):
    (project / "results" / "metrics.json").write_text(
        json.dumps({"test": {"accuracy": 0.9312, "loss": 0.2871}})
    )
    (project / "results" / "table.csv").unlink()
    (project / "paper.md").write_text("# R\n\nTest accuracy was 0.874 and test loss was 0.931.\n")
    made = from_project(project)

    loss = items_of(project)["line-3-2"]
    assert loss.context["words_before"] == "and test loss was"
    assert places(loss) == [("metrics", "/test/accuracy")]
    assert not loss.unique
    assert loss.reason == "the line names a label or a split no matching address carries"
    assert made.unique == 0


def test_a_sentence_wrapped_onto_the_number_s_line_is_the_claim_s_text(project):
    (project / "paper.md").write_text(
        "# R\n\nHeld-out accuracy on the\n0.931 mark was reached, and the rate\nwas 4.3%.\n"
    )
    from_project(project)
    texts = {c.id: c.text for c in load(project / DRAFT_NAME).claims}
    assert (
        texts["line-4-1"]
        == "Held-out accuracy on the 0.931 mark was reached, and the rate was 4.3%."
    )
    assert texts["line-5-1"] == texts["line-4-1"]


TEX = r"""\documentclass{article}
% 0.9999 in a comment
\usepackage{graphicx}
\begin{document}
\section{Results}
Accuracy was 0.931 on the held-out set.
\begin{tabular}{lc}
model & recall \\
lasso & 0.6543 \\
\end{tabular}
The held-out loss was $0.4417$.
\end{document}
"""


def test_a_latex_manuscript_counts_source_lines_and_reads_tables_and_inline_math(project):
    (project / "paper.md").unlink()
    (project / "paper.tex").write_text(TEX)
    (project / "results" / "metrics.json").write_text(
        json.dumps({"scores": {"accuracy": 0.9312}, "loss": 0.4417})
    )
    from_project(project)

    claims = {c.id: c for c in load(project / DRAFT_NAME).claims}
    assert list(claims) == ["line-6-1", "line-9-1", "line-11-1"]
    assert claims["line-6-1"].where == "paper.tex, line 6"
    assert claims["line-11-1"].text == "The held-out loss was 0.4417."
    items = items_of(project)
    assert places(items["line-9-1"]) == [("table", "recall[0]"), ("table", "recall[1]")]
    assert items["line-9-1"].context["words_before"] == "lasso"
    assert items["line-9-1"].unique
    assert places(items["line-11-1"]) == [("metrics", "/loss")]
    assert items["line-11-1"].unique


def test_open_items_alone_is_a_scaffold_present_and_is_named(project):
    (project / ITEMS_NAME).write_text("{}\n")
    with pytest.raises(ScaffoldExistsError) as refused:
        from_project(project)
    assert str(refused.value) == (
        "open-items.json is already here and was not replaced; --force replaces "
        "repro.draft.yaml and open-items.json"
    )
    assert not (project / DRAFT_NAME).exists()


def test_a_result_file_linked_out_of_the_project_is_listed_as_not_checked(tmp_path, project):
    (tmp_path / "outside").mkdir()
    (tmp_path / "outside" / "ext.json").write_text('{"accuracy": 0.9312}')
    (project / "results" / "ext.json").symlink_to(tmp_path / "outside" / "ext.json")
    made = from_project(project)
    assert [(p.file, p.reason) for p in made.written.not_checked] == [
        ("results/ext.json", "a symbolic link, which is not followed")
    ]
    assert "results/ext.json" not in {
        a.path.as_posix() for a in load(project / DRAFT_NAME).artifacts
    }
