import json
import pathlib
import shutil
from typing import Any

import anyio
import pytest
import yaml
from claims.cli import main as claims_main
from claims.manifest import load
from claims.models import Digest, Manifest
from claims.open_items import OpenItem, Source, tally, write_draft
from claims.verify import verify as run_verify
from mcp import Client
from provenance_core import chain
from repro import proposals
from repro.mcp_server import INSTRUCTIONS, build

PASSAGE = "the set of changes over which a relationship is invariant"

#: Text in the result files that no packet may carry: it is neither the matched cell nor a label.
ELSEWHERE = "unrelated-text-elsewhere-in-the-file"


def _candidate(pointer: str, reported: str = "0.9375") -> dict[str, Any]:
    return {
        "kind": "value",
        "artifact": "metrics",
        "name": "auc",
        "reported": reported,
        "locator": {"kind": "tree", "pointer": pointer},
        "basis": "inferred",
    }


@pytest.fixture
def project(tmp_path: pathlib.Path) -> pathlib.Path:
    root = tmp_path / "project"
    (root / "results").mkdir(parents=True)
    metrics = {"auc": {"held": 0.9375, "train": 0.99}, "notes": ELSEWHERE}
    (root / "results" / "metrics.json").write_text(json.dumps(metrics))
    rows = "\n".join(f"{ELSEWHERE}-{n},{n / 7:.6f}" for n in range(200))
    (root / "results" / "table.csv").write_text(f"split,acc\n{rows}\ntest,0.81\n")
    digest = Digest.of_file(root / "results" / "metrics.json").value
    (root / "paper.md").write_text("The AUC was 0.9375 on held-out data, over 3 seeds.\n")
    table = Digest.of_file(root / "results" / "table.csv").value

    (root / "repro.yaml").write_text(
        yaml.safe_dump(
            {
                "artifacts": [
                    {
                        "id": "metrics",
                        "path": "results/metrics.json",
                        "digest": {"algorithm": "sha256", "value": digest},
                    },
                    {
                        "id": "paper",
                        "path": "paper.md",
                        "digest": {
                            "algorithm": "sha256",
                            "value": Digest.of_file(root / "paper.md").value,
                        },
                    },
                ],
                "claims": [
                    {
                        "id": "auc",
                        "text": "The AUC was 0.9375 on held-out data.",
                        "evidence": [_candidate("/auc/held") | {"basis": "declared"}],
                    }
                ],
            },
            sort_keys=False,
        )
    )

    artifacts = [
        {
            "id": "metrics",
            "path": "../results/metrics.json",
            "digest": {"algorithm": "sha256", "value": digest},
        },
        {
            "id": "table",
            "path": "../results/table.csv",
            "digest": {"algorithm": "sha256", "value": table},
        },
    ]
    document = {
        "artifacts": artifacts,
        "claims": [
            {"id": "auc", "text": "The AUC was 0.9375 on held-out data."},
            {"id": "acc", "text": "Accuracy on the test split was 0.81."},
            {
                "id": "bound",
                "text": "Training AUC was 0.99.",
                "evidence": [_candidate("/auc/train", "0.99") | {"name": "train"}],
            },
            {"id": "unlisted", "text": "A claim no item names."},
        ],
    }
    for entry in document["claims"][2]["evidence"]:
        entry.pop("basis")
    items = (
        OpenItem(
            id="auc/value",
            claim="auc",
            need="value",
            asks="the address of this value",
            context={
                "text": "The AUC was 0.9375 on held-out data.",
                "line": 12,
                "printed": "0.9375",
                "value": "0.9375",
            },
            candidates=(_candidate("/auc/held"),),
            unique=True,
        ),
        OpenItem(
            id="acc/value",
            claim="acc",
            need="value",
            asks="the address of this value",
            context={"question": "Report the accuracy on the test split.", "values": ["0.81"]},
        ),
        OpenItem(
            id="bound/value",
            claim="bound",
            need="value",
            asks="the address of this value",
            context={"value": "0.99"},
        ),
    )
    source = Source(
        reader="test",
        reader_version="0",
        format="test",
        path="source.json",
        digest=Digest.of_text("{}").value,
    )
    write_draft(root / "draft", document, source, items)

    (root / "source.txt").write_text(f"A generalization is invariant: {PASSAGE} is its domain.\n")
    (root / "claims").mkdir()
    (root / "claims" / "woodward.yaml").write_text(
        "source:\n  citation: woodward\n  local: source.txt\nclaims: {}\n"
    )
    return root


def call(root: pathlib.Path, tool: str, arguments: dict[str, Any] | None = None):
    async def run():
        async with Client(build(root)) as client:
            return await client.call_tool(tool, arguments or {})

    return anyio.run(run)


def session(root: pathlib.Path):
    async def run():
        async with Client(build(root)) as client:
            return client.instructions, [tool.name for tool in (await client.list_tools()).tools]

    return anyio.run(run)


def tallied(project: pathlib.Path) -> dict[str, Any]:
    return tally(project / DRAFT_ITEMS).model_dump(mode="json")


def values(found: Any) -> list[Any]:
    if isinstance(found, dict):
        return [v for value in found.values() for v in values(value)]
    if isinstance(found, list):
        return [v for value in found for v in values(value)]
    return [found]


DRAFT_ITEMS = "draft/open-items.json"


def test_the_server_lists_every_tool_and_carries_the_procedure(project):
    instructions, tools = session(project)
    assert set(tools) == {
        "verify",
        "why",
        "stale",
        "numbers",
        "origins",
        "next_open_item",
        "get_open_item",
        "prereg_check",
        "results_verify",
        "citations_verify",
        "propose_binding",
        "pin_quote",
        "add_artifact",
        "mark_reviewed",
    }
    assert instructions == INSTRUCTIONS
    for rule in (
        "basis: inferred",
        "matched, inferred: not verified",
        "Pass absolute paths, or a `project` folder",
        "call mark_reviewed only for the items",
        "Never: edit open-items.json",
        "edit a pinned quotation",
        "ask the human to run them: prereg freeze, prereg register, results seal",
    ):
        assert rule in instructions


def test_verify_checks_the_manifest_and_writes_no_record(project):
    result = call(project, "verify", {"policy": "exploratory"})
    assert not result.is_error
    assert result.structured_content["counts"] == {"verified": 1}
    assert result.structured_content["assessment"]["passed"] is True
    assert not (project / ".repro").exists()


def test_verify_refuses_a_policy_it_does_not_know(project):
    result = call(project, "verify", {"policy": "lenient"})
    assert result.is_error
    assert result.structured_content["refused"] == "policy"


def test_why_accounts_for_one_claim(project):
    result = call(project, "why", {"claim": "auc"})
    assert result.structured_content["claim_id"] == "auc"
    assert result.structured_content["assertions"][0]["outcome"] == "verified"


def test_why_names_an_unknown_claim_as_an_error(project):
    result = call(project, "why", {"claim": "nope"})
    assert result.is_error
    assert result.structured_content["error"] == "UnknownClaimError"


def test_stale_says_no_command_is_declared(project):
    result = call(project, "stale")
    assert result.structured_content["regenerations"] == 0


def test_numbers_counts_what_a_text_prints(project):
    result = call(project, "numbers", {"texts": ["paper"]})
    assert not result.is_error
    (text,) = result.structured_content["texts"]
    assert [number["text"] for number in text["numbers"]] == ["0.9375", "3"]
    assert result.structured_content["counts"]["unbound"] == 2


def test_origins_compares_nothing_where_none_is_declared(project):
    result = call(project, "origins")
    assert result.structured_content["origins"]["origins"] == []


def test_items_are_handed_over_one_at_a_time_with_counts(project):
    first = call(project, "next_open_item", {"open_items": DRAFT_ITEMS}).structured_content
    assert first["item"] == "auc/value"
    assert (first["total"], first["remaining"], first["next_item"]) == (3, 2, "acc/value")
    assert first["printed"] == ["0.9375"]
    assert (first["sentence"], first["line"]) == ("The AUC was 0.9375 on held-out data.", 12)
    assert first["unique"] is True
    (candidate,) = first["candidates"]
    assert candidate["file"] == "../results/metrics.json"
    assert candidate["address"] == "/auc/held"
    assert candidate["labels"] == ["auc", "held"]
    assert candidate["stored"] == "0.9375"

    second = call(project, "next_open_item", {"open_items": DRAFT_ITEMS, "after": "auc/value"})
    assert second.structured_content["item"] == "acc/value"
    assert second.structured_content["next_item"] is None
    last = call(project, "next_open_item", {"open_items": DRAFT_ITEMS, "after": "acc/value"})
    assert last.structured_content["refused"] == "no_open_item"

    named = call(project, "get_open_item", {"open_items": DRAFT_ITEMS, "item": "bound/value"})
    assert named.structured_content["filled"] is True


def test_a_packet_carries_no_file_contents_beyond_the_cell_and_its_labels(project):
    for item in ("auc/value", "acc/value", "bound/value"):
        result = call(project, "get_open_item", {"open_items": DRAFT_ITEMS, "item": item})
        said = json.dumps(result.structured_content) + result.content[0].text
        assert ELSEWHERE not in said
        assert "0.99" not in said or item == "bound/value"
        assert len(said) < 2000


def test_a_matched_proposal_is_written_inferred_and_never_called_verified(project):
    result = call(
        project,
        "propose_binding",
        {"open_items": DRAFT_ITEMS, "claim": "auc", "assertion": _candidate("/auc/held")},
    )
    assert not result.is_error
    found = result.structured_content
    assert found["said"] == "matched, inferred: not verified"
    assert found["outcome"] == "matched"
    assert found["counted_as_verified"] is False
    assert "verified" not in values(found)
    assert "verified" not in [word.strip(",:") for word in result.content[0].text.split()][:2]

    draft = yaml.safe_load((project / "draft" / "repro.draft.yaml").read_text())
    (written,) = draft["claims"][0]["evidence"]
    assert written["basis"] == "inferred"

    why = call(project, "why", {"claim": "auc", "manifest": "draft/repro.draft.yaml"})
    assert why.structured_content["assertions"][0]["outcome"] == "matched"
    assert "verified" not in why.structured_content["inferred"]

    after = tallied(project)
    assert after["items"]["filled_by_inferred"] == 1
    assert "verified" not in after["assertions"]["inferred"]


def test_a_proposal_that_does_not_match_is_reported_as_what_the_check_found(project):
    result = call(
        project,
        "propose_binding",
        {
            "open_items": DRAFT_ITEMS,
            "claim": "auc",
            "assertion": _candidate("/auc/train"),
        },
    )
    assert result.structured_content["outcome"] == "mismatch"
    assert result.structured_content["said"] == "mismatch, inferred: not verified"


def unchanged(project: pathlib.Path):
    draft = project / "draft" / "repro.draft.yaml"
    before = draft.read_bytes()
    return lambda: draft.read_bytes() == before


@pytest.mark.parametrize(
    ("arguments", "rule"),
    [
        ({"basis": "declared"}, "basis"),
        ({"assertion": _candidate("/auc/held") | {"basis": "declared"}}, "basis"),
        (
            {
                "assertion": _candidate("/auc/held")
                | {"reviewed": {"who": "x", "when": "2026-01-01"}}
            },
            "reviewed",
        ),
        ({"assertion": _candidate("/auc/held", "0.94")}, "reported_changed"),
        ({"claim": "unlisted"}, "claim_not_in_open_items"),
        ({"claim": "missing"}, "claim_not_in_open_items"),
        ({"claim": "bound", "assertion": _candidate("/auc/train", "0.99")}, "fills_no_open_item"),
        (
            {"assertion": {"kind": "quote", "artifact": "metrics", "text": "x"}},
            "fills_no_open_item",
        ),
        ({"assertion": _candidate("/auc/held") | {"artifact": "paper"}}, "artifact_undeclared"),
        ({"open_items": "../outside/open-items.json"}, "no_project"),
    ],
)
def test_propose_binding_refuses_and_writes_nothing(project, arguments, rule):
    same = unchanged(project)
    given = {"open_items": DRAFT_ITEMS, "claim": "auc", "assertion": _candidate("/auc/held")}
    result = call(project, "propose_binding", given | arguments)
    assert result.is_error
    assert result.structured_content["refused"] == rule
    assert same()


def test_a_value_the_source_states_in_a_task_cannot_be_changed(project):
    proposal = {"kind": "value", "artifact": "table", "name": "acc", "reported": "0.810"}
    proposal["locator"] = {"kind": "table", "column": "acc", "where": {"split": "test"}}
    result = call(
        project,
        "propose_binding",
        {"open_items": DRAFT_ITEMS, "claim": "acc", "assertion": proposal},
    )
    assert result.structured_content["refused"] == "reported_changed"
    result = call(
        project,
        "propose_binding",
        {"open_items": DRAFT_ITEMS, "claim": "acc", "assertion": proposal | {"reported": "0.81"}},
    )
    assert result.structured_content["said"] == "matched, inferred: not verified"


def test_a_symlink_out_of_the_root_is_refused(project, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "repro.yaml").write_text((project / "repro.yaml").read_text())
    (project / "elsewhere").symlink_to(outside)
    result = call(project, "verify", {"manifest": "elsewhere/repro.yaml"})
    assert result.structured_content["refused"] == "outside_root"
    result = call(project, "citations_verify", {"claims": "elsewhere"})
    assert result.structured_content["refused"] == "outside_root"


def test_a_draft_named_through_a_symlink_out_of_the_root_is_refused(project, tmp_path):
    away = tmp_path / "away"
    (project / "draft").rename(away)
    (project / "draft").symlink_to(away)
    result = call(
        project,
        "propose_binding",
        {"open_items": DRAFT_ITEMS, "claim": "auc", "assertion": _candidate("/auc/held")},
    )
    assert result.structured_content["refused"] == "outside_root"


def test_a_manifest_naming_a_file_outside_the_root_is_refused(project, tmp_path):
    manifest = yaml.safe_load((project / "repro.yaml").read_text())
    manifest["artifacts"][0]["path"] = str(tmp_path / "metrics.json")
    (project / "repro.yaml").write_text(yaml.safe_dump(manifest))
    result = call(project, "verify")
    assert result.structured_content["refused"] == "outside_root"


def test_pin_quote_writes_a_passage_that_resolves(project):
    claims = project / "claims" / "woodward.yaml"
    checked = call(
        project,
        "pin_quote",
        {"claims_file": "claims/woodward.yaml", "id": "domain", "quote": PASSAGE, "check": True},
    )
    assert checked.structured_content["written"] is False
    assert "domain" not in yaml.safe_load(claims.read_text())["claims"]

    result = call(
        project,
        "pin_quote",
        {"claims_file": "claims/woodward.yaml", "id": "domain", "quote": PASSAGE},
    )
    assert result.structured_content["written"] is True
    assert yaml.safe_load(claims.read_text())["claims"]["domain"]["quotes"][0]["exact"] == PASSAGE


def test_pin_quote_never_edits_a_pinned_quotation(project):
    claims = project / "claims" / "woodward.yaml"
    arguments = {"claims_file": "claims/woodward.yaml", "id": "domain", "quote": PASSAGE}
    call(project, "pin_quote", arguments)
    before = claims.read_bytes()
    result = call(project, "pin_quote", arguments | {"quote": "A generalization is invariant"})
    assert result.structured_content["refused"] == "pin_refused"
    assert claims.read_bytes() == before


def test_pin_quote_writes_nothing_for_a_passage_the_source_lacks(project):
    claims = project / "claims" / "woodward.yaml"
    before = claims.read_bytes()
    result = call(
        project,
        "pin_quote",
        {"claims_file": "claims/woodward.yaml", "id": "nope", "quote": "a sentence it lacks"},
    )
    assert result.structured_content["refused"] == "pin_refused"
    assert claims.read_bytes() == before


def test_citations_verify_reports_what_the_command_found(project):
    arguments = {"claims_file": "claims/woodward.yaml", "id": "domain", "quote": PASSAGE}
    call(project, "pin_quote", arguments)
    result = call(project, "citations_verify")
    assert result.structured_content["command"] == "citations verify"
    assert result.structured_content["found"]["quotes"] == 1
    assert result.structured_content["found"]["counts"]["found"] == 1


def test_prereg_check_and_results_verify_report_a_project_without_their_records(project):
    prereg = call(project, "prereg_check").structured_content
    assert prereg["command"] == "prereg check"
    assert prereg["exit"] == 2
    results = call(project, "results_verify", {"files": True}).structured_content
    assert results["command"] == "results verify"
    assert results["exit"] != 0


AUC_LINE = "  text: The AUC was 0.9375 on held-out data.\n"
QUOTE = '{kind: quote, artifact: table, text: "test,0.81"}'


@pytest.mark.parametrize(
    "layout",
    [
        "",
        "  evidence: []  # nothing yet\n",
        f"  evidence:\n  - {QUOTE}  # the reader's quotation\n  # a comment after the list\n",
        f"  evidence:\n    - {QUOTE}\n",
    ],
)
def test_a_proposal_inserts_one_block_and_leaves_every_other_byte(project, layout):
    draft = project / "draft" / "repro.draft.yaml"
    text = draft.read_text()
    assert AUC_LINE in text
    text = "# written by a reader, then annotated\n" + text.replace(AUC_LINE, AUC_LINE + layout)
    draft.write_text(text + "# the end\n")
    old = draft.read_text()

    result = call(
        project,
        "propose_binding",
        {"open_items": DRAFT_ITEMS, "claim": "auc", "assertion": _candidate("/auc/held")},
    )
    assert result.structured_content["said"] == "matched, inferred: not verified"
    new = draft.read_text()
    start = next(i for i, (a, b) in enumerate(zip(old, new, strict=False)) if a != b)
    inserted = len(new) - len(old)
    assert new[:start] == old[:start]
    assert new[start + inserted :] == old[start:]
    assert '"basis": "inferred"' in new[start : start + inserted]
    claim = next(c for c in yaml.safe_load(new)["claims"] if c["id"] == "auc")
    assert claim["evidence"][-1] == _candidate("/auc/held")


def test_a_claim_the_draft_does_not_hold_is_refused(project):
    draft = project / "draft" / "repro.draft.yaml"
    document = yaml.safe_load(draft.read_text())
    document["claims"] = [c for c in document["claims"] if c["id"] != "acc"]
    draft.write_text(yaml.safe_dump(document, sort_keys=False))
    proposal = {"kind": "value", "artifact": "table", "name": "acc", "reported": "0.81"}
    proposal["locator"] = {"kind": "table", "column": "acc", "where": {"split": "test"}}
    result = call(
        project,
        "propose_binding",
        {"open_items": DRAFT_ITEMS, "claim": "acc", "assertion": proposal},
    )
    assert result.structured_content["refused"] == "claim_not_in_draft"


@pytest.mark.parametrize(
    ("assertion", "rule"),
    [
        ({k: v for k, v in _candidate("/auc/held").items() if k != "reported"}, "missing"),
        (_candidate("/auc/held") | {"reported": "9" * 500}, "too_long"),
        (_candidate("/" + "a" * 5000), "too_long"),
    ],
)
def test_a_missing_or_oversized_field_is_refused(project, assertion, rule):
    same = unchanged(project)
    result = call(
        project,
        "propose_binding",
        {"open_items": DRAFT_ITEMS, "claim": "auc", "assertion": assertion},
    )
    assert result.structured_content["refused"] == rule
    assert same()


@pytest.mark.parametrize(
    "arguments",
    [
        {"quote": "--url=https://example.com/"},
        {"quote": "-h"},
        {"quote": "x" * 5000},
    ],
)
def test_no_argument_to_pin_quote_ends_the_server_or_reaches_the_network(project, arguments):
    claims = project / "claims" / "woodward.yaml"
    before = claims.read_bytes()

    async def run():
        with anyio.fail_after(30):
            async with Client(build(project)) as client:
                given = {"claims_file": "claims/woodward.yaml", "id": "q", "quote": PASSAGE}
                refused = await client.call_tool("pin_quote", given | arguments)
                after = await client.call_tool("next_open_item", {"open_items": DRAFT_ITEMS})
                return refused, after

    refused, after = anyio.run(run)
    assert refused.is_error
    assert refused.structured_content["refused"] in ("pin_refused", "too_long")
    assert not after.is_error
    assert claims.read_bytes() == before


@pytest.mark.parametrize(("field", "value"), [("id", "--check"), ("section", "--recapture")])
def test_a_value_beginning_with_a_dash_is_read_as_the_value(project, field, value):
    given = {"claims_file": "claims/woodward.yaml", "id": "q", "quote": PASSAGE, field: value}
    result = call(project, "pin_quote", given)
    assert result.structured_content["written"] is True
    claims = yaml.safe_load((project / "claims" / "woodward.yaml").read_text())["claims"]
    if field == "id":
        assert "--check" in claims
    else:
        assert claims["q"]["quotes"][0]["section"] == "--recapture"


def propose_auc(project: pathlib.Path, pointer: str):
    given = {"open_items": DRAFT_ITEMS, "claim": "auc", "assertion": _candidate(pointer)}
    return call(project, "propose_binding", given)


def auc_evidence(project: pathlib.Path) -> list:
    draft = yaml.safe_load((project / "draft" / "repro.draft.yaml").read_text())
    return next(c for c in draft["claims"] if c["id"] == "auc").get("evidence", [])


def test_a_retry_after_a_mismatch_replaces_it_and_nothing_else(project):
    draft = project / "draft" / "repro.draft.yaml"
    first = propose_auc(project, "/auc/train").structured_content
    assert (first["outcome"], first["attempt"], first["replaced"]) == ("mismatch", 1, False)
    old = draft.read_text()
    second = propose_auc(project, "/auc/held").structured_content
    assert (second["outcome"], second["attempt"], second["replaced"]) == ("matched", 2, True)
    assert auc_evidence(project) == [_candidate("/auc/held")]
    new = draft.read_text()
    old_line = json.dumps(_candidate("/auc/train"))
    assert new.replace(json.dumps(_candidate("/auc/held")), old_line) == old


def test_a_matched_assertion_is_never_replaced(project):
    propose_auc(project, "/auc/held")
    same = unchanged(project)
    result = propose_auc(project, "/auc/train")
    assert result.structured_content["refused"] == "fills_no_open_item"
    assert same()


def test_an_inferred_assertion_the_agent_did_not_propose_is_never_replaced(project):
    draft = project / "draft" / "repro.draft.yaml"
    held = json.dumps(_candidate("/auc/train"))
    draft.write_text(draft.read_text().replace(AUC_LINE, AUC_LINE + f"  evidence:\n  - {held}\n"))
    same = unchanged(project)
    result = propose_auc(project, "/auc/held")
    assert result.structured_content["refused"] == "fills_no_open_item"
    assert same()


def test_attempts_are_appended_to_a_hash_chain(project):
    record = project / "draft" / ".repro" / "attempts.jsonl"
    propose_auc(project, "/auc/train")
    first = record.read_bytes()
    propose_auc(project, "/auc/held")
    assert record.read_bytes().startswith(first)
    assert chain.verify(record)[0] is chain.ChainStatus.INTACT
    events = chain.read_ledger(record)
    assert [(e["event"], e["item"], e["attempt"], e["outcome"]) for e in events] == [
        ("attempt", "auc/value", 1, "mismatch"),
        ("attempt", "auc/value", 2, "matched"),
    ]
    assert events[1]["prev_hash"] != events[0]["prev_hash"]
    assert events[0]["assertion"]["locator"] == {"kind": "tree", "pointer": "/auc/train"}
    assert events[0]["open_items"] == "open-items.json"


def test_an_edited_record_of_attempts_is_reported(project, capsys):
    record = project / "draft" / ".repro" / "attempts.jsonl"
    propose_auc(project, "/auc/train")
    propose_auc(project, "/auc/train")
    record.write_text(record.read_text().replace('"mismatch"', '"matched"', 1))
    counted = tallied(project)
    assert counted["attempt_record"]["status"] != "intact"
    assert claims_main(["open-items", str(project / DRAFT_ITEMS)]) == 0
    assert "does not verify" in capsys.readouterr().out
    refused = propose_auc(project, "/auc/held")
    assert refused.is_error


def test_a_warning_comes_at_the_sixth_attempt_and_not_the_fifth(project, capsys):
    for attempt in range(1, 6):
        result = propose_auc(project, "/auc/train").structured_content
        assert (result["attempt"], result["warning"]) == (attempt, "")
    sixth = propose_auc(project, "/auc/held").structured_content
    assert sixth["warning"] == (
        "item auc/value matched on attempt 6: check the binding is the claim's own value, "
        "not a search"
    )
    assert sixth["said"] == "matched, inferred: not verified"
    assert auc_evidence(project)[0]["basis"] == "inferred"

    counted = tallied(project)
    assert counted["attempts"] == {"auc/value": 6}
    assert counted["over_attempt_limit"] == ["auc/value"]
    assert counted["items"]["filled_by_inferred"] == 1

    assert claims_main(["open-items", str(project / DRAFT_ITEMS)]) == 0
    assert "auc/value: 6 attempts, over 5" in capsys.readouterr().out


def test_five_attempts_are_counted_and_not_flagged(project, capsys):
    for _ in range(5):
        propose_auc(project, "/auc/train")
    assert claims_main(["open-items", str(project / DRAFT_ITEMS), "--format", "json"]) == 0
    counted = json.loads(capsys.readouterr().out)
    assert counted["attempts"] == {"auc/value": 5}
    assert counted["over_attempt_limit"] == []
    (fill,) = [f for c in counted["per_claim"] for f in c["items"] if f["id"] == "auc/value"]
    assert fill["attempts"] == 5


# ------------------------------------------------------------------------------ add_artifact


@pytest.fixture
def committed(project: pathlib.Path) -> pathlib.Path:
    (project / "paper.txt").write_text("The AUC was 0.9375 on held-out data.\n")
    (project / "pointer.bin").write_text(
        "version https://git-lfs.github.com/spec/v1\noid sha256:" + "0" * 64 + "\nsize 1\n"
    )
    return project


def session_calls(root: pathlib.Path, steps: list) -> list:
    """Calls in one session, where a step may be a function run between them."""

    async def run():
        found = []
        async with Client(build(root)) as client:
            for step in steps:
                if callable(step):
                    step()
                else:
                    found.append(await client.call_tool(*step))
        return found

    return anyio.run(run)


def add(path: str, **more) -> tuple[str, dict]:
    return ("add_artifact", {"open_items": DRAFT_ITEMS, "path": path, **more})


def test_a_committed_file_is_added_inferred_and_nothing_else_changes(committed):
    draft = committed / "draft" / "repro.draft.yaml"
    old = draft.read_text()
    (result,) = session_calls(committed, [add("paper.txt", id="paper")])
    assert not result.is_error, result.content[0].text
    new = draft.read_text()
    line = json.dumps(result.structured_content["artifact"])
    assert new.replace(f"- {line}\n", "", 1) == old
    artifact = yaml.safe_load(new)["artifacts"][-1]
    assert artifact["basis"] == "inferred"
    assert artifact["path"] == "../paper.txt"
    assert artifact["media_type"] == "text/plain"


def test_add_artifact_refuses_and_writes_nothing(committed, tmp_path, monkeypatch):
    (tmp_path / "away.txt").write_text("x")
    (committed / "away").symlink_to(tmp_path / "away.txt")
    same = unchanged(committed)
    for path, rule, said in [
        ("../away.txt", "outside_root", ""),
        ("away", "outside_root", ""),
        ("results/metrics.json", "already_declared", ""),
        ("results", "not_a_file", "directory"),
        ("absent.txt", "not_a_file", ""),
        ("pointer.bin", "lfs_pointer", ""),
    ]:
        (result,) = session_calls(committed, [add(path)])
        assert result.structured_content["refused"] == rule, path
        assert said in result.structured_content["detail"]
    monkeypatch.setattr(proposals, "MAX_ARTIFACT_BYTES", 10)
    (result,) = session_calls(committed, [add("paper.txt")])
    assert result.structured_content["refused"] == "too_large"
    monkeypatch.undo()
    assert same()


def manifest_over(tmp_path: pathlib.Path, artifact: dict) -> Manifest:
    data = tmp_path / "metrics.json"
    data.write_text('{"auc": 0.9375}')
    artifact = {
        "id": "metrics",
        "path": "metrics.json",
        "digest": {"algorithm": "sha256", "value": Digest.of_file(data).value},
        **artifact,
    }
    assertion = {k: v for k, v in _candidate("/auc").items() if k != "basis"}
    text = yaml.safe_dump(
        {"artifacts": [artifact], "claims": [{"id": "c", "text": "t", "evidence": [assertion]}]}
    )
    (tmp_path / "repro.yaml").write_text(text)
    return load(tmp_path / "repro.yaml")


def test_a_declared_assertion_over_an_inferred_artifact_counts_as_inferred(tmp_path):
    report = run_verify(manifest_over(tmp_path, {"basis": "inferred"}))
    (decision,) = report.decisions
    assert decision.said == "matched"
    assert report.counts == {"inferred_matched": 1}


def test_a_reviewed_artifact_counts_as_declared(tmp_path):
    review = {"who": "An Author", "when": "2026-10-14"}
    report = run_verify(manifest_over(tmp_path, {"basis": "inferred", "reviewed": review}))
    assert report.counts == {"verified": 1}


# ------------------------------------------------------------------- the project of each call


def calls(root: pathlib.Path | None, steps: list) -> list:
    return session_calls(root, steps)


def copy_project(source: pathlib.Path, target: pathlib.Path) -> pathlib.Path:
    shutil.copytree(source, target, symlinks=True)
    return target


def test_each_call_follows_the_project_its_path_is_in(project, tmp_path, monkeypatch):
    other = copy_project(project, tmp_path / "other")
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    monkeypatch.chdir(unrelated)
    in_a, in_b, no_path, named = calls(
        None,
        [
            ("verify", {"manifest": str(project / "repro.yaml"), "policy": "exploratory"}),
            ("next_open_item", {"open_items": str(other / DRAFT_ITEMS)}),
            ("verify", {"policy": "exploratory"}),
            ("verify", {"project": str(project), "policy": "exploratory"}),
        ],
    )
    assert (in_a.structured_content["root"], in_a.structured_content["counts"]) == (
        project.as_posix(),
        {"verified": 1},
    )
    assert in_b.structured_content["root"] == other.as_posix()
    assert no_path.structured_content["root"] == other.as_posix()
    assert named.structured_content["root"] == project.as_posix()


def test_with_no_project_anywhere_a_call_says_to_pass_one(tmp_path, monkeypatch):
    nowhere = tmp_path / "nowhere"
    nowhere.mkdir()
    (nowhere / "stray.yaml").write_text("claims: []\n")
    monkeypatch.chdir(nowhere)
    plain, under_none = calls(None, [("verify", {}), ("verify", {"manifest": "stray.yaml"})])
    assert plain.structured_content["detail"] == "no project: pass a path or a project"
    assert under_none.structured_content["refused"] == "no_project"


def test_a_symlink_belongs_to_the_project_it_sits_in(project, tmp_path):
    other = copy_project(project, tmp_path / "other")
    (project / "to-other").symlink_to(other)
    (project / "also-here").symlink_to(project / "results")
    out, kept = calls(
        project,
        [
            ("verify", {"manifest": str(project / "to-other" / "repro.yaml")}),
            ("next_open_item", {"open_items": str(project / DRAFT_ITEMS)}),
        ],
    )
    assert out.structured_content["refused"] == "outside_root"
    assert kept.structured_content["root"] == project.as_posix()
    (inside_link,) = calls(project, [("verify", {"manifest": str(project / "repro.yaml")})])
    assert inside_link.structured_content["root"] == project.as_posix()


def test_a_path_that_walks_out_of_its_project_is_refused(project, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "repro.yaml").write_text((project / "repro.yaml").read_text())
    (project / "elsewhere").symlink_to(outside / "repro.yaml")
    (result,) = calls(project, [("verify", {"manifest": str(project / "elsewhere")})])
    assert result.structured_content["refused"] == "outside_root"


def test_a_crlf_draft_keeps_its_line_endings(project):
    draft = project / "draft" / "repro.draft.yaml"
    draft.write_bytes(draft.read_bytes().replace(b"\n", b"\r\n"))
    old = draft.read_bytes()
    result = propose_auc(project, "/auc/held")
    assert result.structured_content["said"] == "matched, inferred: not verified"
    new = draft.read_bytes()
    assert new.count(b"\n") == new.count(b"\r\n")
    start = next(i for i, (a, b) in enumerate(zip(old, new, strict=False)) if a != b)
    inserted = len(new) - len(old)
    assert new[:start] + new[start + inserted :] == old


# ----------------------------------------------------------------------------- mark_reviewed


@pytest.fixture
def reviewer(tmp_path, monkeypatch):
    config = tmp_path / "gitconfig"
    config.write_text("[user]\n\tname = A Reviewer\n\temail = reviewer@example.org\n")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    return config


def review(project: pathlib.Path, items: list[str]):
    (result,) = calls(
        project,
        [("mark_reviewed", {"open_items": DRAFT_ITEMS, "items": items, "note": "looked fine"})],
    )
    return result


def test_mark_reviewed_promotes_an_item_and_records_the_chat(project, reviewer):
    propose_auc(project, "/auc/held")
    result = review(project, ["auc/value"])
    assert not result.is_error, result.content[0].text
    (written,) = auc_evidence(project)
    assert written["basis"] == "inferred"
    assert written["reviewed"]["who"] == "A Reviewer <reviewer@example.org>"
    assert written["reviewed"]["how"].startswith("approved in chat via ")
    assert written["reviewed"]["how"].endswith(": looked fine")
    assert len(written["reviewed"]["digest"]) == 64
    counts = tallied(project)["items"]
    assert (counts["filled_by_inferred"], counts["filled_by_declared_only"]) == (0, 2)
    (checked,) = calls(
        project, [("verify", {"manifest": str(project / "draft" / "repro.draft.yaml")})]
    )
    assert checked.structured_content["counts"] == {"verified": 2, "not_offered": 2}


def test_a_review_lapses_when_what_it_accepted_changes(project, reviewer):
    propose_auc(project, "/auc/held")
    review(project, ["auc/value"])
    draft = project / "draft" / "repro.draft.yaml"
    draft.write_text(draft.read_text().replace('"name": "auc"', '"name": "auc, renamed"'))
    counts = tallied(project)["items"]
    assert counts["filled_by_inferred"] == 1
    (checked,) = calls(project, [("verify", {"manifest": str(draft)})])
    assert checked.structured_content["counts"] == {
        "inferred_matched": 1,
        "verified": 1,
        "not_offered": 2,
    }


def test_mark_reviewed_refuses_what_did_not_match_and_a_project_with_no_git_user(project, reviewer):
    propose_auc(project, "/auc/train")
    same = unchanged(project)
    assert review(project, ["auc/value"]).structured_content["refused"] == "not_matched"
    reviewer.write_text("")
    propose_auc(project, "/auc/held")
    same = unchanged(project)
    assert review(project, ["auc/value"]).structured_content["refused"] == "no_reviewer"
    assert same()
