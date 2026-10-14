"""`repro badges`: the count and colour of each check's badge, and the block it writes in a README.

The projects are built with the helpers `test_ci.py` builds them with, so each badge is read
from the same records the `repro ci` checks read.
"""

from __future__ import annotations

import base64
import importlib.util
import json
import pathlib
import urllib.parse

import pytest
import yaml
from repro import badges, ci, citations_record
from repro.badges import AMBER, BLUE, END, GRAY, GREEN, RED, START, Badge
from repro.cli import main
from repro.models import Claim
from repro.verify import verify

_SPEC = importlib.util.spec_from_file_location(
    "ci_helpers", pathlib.Path(__file__).with_name("test_ci.py")
)
assert _SPEC is not None and _SPEC.loader is not None
helpers = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(helpers)

tools = helpers.tools
SCRIPT, ledger, metric, on_disk, pin, plan, project, rerun = (
    helpers.SCRIPT,
    helpers.ledger,
    helpers.metric,
    helpers.on_disk,
    helpers.pin,
    helpers.plan,
    helpers.project,
    helpers.rerun,
)


def given(root, every=False):
    """Each badge the project gives, as (message, colour), by label."""
    return {
        badge.name: (badge.message, badge.color) for badge in badges.found(root, every=every).badges
    }


# -- prereg --------------------------------------------------------------------------------


def test_a_frozen_plan_is_counted_green(tools):
    plan(tools)
    assert given(tools)["prereg"] == ("1 plan frozen", GREEN)


def test_a_plan_edited_after_its_freeze_is_red(tools):
    plan(tools)
    (tools / "PREREG.md").chmod(0o644)
    (tools / "PREREG.md").write_text((tools / "PREREG.md").read_text() + "\nAlso p < 0.10.\n")
    assert given(tools)["prereg"] == ("1 of 1 frozen plan changed", RED)


def test_a_plan_never_frozen_is_amber_and_counted_against_the_plans(tools):
    plan(tools, freeze=False)
    assert given(tools)["prereg"] == ("0/1 plans frozen", AMBER)


def test_frozen_changed_and_draft_plans_add_up():
    def entry(frozen, check):
        return {"frozen": frozen, "check": check}

    account = {
        "plans": [entry(True, "unchanged"), entry(True, "unchanged"), entry(False, "not frozen")],
        "commit_pinned": [{"status": "appended"}, {"status": "pending"}, {"status": "withdrawn"}],
    }
    run = ci.ToolRun(check="prereg", outcome="failed", account=account)
    assert badges.prereg_badge(run) == Badge(
        check="prereg", message="3/5 plans frozen", color=AMBER
    )
    account["commit_pinned"][0]["status"] = "changed"
    assert badges.prereg_badge(run).message == "1 of 3 frozen plans changed"


# -- results -------------------------------------------------------------------------------


def test_runs_after_a_seal_are_sealed_and_runs_named_as_tests_are_left_out():
    events = [
        {"event": "run", "run_id": "early"},
        {"event": "seal"},
        {"event": "run", "run_id": "r1"},
        {"event": "run", "run_id": "smoke_r2"},
        {"event": "run", "run_id": "dryrun-r3"},
        {"event": "claim", "run_id": "r1"},
        {"event": "run", "run_id": "r4"},
    ]
    assert badges.runs(events) == badges.Runs(runs=3, sealed=2)


def test_a_ledger_whose_runs_are_all_sealed_and_files_match_is_green(tools):
    ledger(tools)
    assert given(tools)["results"] == ("1/1 runs sealed", GREEN)


def test_a_recorded_file_that_changed_or_went_missing_is_amber_and_the_message_is_runs_only(tools):
    ledger(tools)
    (tools / "results.json").write_text(json.dumps({"total": 7}))
    assert given(tools)["results"] == ("1/1 runs sealed", AMBER)
    (tools / "inputs.json").unlink()
    assert given(tools)["results"] == ("1/1 runs sealed", AMBER)


def results_run(outcome, states, events=True):
    account = {
        "chain": "intact",
        "files": [{"path": f"f{i}", "state": s} for i, s in enumerate(states)],
    }
    return ci.ToolRun(
        check="results", outcome=outcome, account=account | ({"events": 9} if events else {})
    )


def test_the_colour_follows_what_verify_reported_and_not_the_file_states_themselves():
    sealed = badges.Runs(runs=2, sealed=2)
    # States verify reports and passes are green.
    assert badges.results_badge(results_run("passed", ["resealed"]), sealed).color == GREEN
    assert badges.results_badge(results_run("passed", ["ok", "appended"]), sealed).color == GREEN
    assert badges.results_badge(results_run("passed", ["ok", "ignored"]), sealed).color == GREEN
    assert badges.results_badge(results_run("passed", ["ok", "retired"]), sealed).color == GREEN
    # A state verify fails on is amber.
    assert badges.results_badge(results_run("failed", ["ok", "reverted"]), sealed).color == AMBER
    assert badges.results_badge(results_run("failed", ["ok", "reappeared"]), sealed).color == AMBER
    assert (
        badges.results_badge(results_run("failed", ["changed", "missing"]), sealed).color == AMBER
    )
    # Failed with every recorded file in a state that passes: the timestamp contradicts the
    # chain.
    assert badges.results_badge(results_run("failed", ["ok", "ok"]), sealed).color == RED
    assert (
        badges.results_badge(
            results_run("failed", ["resealed", "appended", "ignored", "retired"]), sealed
        ).color
        == RED
    )
    assert badges.results_badge(results_run("failed", [], events=False), sealed) == Badge(
        check="results", message="2/2 runs sealed", color=RED
    )


def test_a_run_with_no_seal_before_it_is_amber(tools):
    (tools / "results.json").write_text(json.dumps({"total": 6}))
    assert main(["results", "init"]) == 0
    assert main(["results", "run", "results.json", "--run-id", "r1"]) == 0
    assert given(tools)["results"] == ("0/1 runs sealed", AMBER)


def test_a_chain_that_does_not_verify_is_red(tools):
    ledger(tools)
    path = tools / ".results" / "ledger.jsonl"
    path.write_text(path.read_text().replace("r1", "r2"))
    assert given(tools)["results"] == ("1/1 runs sealed", RED)


def test_a_ledger_with_a_line_that_is_not_an_event_is_red_with_no_run_counted(tools):
    ledger(tools)
    with (tools / ".results" / "ledger.jsonl").open("a") as handle:
        handle.write("not an event\n")
    assert given(tools)["results"] == ("0/0 runs sealed", RED)


# -- claims --------------------------------------------------------------------------------


def test_every_assertion_verified_is_green(tmp_path):
    assert badges.claims_badge(verify(project(tmp_path, "6", "6.0"))) == Badge(
        check="claims", message="2/2 verified", color=GREEN
    )


def test_a_mismatch_is_red_and_not_counted_as_verified(tmp_path):
    assert badges.claims_badge(verify(project(tmp_path, "6", "7", "6"))) == Badge(
        check="claims", message="2/3 verified", color=RED
    )


def test_an_assertion_not_found_with_no_mismatch_is_amber(tmp_path):
    manifest = project(tmp_path)
    claims = (
        *manifest.claims,
        Claim(id="gone", text="t", evidence=(metric("figures", "6", pointer="/absent"),)),
    )
    report = verify(manifest.model_copy(update={"claims": claims}))
    assert badges.claims_badge(report) == Badge(check="claims", message="1/2 verified", color=AMBER)


# -- citations -----------------------------------------------------------------------------


def test_every_quotation_found_is_green(tools):
    pin(tools, "here")
    pin(tools, "there")
    assert given(tools)["citations"] == ("2/2 verified", GREEN)


def test_a_quotation_whose_source_is_absent_is_amber(tools):
    pin(tools, "here")
    pin(tools, "gone", there=False)
    assert given(tools)["citations"] == ("1/2 verified", AMBER)


def test_a_run_citations_verify_passes_with_quotations_unchecked_is_amber_with_the_count():
    run = ci.ToolRun(
        check="citations", outcome="passed", account={"quotes": 203, "counts": {"found": 200}}
    )
    assert badges.citations_badge(run) == Badge(
        check="citations", message="200/203 verified", color=AMBER
    )


def test_a_quotation_its_source_does_not_hold_is_red(tools):
    pin(tools, "here")
    pin(tools, "other", quote="a sentence the source does not contain anywhere in its text")
    assert given(tools)["citations"] == ("1/2 verified", RED)


def test_quotations_none_of_whose_sources_was_read_are_counted_as_pinned(tools):
    pin(tools, "gone", there=False)
    pin(tools, "lost", there=False)
    assert given(tools)["citations"] == ("2 pinned", BLUE)


# -- reproduced ----------------------------------------------------------------------------


def test_every_command_current_with_a_rerun_on_record_is_green(tmp_path):
    manifest = project(tmp_path, script=SCRIPT)
    rerun(manifest)
    on_disk(manifest)
    assert given(tmp_path)["reproduced"] == ("1/1", GREEN)


def test_an_input_edited_after_its_rerun_is_amber(tmp_path):
    manifest = project(tmp_path, script=SCRIPT)
    rerun(manifest)
    on_disk(manifest)
    (tmp_path / "inputs.json").write_text(json.dumps({"xs": [1, 2, 4]}))
    assert given(tmp_path)["reproduced"] == ("0/1", AMBER)


def test_a_command_never_rerun_is_amber(tmp_path):
    on_disk(project(tmp_path, script=SCRIPT))
    assert given(tmp_path)["reproduced"] == ("0/1", AMBER)


# -- no record -----------------------------------------------------------------------------


def test_a_check_with_no_record_has_no_badge_and_standard_error_says_why(tools, capfd):
    on_disk(project(tools))
    assert main(["badges"]) == 0
    out, err = capfd.readouterr()
    assert out.splitlines() == [Badge(check="claims", message="1/1 verified", color=GREEN).markdown]
    assert err.splitlines() == [
        f"left out prereg: {ci.NO_RECORD['prereg']}",
        f"left out results: {ci.NO_RECORD['results']}",
        f"left out citations: {ci.NO_RECORD['citations']}",
        f"left out reruns: {ci.NO_RECORD['reruns']}",
    ]


def test_all_gives_a_gray_badge_for_each_check_with_no_record_in_badge_order(tools, capfd):
    on_disk(project(tools))
    assert list(given(tools, every=True).items()) == [
        ("prereg", ("none declared", GRAY)),
        ("results", ("none declared", GRAY)),
        ("claims", ("1/1 verified", GREEN)),
        ("citations", ("none declared", GRAY)),
        ("reproduced", ("none declared", GRAY)),
    ]
    assert main(["badges", "--all"]) == 0
    out, err = capfd.readouterr()
    assert len(out.splitlines()) == 5 and err == ""


def test_a_project_with_no_record_at_all_exits_2(tools, capfd):
    assert main(["badges"]) == 2
    assert "keeps no record a check reads" in capfd.readouterr().out


# -- the badge -----------------------------------------------------------------------------


def test_the_message_is_encoded_and_the_badge_is_static_with_the_checks_icon():
    badge = Badge(check="reruns", message="76/76 verified", color=GREEN)
    image = urllib.parse.urlsplit(badge.image)
    assert f"{image.scheme}://{image.netloc}{image.path}" == "https://img.shields.io/static/v1"
    assert "message=76%2F76%20verified" in image.query
    assert " " not in badge.image and "/" not in image.query
    assert urllib.parse.parse_qs(image.query) == {
        "label": ["reproduced"],
        "message": ["76/76 verified"],
        "color": [GREEN],
        "labelColor": [ci.LABEL_COLOR],
        "logo": [ci.logo("reruns")],
    }
    assert badge.markdown == (
        f"[![reproduced: 76/76 verified]({badge.image})]"
        "(https://reproducible.science/tools/repro/#reruns-in-ci)"
    )


# -- README --------------------------------------------------------------------------------

AFTER = "\nWhat it is.\n\n## Use\n\n<!-- a comment -->\nText   with trailing spaces   \n"


def test_readme_puts_the_block_under_the_first_heading_then_replaces_only_the_block(tools, capfd):
    manifest = project(tools)
    on_disk(manifest)
    readme = tools / "README.md"
    readme.write_text("# Study\n" + AFTER)
    assert main(["badges", "--readme"]) == 0
    first = Badge(check="claims", message="1/1 verified", color=GREEN).markdown
    assert readme.read_text() == f"# Study\n\n{START}\n{first}\n{END}\n" + AFTER

    assert main(["badges", "--check"]) == 0
    assert readme.read_text() == f"# Study\n\n{START}\n{first}\n{END}\n" + AFTER

    (tools / "figures.json").write_text(json.dumps({"total": 7}, indent=2))
    capfd.readouterr()
    assert main(["badges", "--check"]) == 1
    out = capfd.readouterr().out
    assert "  claims: README.md shows `1/1 verified`; now `0/1 verified`" in out
    assert "repro badges --readme" in out
    assert readme.read_text() == f"# Study\n\n{START}\n{first}\n{END}\n" + AFTER

    assert main(["badges", "--readme"]) == 0
    second = Badge(check="claims", message="0/1 verified", color=RED).markdown
    assert readme.read_text() == f"# Study\n\n{START}\n{second}\n{END}\n" + AFTER
    assert main(["badges", "--check"]) == 0


def test_a_block_already_there_is_replaced_wherever_it_stands_and_nothing_else_changes(tools):
    on_disk(project(tools))
    before, after = "Intro\r\n\r\n# Study\r\n", "\r\n\r\nText\r\n"
    readme = tools / "README.md"
    readme.write_bytes(f"{before}{START}\r\nold\r\n{END}{after}".encode())
    assert main(["badges", "--readme"]) == 0
    line = badges.found(tools).line
    assert readme.read_bytes() == f"{before}{START}\r\n{line}\r\n{END}{after}".encode()


def test_the_block_goes_at_the_head_of_badges_already_there_or_at_the_top_without_a_heading(
    tmp_path,
):
    path = tmp_path / "README.md"
    assert badges.written("# Study\n\n[![pypi](a)](b)\n\nText.\n", "L", path) == (
        f"# Study\n\n{START}\nL\n{END}\n[![pypi](a)](b)\n\nText.\n"
    )
    assert badges.written("Text.\n", "L", path) == f"{START}\nL\n{END}\n\nText.\n"
    assert badges.written("# Study", "L", path) == f"# Study\n\n{START}\nL\n{END}\n"


def test_check_with_no_block_fails_and_with_no_readme_could_not_compare(tools, capfd):
    on_disk(project(tools))
    assert main(["badges", "--check"]) == 2
    assert "no README.md" in capfd.readouterr().out
    (tools / "README.md").write_text("# Study\n")
    assert main(["badges", "--check", "--all"]) == 1
    out = capfd.readouterr().out
    assert "holds no badge block" in out and "repro badges --readme --all" in out
    assert (tools / "README.md").read_text() == "# Study\n"


def test_readme_with_no_readme_writes_nothing(tools, capfd):
    on_disk(project(tools))
    assert main(["badges", "--readme"]) == 2
    assert "no README.md" in capfd.readouterr().out
    assert not (tools / "README.md").exists()


def test_a_block_that_is_never_closed_is_refused_and_the_readme_is_kept(tools, capfd):
    on_disk(project(tools))
    readme = tools / "README.md"
    readme.write_text(f"# Study\n\n{START}\nold\n")
    for mode in ("--readme", "--check"):
        assert main(["badges", mode]) == 2
        assert f"with no `{END}` after it" in capfd.readouterr().out
    assert readme.read_text() == f"# Study\n\n{START}\nold\n"


@pytest.mark.parametrize("check", ci.CHECKS)
def test_each_badge_links_to_the_section_its_ci_summary_links_to(check):
    badge = Badge(check=check, message="1/1", color=GREEN)
    assert badge.markdown.endswith(f"]({ci.DOCS}#{ci.ANCHORS[check]})")


def test_check_names_a_badge_gone_one_added_and_one_drawn_in_another_colour(tmp_path):
    before = " ".join(
        badge.markdown
        for badge in (
            Badge(check="prereg", message="1 plan frozen", color=GREEN),
            Badge(check="claims", message="1/2 verified", color=AMBER),
        )
    )
    now = badges.Found(
        root=tmp_path,
        badges=(
            Badge(check="claims", message="1/2 verified", color=RED),
            Badge(check="reruns", message="1/1", color=GREEN),
        ),
    )
    assert badges.differences(before, now) == [
        "  claims: `1/2 verified`, drawn in another colour than now",
        "  reproduced: not in README.md; now `1/1`",
        "  prereg: README.md shows `1 plan frozen`; no badge is given now",
    ]


# -- endpoint files ------------------------------------------------------------------------


def test_an_endpoint_file_draws_what_the_static_badge_draws():
    badge = Badge(check="citations", message="203/203 verified", color=GREEN)
    endpoint = badge.endpoint
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(badge.image).query)
    assert endpoint["schemaVersion"] == 1
    assert [endpoint[key] for key in ("label", "message", "color", "labelColor")] == [
        query[key][0] for key in ("label", "message", "color", "labelColor")
    ]
    # The static badge carries the icon as a data URI; the endpoint file as the SVG text.
    encoded = query["logo"][0].removeprefix("data:image/svg+xml;base64,")
    assert base64.b64decode(encoded).decode() == endpoint["logoSvg"]
    assert endpoint["logoSvg"].startswith("<svg") and endpoint["logoSvg"].endswith("</svg>")


# -- the citations record ------------------------------------------------------------------


def test_the_record_covers_each_claims_file_and_goes_stale_when_one_changes(tools):
    pin(tools, "here")
    pin(tools, "gone", there=False)
    made = citations_record.write(tools)
    assert made.quotes == 2 and made.counts["found"] == 1 and made.counts["unchecked"] == 1
    assert sorted(made.claims) == ["claims/gone.yaml", "claims/here.yaml"]
    assert made.claims["claims/here.yaml"].source == helpers.Digest.of_text(helpers.TEXT).value
    stored = json.loads((tools / citations_record.RECORD).read_text())
    assert stored["record"] == citations_record.VERSION
    assert stored["claims"]["claims/gone.yaml"]["sha256"] == made.claims["claims/gone.yaml"].sha256

    compared = citations_record.compare(tools)
    assert compared.standing is citations_record.Standing.CURRENT
    assert badges.recorded_citations_badge(compared) == Badge(
        check="citations", message="1/2 verified locally", color=AMBER
    )

    edited = tools / "claims" / "gone.yaml"
    edited.write_text(edited.read_text().replace("quick brown", "quick red"))
    compared = citations_record.compare(tools)
    assert compared.standing is citations_record.Standing.STALE
    assert compared.differing == ("claims/gone.yaml",)
    assert badges.recorded_citations_badge(compared) == Badge(
        check="citations", message="re-verify locally", color=AMBER
    )


def test_a_claims_file_added_or_removed_since_the_record_makes_it_stale(tools):
    pin(tools, "here")
    citations_record.write(tools)
    pin(tools, "there")
    assert citations_record.compare(tools).differing == ("claims/there.yaml",)
    citations_record.write(tools)
    (tools / "claims" / "here.yaml").unlink()
    assert citations_record.compare(tools).differing == ("claims/here.yaml",)


def test_no_record_is_gray_and_every_quotation_found_is_green_locally(tools):
    pin(tools, "here")
    pin(tools, "there")
    compared = citations_record.compare(tools)
    assert compared.standing is citations_record.Standing.ABSENT
    assert badges.recorded_citations_badge(compared) == Badge(
        check="citations", message="not verified locally", color=GRAY
    )
    citations_record.write(tools)
    assert badges.recorded_citations_badge(citations_record.compare(tools)) == Badge(
        check="citations", message="2/2 verified locally", color=GREEN
    )


def test_ci_endpoints_writes_every_check_and_reads_citations_from_the_record_alone(tools, capsys):
    ledger(tools)
    on_disk(project(tools))
    pin(tools, "here")
    assert main(["badges", "--record"]) == 0
    # A clone does not hold the source; the record says what the author's machine found.
    (tools / "sources" / "here.txt").unlink()
    out = tools / "out"
    assert main(["ci", "endpoints", str(out)]) == 0
    written = {path.stem: json.loads(path.read_text()) for path in out.iterdir()}
    assert sorted(written) == sorted(ci.CHECKS)
    said = {check: (data["message"], data["color"]) for check, data in written.items()}
    assert said == {
        "prereg": ("none declared", GRAY),
        "results": ("1/1 runs sealed", GREEN),
        "claims": ("1/1 verified", GREEN),
        "citations": ("1/1 verified locally", GREEN),
        "reruns": ("none declared", GRAY),
    }
    assert all(data["labelColor"] == ci.LABEL_COLOR for data in written.values())
    assert written["citations"]["logoSvg"] == ci.icon("citations")


def test_ci_endpoints_names_the_command_where_no_citations_record_is_committed(tools, capsys):
    pin(tools, "here")
    assert main(["ci", "endpoints", str(tools / "out")]) == 0
    assert json.loads((tools / "out" / "citations.json").read_text())["color"] == GRAY
    assert badges.REFRESH_RECORD in capsys.readouterr().out


# -- repro badges init ---------------------------------------------------------------------


@pytest.fixture
def github(tools):
    """A repository with a GitHub remote, a README, a ledger, a manifest and a pinned source."""
    helpers.git(tools, "remote", "add", "origin", "git@github.com:someone/study.git")
    (tools / "README.md").write_text("# Study\n\nText.\n")
    ledger(tools)
    on_disk(project(tools))
    pin(tools, "here")
    return tools


def test_init_writes_one_workflow_that_pushes_only_to_the_badges_branch(github, capsys):
    assert main(["badges", "init"]) == 0
    text = (github / badges.WORKFLOW_FILE).read_text()
    assert text.startswith(badges.MARKER)
    flow = yaml.safe_load(text)
    # `on` is read by YAML 1.1 as True.
    assert flow[True] == {"push": {"branches": ["main"]}, "workflow_dispatch": None}
    assert flow["permissions"] == {"contents": "write"}
    steps = flow["jobs"]["badges"]["steps"]
    assert [step.get("uses") for step in steps[:2]] == [
        ci.CHECKOUT.split()[0],
        ci.SETUP_UV.split()[0],
    ]
    assert steps[0]["with"] == {"persist-credentials": False}
    assert steps[2]["run"].startswith(f"uvx --from {ci.DISTRIBUTION}==")
    assert steps[2]["run"].endswith('repro ci endpoints "$OUT"')
    pushes = [line for line in steps[3]["run"].splitlines() if "refs/heads/" in line]
    assert [line.strip() for line in pushes] == ["HEAD:refs/heads/badges"]
    assert 'test "$DEFAULT" != badges' in steps[3]["run"]
    assert "pull_request" not in text

    readme = (github / "README.md").read_text()
    runs = "https://github.com/someone/study/actions/workflows/repro.yml"
    line = " ".join(
        f"[![{name}](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/"
        f"someone/study/badges/{check}.json)]({runs})"
        for check, name in (
            ("results", "results"),
            ("claims", "claims"),
            ("citations", "citations"),
        )
    )
    assert readme == f"# Study\n\n{START}\n{line}\n{END}\n\nText.\n"
    assert citations_record.compare(github).standing is citations_record.Standing.CURRENT
    out = capsys.readouterr().out
    assert "left out prereg" in out and "public repository" in out and "next:" in out


def test_init_never_rewrites_a_block_or_its_workflow_without_force(github, capsys):
    readme = github / "README.md"
    readme.write_text(f"# Study\n\n{START}\nmine\n{END}\n")
    assert main(["badges", "init"]) == 0
    assert readme.read_text() == f"# Study\n\n{START}\nmine\n{END}\n"
    assert "left as it is" in capsys.readouterr().out

    assert main(["badges", "init"]) == 2
    assert "`--force` replaces" in capsys.readouterr().out
    assert main(["badges", "init", "--force"]) == 0
    assert badges.is_endpoint_block(badges.shown(readme.read_text(), readme))


def test_init_leaves_a_workflow_it_did_not_write_and_a_repository_off_github(github, capsys):
    target = github / badges.WORKFLOW_FILE
    target.parent.mkdir(parents=True)
    target.write_text("name: theirs\n")
    assert main(["badges", "init", "--force"]) == 2
    assert "did not write it" in capsys.readouterr().out
    assert target.read_text() == "name: theirs\n"
    target.unlink()

    helpers.git(github, "remote", "set-url", "origin", "https://gitlab.com/someone/study.git")
    assert main(["badges", "init"]) == 2
    assert "names no GitHub repository" in capsys.readouterr().out
    assert not target.exists() and START not in (github / "README.md").read_text()


def test_check_of_the_block_init_wrote_compares_the_citations_record(github, capsys):
    assert main(["badges", "init"]) == 0
    before = (github / "README.md").read_text()
    capsys.readouterr()
    assert main(["badges", "--check"]) == 0
    claims = github / "claims" / "here.yaml"
    claims.write_text(claims.read_text().replace("quick brown", "quick red"))
    assert main(["badges", "--check"]) == 1
    out = capsys.readouterr().out
    assert "claims/here.yaml" in out and badges.REFRESH_RECORD in out
    assert main(["badges", "--readme"]) == 2
    assert "`repro badges init` wrote" in capsys.readouterr().out
    assert (github / "README.md").read_text() == before
    assert main(["badges", "--record"]) == 0
    assert main(["badges", "--check"]) == 0
