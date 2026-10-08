"""`repro audit` reports on a clone, and keeps three things apart that a summary would merge.

Every repository here is a real one made in `tmp_path` and passed by path, so nothing reaches
a network. The `.bib` step reaches registries and is exercised only as skipped.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import pathlib
import subprocess

import pytest
import yaml
from provenance_core.gitref import clean_env
from repro import audit, cli
from repro.delegate import BY_NAME, run

SOURCE = "the measured angle matches the Haar expectation for this ensemble\n"
QUOTED = "matches the Haar expectation for this ensemble"


def git(repo: pathlib.Path, *args: str) -> str:
    # `clean_env`, because the pre-push hook runs this suite with `GIT_DIR` exported and these
    # commits would otherwise land in the repository being pushed.
    return subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
        cwd=repo,
        env=clean_env(),
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def commit(repo: pathlib.Path, message: str) -> str:
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)
    return git(repo, "rev-parse", "HEAD")


def tool(repo: pathlib.Path, name: str, *argv: str) -> None:
    with contextlib.chdir(repo):
        assert run(BY_NAME[name], argv) == 0, (name, argv)


def write_claims(directory: pathlib.Path, quoted: str = QUOTED) -> None:
    directory.mkdir(parents=True)
    (directory / "angle.yaml").write_text(
        yaml.safe_dump(
            {
                "source": {
                    "citation": "x",
                    "local": "reference/source.txt",
                    "sha256": hashlib.sha256(SOURCE.encode()).hexdigest(),
                },
                "claims": {"c1": {"quotes": [{"exact": quoted}]}},
            }
        )
    )


@pytest.fixture(autouse=True)
def library(tmp_path, monkeypatch):
    """An empty citations library, so no test reads the one this machine keeps."""
    home = tmp_path / "library"
    (home / "pdfs").mkdir(parents=True)
    monkeypatch.setenv("CITATIONS_HOME", str(home))
    return home


@pytest.fixture
def empty(tmp_path):
    repo = tmp_path / "study"
    repo.mkdir()
    git(repo, "init", "-q")
    (repo / "README.md").write_text("# A study\n")
    commit(repo, "start")
    return repo


@pytest.fixture
def repo(empty, capsys):
    """A frozen plan, a ledger, a claims directory with its source, a manifest and a `.bib`."""
    tool(empty, "prereg", "new", "plan")
    commit(empty, "plan")
    tool(empty / "plan", "prereg", "freeze")

    (empty / "analysis.py").write_text("print(0.9)\n")
    (empty / "out.json").write_text('{"accuracy": 0.9}\n')
    tool(empty, "results", "init")
    tool(empty, "results", "seal", "analysis.py")
    tool(empty, "results", "run", "out.json", "--run-id", "r1")
    tool(empty, "results", "claim", "accuracy = 0.9", "--run-id", "r1")

    (empty / "reference").mkdir()
    (empty / "reference" / "source.txt").write_text(SOURCE)
    write_claims(empty / "claims")
    (empty / "refs.bib").write_text("@article{a2020,\n  title = {A},\n  year = {2020}\n}\n")
    (empty / "repro.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": "repro/1",
                "project": "study",
                "artifacts": [
                    {
                        "id": "out",
                        "path": "out.json",
                        "media_type": "application/json",
                        "digest": {
                            "algorithm": "sha256",
                            "value": hashlib.sha256(b'{"accuracy": 0.9}\n').hexdigest(),
                        },
                    }
                ],
                "claims": [
                    {
                        "id": "accuracy",
                        "text": "Accuracy is 0.9.",
                        "evidence": [
                            {
                                "kind": "metric",
                                "artifact": "out",
                                "name": "accuracy",
                                "reported": "0.9",
                                "pointer": "/accuracy",
                            }
                        ],
                    }
                ],
            }
        )
    )
    commit(empty, "records")
    capsys.readouterr()
    return empty


@pytest.fixture
def run_audit(tmp_path, capsys):
    def go(*argv: str) -> tuple[int, dict, str]:
        out = tmp_path / "out"
        code = cli.main(
            ["audit", *argv, "--offline", "--cache", str(tmp_path / "cache"), "--out", str(out)]
        )
        printed = capsys.readouterr().out
        records = sorted(out.glob("*_audit.json"))
        return code, json.loads(records[0].read_text()) if records else {}, printed

    return go


def outcomes(record: dict) -> dict[str, str]:
    return {name: step["outcome"] for name, step in record["steps"].items()}


def snapshot(repo: pathlib.Path) -> tuple[str, str]:
    status = git(repo, "status", "--porcelain")
    digest = hashlib.sha256()
    for path in sorted(p for p in repo.rglob("*") if p.is_file()):
        digest.update(path.relative_to(repo).as_posix().encode() + b"\0" + path.read_bytes())
    return status, digest.hexdigest()


def test_every_kind_of_record_is_checked_and_the_record_names_the_commit_and_tree(repo, run_audit):
    code, record, printed = run_audit(str(repo))

    assert record["pin"]["commit"] == git(repo, "rev-parse", "HEAD")
    assert record["pin"]["tree"] == git(repo, "rev-parse", "HEAD^{tree}")
    assert record["pin"]["dirty"] is False
    assert {name: step["exit"] for name, step in record["steps"].items()} == {
        "prereg.check": 0,
        "results.verify": 0,
        "citations.verify": 0,
        "repro.verify": 0,
    }
    assert set(outcomes(record).values()) == {audit.PASSED}
    assert "1 plans: 1 unchanged" in record["steps"]["prereg.check"]["output"]
    assert "chain intact: 4 events" in record["steps"]["results.verify"]["found"]
    assert record["steps"]["citations.verify"]["found"] == "found 1; not found 0"
    assert "1 verified" in record["steps"]["repro.verify"]["found"]
    assert record["declared"] | {"tracked_files": 0} == {
        "tracked_files": 0,
        "registered_plans": 1,
        "evidence_manifests": 1,
        "results_ledgers": 1,
        "claim_records": 1,
        "claims": 1,
        "quotations": 1,
        "pinned_sources": 1,
        "sources_carrying_a_digest": 1,
        "bibliography_entries_refs_bib": 1,
        "manifest_artifacts": 1,
        "manifest_claims": 1,
        "manifest_assertions": 1,
        "manifest_assertions_by_kind": {"metric": 1},
        "manifest_regenerations": 0,
        "ledger_events": 4,
        "runs": 1,
        "file_digests_recorded": 2,
        "manuscript_claims_bound": 1,
        "confirmatory_claims": 0,
    }
    assert code == 0
    assert record["pin"]["commit"] in printed


def test_a_step_that_reaches_a_registry_is_skipped_offline_and_never_reported_as_run(
    repo, run_audit
):
    _, record, printed = run_audit(str(repo))
    assert "citations.audit" not in record["steps"]
    assert record["skipped"]["citations.audit"]["reason"].startswith("offline")
    assert record["skipped"]["citations.audit"]["command"].startswith(
        "citations audit --bib refs.bib"
    )
    row = next(line for line in printed.splitlines() if line.startswith("citations.audit"))
    assert "not run" in row and "offline" in row


def test_an_absent_source_could_not_be_checked_which_is_neither_a_failure_nor_a_pass(
    repo, run_audit
):
    git(repo, "rm", "-q", "reference/source.txt")
    commit(repo, "the source is not redistributable")

    code, record, printed = run_audit(str(repo))
    step = record["steps"]["citations.verify"]
    assert step["outcome"] == audit.COULD_NOT
    assert step["could_not"].startswith("unchecked 1")
    row = next(line for line in printed.splitlines() if line.startswith("citations.verify"))
    assert audit.COULD_NOT in row and "unchecked 1" in row
    assert code == 2
    others = {name: o for name, o in outcomes(record).items() if name != "citations.verify"}
    assert set(others.values()) == {audit.PASSED}


def test_a_quotation_its_source_does_not_hold_failed(repo, run_audit):
    (repo / "claims" / "angle.yaml").unlink()
    (repo / "claims").rmdir()
    write_claims(repo / "claims", quoted="contradicts the Haar expectation for this ensemble")
    commit(repo, "misquote")

    code, record, _ = run_audit(str(repo))
    step = record["steps"]["citations.verify"]
    assert step["outcome"] == audit.FAILED
    assert step["found"] == "not found 1"
    assert step["could_not"] == ""
    assert code == 1


def test_an_absent_source_is_read_from_the_library_when_its_bytes_match_the_pin(
    repo, library, run_audit
):
    git(repo, "rm", "-q", "reference/source.txt")
    commit(repo, "the source is not redistributable")
    (library / "pdfs" / "source.txt").write_text(SOURCE)

    code, record, _ = run_audit(str(repo))
    step = record["steps"]["citations.verify"]
    assert step["outcome"] == audit.PASSED
    assert "1 source absent at the path the record names and read from the library" in step["found"]
    assert code == 0


def test_a_repository_keeping_no_record_has_nothing_to_read_and_nothing_is_established(
    empty, run_audit
):
    code, record, printed = run_audit(str(empty))
    assert outcomes(record) == dict.fromkeys(
        ("prereg.check", "results.verify", "citations.verify", "repro.verify"), audit.NOTHING
    )
    assert {step["exit"] for step in record["steps"].values()} == {2}
    assert record["skipped"]["citations.audit"]["reason"] == "no .bib file in the repository"
    assert record["declared"] == {
        "tracked_files": 1,
        "registered_plans": 0,
        "evidence_manifests": 0,
        "results_ledgers": 0,
    }
    assert printed.count(audit.NOTHING) == 4
    assert code == 2


def test_commit_pins_an_older_revision_and_the_record_names_it(repo, run_audit):
    older = git(repo, "rev-parse", "HEAD~1")
    code, record, _ = run_audit(str(repo), "--commit", older)
    assert record["pin"]["commit"] == older
    assert record["pin"]["tree"] == git(repo, "rev-parse", f"{older}^{{tree}}")
    assert outcomes(record) == {
        "prereg.check": audit.FAILED,
        "results.verify": audit.NOTHING,
        "citations.verify": audit.NOTHING,
        "repro.verify": audit.NOTHING,
    }
    assert (
        record["steps"]["prereg.check"]["found"] == "1 plans: 0 unchanged, 0 changed, 1 not frozen"
    )
    assert record["steps"]["prereg.check"]["could_not"] == "1 not frozen"
    assert code == 1


def test_the_audited_repository_is_left_byte_for_byte_as_it_was(repo, run_audit):
    before = snapshot(repo)
    refs = git(repo, "for-each-ref")
    run_audit(str(repo))
    assert snapshot(repo) == before
    assert git(repo, "for-each-ref") == refs


def test_a_cached_clone_is_brought_to_the_new_head_and_cleaned(repo, run_audit, tmp_path):
    run_audit(str(repo))
    leftovers = git(tmp_path / "cache" / "checkout", "status", "--porcelain", "--ignored")
    assert leftovers, "the tools left nothing in the clone, so this cannot show it was cleaned"

    (repo / "README.md").write_text("# A study, revised\n")
    head = commit(repo, "revise")
    _, record, _ = run_audit(str(repo))
    assert record["pin"]["commit"] == head
    assert record["pin"]["dirty"] is False


def test_an_audit_started_from_a_git_hook_audits_the_repository_it_was_given(
    repo, run_audit, tmp_path, monkeypatch
):
    hooked = tmp_path / "hooked"
    hooked.mkdir()
    git(hooked, "init", "-q")
    (hooked / "unrelated.txt").write_text("another project\n")
    elsewhere = commit(hooked, "unrelated")
    monkeypatch.setenv("GIT_DIR", str(hooked / ".git"))
    monkeypatch.setenv("GIT_INDEX_FILE", str(hooked / ".git" / "index"))

    code, record, _ = run_audit(str(repo))
    assert record["pin"]["commit"] == git(repo, "rev-parse", "HEAD") != elsewhere
    assert record["declared"]["registered_plans"] == 1
    assert set(outcomes(record).values()) == {audit.PASSED}
    assert code == 0
    assert git(hooked, "rev-parse", "HEAD") == elsewhere
    assert git(hooked, "status", "--porcelain") == ""


def test_a_tree_that_disagrees_with_the_target_is_recorded_and_the_run_continues(
    repo, run_audit, tmp_path
):
    target = tmp_path / "moved_target.yaml"
    target.write_text(
        yaml.safe_dump(
            {"repository": str(repo), "commit": git(repo, "rev-parse", "HEAD"), "tree": "0" * 40}
        )
    )
    code, record, printed = run_audit("--target", str(target))
    assert (tmp_path / "out" / "moved_audit.log").is_file()
    assert record["pin"]["commit_matches_pin"] is True
    assert record["pin"]["tree_matches_pin"] is False
    assert record["target"]["tree"] == "0" * 40
    assert len(record["steps"]) == 4
    assert "not what was audited" in printed
    assert code == 0


def test_a_tree_nobody_pinned_is_not_reported_as_matching_or_as_differing(repo, run_audit):
    _, record, _ = run_audit(str(repo))
    assert record["pin"]["tree_matches_pin"] is None


def test_a_target_names_an_unusual_path_and_adds_a_step_beside_the_defaults(
    repo, run_audit, tmp_path
):
    git(repo, "mv", "claims", "quotes")
    commit(repo, "claims kept under another name")
    target = tmp_path / "study_target.yaml"
    target.write_text(
        yaml.safe_dump(
            {
                "repository": str(repo),
                "layout": {"claims": "quotes", "globs": {"readmes": ["README.md", "*/README.md"]}},
                "steps": [
                    {
                        "name": "results.coverage.readme",
                        "argv": ["results", "coverage", "README.md"],
                    }
                ],
            }
        )
    )
    code, record, _ = run_audit("--target", str(target))
    assert [s["name"] for s in record["target"]["steps"]] == [
        "results.coverage.readme",
        "prereg.check",
        "results.verify",
        "citations.verify",
        "citations.audit",
        "repro.verify",
    ]
    assert set(record["steps"]) == {s["name"] for s in record["target"]["steps"]} - {
        "citations.audit"
    }
    assert record["steps"]["citations.verify"]["command"] == "citations verify --claims quotes"
    assert record["steps"]["citations.verify"]["outcome"] == audit.PASSED
    assert record["declared"]["quotations"] == 1
    assert record["declared"]["readmes"] == 1
    assert code == 0


def test_a_target_step_replaces_the_default_of_the_same_name(repo, run_audit, tmp_path):
    target = tmp_path / "study_target.yaml"
    target.write_text(
        yaml.safe_dump(
            {
                "steps": [
                    {"name": "results.verify", "argv": ["results", "verify"], "note": "chain only"}
                ]
            }
        )
    )
    _, record, _ = run_audit(str(repo), "--target", str(target))
    assert record["steps"]["results.verify"]["command"] == "results verify"
    assert record["steps"]["results.verify"]["note"] == "chain only"
    assert "file hashes were not checked" in record["steps"]["results.verify"]["output"]


def test_a_step_may_only_run_one_of_the_four_tools(repo, run_audit, tmp_path):
    target = tmp_path / "study_target.yaml"
    target.write_text(yaml.safe_dump({"steps": [{"name": "shell", "argv": ["sh", "-c", "true"]}]}))
    code, record, printed = run_audit(str(repo), "--target", str(target))
    assert code == 2
    assert record == {}
    assert "'sh'" in printed


def test_a_cache_below_another_projects_plan_is_refused(repo, run_audit, tmp_path):
    (tmp_path / "PREREG.md").write_text("# somebody else's plan\n")
    code, record, printed = run_audit(str(repo))
    assert code == 2
    assert record == {}
    assert str(tmp_path / "PREREG.md") in printed


@pytest.mark.parametrize(
    ("argv", "code", "output", "expected"),
    [
        (
            ["citations", "audit"],
            0,
            "  checked  3\n  agree  3\n  disagree  0\n\nevery checked entry matches.",
            (audit.PASSED, "checked 3; agree 3; disagree 0", ""),
        ),
        (
            ["citations", "audit"],
            0,
            "  checked  3\n  agree  2\n  disagree  1\n",
            (audit.FAILED, "checked 3; agree 2; disagree 1", ""),
        ),
        (
            ["citations", "audit"],
            0,
            "  checked  0\n  agree  0\n  disagree  0\n"
            "  unresolved  3   the identifier did not fetch; no measurement was made\n\n"
            "nothing disagreed. 3 unresolved — no measurement for those.",
            (
                audit.COULD_NOT,
                "checked 0; agree 0; disagree 0",
                "unresolved 3 the identifier did not fetch; no measurement was made",
            ),
        ),
        (
            ["prereg", "check"],
            2,
            "1 commit-pinned: 0 unchanged, 0 appended, 0 changed, 0 pending, 1 unknown commit",
            (
                audit.COULD_NOT,
                "1 commit-pinned: 0 unchanged, 0 appended, 0 changed, 0 pending, 1 unknown commit",
                "1 unknown commit",
            ),
        ),
        (
            ["results", "verify"],
            2,
            "ValueError: a ledger line is not JSON",
            (audit.COULD_NOT, "", "ValueError: a ledger line is not JSON"),
        ),
    ],
)
def test_an_outcome_is_read_from_what_the_tool_measured_not_from_its_exit_code(
    argv, code, output, expected, tmp_path
):
    assert audit.read(argv, code, output, tmp_path) == expected


def test_a_registry_that_did_not_answer_is_not_established_whatever_the_other_steps_did():
    steps = {
        "prereg.check": {"outcome": audit.PASSED},
        "citations.audit": {"outcome": audit.COULD_NOT},
    }
    assert audit.exit_code(steps) == 2
    assert audit.exit_code(steps | {"results.verify": {"outcome": audit.FAILED}}) == 1
    assert audit.exit_code({"prereg.check": {"outcome": audit.PASSED}}) == 0


def test_restored_sidecars_are_counted_apart_from_the_claims_the_authors_declared(repo):
    layout = audit.Layout(claims="claims")
    before = audit.declared(repo, layout)
    claims = repo / "claims"
    original = sorted(claims.glob("*.yaml"))[0]
    doc = yaml.safe_load(original.read_text())
    doc["claims"] = {
        "c-restored": {"restored": {"from": "c"}, "quotes": [{"exact": "the source's passage"}]}
    }
    (claims / f"{original.stem}.restored.yaml").write_text(yaml.safe_dump(doc))
    after = audit.declared(repo, layout)
    for key in ("claim_records", "claims", "quotations", "pinned_sources"):
        assert after[key] == before[key], key
    assert (after["restored_claim_records"], after["restored_quotations"]) == (1, 1)
    assert "restored_claim_records" not in before
