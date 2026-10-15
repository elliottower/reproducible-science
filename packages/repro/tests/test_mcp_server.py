import json
import pathlib
from typing import Any

import anyio
import pytest
import yaml
from claims.models import Digest
from claims.open_items import OpenItem, Source, write_draft
from mcp import Client
from mcp.types import ListRootsResult, Root
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
    other = tmp_path / "other"
    (other / "claims").mkdir(parents=True)
    named, verified = calls(
        tmp_path,
        [("set_project", {"path": str(project)}), ("verify", {"policy": "exploratory"})],
        roots=[other],
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
