"""The commands that check what a manifest declares, and how each prints what it found.

    repro manifest init   write a starter repro.yaml for an existing project
    repro verify          check every evidence assertion in repro.yaml
    repro stale           say which claims read a file changed since its recorded re-run
    repro why             say what the record establishes for one claim, and what it does not
    repro numbers         count every number the manuscript prints, and which a claim binds
    repro export          write the check records in another format

Each is a renderer over the library, as `repro.cli` says of the whole command. They are apart
from the rest because nothing here runs a declared command, writes the record of re-runs or
drives another tool: this module imports the claims side and none of the wrapper side, and an
import-linter contract holds it to that. `repro.cli` builds the parser, and has every name
defined here under the name it had there.
"""

from __future__ import annotations

import argparse
import collections
import enum
import json
import os
import shlex
from pathlib import Path

from provenance_core import atomic_write
from provenance_core.chain import ChainError

from repro import __version__
from repro.checks import record as record_checks
from repro.checks import set_aside as set_aside_checks
from repro.exceptions import ReproError
from repro.export import EXPORTS
from repro.export.rocrate import METADATA_FILE
from repro.manifest import DEFAULT_NAME, find, load
from repro.models import (
    AssertionAccount,
    Availability,
    ChainNode,
    CheckedAssertion,
    ClaimAccount,
    Freshness,
    NumberForm,
    NumbersReport,
    Ordering,
    Outcome,
    Reason,
    StaleCause,
    StaleFinding,
    StalenessReport,
    Standing,
    Validity,
    VerificationReport,
    Warning_,
)
from repro.numbers import numbers as run_numbers
from repro.policy import PROFILES, Assessment, Policy
from repro.record import check_records
from repro.renderers import to_sarif
from repro.reruns import RECORD
from repro.stale import stale as run_stale
from repro.starter import CONVENTIONAL, MAX_DISCOVERED, project_root
from repro.starter import write as write_starter
from repro.verify import verify as run_verify
from repro.why import why as run_why

SYMBOL = {
    Outcome.VERIFIED: "ok  ",
    Outcome.MISMATCH: "MISS",
    Outcome.NOT_FOUND: "GONE",
    Outcome.UNCHECKED: "--  ",
    Outcome.ERROR: "ERR ",
    Outcome.NOT_OFFERED: "none",
}


def cmd_manifest_init(args: argparse.Namespace) -> int:
    starter = write_starter(project_root(Path.cwd()), args.files, Path.cwd())
    print(f"wrote {starter.path}")

    count = f"{len(starter.artifacts)} artifact{'' if len(starter.artifacts) == 1 else 's'}"
    if starter.discovered:
        places = ", ".join(f"{name}/" for name in CONVENTIONAL)
        print(f"  pinned {count}, found by looking under {places} and for one manuscript")
    else:
        print(f"  pinned {count}, as named")
    width = max((len(artifact.id) for artifact in starter.artifacts), default=0)
    for artifact in starter.artifacts:
        print(f"    {artifact.id:<{width}}  {artifact.path.as_posix()}")
    if starter.capped:
        print(
            f"  more than {MAX_DISCOVERED} files were found; the first {MAX_DISCOVERED} are pinned"
        )
    for note in starter.notes:
        print(f"  passed over: {note}")
    if starter.discovered and starter.artifacts:
        # Discovery reads names and suffixes, and knows nothing of what the manuscript reports.
        print("  That list is a guess. Remove an entry under `artifacts`, or add one with its")
        print(f"  `shasum -a 256`; or delete {DEFAULT_NAME} and name the files:")
        print("      repro manifest init <file> ...")
    elif starter.discovered:
        print(f"  Nothing was found there. Delete {DEFAULT_NAME} and name the files to pin:")
        print("      repro manifest init <file> ...")

    if starter.written:
        print(f"  example claims, to edit: {', '.join(starter.written)}")
    if starter.commented:
        print(f"  example claims left as comments: {', '.join(starter.commented)}")
    if not starter.written:
        print("  No claim is declared, and `repro verify` fails a manifest that checks nothing")
        print("  (`report.empty`). Declare one claim and it will report on it and on the pins.")
    print("\nnext: repro verify")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    path = Path(args.manifest) if args.manifest else find()
    if path is None:
        print(f"no {DEFAULT_NAME} here or above.\n")
        print("write one that pins this project's result files, with example claims to edit:\n")
        print("    repro manifest init")
        return 2

    manifest = load(path)
    report = run_verify(manifest)
    policy = PROFILES[args.policy]
    assessment = policy.assess(report)
    # The record sits beside the check and never decides it: where it cannot be written, one
    # line on standard error says so and why, and the report and the exit code are the
    # verification's. Standard error, so `--format json` still prints one document. Outside a
    # git repository there is no local record and nothing is said.
    if args.set_aside_record:
        try:
            moved = set_aside_checks(manifest, local=args.local_record, tracked=args.record)
        except (ReproError, ChainError) as e:
            os.write(2, f"record not set aside: {e}\n".encode())
        except OSError as e:
            os.write(2, f"record not set aside: {e.filename}: {e.strerror}\n".encode())
        else:
            for note in moved:
                os.write(
                    2,
                    f"record set aside: the {note.kind} record is kept as {note.kept_as}, and "
                    "a new one starts by saying so\n".encode(),
                )
    try:
        record_checks(manifest, report, local=args.local_record, tracked=args.record)
    except (ReproError, ChainError) as e:
        os.write(2, f"record not written: {e}\n".encode())
    except OSError as e:
        os.write(2, f"record not written: {e.filename}: {e.strerror}\n".encode())

    if args.format == "sarif":
        print(json.dumps(to_sarif(report, assessment, version=__version__), indent=2))
        return 0 if assessment.passed else 1
    if args.format == "json":
        print(
            json.dumps(
                {
                    "report": report.model_dump(mode="json"),
                    "assessment": assessment.model_dump(mode="json"),
                },
                indent=2,
            )
        )
        return 0 if assessment.passed else 1

    _verify_text(path, report, policy, assessment)
    return 0 if assessment.passed else 1


def _verify_text(
    path: Path, report: VerificationReport, policy: Policy, assessment: Assessment
) -> None:
    print(f"{path}\n")
    for artifact in report.artifacts:
        if artifact.validity is Validity.BROKEN_PIN:
            print(
                f"  BROKEN PIN  {artifact.artifact_id}: pinned "
                f"{(artifact.expected or '')[:12]}, found {(artifact.actual or '')[:12]}"
            )
        elif artifact.validity is Validity.ARTIFACT_ABSENT:
            print(f"  ABSENT      {artifact.artifact_id}: nothing at the declared path")
        elif artifact.validity is Validity.UNPINNED_ARTIFACT:
            print(f"  unpinned    {artifact.artifact_id}")
    if any(a.validity is not Validity.AUTHORITATIVE for a in report.artifacts):
        print()

    for claim in report.claims:
        if claim.availability is Availability.NOT_OFFERED:
            print(
                f"  {SYMBOL[Outcome.NOT_OFFERED]}  {claim.claim_id:<12} "
                f"{'-':<8} no evidence offered"
            )
            continue
        if claim.ordering is Ordering.VIOLATED:
            print(f"  ORDER       {claim.claim_id:<12} {claim.ordering_detail[:52]}")
        elif claim.ordering is Ordering.UNCHECKED:
            print(
                f"  order?      {claim.claim_id:<12} "
                f"{claim.ordering_reason.value}: {claim.ordering_detail[:38]}"
            )
        for d in claim.decisions:
            mark = "" if d.is_authoritative else f"  <{d.validity.value}>"
            note = f"  [{','.join(w.value for w in d.warnings)}]" if d.warnings else ""
            # Said outside the detail, which is cut short and would lose it.
            tie = f"  [exact tie: {d.tie.lower} or {d.tie.upper}]" if d.tie else ""
            print(
                f"  {SYMBOL[d.outcome]}  {d.claim_id:<12} {d.kind:<8} "
                f"{d.detail[:52]}{tie}{note}{mark}"
            )

    counts = report.counts
    print(f"\n  {', '.join(f'{v} {k}' for k, v in sorted(counts.items()))}")
    print(
        f"  policy {policy.name}: {'passed' if assessment.passed else 'FAILED'}"
        f"  ({len(assessment.errors)} errors, {len(assessment.warnings)} warnings)"
    )
    for v in assessment.errors[:10]:
        print(f"    error   {v.rule:<26} {v.subject}: {v.detail[:44]}")


def _said(state: enum.StrEnum) -> str:
    return state.value.replace("_", " ")


def _named(artifact_id: str, paths: dict[str, str]) -> str:
    path = paths.get(artifact_id, "")
    return f"{artifact_id} ({path})" if path and path != artifact_id else artifact_id


def _finding_said(found: StaleFinding, paths: dict[str, str]) -> str:
    """One difference from a recorded re-run, as a clause."""

    def digests(verb: str) -> str:
        return (
            f"the re-run of {found.rerun_at} {verb} {(found.observed or 'nothing')[:12]}, "
            f"on disk {(found.on_disk or 'nothing')[:12]}"
        )

    cause = _said(found.cause)
    # Appended, and only where the re-run's entry says where it ran.
    where = f"; that re-run was {found.witness.said}" if found.witness else ""
    if found.cause is StaleCause.INPUT_CHANGED:
        return f"{cause}: {_named(found.artifact, paths)}: {digests('read')}{where}"
    if found.cause is StaleCause.OUTPUT_CHANGED:
        return f"{cause}: {_named(found.artifact, paths)}: {digests('wrote')}{where}"
    if found.cause is StaleCause.COMMAND_CHANGED:
        return f"{cause} since the re-run of {found.rerun_at}{where}"
    if found.cause is StaleCause.CYCLE:
        return f"{cause}: {found.regeneration} is upstream of itself"
    if found.cause is StaleCause.LATER_RERUN_DID_NOT_REPRODUCE:
        wrote = f"wrote {found.observed[:12]}" if found.observed else "wrote no output"
        return (
            f"{cause}: the re-run of {found.rerun_at} read the same inputs and {wrote}, "
            f"on disk {(found.on_disk or 'nothing')[:12]}{where}"
        )
    return f"{cause}: {_named(found.artifact, paths)}"


def _stale_lines(report: StalenessReport) -> list[str]:
    """One line per difference from a recorded re-run, then one per record that takes its state
    from upstream, then the claims that read them."""
    paths = {artifact.id: artifact.path for artifact in report.artifacts}
    outputs = {node.id: node.artifact for node in report.regenerations}

    lines = []
    for found in report.findings:
        said = _finding_said(found, paths)
        label = (
            "UNDETERMINED"
            if found.cause
            in (
                StaleCause.INPUT_MISSING,
                StaleCause.OUTPUT_MISSING,
                StaleCause.CYCLE,
                StaleCause.LATER_RERUN_DID_NOT_REPRODUCE,
            )
            else "STALE"
        )
        lines.append(f"  {label:<13} {outputs[found.regeneration]}: {said}")
    for node in report.regenerations:
        label = _said(node.state).upper()
        if node.upstream:
            steps = f"{node.distance} step{'' if node.distance == 1 else 's'} up"
            lines.append(
                f"  {label:<13} {node.artifact}: upstream {_said(node.state)}: "
                f"{node.upstream}, {steps}"
            )
        elif node.state is Freshness.NEVER_RERUN:
            lines.append(
                f"  {label:<13} {node.artifact}: no re-run of {node.id} that reproduced is recorded"
            )
    for note in report.record_disagrees_with_pin:
        lines.append(
            f"  {'note':<13} {note.regeneration}: record disagrees with pin: "
            f"{_named(note.artifact, paths)}: the record names {note.recorded[:12]}, "
            f"the manifest pins {note.pinned[:12]}"
        )
    if lines:
        lines.append("")

    states = {artifact.id: artifact.state for artifact in report.artifacts}
    reported = (Freshness.STALE, Freshness.NEVER_RERUN, Freshness.UNDETERMINED)
    width = max((len(claim.id) for claim in report.claims), default=0)
    claimed = [
        f"  {_said(claim.state):<13} {claim.id:<{width}}  reads "
        + ", ".join(
            dict.fromkeys(
                name
                for assertion in claim.assertions
                for name in assertion.artifacts
                if states.get(name) is claim.state
            )
        )
        for claim in report.claims
        if claim.state in reported
    ]
    return [*lines, *claimed, *([""] if claimed else [])]


def _stale_summary(report: StalenessReport) -> list[str]:
    """The three counts, each with what it is a count of. A line saying nothing is stale is
    never printed without how many assertions could have been."""
    assertions = [assertion for claim in report.claims for assertion in claim.assertions]
    outside = (Freshness.NO_PRODUCER, Freshness.PARTLY_OUTSIDE)
    covered = collections.Counter(a.state for a in assertions if a.state not in outside)
    produced = {node.artifact for node in report.regenerations}
    uncovered = [a for a in assertions if a.state in outside]
    files = {name for a in uncovered for name in a.artifacts if name not in produced}
    claims = collections.Counter(claim.state for claim in report.claims)
    return [
        f"  {covered[Freshness.STALE]} stale, {covered[Freshness.NEVER_RERUN]} never rerun, "
        f"{covered[Freshness.UNDETERMINED]} undetermined, {covered[Freshness.CURRENT]} current "
        f"of {sum(covered.values())} assertions that read a file with a recorded producer",
        f"  {len(uncovered)} assertions read {len(files)} files no command is recorded for: "
        "nothing upstream to compare",
        f"  {len(report.claims)} claims: {claims[Freshness.STALE]} stale, "
        f"{claims[Freshness.NEVER_RERUN]} never rerun, {claims[Freshness.CURRENT]} current, "
        f"{claims[Freshness.PARTLY_OUTSIDE]} partly outside the record, "
        f"{claims[Freshness.NO_PRODUCER]} outside the record, "
        f"{claims[Freshness.UNDETERMINED]} undetermined",
    ]


def cmd_stale(args: argparse.Namespace) -> int:
    path = Path(args.manifest) if args.manifest else find()
    if path is None:
        print(f"no {DEFAULT_NAME} here or above.\n")
        print("write one that pins this project's result files, with example claims to edit:\n")
        print("    repro manifest init")
        return 2
    manifest = load(path)
    if not manifest.regenerations:
        print(f"{path}\n")
        print("  no command is declared, so no file has a recorded producer to compare it with.")
        print("  A record under `regenerations` names a command, the files it reads and the")
        print("  file it writes.")
        return 2

    report = run_stale(manifest)
    policy = PROFILES[args.policy]
    assessment = policy.assess_staleness(report)

    if args.format == "json":
        print(
            json.dumps(
                {
                    "staleness": report.model_dump(mode="json"),
                    "assessment": assessment.model_dump(mode="json"),
                },
                indent=2,
            )
        )
        return 0 if assessment.passed else 1

    _stale_text(path, report, policy, assessment)
    return 0 if assessment.passed else 1


def _stale_text(
    path: Path, report: StalenessReport, policy: Policy, assessment: Assessment
) -> None:
    print(f"{path}\n")
    if not report.reruns:
        print(f"  {RECORD.as_posix()} holds no re-run; `repro reproduce` records one.\n")
    print("\n".join([*_stale_lines(report), *_stale_summary(report)]))
    print(
        f"  policy {policy.name}: {'passed' if assessment.passed else 'FAILED'}"
        f"  ({len(assessment.errors)} errors, {len(assessment.warnings)} warnings)"
    )


def _steps(count: int | None) -> str:
    return f"{count} step{'' if count == 1 else 's'} up"


def _assertion_lines(assertion: AssertionAccount, paths: dict[str, str]) -> list[str]:
    """The pin of each file the assertion reads, the value at each address, and the outcome."""
    lines = []
    # A file read at two addresses is pinned once.
    for file in {file.artifact: file for file in assertion.reads}.values():
        name = _named(file.artifact, paths)
        if file.validity is None:
            lines.append(f"{name}: the manifest declares no such artifact")
        elif file.validity is Validity.ARTIFACT_ABSENT:
            lines.append(f"{name}: nothing at the declared path")
        elif file.validity is Validity.UNPINNED_ARTIFACT:
            lines.append(f"{name}: no digest is pinned, on disk {(file.on_disk or '')[:12]}")
        elif file.validity is Validity.BROKEN_PIN:
            lines.append(
                f"{name}: does not match its pinned digest: pinned "
                f"{(file.pinned or '')[:12]}, on disk {(file.on_disk or '')[:12]}"
            )
        else:
            lines.append(f"{name}: matches its pinned digest {(file.pinned or '')[:12]}")
    for file in assertion.reads:
        if file.address:
            side = f"{file.side}: " if file.side else ""
            held = f"holds {file.stored}" if file.stored is not None else "no value was read"
            if file.conversion is not None and file.converted is not None:
                held += f", {file.converted} {file.conversion.said}"
            lines.append(f"{side}{file.artifact} at {file.address}: {held}")
    if assertion.statistic is not None and assertion.computed is not None:
        lines.append(
            f"the {assertion.statistic.value} of the {len(assertion.reads)} values: "
            f"{assertion.computed}"
        )
    if assertion.tie is not None:
        lines.append(
            f"an exact tie between {assertion.tie.lower} and {assertion.tie.upper}: "
            "rounding half up prints one and half to even may print the other"
        )
    outcome = _said(assertion.outcome)
    if (
        assertion.outcome not in (Outcome.VERIFIED, Outcome.MISMATCH)
        or assertion.reason is Reason.PLACES_MISMATCH
    ):
        outcome += f" ({_said(assertion.reason)})"
    if assertion.kind == "quote":
        passage = assertion.printed or ""
        shown = passage if len(passage) <= 60 else f"{passage[:60]}..."
        within = assertion.reads[0].artifact if assertion.reads else "the artifact"
        lines.append(f'the passage "{shown}" in {within}: {outcome}')
    elif assertion.printed is not None:
        declared = (
            ""
            if assertion.places is None
            else f", declared to {assertion.places} "
            f"decimal place{'' if assertion.places == 1 else 's'}"
        )
        lines.append(f"the manuscript prints {assertion.printed}{declared}: {outcome}")
    else:
        lines.append(f"the two sides compared: {outcome}")
    # One line a warning, named as `repro verify` names it in brackets. An unchecked page says
    # why, since that is in the detail and the detail of a verified assertion is not printed.
    for warning in assertion.warnings:
        why_not = assertion.detail if warning is Warning_.PAGE_UNCHECKED else ""
        lines.append(f"warning: {warning.value}" + (f": {why_not}" if why_not else ""))
    return [*lines, *_history_lines(assertion)]


def _checked_said(state: CheckedAssertion, before: CheckedAssertion | None) -> str:
    """What one check found an assertion declaring, the bytes it read and the outcome, and
    what differs from the check before it."""
    if state.kind == "quote":
        passage = state.printed or ""
        said = f'the passage "{passage if len(passage) <= 60 else f"{passage[:60]}..."}"'
    elif state.printed is not None:
        said = f"reported {state.printed}" + (f" at {state.address}" if state.address else "")
    else:
        said = state.address
    files = ", ".join(
        f"{name} {digest[:12] if digest else 'absent'}" for name, digest in state.digests.items()
    )
    line = f"{said}, {files}: {_said(state.outcome)}"
    if before is None:
        return line
    changed = [
        label
        for label, then, now in (
            ("claim text", before.claim_digest, state.claim_digest),
            ("passage" if state.kind == "quote" else "reported", before.printed, state.printed),
            ("address", before.address, state.address),
            ("conversion", before.conversion, state.conversion),
            ("file", before.digests, state.digests),
        )
        if then != now
    ]
    return (
        f"{line} (after {_said(before.outcome)}: "
        f"{', '.join(changed) or 'nothing declared'} changed)"
    )


def _history_lines(assertion: AssertionAccount) -> list[str]:
    """The record of checks for one assertion, where it holds more than how the assertion
    stands now: each earlier state as `checked`, and the state now as `since` the check that
    first found it, or as `now` where no recorded check has."""
    states = assertion.history
    renamed = [
        f"a claim named {last.claim_id} was last checked {last.checked_at} at this address: "
        f"{_said(last.outcome)}, and is no longer declared"
        for last in assertion.formerly
    ]
    if len(states) < 2 and assertion.now is None and all(s.verifiable for s in states):
        return renamed
    current = len(states) - 1 if assertion.now is None else len(states)
    lines = [
        f"{'since' if index == current else 'checked'} {state.checked_at}: "
        f"{_checked_said(state, states[index - 1] if index else None)}"
        + ("" if state.verifiable else " [unverifiable]")
        for index, state in enumerate(states)
    ]
    if assertion.now is not None:
        lines.append(
            f"now: {_checked_said(assertion.now, states[-1])}; no check of this is recorded"
        )
    return [*lines, *renamed]


def _record_lines(account: ClaimAccount) -> list[str]:
    """What is to be said of the records of checks themselves: that none is kept here, or
    that one does not verify or the two disagree. Nothing where both are as they should be."""
    lines = []
    if account.no_local_record:
        lines.append(f"no local record is kept here: {account.no_local_record}")
    for note in account.set_aside:
        vouched = f"its last entry that verified hashes to {note.head[:12]}"
        lines.append(
            f"a {note.kind} record of {note.entries} entr{'y' if note.entries == 1 else 'ies'} "
            f"was set aside on {note.at} as {note.kept_as}: reported {note.status}"
            + (f" ({'; '.join(note.problems)})" if note.problems else "")
            + f"; {vouched if note.head.strip('0') else 'none of its entries verified'}"
        )
    for record in account.records:
        said = []
        if record.unverifiable_from is not None or record.status in ("truncated", "corrupt"):
            said.append(f"{record.status.replace('_', ' ')}: {'; '.join(record.problems)}")
        if record.unverifiable_from is not None:
            said.append(f"unverifiable from entry {record.unverifiable_from}")
        if record.diverges_at is not None:
            said.append(f"diverges from the local record at entry {record.diverges_at}")
        if said:
            count = f"{record.entries} entr{'y' if record.entries == 1 else 'ies'}"
            lines.append(f"{record.kind} {record.path}: {count}, {'; '.join(said)}")
    return lines


def _chain_lines(node: ChainNode, account: ClaimAccount, paths: dict[str, str]) -> list[str]:
    """One file the claim rests on: what writes it, the re-run it was compared with, and each
    difference from that re-run."""
    record = node.regeneration
    if record is None:
        if node.validity is Validity.ARTIFACT_ABSENT:
            return ["no command recorded", "nothing at the declared path"]
        return ["no command recorded"]
    lines = [f"written by {record.id}: {shlex.join(node.command)}"]
    reads = [
        _named(edge.target, paths)
        for edge in account.edges
        if edge.kind == "consumes" and edge.source == record.id
    ]
    if reads:
        lines.append(f"which reads {', '.join(reads)}")
    if StaleCause.CYCLE in record.causes:
        lines.append(f"{record.id} is on a cycle of commands, so it is compared with no re-run")
    elif record.rerun_at is None:
        lines.append(f"no re-run of {record.id} that reproduced is recorded")
    else:
        wrote = next(
            edge
            for edge in account.edges
            if edge.kind == "produced_by" and edge.target == record.id
        )
        lines.append(
            f"re-run of {record.rerun_at} reproduced"
            + (f" {record.witness.said}" if record.witness else "")
            + (
                ""
                if wrote.observed != wrote.on_disk
                else ", and its output is what is now on disk outside the fields "
                f"{', '.join(node.volatile)}"
                if node.volatile
                else ", and its output is the bytes now on disk"
            )
        )
    lines += [
        _finding_said(found, paths) for found in account.findings if found.regeneration == record.id
    ]
    if record.upstream:
        lines.append(
            f"upstream {_said(record.state)}: {record.upstream}, {_steps(record.distance)}"
        )
    return lines


def _why_lines(account: ClaimAccount) -> list[str]:
    """The claim, what was computed from the record just now, what the record does not cover,
    and the counts."""
    paths = {node.artifact: node.path for node in account.chain}
    lines = [account.claim_id, *(f"  {line}" for line in account.text.splitlines())]
    if account.where:
        lines.append(f"  {account.where}")

    lines += ["", "established"]
    total = len(account.assertions)
    for number, assertion in enumerate(account.assertions, start=1):
        lines.append(f"  assertion {number} of {total}: {assertion.kind} {assertion.name}".rstrip())
        lines += [f"    {line}" for line in _assertion_lines(assertion, paths)]
    if account.chain:
        lines.append("  chain")
    for node in account.chain:
        where = f", {_steps(node.steps)}" if node.steps else ""
        lines.append(f"    {_named(node.artifact, paths)}: {_said(node.state)}{where}")
        lines += [f"      {line}" for line in _chain_lines(node, account, paths)]

    if recorded := _record_lines(account):
        lines.append("  record of checks")
        lines += [f"    {line}" for line in recorded]

    lines += ["", "not established"]
    lines += [
        f"  {line.subject}: {line.said}" if line.subject else f"  {line.said}"
        for line in account.not_established
    ]

    outcomes = account.outcomes
    covered = {
        state: n for state, n in account.states.items() if state is not Freshness.NO_PRODUCER
    }
    count = sum(covered.values())
    summary = (
        f"  {total} assertion{'' if total == 1 else 's'}: "
        + (", ".join(f"{n} {_said(outcome)}" for outcome, n in outcomes.items()) or "none")
        + f"; {count} of {total} read{'s' if count == 1 else ''} a file with a recorded producer"
        + "".join(f", {n} {_said(state)}" for state, n in covered.items())
    )
    return [*lines, "", summary]


def cmd_why(args: argparse.Namespace) -> int:
    # `repro why repro.yaml` names a manifest, as the first argument of the sibling commands
    # does, and lists its claims.
    if args.manifest is None and args.claim and Path(args.claim).suffix in (".yaml", ".yml"):
        args.manifest, args.claim = args.claim, None
    path = Path(args.manifest) if args.manifest else find()
    if path is None:
        print(f"no {DEFAULT_NAME} here or above.\n")
        print("write one that pins this project's result files, with example claims to edit:\n")
        print("    repro manifest init")
        return 2
    manifest = load(path)
    if args.claim is None:
        ids = [claim.id for claim in manifest.claims]
        print(json.dumps(ids, indent=2) if args.format == "json" else "\n".join(ids))
        return 0

    account = run_why(manifest, args.claim)
    if args.format == "json":
        print(json.dumps(account.model_dump(mode="json"), indent=2))
        return 0
    print(f"{path}\n")
    print("\n".join(_why_lines(account)))
    return 0


def _count_said(counts: collections.Counter[Standing]) -> str:
    """The four counts, which add up to the number before them."""
    return (
        f"{counts[Standing.BOUND]} bound, {counts[Standing.SET_ASIDE_BY_RULE]} set aside by "
        f"rule, {counts[Standing.SET_ASIDE_WITH_A_REASON]} set aside with a reason, "
        f"{counts[Standing.UNBOUND]} unbound"
    )


def _numbers_lines(report: NumbersReport) -> list[str]:
    """Per text the numbers nothing accounts for, then what was set aside and the counts."""
    lines = []
    for text in report.texts:
        lines.append(f"  {_named(text.artifact, {text.artifact: text.path})}")
        unbound = [number for number in text.numbers if number.standing is Standing.UNBOUND]
        width = max((len(number.text) for number in unbound), default=0)
        for number in unbound:
            where = f"line {number.line}" if number.line else f"offset {number.offset}"
            note = "  (reported elsewhere)" if number.reported_elsewhere else ""
            lines.append(f"    {where:<10} {number.text:<{width}}  {number.context}{note}")
        counts = collections.Counter(number.standing for number in text.numbers)
        lines += [f"    {len(text.numbers)} numbers: {_count_said(counts)}", ""]

    if report.rules:
        rules = ", ".join(f"{n} {_said(rule)}" for rule, n in report.rules.items())
        lines.append(f"  set aside by rule: {rules}")
    for entry in report.set_aside:
        passage = entry.text if len(entry.text) <= 60 else f"{entry.text[:60]}..."
        lines.append(
            f'  set aside with a reason: {entry.numbers} in {entry.artifact} "{passage}": '
            f"{entry.reason}"
        )
    counts = report.counts
    total, texts = len(report.numbers), len(report.texts)
    lines.append(
        f"  {total} numbers in {texts} text{'' if texts == 1 else 's'}: {_count_said(counts)}"
    )
    unbound = [number for number in report.numbers if number.standing is Standing.UNBOUND]
    words = sum(number.form is NumberForm.CARDINAL_WORD for number in unbound)
    lines.append(f"  {len(unbound)} unbound: {len(unbound) - words} numerals, {words} number words")
    lines.append(
        f"  {sum(number.reported_elsewhere for number in unbound)} of the {len(unbound)} "
        "unbound print a value an assertion reports, outside the passage it reports it for; "
        f"{sum(number.reported_elsewhere_one_digit for number in unbound)} more match on one "
        "digit and are not marked"
    )
    return lines


def cmd_numbers(args: argparse.Namespace) -> int:
    path = Path(args.manifest) if args.manifest else find()
    if path is None:
        print(f"no {DEFAULT_NAME} here or above.\n")
        print("write one that pins this project's result files, with example claims to edit:\n")
        print("    repro manifest init")
        return 2
    report = run_numbers(load(path), only=tuple(args.text or ()))
    if args.format == "json":
        print(json.dumps(report.model_dump(mode="json"), indent=2))
        return 0
    print(f"{path}\n")
    print("\n".join(_numbers_lines(report)))
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    path = Path(args.manifest) if args.manifest else find()
    if path is None:
        print(f"no {DEFAULT_NAME} here or above.\n")
        print("write one that pins this project's result files, with example claims to edit:\n")
        print("    repro manifest init")
        return 2
    if args.include_matches and args.target != "sarif":
        print("--include-matches is an option of `repro export sarif`.")
        return 2
    options = {"include_matches": True} if args.include_matches else {}
    written = EXPORTS[args.target](check_records(load(path)), **options)
    if args.output:
        target = Path(args.output)
        if args.target == "ro-crate" and (target.is_dir() or target.suffix != ".json"):
            # A crate is a directory holding a file of one fixed name.
            target.mkdir(parents=True, exist_ok=True)
            target = target / METADATA_FILE
        atomic_write(target, written)
    else:
        print(written, end="")
    return 0
