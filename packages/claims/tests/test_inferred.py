"""An assertion marked `basis: inferred`, and the count of what a reader left open.

An inferred assertion is checked as any other and never counted as verified: not in the report's
counts, not by a policy, and not by a reader of the check record. The draft and its open items
are written with `write_draft`, edited as an agent would edit them, and counted with `tally`.
"""

from __future__ import annotations

import datetime
import hashlib
import json

import pytest
import yaml
from claims.cli import main
from claims.exceptions import ManifestError
from claims.manifest import load
from claims.models import Basis, NotEstablishedKind, Outcome
from claims.open_items import (
    DRAFT_NAME,
    ITEMS_NAME,
    ClaimState,
    Need,
    OpenItem,
    OpenItemsError,
    Source,
    tally,
    write_draft,
)
from claims.policy import EXPLORATORY, PUBLICATION, STRICT, Severity
from claims.record import NormalizedOutcome, check_records, read_outcome
from claims.renderers import to_sarif
from claims.verify import verify
from claims.why import why

WHEN = datetime.datetime(2026, 10, 14, 12, 0, tzinfo=datetime.UTC)
RESULTS = '{"auc": 0.912, "n": 480}\n'


def metric(reported: str, pointer: str, **extra) -> dict:
    return {
        "kind": "metric",
        "artifact": "results",
        "name": pointer.strip("/"),
        "reported": reported,
        "pointer": pointer,
        **extra,
    }


def project(tmp_path, *evidence: dict):
    (tmp_path / "results.json").write_text(RESULTS)
    digest = hashlib.sha256(RESULTS.encode()).hexdigest()
    manifest = {
        "artifacts": [
            {
                "id": "results",
                "path": "results.json",
                "digest": {"algorithm": "sha256", "value": digest},
            }
        ],
        "claims": [{"id": "auc", "text": "The AUC was 0.912.", "evidence": list(evidence)}],
    }
    path = tmp_path / "repro.yaml"
    path.write_text(yaml.safe_dump(manifest, sort_keys=False))
    return load(path)


def test_an_inferred_match_is_counted_apart_and_fails_publication(tmp_path):
    report = verify(project(tmp_path, metric("0.912", "/auc", basis="inferred")))

    (decision,) = report.decisions
    assert decision.outcome is Outcome.VERIFIED
    assert decision.inferred
    assert report.counts == {"inferred_verified": 1}

    published = PUBLICATION.assess(report)
    assert not published.passed
    assert [v.rule for v in published.errors] == ["evidence.inferred"]
    drafted = EXPLORATORY.assess(report)
    assert drafted.passed
    assert [(v.rule, v.severity) for v in drafted.violations] == [
        ("evidence.inferred", Severity.WARNING)
    ]


def test_an_inferred_match_fails_strict(tmp_path):
    report = verify(project(tmp_path, metric("0.912", "/auc", basis="inferred")))
    assert "evidence.inferred" in {v.rule for v in STRICT.assess(report).errors}


def test_a_reviewed_inferred_assertion_counts_as_declared_and_says_who(tmp_path):
    review = {"who": "Elliot Tower", "when": "2026-10-14"}
    manifest = project(tmp_path, metric("0.912", "/auc", basis="inferred", reviewed=review))
    report = verify(manifest)

    assert report.counts == {"verified": 1}
    assert PUBLICATION.assess(report).passed
    (record,) = check_records(manifest, checked_at=WHEN)
    assert record.assertion.basis is None
    assert record.assertion.reviewed.who == "Elliot Tower"
    assert read_outcome(record) is NormalizedOutcome.MATCH
    # The manifest keeps what it was, and who accepted it.
    dumped = manifest.model_dump(mode="json")["claims"][0]["evidence"][0]
    assert (dumped["basis"], dumped["reviewed"]["who"]) == ("inferred", "Elliot Tower")


def test_a_review_of_a_declared_assertion_is_refused(tmp_path):
    with pytest.raises(ManifestError, match="reviewed"):
        project(tmp_path, metric("0.912", "/auc", reviewed={"who": "x", "when": "2026-10-14"}))


def test_sarif_does_not_show_an_inferred_match_as_a_pass(tmp_path):
    report = verify(
        project(tmp_path, metric("0.912", "/auc", basis="inferred"), metric("480", "/n"))
    )
    results = to_sarif(report, PUBLICATION.assess(report), version="0")["runs"][0]["results"]
    by_basis = {r["properties"]["basis"]: (r["kind"], r["ruleId"]) for r in results}

    assert by_basis["inferred"] == ("notApplicable", "repro/unchecked")
    assert by_basis["declared"] == ("pass", "repro/verified")


def test_why_never_lists_an_inferred_match_as_verified(tmp_path, capsys):
    manifest = project(tmp_path, metric("0.912", "/auc", basis="inferred"), metric("480", "/n"))
    account = why(manifest, "auc")

    assert account.outcomes == {Outcome.VERIFIED: 1}
    assert account.inferred == {Outcome.VERIFIED: 1}
    assert [line.kind for line in account.not_established].count(NotEstablishedKind.INFERRED) == 1

    assert main(["why", "auc", str(manifest.path)]) == 0
    shown = capsys.readouterr().out
    assert "the manuscript prints 0.912: matched, inferred: not counted as verified" in shown
    assert "the manuscript prints 480: verified" in shown
    assert "2 assertions: 1 verified, 1 inferred that matched;" in shown


def test_an_inferred_mismatch_is_still_a_mismatch(tmp_path):
    report = verify(project(tmp_path, metric("0.913", "/auc", basis="inferred")))

    assert report.counts == {"inferred_mismatch": 1}
    assert {v.rule for v in PUBLICATION.assess(report).errors} == {
        "evidence.mismatch",
        "evidence.inferred",
    }


def test_a_declared_assertion_dumps_as_it_did_before_the_field_existed(tmp_path):
    declared = project(tmp_path, metric("0.912", "/auc"))
    dumped = declared.model_dump(mode="json")["claims"][0]["evidence"][0]
    assert "basis" not in dumped

    inferred = project(tmp_path, metric("0.912", "/auc", basis="inferred"))
    assert inferred.model_dump(mode="json")["claims"][0]["evidence"][0]["basis"] == "inferred"
    assert declared.model_dump_json() != inferred.model_dump_json()


def test_the_record_marks_an_inferred_match_and_a_reader_does_not_pass_it_on(tmp_path):
    manifest = project(tmp_path, metric("0.912", "/auc", basis="inferred"), metric("480", "/n"))
    inferred, declared = check_records(manifest, checked_at=WHEN)

    assert inferred.assertion.basis is Basis.INFERRED
    assert inferred.outcome is NormalizedOutcome.MATCH
    assert read_outcome(inferred) is NormalizedOutcome.NOT_CHECKED
    assert json.loads(inferred.to_json())["assertion"]["basis"] == "inferred"

    assert declared.assertion.basis is None
    assert read_outcome(declared) is NormalizedOutcome.MATCH
    assert "basis" not in json.loads(declared.to_json())["assertion"]


SOURCE = Source(
    reader="claims from-test",
    reader_version="0",
    format="test",
    path="source.json",
    digest="0" * 64,
)


def draft(tmp_path, items: tuple[OpenItem, ...]):
    (tmp_path / "results.json").write_text(RESULTS)
    digest = hashlib.sha256(RESULTS.encode()).hexdigest()
    document = {
        "artifacts": [
            {
                "id": "results",
                "path": "results.json",
                "digest": {"algorithm": "sha256", "value": digest},
            }
        ],
        "claims": [
            {"id": "n", "text": "480 patients.", "evidence": [metric("480", "/n")]},
            {"id": "auc", "text": "The AUC was 0.912."},
            {"id": "auc-again", "text": "An AUC of 0.912."},
        ],
    }
    return write_draft(tmp_path, document, SOURCE, items)


def fill(tmp_path, claim_id: str, *evidence: dict) -> None:
    path = tmp_path / DRAFT_NAME
    document = yaml.safe_load(path.read_text())
    for claim in document["claims"]:
        if claim["id"] == claim_id:
            claim.setdefault("evidence", []).extend(evidence)
    path.write_text(yaml.safe_dump(document, sort_keys=False))


ITEMS = (
    OpenItem(
        id="auc/value",
        claim="auc",
        need=Need.VALUE,
        asks="where the file holds the AUC",
        candidates=(metric("0.912", "/auc", basis="inferred"),),
        unique=True,
    ),
    OpenItem(id="auc-again/value", claim="auc-again", need=Need.VALUE, asks="the AUC again"),
)


def test_the_reader_alone_binds_what_no_item_names_and_the_rest_is_open(tmp_path):
    found = tally(draft(tmp_path, ITEMS))

    assert found.claims == {
        ClaimState.READER: 1,
        ClaimState.BOUND: 0,
        ClaimState.NOT_MATCHING: 0,
        ClaimState.OPEN: 2,
        ClaimState.OUTSIDE: 0,
    }
    assert found.left_open_by_reader == 2
    assert found.items["open"] == 2
    assert found.items["with_unique_candidate"] == 1
    assert found.items["with_no_candidate"] == 1
    assert not found.manifest_changed


def test_filled_items_split_by_whether_the_inferred_assertion_matched(tmp_path):
    items = draft(tmp_path, ITEMS)
    fill(tmp_path, "auc", metric("0.912", "/auc", basis="inferred"))
    fill(tmp_path, "auc-again", metric("0.91", "/n", basis="inferred"))

    found = tally(items)
    states = {entry.claim: entry.state for entry in found.per_claim}
    assert states == {
        "n": ClaimState.READER,
        "auc": ClaimState.BOUND,
        "auc-again": ClaimState.NOT_MATCHING,
    }
    assert found.items["filled_by_inferred"] == 2
    assert (found.items["filled"], found.items["filled_and_passing"]) == (2, 1)
    assert found.assertions[Basis.INFERRED] == {Outcome.VERIFIED: 1, Outcome.MISMATCH: 1}
    assert found.assertions[Basis.DECLARED] == {Outcome.VERIFIED: 1}
    assert found.manifest_changed


def test_a_quote_does_not_fill_an_item_that_needs_a_value(tmp_path):
    (tmp_path / "paper.txt").write_text("The AUC was 0.912 on held-out data.\n")
    items = draft(tmp_path, ITEMS)
    path = tmp_path / DRAFT_NAME
    document = yaml.safe_load(path.read_text())
    document["artifacts"].append({"id": "paper", "path": "paper.txt"})
    path.write_text(yaml.safe_dump(document, sort_keys=False))
    fill(tmp_path, "auc", {"kind": "quote", "artifact": "paper", "text": "The AUC was 0.912"})

    found = tally(items)
    assert {entry.claim: entry.state for entry in found.per_claim}["auc"] is ClaimState.OPEN


def test_a_claim_with_only_inferred_evidence_and_no_item_is_outside(tmp_path):
    items = draft(tmp_path, ITEMS)
    path = tmp_path / DRAFT_NAME
    document = yaml.safe_load(path.read_text())
    document["claims"].append(
        {"id": "added", "text": "Added.", "evidence": [metric("480", "/n", basis="inferred")]}
    )
    path.write_text(yaml.safe_dump(document, sort_keys=False))

    assert tally(items).claims[ClaimState.OUTSIDE] == 1


def test_an_item_is_closed_by_filling_it_never_by_deleting_its_claim(tmp_path):
    items = draft(tmp_path, ITEMS)
    path = tmp_path / DRAFT_NAME
    document = yaml.safe_load(path.read_text())
    document["claims"] = [c for c in document["claims"] if c["id"] != "auc-again"]
    path.write_text(yaml.safe_dump(document, sort_keys=False))

    with pytest.raises(OpenItemsError, match="auc-again"):
        tally(items)


def test_an_open_items_file_never_names_a_draft_outside_its_directory(tmp_path):
    items = draft(tmp_path, ITEMS)
    written = json.loads(items.read_text())
    written["manifest"] = "../elsewhere.yaml"
    items.write_text(json.dumps(written))

    with pytest.raises(OpenItemsError, match="not a file name in this directory"):
        tally(items)


def test_a_reader_never_overwrites_a_draft(tmp_path):
    draft(tmp_path, ITEMS)
    before = (tmp_path / DRAFT_NAME).read_bytes()
    with pytest.raises(OpenItemsError, match="exists"):
        draft(tmp_path, ITEMS)
    assert (tmp_path / DRAFT_NAME).read_bytes() == before


def test_an_item_for_a_claim_the_draft_lacks_writes_nothing(tmp_path):
    stray = OpenItem(id="x/value", claim="x", need=Need.VALUE, asks="?")
    with pytest.raises(OpenItemsError, match="x"):
        draft(tmp_path, (stray,))
    assert not (tmp_path / DRAFT_NAME).exists()
    assert not (tmp_path / ITEMS_NAME).exists()


def test_open_items_prints_the_tally_as_json(tmp_path, capsys):
    items = draft(tmp_path, ITEMS)
    fill(tmp_path, "auc", metric("0.912", "/auc", basis="inferred"))

    assert main(["open-items", str(items), "--format", "json"]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["claims"] == {
        "reader": 1,
        "bound": 1,
        "not_matching": 0,
        "open": 1,
        "outside": 0,
    }
    assert "inferred_counted_as_verified" not in printed
