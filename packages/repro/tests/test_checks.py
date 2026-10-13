"""What each assertion said when it was checked, where that is kept, and whether the record
still holds together.

Each test makes a git repository, writes a manifest in it, runs `repro verify` as a user would,
edits the manifest, a file or the record, and runs it again.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import shutil
import subprocess
import sys
import threading

import pytest
from provenance_core import run as git
from repro.checks import (
    LOCAL,
    NOT_A_REPOSITORY,
    RECORD,
    RecordIntactError,
    Records,
    git_dir,
    record,
    set_aside,
)
from repro.cli import main
from repro.models import (
    ArtifactRef,
    CheckRecord,
    Claim,
    ClaimAccount,
    Conversion,
    Digest,
    Manifest,
    MetricEvidence,
    Outcome,
    QuoteEvidence,
)
from repro.verify import verify
from repro.why import why

IDENTITY = ("accuracy", "metric", "accuracy", 0)
EDITED = "entry 2 does not hash to what entry 3 recorded for the entry before it"


@pytest.fixture
def repo(tmp_path):
    """A git repository holding `results.json`, and nothing recorded."""
    root = tmp_path / "project"
    root.mkdir()
    git("init", "-q", cwd=root)
    put(root)
    return root


def put(root, **fields):
    (root / "results.json").write_text(json.dumps({"acc": 0.91, "accuracy": 0.91, **fields}))


def claim(reported="0.92", pointer="/acc", text="Accuracy is as reported.", name="accuracy"):
    return Claim(
        id=name,
        text=text,
        evidence=(
            MetricEvidence(artifact="results", name="accuracy", reported=reported, pointer=pointer),
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


def local(root):
    return git_dir(root) / LOCAL


def entries(path):
    return path.read_bytes().splitlines(keepends=True) if path.exists() else []


def recorded(root):
    return Records(root).history[IDENTITY]


def tree(root):
    """Every file of the working tree by digest. The git directory is not the working tree."""
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file() and ".git" not in p.relative_to(root).parts
    }


def shown(project, capsys, name="accuracy"):
    """What `repro why` prints under `established` after the first assertion's outcome, the
    chain of files left out."""
    capsys.readouterr()
    assert main(["why", name, str(project.path)]) == 0
    out = capsys.readouterr().out
    block = out.partition("\nestablished\n")[2].partition("\n\nnot established")[0]
    lines = [line.strip() for line in block.splitlines()[4:]]
    dropped = ("chain", "results (", "no command recorded", "record of checks")
    return [line for line in lines if not line.startswith(dropped)]


def rewrite(path, change):
    """Edit a record's lines in place, leaving its head file as it was."""
    lines = path.read_text().splitlines()
    change(lines)
    path.write_text("".join(f"{line}\n" for line in lines))


def forge(lines):
    """Make the second entry say another value was reported."""
    lines[1] = lines[1].replace('"0.91"', '"0.99"')


def three_states(root, *flags):
    """Three recorded states of one assertion: mismatch, verified, mismatch."""
    for reported in ("0.92", "0.91", "0.93"):
        project = manifest(root, claim(reported))
        check(project, *flags)
    return project


def test_plain_verify_leaves_the_working_tree_as_it_was_and_the_local_record_grows(repo):
    project = manifest(repo, claim("0.92"))
    before = tree(repo)
    assert check(project) == 1
    assert tree(repo) == before
    (first,) = entries(local(repo))
    for flags in ((), ("--format", "json"), ("--format", "sarif"), ("--policy", "strict")):
        assert check(project, *flags) == 1
    assert entries(local(repo)) == [first]
    assert tree(repo) == before

    project = manifest(repo, claim("0.91"))
    before = tree(repo)
    assert check(project) == 0
    assert entries(local(repo))[0] == first and len(entries(local(repo))) == 2
    assert tree(repo) == before

    entry = CheckRecord.model_validate_json(first)
    (state,) = entry.assertions
    assert (entry.seq, entry.prev_hash) == (0, "0" * 64)
    assert (state.printed, state.address, state.outcome) == ("0.92", "/acc", Outcome.MISMATCH)
    assert state.digests == {"results": Digest.of_file(repo / "results.json").value}
    last = entries(local(repo))[1]
    second = CheckRecord.model_validate_json(last)
    assert (second.seq, second.prev_hash) == (1, hashlib.sha256(first.strip()).hexdigest())
    head = json.loads((local(repo).parent / "ledger.head").read_text())
    assert (head["count"], head["head"]) == (2, hashlib.sha256(last.strip()).hexdigest())


def test_a_reported_value_changed_after_a_mismatch_is_shown_with_both_states_in_order(repo, capsys):
    check(manifest(repo, claim("0.92")))
    project = manifest(repo, claim("0.91"))
    check(project)
    before, after = recorded(repo)
    assert (before.printed, before.outcome) == ("0.92", Outcome.MISMATCH)
    assert (after.printed, after.outcome) == ("0.91", Outcome.VERIFIED)
    assert before.checked_at < after.checked_at

    account = why(project, "accuracy")
    assert account.assertions[0].history == (before, after)
    assert account.assertions[0].now is None and account.no_local_record == ""
    digest = Digest.of_file(repo / "results.json").value[:12]
    assert shown(project, capsys) == [
        f"checked {before.checked_at}: reported 0.92 at /acc, results {digest}: mismatch",
        f"since {after.checked_at}: reported 0.91 at /acc, results {digest}: verified "
        "(after mismatch: reported changed)",
    ]


@pytest.mark.parametrize(
    ("first", "second", "changed"),
    [
        (claim("0.91", "/nowhere"), claim("0.91", "/acc"), "after not found: address changed"),
        (
            claim("0.91", text="It is 0.92."),
            claim("0.91", text="It is 0.91."),
            "after verified: claim text changed",
        ),
    ],
)
def test_what_changed_between_two_states_is_named(repo, capsys, first, second, changed):
    check(manifest(repo, first))
    project = manifest(repo, second)
    check(project)
    assert shown(project, capsys)[1].endswith(f"verified ({changed})")


def test_a_conversion_declared_after_a_mismatch_is_named(repo, capsys):
    def percent(conversion):
        return Claim(
            id="accuracy",
            text="Accuracy is 91%.",
            evidence=(
                MetricEvidence(
                    artifact="results",
                    name="accuracy",
                    reported="91",
                    pointer="/acc",
                    conversion=conversion,
                ),
            ),
        )

    assert check(manifest(repo, percent(None))) == 1
    project = manifest(repo, percent(Conversion.PERCENT))
    assert check(project) == 0
    before, after = recorded(repo)
    assert (before.conversion, after.conversion) == ("", "percent")
    assert shown(project, capsys)[1].endswith("verified (after mismatch: conversion changed)")


def test_a_file_edited_between_checks_is_a_new_state_with_both_digests(repo, capsys):
    check(manifest(repo, claim("0.92")))
    then = Digest.of_file(repo / "results.json").value
    put(repo, acc=0.92)
    project = manifest(repo, claim("0.92"))
    check(project)
    before, after = recorded(repo)
    assert (before.digests, after.digests) == (
        {"results": then},
        {"results": Digest.of_file(repo / "results.json").value},
    )
    lines = shown(project, capsys)
    assert f"results {then[:12]}: mismatch" in lines[0]
    assert lines[1].endswith("verified (after mismatch: file changed)")


def test_an_edit_no_check_has_seen_is_shown_as_now_and_one_state_prints_nothing(repo, capsys):
    project = manifest(repo, claim("0.92"))
    capsys.readouterr()
    assert main(["why", "accuracy", str(project.path)]) == 0
    fresh = capsys.readouterr().out
    assert "record of checks" not in fresh
    check(project)
    check(project)
    capsys.readouterr()
    assert main(["why", "accuracy", str(project.path)]) == 0
    assert capsys.readouterr().out == fresh
    assert len(why(project, "accuracy").assertions[0].history) == 1

    project = manifest(repo, claim("0.91"))
    (before,) = recorded(repo)
    (assertion,) = why(project, "accuracy").assertions
    assert (assertion.now.printed, assertion.now.checked_at) == ("0.91", "")
    digest = Digest.of_file(repo / "results.json").value[:12]
    assert shown(project, capsys) == [
        f"checked {before.checked_at}: reported 0.92 at /acc, results {digest}: mismatch",
        f"now: reported 0.91 at /acc, results {digest}: verified "
        "(after mismatch: reported changed); no check of this is recorded",
    ]


def test_outside_a_git_repository_nothing_is_recorded_and_why_says_so(tmp_path, capfd):
    put(tmp_path)
    project = manifest(tmp_path, claim("0.92"))
    before = tree(tmp_path)
    capfd.readouterr()
    assert check(project) == 1
    assert capfd.readouterr().err == ""
    assert tree(tmp_path) == before and git_dir(tmp_path) is None

    account = why(project, "accuracy")
    assert (account.no_local_record, account.records) == (NOT_A_REPOSITORY, ())
    assert main(["why", "accuracy", str(project.path)]) == 0
    out = capfd.readouterr().out
    assert "  record of checks\n    no local record is kept here: not in a git repository\n" in out

    # Asked for, the tracked record is the one appended to.
    assert check(project, "--record") == 1
    assert check(manifest(tmp_path, claim("0.91")), "--record") == 0
    assert [s.printed for s in Records(tmp_path).history[IDENTITY]] == ["0.92", "0.91"]
    (state,) = Records(tmp_path).states
    assert (state.kind, state.entries, state.status) == ("tracked", 2, "intact")


def test_record_brings_the_tracked_copy_up_to_the_local_record_entry_for_entry(repo):
    check(manifest(repo, claim("0.92")))
    project = manifest(repo, claim("0.91"))
    assert not (repo / RECORD).exists()
    assert check(project, "--record") == 0
    first = entries(repo / RECORD)
    assert first == entries(local(repo)) and len(first) == 2
    ours, theirs = (
        json.loads((path.parent / "ledger.head").read_text())
        for path in (repo / RECORD, local(repo))
    )
    assert (ours["count"], ours["head"]) == (theirs["count"], theirs["head"])

    check(manifest(repo, claim("0.93")))
    assert entries(repo / RECORD) == first
    assert check(manifest(repo, claim("0.93")), "--record") == 1
    assert entries(repo / RECORD) == entries(local(repo))
    assert entries(repo / RECORD)[:2] == first and len(entries(repo / RECORD)) == 3
    assert [(s.kind, s.status, s.diverges_at) for s in Records(repo).states] == [
        ("local", "intact", None),
        ("tracked", "intact", None),
    ]


def test_a_clone_takes_the_tracked_entries_it_has_not_seen_and_appends_after_them(repo, tmp_path):
    check(manifest(repo, claim("0.92")), "--record")
    clone = tmp_path / "clone"
    shutil.copytree(repo, clone, ignore=shutil.ignore_patterns(".git"))
    git("init", "-q", cwd=clone)
    check(manifest(clone, claim("0.91")))
    assert entries(local(clone))[0] == entries(repo / RECORD)[0]
    assert [s.printed for s in Records(clone).history[IDENTITY]] == ["0.92", "0.91"]
    assert CheckRecord.model_validate_json(entries(local(clone))[1]).seq == 1


def test_a_linked_worktree_records_into_its_own_git_directory(repo, tmp_path):
    check(manifest(repo, claim("0.92")))
    mine = entries(local(repo))
    linked = tmp_path / "linked"
    git("worktree", "add", "-q", "--orphan", "-b", "linked", str(linked), cwd=repo)
    put(linked)
    check(manifest(linked, claim("0.91")))
    assert local(linked) == git_dir(repo) / "worktrees" / "linked" / LOCAL
    assert len(entries(local(linked))) == 1
    assert entries(local(repo)) == mine


@pytest.mark.parametrize("kind", ["local", "tracked"])
def test_an_entry_edited_in_the_middle_is_reported_with_its_number(repo, capsys, kind):
    project = three_states(repo, "--record")
    path = local(repo) if kind == "local" else repo / RECORD
    rewrite(path, forge)

    account = why(project, "accuracy")
    state = next(s for s in account.records if s.kind == kind)
    other = next(s for s in account.records if s.kind != kind)
    assert (state.status, state.unverifiable_from, state.entries) == ("edited", 2, 3)
    assert state.problems == (EDITED,)
    assert (other.status, other.unverifiable_from) == ("intact", None)
    assert account.records[1].diverges_at == 2

    # The edited entry is shown as it now reads and marked. What the other record still
    # vouches for is not.
    capsys.readouterr()
    assert main(["why", "accuracy", str(project.path)]) == 0
    out = capsys.readouterr().out
    forged = [line for line in out.splitlines() if "reported 0.99" in line]
    assert len(forged) == 1 and forged[0].endswith("[unverifiable]")
    assert sum(line.endswith("[unverifiable]") for line in out.splitlines()) == 1
    assert f"    {kind} {path}: 3 entries, edited: {EDITED}; unverifiable from entry 2" in out
    assert "diverges from the local record at entry 2" in out


def test_an_entry_removed_from_the_middle_is_reported_with_its_number(repo, capsys):
    project = three_states(repo)
    rewrite(local(repo), lambda lines: lines.pop(1))
    (state,) = why(project, "accuracy").records
    assert (state.status, state.unverifiable_from) == ("edited", 1)
    assert state.problems == (
        "entry 1 does not hash to what entry 2 recorded for the entry before it",
        "entry 2 is numbered 3 of the chain",
        "the head file records 3 entries, the record holds 2",
    )
    lines = shown(project, capsys)
    assert [line.endswith("[unverifiable]") for line in lines[:2]] == [True, True]
    assert lines[-1].endswith("unverifiable from entry 1")


def test_a_gap_in_the_numbering_and_entries_cut_from_the_end_are_each_reported(repo, capsys):
    project = three_states(repo)
    kept = local(repo).read_text()
    rewrite(local(repo), lambda lines: lines.__setitem__(2, lines[2].replace('"seq":2', '"seq":5')))
    (state,) = why(project, "accuracy").records
    assert (state.status, state.unverifiable_from) == ("reordered", 3)
    assert state.problems == (
        "entry 3 is numbered 6 of the chain",
        "entry 3 does not hash to what the head file records",
    )

    local(repo).write_text(kept)
    assert why(project, "accuracy").records[0].status == "intact"
    rewrite(local(repo), lambda lines: lines.pop())
    (state,) = why(project, "accuracy").records
    assert (state.status, state.unverifiable_from) == ("truncated", None)
    assert shown(project, capsys)[-1].endswith(
        "2 entries, truncated: the head file records 3 entries, the record holds 2"
    )


def test_a_tracked_record_that_is_not_the_local_ones_beginning_is_said_to_diverge(
    repo, tmp_path, capfd
):
    check(manifest(repo, claim("0.92")), "--record")
    other = tmp_path / "other"
    shutil.copytree(repo, other, ignore=shutil.ignore_patterns(".git"))
    git("init", "-q", cwd=other)
    check(manifest(other, claim("0.95")), "--record")
    project = manifest(repo, claim("0.91"))
    check(project)
    # What a pull of the other clone's tracked record leaves here.
    shutil.copytree(other / ".repro", repo / ".repro", dirs_exist_ok=True)

    account = why(project, "accuracy")
    here, there = account.records
    assert (here.diverges_at, there.diverges_at) == (None, 2)
    assert (there.status, there.unverifiable_from) == ("intact", None)
    assert sorted(s.printed for s in account.assertions[0].history) == ["0.91", "0.92", "0.95"]
    capfd.readouterr()
    assert main(["why", "accuracy", str(project.path)]) == 0
    assert (
        f"tracked {repo / RECORD}: 2 entries, diverges from the local record at entry 2"
        in capfd.readouterr().out
    )

    held = entries(repo / RECORD)
    assert check(project, "--record") == 0
    assert capfd.readouterr().err == (
        f"record not written: {repo / RECORD}: diverges from the local record at entry 2\n"
    )
    assert entries(repo / RECORD) == held


def test_a_claim_given_another_id_after_a_failed_check_is_named_under_the_new_one(repo, capsys):
    check(manifest(repo, claim("0.92")))
    project = manifest(repo, claim("0.92", name="held-out"))
    check(project)
    (old,) = Records(repo).history[IDENTITY]

    (assertion,) = why(project, "held-out").assertions
    assert assertion.formerly == (old,) and len(assertion.history) == 1
    assert shown(project, capsys, "held-out") == [
        f"a claim named accuracy was last checked {old.checked_at} at this address: mismatch, "
        "and is no longer declared"
    ]

    # Not at another address, and not where the old claim verified when last checked.
    moved = manifest(repo, claim("0.92", "/accuracy", name="moved"))
    assert why(moved, "moved").assertions[0].formerly == ()
    check(manifest(repo, claim("0.91")))
    renamed = manifest(repo, claim("0.91", name="held-out"))
    assert why(renamed, "held-out").assertions[0].formerly == ()


def test_checks_running_at_once_append_one_after_another(repo):
    reports = []
    for reported in ("0.92", "0.91"):
        project = manifest(repo, claim(reported))
        reports.append((project, verify(project)))
    failures = []

    def run(index):
        try:
            record(*reports[index % 2])
        except Exception as e:
            failures.append(e)

    threads = [threading.Thread(target=run, args=(index,)) for index in range(12)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert failures == []
    written = [CheckRecord.model_validate_json(line) for line in entries(local(repo))]
    assert [entry.seq for entry in written] == list(range(len(written)))
    (state,) = Records(repo).states
    assert (state.status, state.problems) == ("intact", ())
    # Each entry differs from the one before it: every check read what the last one wrote.
    printed = [entry.assertions[0].printed for entry in written]
    assert len(printed) >= 2
    assert all(a != b for a, b in itertools.pairwise(printed))


def test_the_json_account_carries_the_records_and_reads_back(repo, capsys):
    three_states(repo, "--record")
    project = manifest(repo, claim("0.93", name="renamed"))
    rewrite(local(repo), forge)
    capsys.readouterr()
    assert main(["why", "renamed", str(project.path), "--format", "json"]) == 0
    document = json.loads(capsys.readouterr().out)
    account = ClaimAccount.model_validate(document)
    assert account == why(project, "renamed")
    assert ClaimAccount.model_validate_json(account.model_dump_json()) == account
    assert [
        (r["kind"], r["status"], r["unverifiable_from"], r["diverges_at"])
        for r in document["records"]
    ] == [("local", "edited", 2, None), ("tracked", "intact", None, 2)]
    (assertion,) = document["assertions"]
    assert [(s["claim_id"], s["printed"], s["outcome"]) for s in assertion["formerly"]] == [
        ("accuracy", "0.93", "mismatch")
    ]
    assert document["no_local_record"] == ""


def test_verify_prints_and_returns_the_same_whatever_the_record(repo, capfd):
    project = three_states(repo)

    def run(*flags, local_record=True):
        capfd.readouterr()
        code = main(["verify", str(project.path), *flags], local_record=local_record)
        return code, capfd.readouterr()

    formats = ((), ("--format", "json"), ("--format", "sarif"))
    wanted = [run(*flags, local_record=False) for flags in formats]
    assert all(streams.err == "" for _, streams in wanted)
    assert [run(*flags) for flags in formats] == wanted

    # A record that does not verify is said on standard error and appended to no further.
    rewrite(local(repo), forge)
    project = manifest(repo, claim("0.94"))
    held = entries(local(repo))
    wanted = [run(*flags, local_record=False) for flags in formats]
    for flags, (code, streams) in zip(formats, wanted, strict=True):
        got_code, got = run(*flags)
        assert (got_code, got.out) == (code, streams.out)
        assert got.err == (
            f"record not written: {local(repo)}: refusing to append to a chain reported as "
            f"edited: {EDITED}; `repro verify --set-aside-record` keeps it and starts anew\n"
        )
    assert entries(local(repo)) == held


def test_a_git_directory_that_cannot_be_written_to_is_said_in_one_line(repo, capfd):
    project = manifest(repo, claim("0.92"))
    (git_dir(repo) / "repro").write_text("")
    before = tree(repo)
    capfd.readouterr()
    assert main(["verify", str(project.path)], local_record=False) == 1
    wanted = capfd.readouterr()
    assert check(project) == 1
    got = capfd.readouterr()
    assert got.out == wanted.out
    assert got.err.startswith("record not written: ") and got.err.count("\n") == 1
    assert str(git_dir(repo) / "repro") in got.err
    assert tree(repo) == before


def test_an_audit_keeps_no_record_in_the_repository_it_reads(repo):
    project = manifest(repo, claim("0.92"))
    assert main(["verify", str(project.path)], local_record=False) == 1
    assert not local(repo).exists() and not (repo / RECORD).exists()
    assert check(project) == 1
    assert local(repo).exists()


def test_two_quotations_in_one_claim_are_followed_by_their_position(repo):
    (repo / "paper.txt").write_text("Accuracy was 0.91 on the held-out split.\n")

    def both(second):
        return Claim(
            id="accuracy",
            text="Accuracy was 0.91.",
            evidence=(
                QuoteEvidence(artifact="paper", text="Accuracy was 0.91"),
                QuoteEvidence(artifact="paper", text=second),
            ),
        )

    check(manifest(repo, both("on the held-out split")))
    check(manifest(repo, both("on the held-in split")))
    first, second = (CheckRecord.model_validate_json(line) for line in entries(local(repo)))
    assert [(a.kind, a.position) for a in first.assertions] == [("quote", 0), ("quote", 1)]
    assert [(a.kind, a.position, a.outcome) for a in second.assertions] == [
        ("quote", 1, Outcome.MISMATCH)
    ]


def test_separate_processes_checking_at_once_write_one_chain(repo):
    """What the status line and a hook do: several `repro verify` processes, started together,
    over one repository, round after round as the manifest changes."""
    rounds, at_once = ("0.92", "0.91", "0.93", "0.91"), 5
    for reported in rounds:
        project = manifest(repo, claim(reported))
        alone = main(["verify", str(project.path)], local_record=False)
        started = [
            subprocess.Popen(
                [sys.executable, "-m", "repro", "verify", str(project.path)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            for _ in range(at_once)
        ]
        finished = [(process.communicate(timeout=300), process.returncode) for process in started]
        # Each exits as a lone check does, and none had anything to say about the record.
        assert [code for _, code in finished] == [alone] * at_once
        assert [streams[1] for streams, _ in finished] == [""] * at_once
        assert len({streams[0] for streams, _ in finished}) == 1

    written = [CheckRecord.model_validate_json(line) for line in entries(local(repo))]
    # One entry per round: the first process to hold the lock wrote it and the rest found it.
    assert [entry.assertions[0].printed for entry in written] == list(rounds)
    assert [entry.seq for entry in written] == list(range(len(rounds)))
    assert len(set(entries(local(repo)))) == len(rounds)
    (state,) = Records(repo).states
    assert (state.status, state.problems, state.entries) == ("intact", (), len(rounds))


def test_a_checkout_whose_git_directory_is_inside_another_repositorys_records_there(tmp_path):
    """The layout of a submodule: a working tree whose `.git` is a file naming a directory
    under the superproject's `.git/modules/`."""
    above = tmp_path / "super"
    above.mkdir()
    git("init", "-q", cwd=above)
    put(above)
    check(manifest(above, claim("0.92")))
    theirs = entries(local(above))

    inside = above / "vendored"
    modules = git_dir(above) / "modules" / "vendored"
    modules.parent.mkdir()
    git("init", "-q", f"--separate-git-dir={modules}", str(inside), cwd=above)
    put(inside)
    project = manifest(inside, claim("0.91"))
    before = tree(inside)
    assert (inside / ".git").is_file()
    assert check(project) == 0

    assert local(inside) == modules / LOCAL
    assert len(entries(local(inside))) == 1
    assert entries(local(above)) == theirs
    # `.git` here is a file, and it is as it was with everything else.
    assert tree(inside) == before
    assert (inside / ".git").read_text().strip() == f"gitdir: {modules}"


def kept(directory):
    """Every file in a record's directory by digest, the lock beside it left out."""
    return {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(directory.iterdir())
        if not p.name.endswith(".provenance-lock")
    }


def test_a_damaged_record_is_set_aside_by_name_and_the_new_chain_says_so(repo, capfd):
    three_states(repo)
    rewrite(local(repo), forge)
    old = kept(local(repo).parent)
    first = hashlib.sha256(entries(local(repo))[0].strip()).hexdigest()
    project = manifest(repo, claim("0.94"))
    before = tree(repo)

    capfd.readouterr()
    assert main(["verify", str(project.path)], local_record=False) == 1
    wanted = capfd.readouterr().out
    assert check(project, "--set-aside-record") == 1
    got = capfd.readouterr()
    assert got.out == wanted
    (name,) = (n for n in kept(local(repo).parent) if n.startswith("checks.jsonl.set-aside-"))
    stamp = name.rpartition("-")[2]
    assert got.err == (
        f"record set aside: the local record is kept as {name}, and a new one starts by saying so\n"
    )
    assert tree(repo) == before

    # The old record and its head file are there under the new names, byte for byte.
    now = kept(local(repo).parent)
    assert now[name] == old["checks.jsonl"]
    assert now[f"ledger.head.set-aside-{stamp}"] == old["ledger.head"]
    assert set(now) == {name, f"ledger.head.set-aside-{stamp}", "checks.jsonl", "ledger.head"}

    opening, then = (CheckRecord.model_validate_json(line) for line in entries(local(repo)))
    note = opening.set_aside
    assert (opening.seq, opening.prev_hash, opening.assertions) == (0, "0" * 64, ())
    assert (note.kind, note.kept_as, note.entries, note.status) == ("local", name, 3, "edited")
    assert (note.head, note.problems) == (first, (EDITED,))
    assert (then.seq, then.set_aside, then.assertions[0].printed) == (1, None, "0.94")
    (state,) = Records(repo).states
    assert (state.status, state.problems) == ("intact", ())

    account = why(project, "accuracy")
    assert account.set_aside == (note.model_copy(update={"at": opening.timestamp}),)
    assert ClaimAccount.model_validate_json(account.model_dump_json()) == account
    assert main(["why", "accuracy", str(project.path)]) == 0
    out = capfd.readouterr().out
    assert out.count("was set aside on") == 1
    assert (
        f"  record of checks\n    a local record of 3 entries was set aside on "
        f"{opening.timestamp} as {name}: reported edited ({EDITED}); its last entry that "
        f"verified hashes to {first[:12]}\n"
    ) in out

    # Checks go on in the new chain, and a second asking finds nothing to set aside.
    held = entries(local(repo))
    assert check(project, "--set-aside-record") == 1
    assert capfd.readouterr().err == (
        f"record not set aside: {repo}: no record here is damaged, so none is set aside\n"
    )
    assert entries(local(repo)) == held and kept(local(repo).parent) == now


def test_an_intact_record_is_not_set_aside(repo):
    project = three_states(repo, "--record")
    here, there = kept(local(repo).parent), kept(repo / ".repro")
    with pytest.raises(RecordIntactError):
        set_aside(project, tracked=True)
    assert (kept(local(repo).parent), kept(repo / ".repro")) == (here, there)


def test_a_tracked_record_follows_a_local_one_that_started_again_only_when_set_aside_too(
    repo, capfd
):
    project = three_states(repo, "--record")
    rewrite(local(repo), forge)
    tracked = kept(repo / ".repro")
    assert check(project, "--set-aside-record") == 1
    # Not asked for, the tracked record is left as it was, and no longer begins the local one.
    assert kept(repo / ".repro") == tracked
    assert Records(repo).state("tracked").diverges_at == 1
    capfd.readouterr()
    assert check(project, "--record") == 1
    assert capfd.readouterr().err == (
        f"record not written: {repo / RECORD}: diverges from the local record at entry 1\n"
    )

    assert check(project, "--record", "--set-aside-record") == 1
    (name,) = (n for n in kept(repo / ".repro") if n.startswith("checks.jsonl.set-aside-"))
    assert kept(repo / ".repro")[name] == tracked["checks.jsonl"]
    assert entries(repo / RECORD) == entries(local(repo))
    notes = Records(repo).set_aside
    assert [(note.kind, note.status) for note in notes] == [
        ("local", "edited"),
        ("tracked", "intact"),
    ]
    assert notes[1].problems == ("diverges from the local record at entry 1",)
    assert [(s.kind, s.status, s.diverges_at) for s in Records(repo).states] == [
        ("local", "intact", None),
        ("tracked", "intact", None),
    ]
