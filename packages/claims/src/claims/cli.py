"""The commands that check what a manifest declares, and how each prints what it found.

    claims manifest init   write a starter repro.yaml for an existing project
    claims verify          check every evidence assertion in repro.yaml
    claims stale           say which claims read a file changed since its recorded re-run
    claims why             say what the record establishes for one claim, and what it does not
    claims numbers         count every number the manuscript prints, and which a claim binds
    claims origins         compare each artifact copied from another repository with its origin
    claims export          write the check records in another format

Each is also the `repro` command of the same name: `repro.cli` adds these functions to its
parser with `add_manifest` through `add_origins`, and `main` here adds them to the parser of
`claims`. Each handler reads the name the user typed off the parsed arguments, so a message that
says what to run next names a command that user has. Nothing here runs a declared command,
writes the record of re-runs or drives another tool, and an import-linter contract holds this
package to importing nothing of `repro`.
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

from claims import __version__
from claims.checks import LOCAL as LOCAL_CHECKS
from claims.checks import RECORD as CHECKS
from claims.checks import SET_ASIDE
from claims.checks import record as record_checks
from claims.checks import set_aside as set_aside_checks
from claims.exceptions import ReproError
from claims.export import EXPORTS
from claims.export.rocrate import METADATA_FILE
from claims.manifest import DEFAULT_NAME, find, load
from claims.models import (
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
from claims.numbers import numbers as run_numbers
from claims.origins import OriginCheck, OriginsReport, OriginState, fetch_url
from claims.origins import origins as run_origins
from claims.policy import PROFILES, Assessment, Policy
from claims.record import check_records
from claims.renderers import survey_to_sarif, to_sarif
from claims.reruns import RECORD
from claims.stale import stale as run_stale
from claims.starter import (
    CONVENTIONAL,
    FORMAT_NAMES,
    MAX_DISCOVERED,
    SURVEY_SCHEMA,
    Survey,
    address_said,
    project_root,
    survey,
)
from claims.starter import write as write_starter
from claims.verify import verify as run_verify
from claims.why import why as run_why

#: The two commands these functions answer to. `repro` is the one they were written for, and
#: every message is as it was under it. Under `claims` a message names `claims` for a command
#: this module holds, and says who provides the one it does not.
REPRO = "repro"
CLAIMS = "claims"


def _program(args: argparse.Namespace) -> str:
    """The command the user typed, which the parser recorded. `repro` where none did."""
    return getattr(args, "program", REPRO)


def _reproduce(program: str) -> str:
    """The command that runs the declared commands again, as a reader of `program` needs it
    named: it is not one of `claims`'s, so there it comes with the distribution that has it."""
    if program == REPRO:
        return "`repro reproduce`"
    return "`repro reproduce` (from the `reproducible-science` distribution)"


SYMBOL = {
    Outcome.VERIFIED: "ok  ",
    Outcome.MISMATCH: "MISS",
    Outcome.NOT_FOUND: "GONE",
    Outcome.UNCHECKED: "--  ",
    Outcome.ERROR: "ERR ",
    Outcome.NOT_OFFERED: "none",
}


def cmd_manifest_init(args: argparse.Namespace) -> int:
    starter = write_starter(project_root(Path.cwd()), args.files, Path.cwd(), _program(args))
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
        print(f"      {_program(args)} manifest init <file> ...")
    elif starter.discovered:
        print(f"  Nothing was found there. Delete {DEFAULT_NAME} and name the files to pin:")
        print(f"      {_program(args)} manifest init <file> ...")

    if starter.written:
        print(f"  example claims, to edit: {', '.join(starter.written)}")
    if starter.commented:
        print(f"  example claims left as comments: {', '.join(starter.commented)}")
    if not starter.written:
        print(
            f"  No claim is declared, and `{_program(args)} verify` fails a manifest that "
            "checks nothing"
        )
        print("  (`report.empty`). Declare one claim and it will report on it and on the pins.")
    print(f"\nnext: {_program(args)} verify")
    return 0


#: How many candidate bindings `verify` prints with no manifest. The survey holds every one.
SHOWN_CANDIDATES = 20


def _survey_lines(found: Survey) -> list[str]:
    """What a project with no manifest holds that a manifest could pin, and the numbers its
    manuscript prints that agree with a stored value, each said to be a guess."""
    places = ", ".join(f"{name}/" for name in CONVENTIONAL)
    lines = [f"found by looking under {places} and for one manuscript:", ""]

    count = sum(len(paths) for paths in found.results.values())
    lines.append(f"  result files: {count}")
    names = {FORMAT_NAMES[key]: paths for key, paths in found.results.items()}
    width = max((len(name) for name in names), default=0)
    for name, paths in names.items():
        lines += [f"    {name if i == 0 else '':<{width}}  {p}" for i, p in enumerate(paths)]
    if found.capped:
        lines.append(
            f"    more than {MAX_DISCOVERED} were found; these are the first {MAX_DISCOVERED}"
        )
    lines.append(f"  manuscript: {found.manuscript or 'none found'}")
    lines += [f"  note: {note}" for note in found.notes]

    lines.append("")
    if found.manuscript is None or not found.values:
        missing = "no manuscript" if found.manuscript is None else "no number in a result file"
        lines.append(f"  candidate bindings: none, because there is {missing} to compare")
    else:
        agreeing = len({c.offset for c in found.candidates})
        files = f"{len(found.read_from)} result file{'' if len(found.read_from) == 1 else 's'}"
        lines.append(
            f"  candidate bindings, guessed: {agreeing} of the {found.compared} numbers "
            "compared agree with one of"
        )
        lines.append(f"  the {found.values} values read from {files}, at the precision printed.")
        if found.not_compared:
            printed = found.compared + found.not_compared
            lines.append(
                f"  {found.not_compared} of the {printed} numbers {found.manuscript} prints were "
                "not compared: the cap on comparisons was reached."
            )
        lines.append("  A guess says the digits agree, never that the sentence reports that value.")
        shown = found.candidates[:SHOWN_CANDIDATES]
        width = max((len(c.printed) for c in shown), default=0)
        for c in shown:
            where = f"line {c.line}" if c.line else "line ?"
            held = f"{c.path} {address_said(c.locator)} holds {c.stored}"
            if c.conversion is not None:
                held += f", {c.conversion.said}"
            if c.more_rows:
                held += f", and {c.more_rows} more row{'' if c.more_rows == 1 else 's'}"
            lines.append(f"    guess  {where:<8}  {c.printed:<{width}}  {held}")
            lines.append(f"           {'':<8}  {'':<{width}}  ...{c.context}...")
        if len(found.candidates) > SHOWN_CANDIDATES:
            lines.append(f"    and {len(found.candidates) - SHOWN_CANDIDATES} more guesses")

    lines += [
        "",
        "  verified: 0. With no manifest no claim is declared, so nothing was checked, and",
        "  nothing was written.",
        "",
    ]
    return lines


def cmd_verify(args: argparse.Namespace) -> int:
    path = Path(args.manifest) if args.manifest else find()
    if path is None:
        # Exits 2 as every command does with nothing to read: a project with no manifest has
        # checked nothing, which is neither a pass (0) nor a finding against it (1).
        found = survey(project_root(Path.cwd()))
        if args.format == "json":
            print(
                json.dumps(
                    {
                        "schema_version": SURVEY_SCHEMA,
                        "manifest": None,
                        "verified": 0,
                        "survey": found.model_dump(mode="json"),
                    },
                    indent=2,
                )
            )
            return 2
        if args.format == "sarif":
            print(json.dumps(survey_to_sarif(found, version=__version__), indent=2))
            return 2
        print(f"no {DEFAULT_NAME} here or above.\n")
        print("\n".join(_survey_lines(found)))
        print("write one that pins this project's result files, with example claims to edit:\n")
        print(f"    {_program(args)} manifest init")
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
        record_checks(
            manifest,
            report,
            local=args.local_record,
            tracked=args.record,
            program=_program(args),
        )
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
        print(f"    {_program(args)} manifest init")
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

    _stale_text(path, report, policy, assessment, program=_program(args))
    return 0 if assessment.passed else 1


def _stale_text(
    path: Path,
    report: StalenessReport,
    policy: Policy,
    assessment: Assessment,
    program: str = REPRO,
) -> None:
    print(f"{path}\n")
    if not report.reruns:
        print(f"  {RECORD.as_posix()} holds no re-run; {_reproduce(program)} records one.\n")
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
        print(f"    {_program(args)} manifest init")
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
        print(f"    {_program(args)} manifest init")
        return 2
    report = run_numbers(load(path), only=tuple(args.text or ()))
    if args.format == "json":
        print(json.dumps(report.model_dump(mode="json"), indent=2))
        return 0
    print(f"{path}\n")
    print("\n".join(_numbers_lines(report)))
    return 0


def _origin_lines(check: OriginCheck) -> list[str]:
    """One artifact's origin: the state and why, both digests where they differ, and the file
    on disk where it is not the pinned bytes."""
    origin = check.origin
    lines = [
        f"  {_said(check.state).upper() if check.state is not OriginState.SAME else 'same':<14} "
        f"{check.artifact_id}: {origin.repository} {origin.commit[:12]}:{origin.path}",
        f"  {'':<14} {check.reason}"
        + (f" (read from {check.read_from})" if check.read_from else ""),
    ]
    if check.state is OriginState.DIFFERS:
        lines.append(f"  {'':<14} pinned    {check.pinned}")
        lines.append(f"  {'':<14} at origin {check.at_origin}")
    if check.disk_disagrees:
        found = f"on disk {check.on_disk}" if check.on_disk else "nothing is at the declared path"
        lines.append(
            f"  {'':<14} note: {check.path} is not the pinned bytes ({found}); "
            "`verify` reports that, and this compares the pin with the origin"
        )
    return lines


def _origins_exit(report: OriginsReport) -> int:
    """0 where every declared origin holds the pinned bytes, 1 where one does not or lacks
    the path, 2 where something could not be checked and nothing failed."""
    states = {check.state for check in report.origins}
    if states & {OriginState.DIFFERS, OriginState.ABSENT}:
        return 1
    if not states or states != {OriginState.SAME}:
        return 2
    return 0


def cmd_origins(args: argparse.Namespace) -> int:
    path = Path(args.manifest) if args.manifest else find()
    if path is None:
        print(f"no {DEFAULT_NAME} here or above.\n")
        print("write one that pins this project's result files, with example claims to edit:\n")
        print(f"    {_program(args)} manifest init")
        return 2
    clones: dict[str, Path] = {}
    for given in args.repo or ():
        repository, sep, clone = given.partition("=")
        if not sep or not repository or not clone:
            print(f"--repo {given}: expected REPOSITORY=PATH, a repository as an origin names it")
            return 2
        clones[repository] = Path(clone).expanduser().resolve()

    report = run_origins(load(path), clones, fetch_url if args.fetch else None)
    code = _origins_exit(report)
    if args.format == "json":
        print(json.dumps({"origins": report.model_dump(mode="json")}, indent=2))
        return code

    print(f"{path}\n")
    if not report.origins:
        print("  no artifact declares an origin, so nothing was compared.")
        print("  `origin: {repository, commit, path}` on an artifact names the file it was")
        print("  copied from.")
        return code
    for check in report.origins:
        print("\n".join(_origin_lines(check)))
    counts = report.counts
    print(
        f"\n  {len(report.origins)} origins: "
        + ", ".join(f"{counts.get(state.value, 0)} {_said(state)}" for state in OriginState)
    )
    if report.without_origin:
        print(f"  {len(report.without_origin)} artifacts declare no origin")
    return code


def cmd_export(args: argparse.Namespace) -> int:
    path = Path(args.manifest) if args.manifest else find()
    if path is None:
        print(f"no {DEFAULT_NAME} here or above.\n")
        print("write one that pins this project's result files, with example claims to edit:\n")
        print(f"    {_program(args)} manifest init")
        return 2
    if args.include_matches and args.target != "sarif":
        print(f"--include-matches is an option of `{_program(args)} export sarif`.")
        return 2
    options: dict[str, bool | str] = {"include_matches": True} if args.include_matches else {}
    if args.target == "sarif":
        # The log's help text names the command to run next, as the user's command names it.
        options["program"] = _program(args)
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


def add_manifest(sub, program: str = REPRO) -> None:
    """`manifest init`: write a starter manifest. Added to `repro`'s parser and to `claims`'s, each under its own name."""
    p_manifest = sub.add_parser("manifest", help=f"write a starter {DEFAULT_NAME}")
    p_manifest.set_defaults(func=lambda args: p_manifest.print_help() or 1)
    p_manifest_init = p_manifest.add_subparsers(dest="action").add_parser(
        "init",
        help=f"write a starter {DEFAULT_NAME} for an existing project",
        description=(
            f"Write {DEFAULT_NAME} at the top of the project this is run in: its git root, or "
            "the working directory outside a repository. Each file is pinned by sha256, and "
            "example claims are written for a number and a quotation found in the pinned files, "
            "so the manifest verifies as written. An example with nothing to point at is "
            "written as a comment. An existing manifest is never overwritten."
        ),
    )
    p_manifest_init.add_argument(
        "files",
        nargs="*",
        help=(
            "files to pin, inside the project (default: data files the adapters read under "
            f"{', '.join(f'{name}/' for name in CONVENTIONAL)}, at most {MAX_DISCOVERED}, and "
            "a manuscript when exactly one of paper, manuscript or main .tex/.md/.txt exists)"
        ),
    )
    p_manifest_init.set_defaults(func=cmd_manifest_init, program=program)


def add_verify(sub, program: str = REPRO) -> None:
    """`verify`: check every assertion. Added to `repro`'s parser and to `claims`'s, each under its own name."""
    p_verify = sub.add_parser("verify", help="check every evidence assertion in repro.yaml")
    p_verify.add_argument("manifest", nargs="?", help=f"path to {DEFAULT_NAME}")
    p_verify.add_argument("--policy", choices=sorted(PROFILES), default="publication")
    p_verify.add_argument("--format", choices=("text", "json", "sarif"), default="text")
    p_verify.add_argument(
        "--record",
        action="store_true",
        help=(
            f"also bring the tracked record {CHECKS.as_posix()} up to the local one, which "
            f"every check appends to at {LOCAL_CHECKS.as_posix()} in the git directory"
        ),
    )
    p_verify.add_argument(
        SET_ASIDE,
        action="store_true",
        help=(
            "where the record of checks does not verify, keep it under a name that says when "
            "it was set aside and start a new one whose first entry says so; with --record, "
            "the tracked record as well. Refused where every record verifies"
        ),
    )
    p_verify.set_defaults(func=cmd_verify, program=program)


def add_stale(sub, program: str = REPRO) -> None:
    """`stale`: compare the files with the record of re-runs. Added to `repro`'s parser and to `claims`'s, each under its own name."""
    p_stale = sub.add_parser(
        "stale",
        help="say which claims read a file changed since its recorded re-run",
        description=(
            f"Compare each command declared under `regenerations` in {DEFAULT_NAME} with the "
            f"re-runs {_reproduce(program)} recorded in {RECORD.as_posix()}, and say for "
            "every claim "
            "whether the files it reads are still the ones a re-run that reproduced was made "
            "over. Executes nothing and writes nothing. `current` means consistent with a "
            "recorded re-run, and a file the manifest does not declare as an input is not "
            "compared."
        ),
    )
    p_stale.add_argument("manifest", nargs="?", help=f"path to {DEFAULT_NAME}")
    p_stale.add_argument("--policy", choices=sorted(PROFILES), default="publication")
    p_stale.add_argument("--format", choices=("text", "json"), default="text")
    p_stale.set_defaults(func=cmd_stale, program=program)


def add_why(sub, program: str = REPRO) -> None:
    """`why`: one claim's account. Added to `repro`'s parser and to `claims`'s, each under its own name."""
    p_why = sub.add_parser(
        "why",
        help="say what the record establishes for one claim, and what it does not",
        description=(
            f"For one claim in {DEFAULT_NAME}: each assertion as `{program} verify` evaluates it now, "
            f"each file the claim reads and each file upstream of one as `{program} stale` finds it, "
            "and then what the record does not cover. Executes nothing and writes nothing. Exits "
            f"0 whatever it finds; `{program} verify` and `{program} stale` are the checks that fail. With "
            "no claim, lists the claim ids."
        ),
    )
    p_why.add_argument("claim", nargs="?", help="a claim id (default: list the ids)")
    p_why.add_argument("manifest", nargs="?", help=f"path to {DEFAULT_NAME}")
    p_why.add_argument("--format", choices=("text", "json"), default="text")
    p_why.set_defaults(func=cmd_why, program=program)


def add_numbers(sub, program: str = REPRO) -> None:
    """`numbers`: count the numbers a text prints. Added to `repro`'s parser and to `claims`'s, each under its own name."""
    p_numbers = sub.add_parser(
        "numbers",
        help="count every number the manuscript prints, bound to a claim or not",
        description=(
            f"Read the text the claims in {DEFAULT_NAME} read their sentences from and count "
            "every number in it: bound where an assertion accounts for that occurrence, set "
            "aside by a named rule (a year, a table's number), set aside with a reason where "
            "the manifest lists its passage under `set_aside`, and otherwise unbound. Executes "
            "nothing and writes nothing. Exits 0 whatever it counts."
        ),
    )
    p_numbers.add_argument("manifest", nargs="?", help=f"path to {DEFAULT_NAME}")
    p_numbers.add_argument(
        "--text",
        action="append",
        metavar="ID",
        help=(
            "read this text artifact; repeatable (default: each artifact a `quote` beside "
            "another assertion, or a prose address, reads)"
        ),
    )
    p_numbers.add_argument("--format", choices=("text", "json"), default="text")
    p_numbers.set_defaults(func=cmd_numbers, program=program)


def add_export(sub, program: str = REPRO) -> None:
    """`export`: write the check records in another format. Added to `repro`'s parser and to `claims`'s, each under its own name."""
    p_export = sub.add_parser(
        "export",
        help="write one record per checked assertion, for another program to read",
        description=(
            f"Check every assertion in {DEFAULT_NAME} as `{program} verify` does and write what was "
            "found in another format. `record` is JSON Lines, one object per assertion: the "
            "file read and its digests, the address, the value stored there, the value the "
            "manuscript reports, the comparison and the outcome. Experimental: each record "
            "names its version. Executes nothing, writes only what it is asked for, and exits "
            f"0 whatever the outcomes; `{program} verify` is the check that fails. `sarif` is a "
            "SARIF 2.1.0 log for GitHub code scanning, built from the records: a result for "
            "each mismatch, not-found and error, and a notification for each assertion that "
            "was not checked. `ro-crate` is the same records as an RO-Crate 1.3 "
            f"{METADATA_FILE}, and `-o DIR` writes it into DIR."
        ),
    )
    p_export.add_argument(
        "--include-matches",
        action="store_true",
        help=(
            "sarif only: also write a `pass` result for each assertion that matched. Not for "
            "an upload to GitHub, which shows each as a warning alert"
        ),
    )
    p_export.add_argument("target", choices=sorted(EXPORTS))
    p_export.add_argument("manifest", nargs="?", help=f"path to {DEFAULT_NAME}")
    p_export.add_argument("--output", "-o", help="write to this file (default: standard output)")
    p_export.set_defaults(func=cmd_export, program=program)


def add_origins(sub, program: str = REPRO) -> None:
    """`origins`: compare copied artifacts with their origins. Added to `repro`'s parser and to `claims`'s, each under its own name."""
    p_origins = sub.add_parser(
        "origins",
        help="compare each artifact copied from another repository with its origin",
        description=(
            f"For each artifact in {DEFAULT_NAME} that declares `origin: {{repository, commit, "
            "path}`, read the bytes of that path at that commit and compare their sha256 with "
            "the artifact's pinned digest. A clone is read with `git cat-file`, so committed "
            "bytes are compared and never a working tree. Without a clone, a public GitHub "
            "repository is fetched only with --fetch; otherwise nothing touches the network "
            "and the origin is `not checked`. States: same, differs, absent (the commit has no "
            "such path), unknown commit (the clone has no such commit), not checked. Exits 0 "
            "where every origin is the same, 1 where one differs or is absent, 2 where one "
            f"could not be checked and none failed. `{program} verify` never reads an origin."
        ),
    )
    p_origins.add_argument("manifest", nargs="?", help=f"path to {DEFAULT_NAME}")
    p_origins.add_argument(
        "--repo",
        action="append",
        metavar="REPOSITORY=PATH",
        help=(
            "read this repository, as an origin names it, from the clone at PATH; repeatable. "
            "An origin whose repository is a local path is read from there"
        ),
    )
    p_origins.add_argument(
        "--fetch",
        action="store_true",
        help=(
            "for a GitHub repository no clone is given for, fetch the file from "
            "raw.githubusercontent.com at the commit (default: no network)"
        ),
    )
    p_origins.add_argument("--format", choices=("text", "json"), default="text")
    p_origins.set_defaults(func=cmd_origins, program=program)


def main(argv: list[str] | None = None, local_record: bool = True) -> int:
    """The `claims` command: the commands above, and nothing that runs one of yours."""
    parser = argparse.ArgumentParser(
        prog=CLAIMS,
        description=(
            "Check what a manuscript states against the files it names: numbers, table cells "
            "and quotations declared in a manifest, each against a pinned file."
        ),
        epilog=(
            "`claims verify` and `repro verify` are the same command, and so is each of the "
            "others here. `repro`, from the `reproducible-science` distribution, adds the "
            "commands that run things: `repro reproduce`, `repro check`, `repro audit` and "
            "`repro ci`."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command")
    add_manifest(sub, CLAIMS)
    add_verify(sub, CLAIMS)
    add_stale(sub, CLAIMS)
    add_why(sub, CLAIMS)
    add_numbers(sub, CLAIMS)
    add_export(sub, CLAIMS)
    add_origins(sub, CLAIMS)

    args = parser.parse_args(argv)
    args.local_record = local_record
    if not hasattr(args, "func") or args.func is None:
        parser.print_help()
        return 1
    try:
        return args.func(args)
    except ReproError as e:
        print(str(e))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
