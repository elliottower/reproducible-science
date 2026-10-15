import json
import os
import pathlib
import subprocess
from typing import Any

import anyio
import pytest
import yaml
from claims.cli import main as claims_main
from claims.manifest import load
from claims.models import Digest, Manifest
from claims.open_items import OpenItem, Source, write_draft
from claims.verify import verify as run_verify
from mcp import Client
from mcp.types import ListRootsResult, Root
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
        "open_items",
        "next_open_item",
        "get_open_item",
        "prereg_check",
        "results_verify",
        "citations_verify",
        "propose_binding",
        "pin_quote",
        "set_project",
        "add_artifact",
    }
    assert instructions == INSTRUCTIONS
    for rule in (
        "basis: inferred",
        "matched, inferred: not verified",
        "call set_project with the project folder first",
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


def test_open_items_counts_and_lists_each_item(project):
    result = call(project, "open_items", {"open_items": DRAFT_ITEMS})
    found = result.structured_content
    assert found["items"]["total"] == 3
    assert found["items"]["open"] == 2
    assert [entry["item"] for entry in found["list"]] == ["auc/value", "acc/value", "bound/value"]
    assert [entry["filled"] for entry in found["list"]] == [False, False, True]


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

    after = call(project, "open_items", {"open_items": DRAFT_ITEMS}).structured_content
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
        ({"open_items": "../outside/open-items.json"}, "outside_root"),
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
                after = await client.call_tool("open_items", {"open_items": DRAFT_ITEMS})
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


def roots_call(
    server_root: pathlib.Path, root: pathlib.Path, tool: str, arguments: dict, mode: str = "auto"
):
    async def list_roots(context) -> ListRootsResult:
        return ListRootsResult(roots=[Root(uri=root.as_uri())])

    async def run():
        async with Client(build(server_root), list_roots_callback=list_roots, mode=mode) as client:
            return await client.call_tool(tool, arguments)

    return anyio.run(run)


@pytest.mark.parametrize("mode", ["auto", "legacy"])
def test_a_client_that_offers_roots_names_the_project(project, tmp_path, mode):
    elsewhere = tmp_path / "started-here"
    elsewhere.mkdir()
    result = roots_call(elsewhere, project, "verify", {"policy": "exploratory"}, mode)
    assert not result.is_error
    assert result.structured_content["root"] == project.as_posix()
    assert result.structured_content["counts"] == {"verified": 1}

    result = roots_call(project, elsewhere, "verify", {}, mode)
    assert result.structured_content["root"] == elsewhere.as_posix()
    assert result.structured_content["error"] == "ManifestError"


def test_a_client_root_confines_every_path(project):
    result = roots_call(
        project.parent, project, "verify", {"manifest": "../project/../outside/repro.yaml"}
    )
    assert result.structured_content["refused"] == "outside_root"
    result = roots_call(
        project.parent, project / "draft", "open_items", {"open_items": "open-items.json"}
    )
    assert not result.is_error
    result = roots_call(project.parent, project / "draft", "verify", {"manifest": "../repro.yaml"})
    assert result.structured_content["refused"] == "outside_root"


def calls(server_root: pathlib.Path | None, steps: list[tuple[str, dict]], roots=None):
    """Several calls in one session, as an agent makes them."""

    async def list_roots(context) -> ListRootsResult:
        return ListRootsResult(roots=[Root(uri=root.as_uri()) for root in roots])

    async def run():
        callback = list_roots if roots else None
        async with Client(build(server_root), list_roots_callback=callback) as client:
            return [await client.call_tool(tool, arguments) for tool, arguments in steps]

    return anyio.run(run)


def test_set_project_names_the_root_for_the_rest_of_the_session(project, tmp_path):
    named, verified = calls(
        tmp_path,
        [("set_project", {"path": str(project)}), ("verify", {"policy": "exploratory"})],
        roots=[tmp_path],
    )
    assert named.structured_content == {"root": project.as_posix()}
    assert verified.structured_content["root"] == project.as_posix()
    assert verified.structured_content["counts"] == {"verified": 1}


@pytest.mark.parametrize("target", ["empty", "file", "missing"])
def test_set_project_refuses_what_is_not_a_project(project, tmp_path, target):
    (tmp_path / "empty").mkdir()
    (tmp_path / "file").write_text("x")
    refused, verified = calls(
        project,
        [("set_project", {"path": str(tmp_path / target)}), ("verify", {"policy": "exploratory"})],
    )
    assert refused.is_error
    assert refused.structured_content["refused"] == "not_a_project"
    assert verified.structured_content["root"] == project.as_posix()


def test_the_project_is_found_above_the_working_directory(project, monkeypatch):
    monkeypatch.chdir(project / "results")
    (result,) = calls(None, [("verify", {"policy": "exploratory"})])
    assert result.structured_content["root"] == project.as_posix()
    assert result.structured_content["counts"] == {"verified": 1}


def test_with_no_project_every_tool_says_to_call_set_project(project, tmp_path, monkeypatch):
    nowhere = tmp_path / "nowhere"
    nowhere.mkdir()
    monkeypatch.chdir(nowhere)
    proposal = {"open_items": DRAFT_ITEMS, "claim": "auc", "assertion": _candidate("/auc/held")}
    pin = {"claims_file": "claims/woodward.yaml", "id": "q", "quote": PASSAGE}
    results = calls(None, [("propose_binding", proposal), ("pin_quote", pin), ("verify", {})])
    for result in results:
        assert result.is_error
        assert result.structured_content["refused"] == "no_project"
        assert result.content[0].text == "no project: call set_project"


def test_paths_stay_inside_the_project_set_project_named(project, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "repro.yaml").write_text((project / "repro.yaml").read_text())
    (project / "elsewhere").symlink_to(outside)
    results = calls(
        tmp_path,
        [
            ("set_project", {"path": str(project)}),
            ("verify", {"manifest": "elsewhere/repro.yaml"}),
            ("verify", {"manifest": "../outside/repro.yaml"}),
            ("verify", {"manifest": str(outside / "repro.yaml")}),
        ],
    )
    assert results[0].structured_content["root"] == project.as_posix()
    for result in results[1:]:
        assert result.structured_content["refused"] == "outside_root"


def test_a_folder_holding_only_a_plan_is_a_project(tmp_path, monkeypatch):
    study = tmp_path / "study"
    (study / "analysis").mkdir(parents=True)
    (study / "PREREG.md").write_text("# Does the plan mark the project?\n")
    (tmp_path / "paper-only" / "paper").mkdir(parents=True)
    named, refused = calls(
        tmp_path,
        [
            ("set_project", {"path": str(study)}),
            ("set_project", {"path": str(tmp_path / "paper-only")}),
        ],
    )
    assert named.structured_content == {"root": study.as_posix()}
    assert refused.structured_content["refused"] == "not_a_project"
    monkeypatch.chdir(study / "analysis")
    (found,) = calls(None, [("prereg_check", {})])
    assert found.structured_content["root"] == study.as_posix()


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
    record = project / ".repro" / "agent.jsonl"
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
    assert events[0]["session"] != events[1]["session"]
    assert events[0]["open_items"] == DRAFT_ITEMS


def test_an_edited_record_of_attempts_is_reported(project, capsys):
    record = project / ".repro" / "agent.jsonl"
    propose_auc(project, "/auc/train")
    propose_auc(project, "/auc/train")
    record.write_text(record.read_text().replace('"mismatch"', '"matched"', 1))
    counted = call(project, "open_items", {"open_items": DRAFT_ITEMS}).structured_content
    assert counted["agent_record"]["status"] != "intact"
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

    counted = call(project, "open_items", {"open_items": DRAFT_ITEMS}).structured_content
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


def test_set_project_is_refused_outside_the_clients_roots_and_logged_inside(project, tmp_path):
    other = tmp_path / "other"
    (other / "claims").mkdir(parents=True)
    refused, named, switched = calls(
        tmp_path,
        [
            ("set_project", {"path": str(project)}),
            ("set_project", {"path": str(other)}),
            ("set_project", {"path": str(other)}),
        ],
        roots=[other],
    )
    assert refused.structured_content["refused"] == "outside_client_roots"
    assert named.structured_content == {"root": other.as_posix()}
    assert not (project / ".repro" / "agent.jsonl").exists()
    events = chain.read_ledger(other / ".repro" / "agent.jsonl")
    assert [(e["event"], e["root"]) for e in events] == [("set_project", other.as_posix())] * 2
    assert switched.structured_content["root"] == other.as_posix()


# ------------------------------------------------------------------------------ add_artifact


def git(root: pathlib.Path, *args: str) -> None:
    # A hook's `GIT_DIR` outranks the directory named, so the environment is cleaned first.
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
        cwd=root,
        check=True,
        capture_output=True,
        env=env,
    )


@pytest.fixture
def committed(project: pathlib.Path) -> pathlib.Path:
    (project / "paper.txt").write_text("The AUC was 0.9375 on held-out data.\n")
    (project / "pointer.bin").write_text(
        "version https://git-lfs.github.com/spec/v1\noid sha256:" + "0" * 64 + "\nsize 1\n"
    )
    git(project, "init", "-q")
    git(project, "add", ".")
    git(project, "commit", "-q", "-m", "start")
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
    assert result.structured_content["by"].startswith("commit ")
    new = draft.read_text()
    line = json.dumps(result.structured_content["artifact"])
    assert new.replace(f"- {line}\n", "", 1) == old
    artifact = yaml.safe_load(new)["artifacts"][-1]
    assert artifact["basis"] == "inferred"
    assert artifact["path"] == "../paper.txt"
    assert artifact["media_type"] == "text/plain"
    events = chain.read_ledger(committed / ".repro" / "agent.jsonl")
    assert events[-1]["event"] == "add_artifact"


def test_add_artifact_refuses_and_writes_nothing(committed, tmp_path, monkeypatch):
    (committed / "untracked.txt").write_text("written in the session\n")
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
    (result,) = session_calls(committed, [add("untracked.txt")])
    assert result.structured_content["refused"] == "not_vouched"
    assert "commit it or record it with results run first" in result.structured_content["detail"]
    assert same()


def test_a_file_committed_during_the_session_is_refused(committed):
    def commit_one():
        (committed / "made.txt").write_text("made by the agent\n")
        git(committed, "add", "made.txt")
        git(committed, "commit", "-q", "-m", "made")

    (result,) = session_calls(committed, [commit_one, add("made.txt")])
    assert result.structured_content["refused"] == "not_vouched"
    assert (
        "committed or changed during this session; a human must add it"
        in (result.structured_content["detail"])
    )
    (later,) = session_calls(committed, [add("made.txt")])
    assert not later.is_error


def test_a_file_changed_after_the_session_started_is_refused(committed):
    def edit():
        (committed / "paper.txt").write_text("The AUC was 0.99 on held-out data.\n")

    def commit_edit():
        git(committed, "commit", "-q", "-am", "edit")

    (changed, committed_too) = session_calls(
        committed, [edit, add("paper.txt"), commit_edit, add("paper.txt")]
    )
    for result in (changed, committed_too):
        assert result.structured_content["refused"] == "not_vouched"
        assert "a human must add it" in result.structured_content["detail"]


def test_a_run_output_the_ledger_recorded_before_the_session_is_added(committed):
    out = committed / "results" / "fresh.json"
    out.write_text('{"auc": 0.5}')
    ledger = committed / ".results" / "ledger.jsonl"
    ledger.parent.mkdir()
    output = {"path": "results/fresh.json", "sha256": Digest.of_file(out).value}
    chain.append_event(ledger, {"event": "run", "run_id": "r1", "outputs": [output]})
    (result,) = session_calls(committed, [add("results/fresh.json")])
    assert not result.is_error, result.content[0].text
    assert "run r1" in result.structured_content["by"]


def test_a_run_recorded_during_the_session_does_not_vouch(committed):
    out = committed / "results" / "fresh.json"

    def record_run():
        out.write_text('{"auc": 0.5}')
        ledger = committed / ".results" / "ledger.jsonl"
        ledger.parent.mkdir(exist_ok=True)
        output = {"path": "results/fresh.json", "sha256": Digest.of_file(out).value}
        chain.append_event(ledger, {"event": "run", "run_id": "r2", "outputs": [output]})

    (result,) = session_calls(committed, [record_run, add("results/fresh.json")])
    assert result.structured_content["refused"] == "not_vouched"


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
