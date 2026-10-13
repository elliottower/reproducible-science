"""For one claim: what the record establishes, and what it does not.

Nothing here executes a command. As in `test_stale.py`, the record of re-runs is written with
the models `repro reproduce` writes it with, and the files are edited afterwards.
"""

from __future__ import annotations

import hashlib
import json

import pytest
from repro.cli import main
from repro.models import (
    ArtifactRef,
    Claim,
    ClaimAccount,
    CorrespondenceEvidence,
    CorrespondenceSide,
    Digest,
    Freshness,
    InputReading,
    Manifest,
    MetricEvidence,
    NotEstablishedKind,
    Outcome,
    QuoteEvidence,
    Reason,
    Regeneration,
    RegenerationReason,
    RegenerationRecord,
    RegenerationState,
    ReproductionReport,
    RunOutput,
    StaleCause,
    TableCellEvidence,
    TreeLocator,
    Validity,
    Warning_,
)
from repro.regenerate import canonical_digest
from repro.reproduce import append
from repro.stale import stale
from repro.verify import verify
from repro.why import (
    ADDRESS_IS_CHOSEN,
    COMPARISON_ONLY,
    MAX_LISTED,
    UNDECLARED_INPUTS,
    UnknownClaimError,
    why,
)

THEN = "2026-01-01T00:00:00+00:00"

ALWAYS = [
    (NotEstablishedKind.UNDECLARED_INPUTS, "", UNDECLARED_INPUTS),
    (NotEstablishedKind.ADDRESS, "", ADDRESS_IS_CHOSEN),
    (NotEstablishedKind.COMPARISON, "", COMPARISON_ONLY),
]


def file(root, name):
    return root / f"{name}.json"


def put(root, name, **fields):
    file(root, name).write_text(json.dumps({"total": 6, **fields}))


def record(root, name, inputs, output):
    return RegenerationRecord(
        id=name,
        command=("make", name),
        inputs=tuple(RunOutput(artifact=i, digest=Digest.of_file(file(root, i))) for i in inputs),
        output=RunOutput(artifact=output, digest=Digest.of_file(file(root, output))),
    )


def claim(artifact, reported="6", pointer="/total"):
    return Claim(
        id=f"on-{artifact}",
        text=f"The total in {artifact} is {reported}.",
        evidence=(
            MetricEvidence(artifact=artifact, name="total", reported=reported, pointer=pointer),
        ),
    )


def manifest(root, records, claims):
    project = Manifest(
        project="p",
        path=root / "repro.yaml",
        artifacts=tuple(
            ArtifactRef(id=p.stem, path=p, digest=Digest.of_file(p))
            for p in sorted(p for p in root.iterdir() if p.suffix in (".json", ".txt", ".csv"))
        ),
        regenerations=tuple(records),
        claims=tuple(claims),
    )
    project.path.write_text(project.model_dump_json())
    return project


def rerun(root, made):
    written = Digest.of_file(file(root, made.output.artifact)).value
    return RegenerationState(
        regeneration_id=made.id,
        artifact_id=made.output.artifact,
        state=Regeneration.REPRODUCED,
        reason=RegenerationReason.OUTPUT_MATCHES,
        expected=written,
        actual=written,
        executed=True,
        bytes_identical=True,
        command=made.command,
        inputs=tuple(
            InputReading(
                artifact_id=wanted.artifact,
                path=wanted.artifact,
                pinned=wanted.digest.value,
                observed=Digest.of_file(file(root, wanted.artifact)).value,
            )
            for wanted in made.inputs
        ),
    )


def chain(root, length, rerun_them=True):
    """`a0 -> ra1 -> a1 -> ...`, each record re-run over the files as written."""
    for i in range(length + 1):
        put(root, f"a{i}", step=i)
    records = [record(root, f"ra{i}", (f"a{i - 1}",), f"a{i}") for i in range(1, length + 1)]
    if rerun_them:
        append(
            ReproductionReport(
                started_at=THEN, regenerations=tuple(rerun(root, made) for made in records)
            ),
            root,
        )
    return records


def said(account):
    return [(line.kind, line.subject, line.said) for line in account.not_established]


def printed(project, claim_id, capsys):
    """The command's three parts: what it lists as established, as not established, and the
    summary."""
    assert main(["why", claim_id, str(project.path)]) == 0
    head, _, rest = capsys.readouterr().out.partition("\nestablished\n")
    established, _, rest = rest.partition("\nnot established\n")
    not_established, _, summary = rest.rstrip().rpartition("\n\n")
    assert f"{claim_id}\n  The total in " in head
    return established, not_established.splitlines(), summary.strip()


def snapshot(root):
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def test_a_rerun_producer_is_established_and_only_its_input_is_not(tmp_path, capsys):
    project = manifest(tmp_path, chain(tmp_path, 1), [claim("a1")])
    account = why(project, "on-a1")

    (assertion,) = account.assertions
    (read,) = assertion.reads
    assert (assertion.outcome, assertion.printed, assertion.state) == (
        Outcome.VERIFIED,
        "6",
        Freshness.CURRENT,
    )
    assert (read.artifact, read.address, read.stored) == ("a1", "/total", "6")
    assert read.validity is Validity.AUTHORITATIVE
    assert read.pinned == read.on_disk == Digest.of_file(file(tmp_path, "a1")).value

    produced, given = account.chain
    assert (produced.artifact, produced.steps, produced.state) == ("a1", 0, Freshness.CURRENT)
    assert (produced.command, produced.regeneration.id) == (("make", "ra1"), "ra1")
    assert produced.regeneration.rerun_at == THEN
    assert (given.artifact, given.steps, given.state) == ("a0", 1, Freshness.NO_PRODUCER)
    assert given.regeneration is None and given.command == ()

    a0 = file(tmp_path, "a0").as_posix()
    assert said(account) == [
        (
            NotEstablishedKind.NO_PRODUCER,
            a0,
            "no command is recorded for it; its bytes are pinned and taken as given",
        ),
        *ALWAYS,
    ]

    established, not_established, summary = printed(project, "on-a1", capsys)
    assert f"matches its pinned digest {read.pinned[:12]}" in established
    assert "a1 at /total: holds 6\n    the manuscript prints 6: verified" in established
    assert "): current\n      written by ra1: make ra1\n      which reads a0 (" in established
    assert (account.outcomes, account.states) == (
        {Outcome.VERIFIED: 1},
        {Freshness.CURRENT: 1},
    )
    assert f"re-run of {THEN} reproduced, and its output is the bytes now on disk" in established
    assert "): no producer, 1 step up\n      no command recorded" in established
    assert not_established == [
        f"  {a0}: no command is recorded for it; its bytes are pinned and taken as given",
        f"  {UNDECLARED_INPUTS}",
        f"  {ADDRESS_IS_CHOSEN}",
        f"  {COMPARISON_ONLY}",
    ]
    assert summary == (
        "1 assertion: 1 verified; 1 of 1 reads a file with a recorded producer, 1 current"
    )


def test_a_claim_reading_a_file_no_command_writes_has_a_chain_of_that_file(tmp_path, capsys):
    project = manifest(tmp_path, chain(tmp_path, 1), [claim("a0")])
    account = why(project, "on-a0")
    (only,) = account.chain
    assert (only.artifact, only.steps, only.state) == ("a0", 0, Freshness.NO_PRODUCER)
    assert only.regeneration is None
    assert [edge.kind for edge in account.edges] == ["reads"]
    assert [kind for kind, _, _ in said(account)] == [
        NotEstablishedKind.NO_PRODUCER,
        NotEstablishedKind.ADDRESS,
        NotEstablishedKind.COMPARISON,
    ]

    established, _, summary = printed(project, "on-a0", capsys)
    assert "written by" not in established and "re-run" not in established
    assert summary == "1 assertion: 1 verified; 0 of 1 read a file with a recorded producer"


def test_a_producer_with_no_recorded_rerun_is_named_as_never_rerun(tmp_path, capsys):
    project = manifest(tmp_path, chain(tmp_path, 1, rerun_them=False), [claim("a1")])
    account = why(project, "on-a1")
    assert account.chain[0].state is Freshness.NEVER_RERUN
    assert account.chain[0].regeneration.rerun_at is None
    a1 = file(tmp_path, "a1").as_posix()
    assert said(account)[1] == (
        NotEstablishedKind.NEVER_RERUN,
        "ra1",
        "no re-run that reproduced is recorded; nothing in the record shows the command "
        f"produces {a1}",
    )
    assert len(account.not_established) == 2 + len(ALWAYS)

    established, _, summary = printed(project, "on-a1", capsys)
    assert "): never rerun\n      written by ra1: make ra1\n" in established
    assert "no re-run of ra1 that reproduced is recorded" in established
    assert "its output is the bytes now on disk" not in established
    assert summary.endswith("1 of 1 reads a file with a recorded producer, 1 never rerun")


def test_an_input_edited_after_the_rerun_is_stale_with_its_cause_under_established(
    tmp_path, capsys
):
    project = manifest(tmp_path, chain(tmp_path, 1), [claim("a1")])
    before = Digest.of_file(file(tmp_path, "a0")).value
    put(tmp_path, "a0", step="edited")
    after = Digest.of_file(file(tmp_path, "a0")).value

    account = why(project, "on-a1")
    assert account.assertions[0].outcome is Outcome.VERIFIED
    assert account.assertions[0].state is Freshness.STALE
    assert account.chain[0].regeneration.causes == (StaleCause.INPUT_CHANGED,)
    (found,) = account.findings
    assert (found.regeneration, found.artifact) == ("ra1", "a0")
    assert (found.observed, found.on_disk) == (before, after)
    # The edit also broke the pin of the file nothing produces, and the line says so.
    assert said(account)[0][2] == (
        "no command is recorded for it; its bytes are not the pinned ones and are taken as given"
    )

    established, not_established, summary = printed(project, "on-a1", capsys)
    assert "): stale\n      written by ra1: make ra1\n" in established
    assert f"the re-run of {THEN} read {before[:12]}, on disk {after[:12]}" in established
    assert "input changed: a0 (" in established
    assert not [line for line in not_established if "stale" in line or "input changed" in line]
    assert summary == (
        "1 assertion: 1 verified; 1 of 1 reads a file with a recorded producer, 1 stale"
    )


def test_a_value_the_manuscript_does_not_print_is_a_mismatch_under_established(tmp_path, capsys):
    project = manifest(tmp_path, chain(tmp_path, 1), [claim("a1", reported="7")])
    account = why(project, "on-a1")
    (assertion,) = account.assertions
    assert (assertion.outcome, assertion.printed, assertion.reads[0].stored) == (
        Outcome.MISMATCH,
        "7",
        "6",
    )
    assert said(account)[1:] == ALWAYS

    established, not_established, summary = printed(project, "on-a1", capsys)
    assert "a1 at /total: holds 6\n    the manuscript prints 7: mismatch" in established
    assert not [line for line in not_established if "mismatch" in line]
    assert summary.startswith("1 assertion: 1 mismatch; ")


def test_an_assertion_that_was_not_checked_is_named_with_its_reason(tmp_path, capsys):
    records = chain(tmp_path, 1)
    put(tmp_path, "gone")
    absent = claim("a1", pointer="/no/such/key")
    missing = Claim(
        id="both",
        text="The total in each is 6.",
        evidence=(*absent.evidence, *claim("gone").evidence, *claim("a1").evidence),
    )
    project = manifest(tmp_path, records, [missing])
    file(tmp_path, "gone").unlink()

    account = why(project, "both")
    assert [a.outcome for a in account.assertions] == [
        Outcome.NOT_FOUND,
        Outcome.UNCHECKED,
        Outcome.VERIFIED,
    ]
    assert [a.reason for a in account.assertions[:2]] == [
        Reason.POINTER_ABSENT,
        Reason.ARTIFACT_MISSING,
    ]
    named = [(kind, subject) for kind, subject, _ in said(account)]
    assert (NotEstablishedKind.NOT_FOUND, "metric total") in named
    assert (NotEstablishedKind.UNCHECKED, "metric total") in named
    lines = {kind: line for kind, _, line in said(account)}
    assert lines[NotEstablishedKind.NOT_FOUND].startswith("not found: pointer absent")
    assert lines[NotEstablishedKind.UNCHECKED].startswith("unchecked: artifact missing")
    # The file that is not there is not taken as given, and nothing produces it.
    assert [s for k, s, _ in said(account) if k is NotEstablishedKind.NO_PRODUCER] == [
        file(tmp_path, "a0").as_posix()
    ]

    established, _, summary = printed(project, "both", capsys)
    assert "a1 at /no/such/key: no value was read" in established
    assert "the manuscript prints 6: not found (pointer absent)" in established
    assert "nothing at the declared path" in established
    assert summary.startswith("3 assertions: 1 verified, 1 not found, 1 unchecked; 2 of 3 read ")
    assert account.outcomes == {Outcome.VERIFIED: 1, Outcome.NOT_FOUND: 1, Outcome.UNCHECKED: 1}


def test_a_chain_of_two_commands_lists_both_and_the_file_under_them(tmp_path, capsys):
    project = manifest(tmp_path, chain(tmp_path, 2), [claim("a2"), claim("a1")])
    account = why(project, "on-a2")
    assert [
        (n.artifact, n.steps, n.regeneration.id if n.regeneration else None) for n in account.chain
    ] == [
        ("a2", 0, "ra2"),
        ("a1", 1, "ra1"),
        ("a0", 2, None),
    ]
    assert [n.command for n in account.chain] == [("make", "ra2"), ("make", "ra1"), ()]
    assert sorted((e.kind, e.source, e.target) for e in account.edges) == [
        ("consumes", "ra1", "a0"),
        ("consumes", "ra2", "a1"),
        ("produced_by", "a1", "ra1"),
        ("produced_by", "a2", "ra2"),
        ("reads", "on-a2", "a2"),
    ]

    put(tmp_path, "a0", step="edited")
    account = why(project, "on-a2")
    near, far, _ = account.chain
    assert (near.state, near.regeneration.upstream, near.regeneration.distance) == (
        Freshness.STALE,
        "ra1",
        1,
    )
    assert far.regeneration.causes == (StaleCause.INPUT_CHANGED,)
    assert [f.regeneration for f in account.findings] == ["ra1"]

    established, _, _ = printed(project, "on-a2", capsys)
    assert "): stale\n      written by ra2: make ra2\n" in established
    assert "upstream stale: ra1, 1 step up" in established
    assert "): stale, 1 step up\n      written by ra1: make ra1\n" in established
    assert "): no producer, 2 steps up\n      no command recorded" in established


def test_the_json_document_is_the_account(tmp_path, capsys):
    project = manifest(tmp_path, chain(tmp_path, 2), [claim("a2", reported="7")])
    put(tmp_path, "a0", step="edited")
    assert main(["why", "on-a2", str(project.path), "--format", "json"]) == 0
    document = json.loads(capsys.readouterr().out)
    account = ClaimAccount.model_validate(document)
    assert account == why(project, "on-a2")
    assert ClaimAccount.model_validate_json(account.model_dump_json()) == account
    assert document["assertions"][0]["outcome"] == "mismatch"
    assert (document["outcomes"], document["states"]) == ({"mismatch": 1}, {"stale": 1})
    assert [node["artifact"] for node in document["chain"]] == ["a2", "a1", "a0"]
    assert all(set(line) == {"kind", "subject", "said"} for line in document["not_established"])
    assert [line["kind"] for line in document["not_established"]] == [
        "no_producer",
        "undeclared_inputs",
        "address",
        "comparison",
    ]


def test_a_claim_the_manifest_does_not_declare_is_an_error_naming_the_near_ones(tmp_path, capsys):
    put(tmp_path, "a0")
    many = [claim("a0").model_copy(update={"id": f"claim-{i:02d}"}) for i in range(30)]
    project = manifest(tmp_path, [], [*many, claim("a0")])

    with pytest.raises(UnknownClaimError, match=r"nearest: on-a0$"):
        why(project, "on-a")
    with pytest.raises(UnknownClaimError) as raised:
        why(project, "zzz")
    listed = str(raised.value).partition("declared: ")[2]
    assert listed == ", ".join(f"claim-{i:02d}" for i in range(MAX_LISTED)) + ", and 21 more"

    assert main(["why", "on-a", str(project.path)]) == 2
    assert capsys.readouterr().out.strip() == (
        "the manifest declares no claim 'on-a'; nearest: on-a0"
    )


def test_with_no_claim_named_the_ids_are_listed(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main(["why"]) == 2
    assert "no repro.yaml here or above" in capsys.readouterr().out

    manifest(tmp_path, chain(tmp_path, 1), [claim("a1"), claim("a0")])
    assert main(["why"]) == 0
    assert capsys.readouterr().out == "on-a1\non-a0\n"


def test_the_command_writes_nothing_and_changes_no_other_report(tmp_path, capsys):
    project = manifest(tmp_path, chain(tmp_path, 2), [claim("a2", reported="7")])
    put(tmp_path, "a0", step="edited")
    before = snapshot(tmp_path), verify(project), stale(project)
    why(project, "on-a2")
    assert main(["why", "on-a2", str(project.path)]) == 0
    assert main(["why", "on-a2", str(project.path), "--format", "json"]) == 0
    assert (snapshot(tmp_path), verify(project), stale(project)) == before


def test_a_quotation_is_shown_as_the_passage_with_no_address(tmp_path, capsys):
    put(tmp_path, "a0")
    (tmp_path / "notes.txt").write_text("The cohort held six participants in all.\n")
    quoted = Claim(
        id="quoted",
        text="The total in notes is six.",
        evidence=(
            QuoteEvidence(artifact="notes", text="six participants"),
            QuoteEvidence(artifact="notes", text="seven participants"),
        ),
    )
    project = manifest(tmp_path, [], [quoted])
    account = why(project, "quoted")
    found, absent = account.assertions
    assert (found.kind, found.printed, found.outcome) == (
        "quote",
        "six participants",
        Outcome.VERIFIED,
    )
    assert absent.outcome is Outcome.MISMATCH
    (read,) = found.reads
    assert (read.artifact, read.address, read.stored) == ("notes", "", None)
    assert read.validity is Validity.AUTHORITATIVE
    # No command is recorded and a quotation has no address, so neither line is printed.
    assert [kind for kind, _, _ in said(account)] == [
        NotEstablishedKind.NO_PRODUCER,
        NotEstablishedKind.COMPARISON,
    ]

    established, _, summary = printed(project, "quoted", capsys)
    assert 'the passage "six participants" in notes: verified' in established
    assert 'the passage "seven participants" in notes: mismatch' in established
    assert "holds" not in established and "manuscript" not in established
    assert summary == (
        "2 assertions: 1 verified, 1 mismatch; 0 of 2 read a file with a recorded producer"
    )


def test_a_table_cell_is_shown_at_its_column_and_row_selector(tmp_path, capsys):
    put(tmp_path, "a0")
    (tmp_path / "t.csv").write_text("arm,total\ncontrol,4\ntreated,6\n")
    cell = Claim(
        id="cell",
        text="The total in the treated arm is 6.",
        evidence=(
            TableCellEvidence(
                artifact="t", name="treated", reported="6", column="total", where={"arm": "treated"}
            ),
            TableCellEvidence(
                artifact="t", name="nobody", reported="6", column="total", where={"arm": "absent"}
            ),
        ),
    )
    project = manifest(tmp_path, [], [cell])
    account = why(project, "cell")
    treated, nobody = account.assertions
    assert (treated.outcome, treated.printed, treated.reads[0].stored) == (
        Outcome.VERIFIED,
        "6",
        "6",
    )
    assert "total" in treated.reads[0].address and "treated" in treated.reads[0].address
    assert nobody.outcome is not Outcome.VERIFIED
    assert nobody.reads[0].stored is None

    established, _, _ = printed(project, "cell", capsys)
    assert f"t at {treated.reads[0].address}: holds 6" in established
    assert "the manuscript prints 6: verified" in established
    assert f"t at {nobody.reads[0].address}: no value was read" in established


def test_a_correspondence_shows_each_side_and_what_it_holds(tmp_path, capsys):
    records = chain(tmp_path, 1)
    put(tmp_path, "other", total=7)
    sides = Claim(
        id="sides",
        text="The total in a1 is the total in other.",
        evidence=(
            CorrespondenceEvidence(
                name="totals",
                sides=(
                    CorrespondenceSide(
                        name="computed", artifact="a1", locator=TreeLocator(pointer="/total")
                    ),
                    CorrespondenceSide(
                        name="written", artifact="other", locator=TreeLocator(pointer="/total")
                    ),
                ),
            ),
        ),
    )
    project = manifest(tmp_path, records, [sides])
    account = why(project, "sides")
    (assertion,) = account.assertions
    assert assertion.outcome is Outcome.MISMATCH and assertion.printed is None
    assert [(r.side, r.artifact, r.address, r.stored) for r in assertion.reads] == [
        ("computed", "a1", "/total", "6"),
        ("written", "other", "/total", "7"),
    ]
    assert account.states == {Freshness.PARTLY_OUTSIDE: 1}
    assert [(n.artifact, n.steps) for n in account.chain] == [("a1", 0), ("other", 0), ("a0", 1)]

    established, _, summary = printed(project, "sides", capsys)
    assert "computed: a1 at /total: holds 6" in established
    assert "written: other at /total: holds 7" in established
    assert "the two sides compared: mismatch" in established
    assert summary.startswith("1 assertion: 1 mismatch; ")


def test_records_on_a_cycle_are_undetermined_and_not_called_never_rerun(tmp_path, capsys):
    for name in ("x", "y"):
        put(tmp_path, name, step=name)
    records = [record(tmp_path, "rx", ("y",), "x"), record(tmp_path, "ry", ("x",), "y")]
    project = manifest(tmp_path, records, [claim("y")])
    account = why(project, "on-y")
    assert {n.artifact: n.state for n in account.chain} == {
        "x": Freshness.UNDETERMINED,
        "y": Freshness.UNDETERMINED,
    }
    assert account.assertions[0].state is Freshness.UNDETERMINED
    assert account.assertions[0].outcome is Outcome.VERIFIED
    on_a_cycle = "on a cycle of commands, so it is compared with no re-run"
    assert said(account) == [
        (NotEstablishedKind.CYCLE, "ry", on_a_cycle),
        (NotEstablishedKind.CYCLE, "rx", on_a_cycle),
        *ALWAYS,
    ]

    established, _, summary = printed(project, "on-y", capsys)
    assert "): undetermined\n      written by ry: make ry\n" in established
    assert "ry is on a cycle of commands, so it is compared with no re-run" in established

    # With a re-run of each in the record, nothing says that none is recorded.
    append(
        ReproductionReport(
            started_at=THEN, regenerations=tuple(rerun(tmp_path, made) for made in records)
        ),
        tmp_path,
    )
    assert said(why(project, "on-y"))[0][0] is NotEstablishedKind.CYCLE
    established, _, _ = printed(project, "on-y", capsys)
    assert "no re-run of" not in established and "reproduced" not in established
    assert summary == (
        "1 assertion: 1 verified; 1 of 1 reads a file with a recorded producer, 1 undetermined"
    )


def test_a_missing_input_leaves_the_claim_undetermined_and_is_not_taken_as_given(tmp_path, capsys):
    project = manifest(tmp_path, chain(tmp_path, 1), [claim("a1")])
    file(tmp_path, "a0").unlink()
    account = why(project, "on-a1")
    produced, gone = account.chain
    assert produced.state is Freshness.UNDETERMINED
    assert produced.regeneration.causes == (StaleCause.INPUT_MISSING,)
    assert (gone.artifact, gone.validity) == ("a0", Validity.ARTIFACT_ABSENT)
    a0 = file(tmp_path, "a0").as_posix()
    assert said(account) == [
        (NotEstablishedKind.ABSENT, a0, "nothing at the declared path"),
        *ALWAYS,
    ]

    established, _, summary = printed(project, "on-a1", capsys)
    assert "no command recorded\n      nothing at the declared path" in established
    assert "): undetermined\n      written by ra1: make ra1\n" in established
    assert summary.endswith("1 of 1 reads a file with a recorded producer, 1 undetermined")


def test_an_assertion_reading_a_produced_and_an_unproduced_file_counts_as_reading_a_produced_one(
    tmp_path, capsys
):
    records = chain(tmp_path, 1)
    put(tmp_path, "other")
    both = Claim(
        id="both",
        text="The total in a1 is the total in other.",
        evidence=(
            CorrespondenceEvidence(
                name="totals",
                sides=(
                    CorrespondenceSide(
                        name="computed", artifact="a1", locator=TreeLocator(pointer="/total")
                    ),
                    CorrespondenceSide(
                        name="written", artifact="other", locator=TreeLocator(pointer="/total")
                    ),
                ),
            ),
        ),
    )
    project = manifest(tmp_path, records, [both])
    assert why(project, "both").assertions[0].state is Freshness.PARTLY_OUTSIDE
    _, _, summary = printed(project, "both", capsys)
    assert summary == (
        "1 assertion: 1 verified; 1 of 1 reads a file with a recorded producer, "
        "1 partly outside the record"
    )


def test_a_rerun_that_did_not_reproduce_is_not_called_no_rerun_at_all(tmp_path, capsys):
    records = chain(tmp_path, 1, rerun_them=False)
    project = manifest(tmp_path, records, [claim("a1")])
    failed = rerun(tmp_path, records[0]).model_copy(
        update={
            "state": Regeneration.FAILED,
            "reason": RegenerationReason.COMMAND_FAILED,
            "actual": None,
            "bytes_identical": False,
        }
    )
    append(ReproductionReport(started_at=THEN, regenerations=(failed,)), tmp_path)

    account = why(project, "on-a1")
    line = next(s for k, _, s in said(account) if k is NotEstablishedKind.NEVER_RERUN)
    assert line.startswith("no re-run that reproduced is recorded; ")
    established, not_established, _ = printed(project, "on-a1", capsys)
    assert "no re-run of ra1 that reproduced is recorded" in established
    assert not [text for text in not_established if "never rerun;" in text]


def test_volatile_fields_are_named_where_the_output_is_compared_without_them(tmp_path, capsys):
    for name in ("a0", "a1"):
        put(tmp_path, name, stamp="first")
    written = canonical_digest(file(tmp_path, "a1"), ("/stamp",))
    made = record(tmp_path, "ra1", ("a0",), "a1").model_copy(
        update={
            "volatile": ("/stamp",),
            "output": RunOutput(artifact="a1", digest=written),
        }
    )
    project = manifest(tmp_path, [made], [claim("a1")])
    ran = rerun(tmp_path, made).model_copy(
        update={"expected": written.value, "actual": written.value}
    )
    append(ReproductionReport(started_at=THEN, regenerations=(ran,)), tmp_path)
    put(tmp_path, "a1", stamp="second")

    account = why(project, "on-a1")
    assert account.chain[0].volatile == ("/stamp",)
    assert account.chain[0].validity is Validity.BROKEN_PIN
    a1 = file(tmp_path, "a1").as_posix()
    assert (NotEstablishedKind.BROKEN_PIN, a1, "its bytes are not the pinned ones") in said(account)

    established, _, _ = printed(project, "on-a1", capsys)
    assert "does not match its pinned digest" in established
    assert "its output is the bytes now on disk" not in established
    assert "its output is what is now on disk outside the fields /stamp" in established


def test_a_manifest_named_where_the_claim_goes_lists_its_claims(tmp_path, capsys, monkeypatch):
    project = manifest(tmp_path, chain(tmp_path, 1), [claim("a1"), claim("a0")])
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    assert main(["why", str(project.path)]) == 0
    assert capsys.readouterr().out == "on-a1\non-a0\n"


def test_a_file_read_at_two_addresses_is_pinned_once_and_text_keeps_its_lines(tmp_path, capsys):
    put(tmp_path, "a0", other=6)
    twice = Claim(
        id="twice",
        text="The total in a0 is 6.\nSo is the other figure.",
        evidence=(
            CorrespondenceEvidence(
                name="same",
                sides=(
                    CorrespondenceSide(
                        name="total", artifact="a0", locator=TreeLocator(pointer="/total")
                    ),
                    CorrespondenceSide(
                        name="other", artifact="a0", locator=TreeLocator(pointer="/other")
                    ),
                ),
            ),
        ),
    )
    project = manifest(tmp_path, [], [twice])
    assert main(["why", "twice", str(project.path)]) == 0
    out = capsys.readouterr().out
    assert "twice\n  The total in a0 is 6.\n  So is the other figure.\n" in out
    assert out.count("matches its pinned digest") == 1
    assert "total: a0 at /total: holds 6" in out and "other: a0 at /other: holds 6" in out


def test_a_later_rerun_that_did_not_reproduce_is_shown_beside_the_one_that_did(tmp_path, capsys):
    records = chain(tmp_path, 1)
    project = manifest(tmp_path, records, [claim("a1")])
    later = "2026-02-01T00:00:00+00:00"
    changed = rerun(tmp_path, records[0]).model_copy(
        update={"state": Regeneration.CHANGED, "actual": "0" * 64, "bytes_identical": False}
    )
    append(ReproductionReport(started_at=later, regenerations=(changed,)), tmp_path)

    account = why(project, "on-a1")
    assert account.assertions[0].state is Freshness.UNDETERMINED
    assert account.chain[0].regeneration.rerun_at == THEN
    established, _, summary = printed(project, "on-a1", capsys)
    assert f"re-run of {THEN} reproduced, and its output is the bytes now on disk" in established
    assert (
        f"later rerun did not reproduce: the re-run of {later} read the same inputs" in established
    )
    assert summary.endswith("1 of 1 reads a file with a recorded producer, 1 undetermined")


def test_the_warnings_on_an_assertion_are_listed_under_it_and_carried_in_the_json(tmp_path, capsys):
    put(tmp_path, "a0")
    (tmp_path / "notes.txt").write_text("The model reached an accuracy of 0.95 on the split.\n")
    quoted = Claim(
        id="quoted",
        text="The total in notes is 0.9.",
        evidence=(
            QuoteEvidence(artifact="notes", text="The model reached an accuracy of 0.9"),
            QuoteEvidence(
                artifact="notes", text="The model reached an accuracy of 0.95 on the split", page=3
            ),
            QuoteEvidence(
                artifact="notes", text="The model reached an accuracy of 0.95 on the split"
            ),
        ),
    )
    project = manifest(tmp_path, [], [quoted])
    cut, paged, clean = why(project, "quoted").assertions
    assert cut.outcome is paged.outcome is Outcome.VERIFIED
    assert cut.warnings == (Warning_.SHORT, Warning_.TRUNCATED)
    assert paged.warnings == (Warning_.PAGE_UNCHECKED,)
    assert clean.warnings == ()

    established, _, summary = printed(project, "quoted", capsys)
    lines = [line.strip() for line in established.splitlines()]
    assert lines.count("warning: short") == 1
    assert lines.count("warning: truncated") == 1
    assert (
        "warning: page_unchecked: page 3 was not checked: the artifact is not read page by page"
    ) in lines
    assert sum(line.startswith("warning:") for line in lines) == 3
    assert summary == ("3 assertions: 3 verified; 0 of 3 read a file with a recorded producer")

    assert main(["why", "quoted", str(project.path), "--format", "json"]) == 0
    document = json.loads(capsys.readouterr().out)
    assert [a["warnings"] for a in document["assertions"]] == [
        ["short", "truncated"],
        ["page_unchecked"],
        [],
    ]


def test_a_row_addressed_by_position_carries_its_warning_into_the_account(tmp_path, capsys):
    (tmp_path / "t.csv").write_text("model,accuracy\nlasso,0.648\n")
    cell = Claim(
        id="cell",
        text="The total in t is 0.648.",
        evidence=(
            TableCellEvidence(artifact="t", name="acc", reported="0.648", column="accuracy", row=0),
        ),
    )
    project = manifest(tmp_path, [], [cell])
    (assertion,) = why(project, "cell").assertions
    assert assertion.warnings == (Warning_.POSITIONAL_ADDRESS,)
    established, _, _ = printed(project, "cell", capsys)
    assert "warning: positional_address" in established
