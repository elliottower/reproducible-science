"""What each assertion said when it was checked, and what `repro why` says of it afterwards.

Each test writes a manifest, runs `repro verify` over it as a user would, edits the manifest or
a file, and runs it again.
"""

from __future__ import annotations

import hashlib
import json
import pathlib

import pytest
import yaml
from repro.audit import Layout, default_steps
from repro.checks import RECORD, ChecksUnreadableError, checks, history
from repro.cli import main
from repro.models import (
    ArtifactRef,
    CheckRecord,
    Claim,
    ClaimAccount,
    Digest,
    Manifest,
    MetricEvidence,
    Outcome,
    QuoteEvidence,
    Reason,
)
from repro.verify import verify
from repro.why import why

REPOSITORY = pathlib.Path(__file__).resolve().parents[3]


def put(root, **fields):
    (root / "results.json").write_text(json.dumps({"acc": 0.91, "accuracy": 0.91, **fields}))


def claim(reported="0.92", pointer="/acc", text="Accuracy is as reported.", name="accuracy"):
    return Claim(
        id="accuracy",
        text=text,
        evidence=(
            MetricEvidence(artifact="results", name=name, reported=reported, pointer=pointer),
        ),
    )


def manifest(root, *claims):
    """The manifest on disk, with every file pinned as it is now."""
    project = Manifest(
        project="p",
        path=root / "repro.yaml",
        artifacts=tuple(
            ArtifactRef(id=p.stem, path=p, digest=Digest.of_file(p))
            for p in sorted(p for p in root.iterdir() if p.suffix in (".json", ".txt"))
        ),
        claims=claims,
    )
    project.path.write_text(project.model_dump_json())
    return project


def check(project, *flags):
    return main(["verify", str(project.path), *flags])


def recorded(root):
    """What the record holds for the one assertion these tests edit, oldest first."""
    return history(root)["accuracy", "metric", "accuracy", 0]


def lines(root):
    return (root / RECORD).read_bytes().splitlines(keepends=True)


def established(project, capsys):
    """The lines `repro why` prints under the claim's first assertion, after its outcome."""
    capsys.readouterr()
    assert main(["why", "accuracy", str(project.path)]) == 0
    block = capsys.readouterr().out.partition("\nestablished\n")[2].partition("\n  chain\n")[0]
    return [line.strip() for line in block.splitlines()[4:]]


def snapshot(root):
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def test_a_check_that_finds_nothing_changed_adds_nothing_to_the_record(tmp_path):
    put(tmp_path)
    project = manifest(tmp_path, claim())
    assert not (tmp_path / RECORD).exists()
    assert check(project) == 1
    (first,) = lines(tmp_path)
    assert check(project) == 1
    assert check(project, "--format", "json") == 1
    assert lines(tmp_path) == [first]

    (line,) = checks(tmp_path)
    (state,) = line.assertions
    assert (state.claim_id, state.kind, state.name, state.position) == (
        "accuracy",
        "metric",
        "accuracy",
        0,
    )
    assert (state.printed, state.address, state.outcome, state.reason) == (
        "0.92",
        "/acc",
        Outcome.MISMATCH,
        Reason.VALUE_MISMATCH,
    )
    assert state.digests == {"results": Digest.of_file(tmp_path / "results.json").value}
    assert state.claim_digest == claim().digest.value
    assert state.checked_at == line.checked_at != ""


def test_a_reported_value_changed_after_a_mismatch_is_shown_with_both_states_in_order(
    tmp_path, capsys
):
    put(tmp_path)
    assert check(manifest(tmp_path, claim("0.92"))) == 1
    project = manifest(tmp_path, claim("0.91"))
    assert check(project) == 0

    before, after = recorded(tmp_path)
    assert (before.printed, before.outcome) == ("0.92", Outcome.MISMATCH)
    assert (after.printed, after.outcome) == ("0.91", Outcome.VERIFIED)
    assert (before.address, before.digests, before.claim_digest) == (
        after.address,
        after.digests,
        after.claim_digest,
    )

    account = why(project, "accuracy")
    assert account.assertions[0].history == (before, after)
    assert account.assertions[0].now is None
    digest = Digest.of_file(tmp_path / "results.json").value[:12]
    assert established(project, capsys) == [
        f"checked {before.checked_at}: reported 0.92 at /acc, results {digest}: mismatch",
        f"since {after.checked_at}: reported 0.91 at /acc, results {digest}: verified "
        "(after mismatch: reported changed)",
    ]


def test_an_address_changed_after_a_mismatch_is_named_as_the_address(tmp_path, capsys):
    put(tmp_path, accuracy=0.92)
    assert check(manifest(tmp_path, claim("0.92", "/acc"))) == 1
    project = manifest(tmp_path, claim("0.92", "/accuracy"))
    assert check(project) == 0

    before, after = recorded(tmp_path)
    assert (before.address, after.address) == ("/acc", "/accuracy")
    assert before.printed == after.printed == "0.92"
    digest = Digest.of_file(tmp_path / "results.json").value[:12]
    assert established(project, capsys) == [
        f"checked {before.checked_at}: reported 0.92 at /acc, results {digest}: mismatch",
        f"since {after.checked_at}: reported 0.92 at /accuracy, results {digest}: verified "
        "(after mismatch: address changed)",
    ]


def test_claim_text_changed_alone_is_a_new_state_named_as_the_text(tmp_path, capsys):
    put(tmp_path)
    assert check(manifest(tmp_path, claim("0.91", text="Accuracy is 0.92."))) == 0
    project = manifest(tmp_path, claim("0.91", text="Accuracy is 0.91."))
    assert check(project) == 0

    before, after = recorded(tmp_path)
    assert before.claim_digest != after.claim_digest
    assert before.model_copy(
        update={"claim_digest": after.claim_digest, "checked_at": after.checked_at}
    ) == (after)
    assert established(project, capsys)[1].endswith("verified (after verified: claim text changed)")


def test_a_file_edited_between_checks_is_a_new_state_with_both_digests(tmp_path, capsys):
    put(tmp_path)
    assert check(manifest(tmp_path, claim("0.92"))) == 1
    then = Digest.of_file(tmp_path / "results.json").value
    put(tmp_path, acc=0.92)
    project = manifest(tmp_path, claim("0.92"))
    assert check(project) == 0

    before, after = recorded(tmp_path)
    assert before.digests == {"results": then}
    assert after.digests == {"results": Digest.of_file(tmp_path / "results.json").value}
    shown = established(project, capsys)
    assert f"results {then[:12]}: mismatch" in shown[0]
    assert shown[1].endswith("verified (after mismatch: file changed)")


def test_an_outcome_that_changes_with_nothing_declared_changed_says_so(tmp_path, capsys):
    put(tmp_path)
    project = manifest(tmp_path, claim("0.91"))
    assert check(project) == 0
    # The record is edited here to hold a different outcome for the same declaration, which is
    # what a changed reader of the same bytes would leave.
    (line,) = checks(tmp_path)
    (state,) = line.assertions
    other = state.model_copy(update={"outcome": Outcome.UNCHECKED})
    (tmp_path / RECORD).write_text(
        line.model_copy(update={"assertions": (other,)}).model_dump_json() + "\n"
    )
    assert check(project) == 0
    assert established(project, capsys)[1].endswith(
        "verified (after unchecked: nothing declared changed)"
    )


def test_an_edit_no_recorded_check_has_seen_is_shown_as_now(tmp_path, capsys):
    put(tmp_path)
    assert check(manifest(tmp_path, claim("0.92"))) == 1
    project = manifest(tmp_path, claim("0.91"))
    assert check(project, "--no-record") == 0

    (before,) = recorded(tmp_path)
    (assertion,) = why(project, "accuracy").assertions
    assert assertion.history == (before,)
    assert (assertion.now.printed, assertion.now.outcome) == ("0.91", Outcome.VERIFIED)
    assert assertion.now.checked_at == ""
    digest = Digest.of_file(tmp_path / "results.json").value[:12]
    assert established(project, capsys) == [
        f"checked {before.checked_at}: reported 0.92 at /acc, results {digest}: mismatch",
        f"now: reported 0.91 at /acc, results {digest}: verified "
        "(after mismatch: reported changed); no check of this is recorded",
    ]


def test_with_no_record_or_one_unchanged_state_why_prints_nothing_more(tmp_path, capsys):
    put(tmp_path)
    project = manifest(tmp_path, claim("0.91"))
    capsys.readouterr()
    assert main(["why", "accuracy", str(project.path)]) == 0
    fresh = capsys.readouterr().out
    assert why(project, "accuracy").assertions[0].history == ()
    assert why(project, "accuracy").assertions[0].now is None
    assert established(project, capsys) == []

    assert check(project) == 0
    assert check(project) == 0
    capsys.readouterr()
    assert main(["why", "accuracy", str(project.path)]) == 0
    assert capsys.readouterr().out == fresh
    assert len(why(project, "accuracy").assertions[0].history) == 1


def test_an_earlier_line_of_the_record_is_never_rewritten(tmp_path):
    put(tmp_path)
    seen = []
    for reported, pointer in (
        ("0.92", "/acc"),
        ("0.93", "/acc"),
        ("0.93", "/nowhere"),
        ("0.91", "/acc"),
    ):
        check(manifest(tmp_path, claim(reported, pointer)))
        written = lines(tmp_path)
        assert written[: len(seen)] == seen
        assert len(written) == len(seen) + 1
        seen = written
    assert [state.outcome for state in recorded(tmp_path)] == [
        Outcome.MISMATCH,
        Outcome.MISMATCH,
        Outcome.NOT_FOUND,
        Outcome.VERIFIED,
    ]
    assert all(CheckRecord.model_validate_json(line) for line in seen)


def test_a_line_holds_only_the_assertions_that_changed(tmp_path):
    put(tmp_path)
    (tmp_path / "paper.txt").write_text("Accuracy was 0.91 on the held-out split.\n")

    def both(reported, second):
        return Claim(
            id="accuracy",
            text="Accuracy was 0.91.",
            evidence=(
                QuoteEvidence(artifact="paper", text="Accuracy was 0.91"),
                MetricEvidence(
                    artifact="results", name="accuracy", reported=reported, pointer="/acc"
                ),
                QuoteEvidence(artifact="paper", text=second),
            ),
        )

    check(manifest(tmp_path, both("0.92", "on the held-out split")))
    check(manifest(tmp_path, both("0.91", "on the held-in split")))
    first, second = checks(tmp_path)
    assert [(a.kind, a.position) for a in first.assertions] == [
        ("quote", 0),
        ("metric", 0),
        ("quote", 1),
    ]
    # The first quotation did not change, so the second line says nothing of it.
    assert [(a.kind, a.position, a.outcome) for a in second.assertions] == [
        ("metric", 0, Outcome.VERIFIED),
        ("quote", 1, Outcome.MISMATCH),
    ]
    assert [len(states) for states in history(tmp_path).values()] == [1, 2, 2]


def test_a_claim_given_another_id_starts_a_new_history(tmp_path):
    put(tmp_path)
    check(manifest(tmp_path, claim("0.92")))
    renamed = claim("0.91").model_copy(update={"id": "held-out"})
    project = manifest(tmp_path, renamed)
    check(project)
    assert sorted(identity[0] for identity in history(tmp_path)) == ["accuracy", "held-out"]
    (assertion,) = why(project, "held-out").assertions
    assert [state.printed for state in assertion.history] == ["0.91"]


def test_the_json_account_carries_the_history_and_reads_back(tmp_path, capsys):
    put(tmp_path)
    check(manifest(tmp_path, claim("0.92")))
    check(manifest(tmp_path, claim("0.91")))
    project = manifest(tmp_path, claim("0.91", "/accuracy"))
    capsys.readouterr()
    assert main(["why", "accuracy", str(project.path), "--format", "json"]) == 0
    document = json.loads(capsys.readouterr().out)
    account = ClaimAccount.model_validate(document)
    assert account == why(project, "accuracy")
    assert ClaimAccount.model_validate_json(account.model_dump_json()) == account
    (assertion,) = document["assertions"]
    assert [(s["printed"], s["address"], s["outcome"]) for s in assertion["history"]] == [
        ("0.92", "/acc", "mismatch"),
        ("0.91", "/acc", "verified"),
    ]
    assert (assertion["now"]["address"], assertion["now"]["checked_at"]) == ("/accuracy", "")


def test_recording_changes_nothing_verify_prints_or_returns(tmp_path, capsys):
    put(tmp_path)
    project = manifest(tmp_path, claim("0.92"))
    before = snapshot(tmp_path)
    capsys.readouterr()
    quiet = [
        (check(project, "--no-record", *flags), capsys.readouterr().out)
        for flags in ((), ("--format", "json"), ("--format", "sarif"))
    ]
    assert snapshot(tmp_path) == before
    recording = [
        (check(project, *flags), capsys.readouterr().out)
        for flags in ((), ("--format", "json"), ("--format", "sarif"))
    ]
    assert recording == quiet
    assert set(snapshot(tmp_path)) - set(before) == {RECORD.as_posix()}
    # The library call the command renders writes nothing either way.
    after = snapshot(tmp_path)
    verify(project)
    why(project, "accuracy")
    assert snapshot(tmp_path) == after


def test_a_record_that_cannot_be_read_leaves_verify_as_it_was_and_stops_why(tmp_path, capsys):
    put(tmp_path)
    project = manifest(tmp_path, claim("0.91"))
    (tmp_path / RECORD).parent.mkdir()
    (tmp_path / RECORD).write_text('{"checked_at": 3}\n')
    before = snapshot(tmp_path)
    assert check(project) == 0
    assert snapshot(tmp_path) == before

    with pytest.raises(ChecksUnreadableError, match=r"checks\.jsonl:1: "):
        why(project, "accuracy")
    capsys.readouterr()
    assert main(["why", "accuracy", str(project.path)]) == 2
    assert "checks.jsonl:1: " in capsys.readouterr().out


def test_the_hooks_and_the_audit_check_without_recording():
    hooks = yaml.safe_load((REPOSITORY / ".pre-commit-hooks.yaml").read_text())
    assert [hook["entry"].split()[:3] for hook in hooks] == [["repro", "verify", "--no-record"]] * 2
    (step,) = (s for s in default_steps(REPOSITORY, Layout()) if s.name == "repro.verify")
    assert step.argv[:3] == ["repro", "verify", "--no-record"]
