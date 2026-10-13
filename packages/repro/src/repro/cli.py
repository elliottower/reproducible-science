"""The `repro` command.

    repro init [name]     scaffold an experiment directory, or set up the project here
    repro demo            write a worked example and run the workflow over it
    repro manifest init   write a starter repro.yaml for an existing project
    repro verify          check every evidence assertion in repro.yaml
    repro reproduce       run the declared commands again and check the numbers still hold
    repro stale           say which claims read a file changed since its recorded re-run
    repro why             say what the record establishes for one claim, and what it does not
    repro numbers         count every number the manuscript prints, bound to a claim or not
    repro export          write one record per checked assertion, for another program to read
    repro check           run every tool this project uses, in one pass
    repro audit           clone a repository at a pinned commit and run every tool over it
    repro prereg          run `prereg`: freeze a plan, and record what deviated from it
    repro citations       run `citations`: does every quotation resolve in its source?
    repro results         run `results`: seal a run, record it, verify the chain

A renderer over the library and nothing more. `verify` calls `repro.verify()` and
`Policy.assess()`, both of which return values, so anything this prints can also be obtained
by importing the package. `main` returns an exit code; the process boundary is the only place
that exits.
"""

from __future__ import annotations

import argparse
import collections
import enum
import functools
import importlib
import json
import os
import pathlib
import shlex
import subprocess
from pathlib import Path

from provenance_core import atomic_write
from provenance_core.gitref import try_run
from results.ledger import ChainError

from repro import __version__, audit, crosscheck
from repro.checks import LOCAL as LOCAL_CHECKS
from repro.checks import RECORD as CHECKS
from repro.checks import SET_ASIDE
from repro.checks import record as record_checks
from repro.checks import set_aside as set_aside_checks
from repro.delegate import BY_NAME, TOOLS
from repro.delegate import check as delegate_check
from repro.delegate import run as delegate_run
from repro.demo import demo
from repro.exceptions import ReproError
from repro.export import EXPORTS
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
    Reading,
    Reason,
    Regeneration,
    StaleCause,
    StaleFinding,
    StalenessReport,
    Standing,
    Validity,
    Warning_,
)
from repro.numbers import numbers as run_numbers
from repro.policy import PROFILES
from repro.record import check_records
from repro.renderers import to_sarif
from repro.reproduce import RECORD
from repro.reproduce import append as append_reproduction
from repro.reproduce import reproduce as run_reproduce
from repro.stale import stale as run_stale
from repro.starter import CONVENTIONAL, MAX_DISCOVERED, project_root
from repro.starter import write as write_starter
from repro.verify import verify as run_verify
from repro.why import why as run_why

CLAUDE_MD = """\
# {name}

## Reproducible science tools

- `prereg` — freeze a plan before running, record amendments and deviations
- `citations` — verify quotations resolve in pinned source artifacts
- `results` — seal inputs, record outputs, bind claims to runs, verify the chain
- `repro verify` — check every evidence assertion declared in repro.yaml

## Workflow

```bash
prereg freeze                         # lock the plan
results seal PREREG.md analysis.py    # hash inputs
results run output.json --run-id exp_001
repro verify                          # check the declared evidence
```
"""

#: What a project's own `.gitignore` should hold, as a comment and the rules under it. `prereg
#: new`, `results init` and `citations init` each write the sidecar rules into the directory they
#: make; `init` puts them at the top, where a locked write beside `repro.yaml` or a claims file
#: leaves its sidecar, and adds the folder that holds other people's files.
SOURCES_DIR = "sources"
IGNORE_RULES = (
    (
        "# Sidecars a locked or interrupted write leaves beside a file. They hold nothing.",
        ("*.provenance-lock", "*.provenance-tmp"),
    ),
    (
        "# Third-party sources: papers, full texts, datasets. Pinned by sha256, never committed.",
        (f"{SOURCES_DIR}/",),
    ),
)

SYMBOL = {
    Outcome.VERIFIED: "ok  ",
    Outcome.MISMATCH: "MISS",
    Outcome.NOT_FOUND: "GONE",
    Outcome.UNCHECKED: "--  ",
    Outcome.ERROR: "ERR ",
    Outcome.NOT_OFFERED: "none",
}


def _run(cmd: list[str], cwd: Path) -> bool:
    try:
        subprocess.run(cmd, cwd=cwd, check=True, capture_output=True)
        return True
    except FileNotFoundError:
        print(f"  skipped: {cmd[0]} not installed")
        return False
    except subprocess.CalledProcessError:
        print(f"  warning: {' '.join(cmd)} failed")
        return False


def _ignore(root: Path) -> tuple[str | None, str | None]:
    """Add the rules of `IGNORE_RULES` that `root/.gitignore` lacks: what was written, and
    what was left out.

    An existing file keeps every byte it has and gains the missing rules at its end, each under
    its comment. The first value is None where nothing was written, so a second run changes
    nothing. A rule counts as present however it is anchored: `/sources/` and `sources` both
    cover the folder.

    The folder rule is not added where git tracks a file under `sources/`: the project keeps
    its own files there, and the rule would hide each new one from `git status`. The second
    value says so. Outside a repository, and where git is absent, nothing is tracked.
    """
    path = root / ".gitignore"
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    held = {line.strip().strip("/") for line in existing.splitlines()}
    folder = f"{SOURCES_DIR}/"
    tracked = (try_run("ls-files", "--", SOURCES_DIR, cwd=root) or "").splitlines()
    note = None
    blocks, added = [], []
    for comment, rules in IGNORE_RULES:
        missing = [rule for rule in rules if rule.strip("/") not in held]
        if folder in missing and tracked:
            missing.remove(folder)
            note = (
                f"left {folder} out of .gitignore: git tracks {len(tracked)} file(s) there. "
                "Keep other people's files in a folder git ignores."
            )
        if missing:
            blocks.append("\n".join([comment, *missing]))
            added += missing
    if not added:
        return None, note
    head = existing + ("" if existing.endswith("\n") or not existing else "\n")
    atomic_write(path, head + ("\n" if head else "") + "\n\n".join(blocks) + "\n")
    verb = "added to" if existing else "wrote"
    return f"{verb} .gitignore: {', '.join(added)}", note


def _plan(root: Path) -> str | None:
    """The plan this project already has, as shown to the user.

    `PREREG.md` is what `prereg check` reads. A plan written by hand under another name is
    left alone too: scaffolding an empty template beside a registration would put two plans in
    one project and say nothing about which governs.
    """
    named = sorted(p.name for p in root.glob("*.md") if p.name.lower().startswith("prereg"))
    if "PREREG.md" in named:
        return "PREREG.md"
    if named:
        return f"{named[0]} (not named PREREG.md, so `prereg check` does not read it)"
    return "PREREG.md, below the top" if BY_NAME["prereg"].used_by(root) else None


def _shown(path: Path, root: Path) -> str:
    return f"{path.relative_to(root).as_posix()}/" if path.is_relative_to(root) else str(path)


def _init_here() -> int:
    """Set up whichever of the four records this project lacks, and touch none it has."""
    root = project_root(Path.cwd())
    print(f"{root}\n")

    # `citations` is asked which library governs this project, because one made here would
    # shadow a shared library the project already reads. Imported by name for the reason
    # `delegate` does it: the tools are reached lazily everywhere in this package.
    library = importlib.import_module("citations.paths").find(root)
    claims = root / "claims" if (root / "claims").is_dir() else BY_NAME["citations"].data_dir(root)
    present = {
        "plan": _plan(root),
        "ledger": ".results/" if (root / ".results").is_dir() else None,
        "citations": f"{_shown(library, root)}, {_shown(claims, root)}"
        if library and claims
        else None,
        "manifest": DEFAULT_NAME if (root / DEFAULT_NAME).exists() else None,
    }

    def plan() -> str | None:
        made = _run(["prereg", "new", ".", "--title", root.name], cwd=root)
        return "PREREG.md" if made else None

    def ledger() -> str | None:
        return ".results/" if _run(["results", "init"], cwd=root) else None

    def citations() -> str | None:
        made = []
        if library is None and _run(["citations", "init"], cwd=root):
            made.append(".citations/")
        if claims is None:
            (root / "claims").mkdir()
            made.append("claims/")
        return ", ".join(made) if library or ".citations/" in made else None

    def manifest() -> str | None:
        starter = write_starter(root, [], root)
        return (
            f"{DEFAULT_NAME} (artifacts pinned: {len(starter.artifacts)}, "
            f"example claims: {len(starter.written)})"
        )

    created = {}
    for label, create in (
        ("plan", plan),
        ("ledger", ledger),
        ("citations", citations),
        ("manifest", manifest),
    ):
        if present[label]:
            print(f"  {label:<12} already present  {present[label]}")
        elif made := create():
            created[label] = made
            print(f"  {label:<12} created          {made}")
        else:
            print(f"  {label:<12} NOT CREATED")

    # After the records: `prereg new .` writes a `.gitignore` holding the sidecar rules where
    # the project has none, and this adds to that file only what it lacks.
    ignored, left_out = _ignore(root)
    if ignored or left_out:
        print("\n" + "\n".join(f"  {line}" for line in (ignored, left_out) if line))
    if not created and all(present.values()):
        if ignored:
            print("\nthe four records are already set up; only .gitignore changed.")
        else:
            print("\neverything is already set up; nothing was created.")
        return 0
    if created:
        print("\nnext:")
    for label, step in (
        ("plan", "fill in PREREG.md, then `prereg freeze`"),
        ("ledger", "`results seal <inputs>` before a run, `results run <outputs>` after it"),
        ("citations", "`citations pin` writes a quotation into claims/ once it resolves"),
        ("manifest", f"edit the claims in {DEFAULT_NAME}, then `repro verify`"),
    ):
        if label in created:
            print(f"  {label:<12} {step}")
    return 0 if all(present[label] or label in created for label in present) else 1


def cmd_init(args: argparse.Namespace) -> int:
    if args.name is None:
        if args.directory:
            print("--directory names where a new project goes, so it needs a name:\n")
            print(f"    repro init <name> --directory {args.directory}\n")
            print("to set up an existing project, run `repro init` inside it.")
            return 2
        return _init_here()
    name = args.name
    # `repro init .` means this directory. Read as a name it scaffolded a new project on top of
    # the one already here: a `CLAUDE.md` headed `# .` and four folders nobody asked for.
    if not args.directory and (Path.cwd() / name).resolve() == Path.cwd().resolve():
        return _init_here()
    target = Path(args.directory) if args.directory else Path.cwd() / name
    target.mkdir(parents=True, exist_ok=True)
    print(f"initializing {target}")

    for cmd in (["prereg", "new", name], ["results", "init"], ["citations", "init"]):
        _run(cmd, cwd=target)
    for d in ("claims", "data", "scripts", "figures"):
        (target / d).mkdir(exist_ok=True)

    claude_md = target / "CLAUDE.md"
    if not claude_md.exists():
        claude_md.write_text(CLAUDE_MD.format(name=name))
        print(f"  wrote {claude_md}")
    if not (target / DEFAULT_NAME).exists():
        print(f"  wrote {write_starter(target, [], target).path}")
    for line in _ignore(target):
        if line:
            print(f"  {line}")
    print("done.")
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    return demo(args.directory, force=args.force)


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
    return 0 if assessment.passed else 1


#: How each outcome is shown. `not_rerun` is the value a record carries; a reader sees the words.
SHOWN = {
    Regeneration.REPRODUCED: "reproduced",
    Regeneration.CHANGED: "changed",
    Regeneration.UNCHECKED: "unchecked",
    Regeneration.FAILED: "failed",
    Regeneration.NOT_RERUN: "not re-run",
}


def cmd_reproduce(args: argparse.Namespace) -> int:
    path = Path(args.manifest) if args.manifest else find()
    if path is None:
        print(f"no {DEFAULT_NAME} here or above.\n")
        print("write one that pins this project's result files, with example claims to edit:\n")
        print("    repro manifest init")
        return 2
    manifest = load(path)
    if not manifest.regenerations:
        print(f"{path}\n")
        print("  no command is declared, so there is nothing to run again. A record under")
        print("  `regenerations` names a command, the files it reads and the file it writes.")
        return 2

    report = run_reproduce(manifest, only=tuple(args.only or ()), skip=tuple(args.skip or ()))
    policy = PROFILES[args.policy]
    assessment = policy.assess_reproduction(report)
    recorded = append_reproduction(report, path.resolve().parent)

    if args.format == "json":
        print(
            json.dumps(
                {
                    "reproduction": report.model_dump(mode="json"),
                    "assessment": assessment.model_dump(mode="json"),
                },
                indent=2,
            )
        )
        return 0 if assessment.passed else 1

    states = report.regenerations
    print(f"{path}\n")
    print(f"  re-ran {sum(1 for s in states if s.executed)} of {len(states)}\n")
    width = max(len(s.regeneration_id) for s in states)
    for state in states:
        detail = "bytes identical" if state.bytes_identical else state.detail
        print(f"  {SHOWN[state.state]:<11} {state.regeneration_id:<{width}}  {detail[:60]}")
        if state.rests_on:
            print(
                f"  {'':<11} {'':<{width}}  on the recorded output of {', '.join(state.rests_on)}"
            )
        for claim in state.claims:
            if claim.reading is Reading.HOLDS:
                continue
            then, now = claim.pinned, claim.fresh
            if claim.conversion is not None:
                unit = claim.conversion.said
                then = f"{then} ({claim.pinned_converted} {unit})"
                now = f"{now} ({claim.fresh_converted} {unit})"
            values = (
                f"{then} then, {now} now, paper prints {claim.printed}"
                if claim.pinned is not None and claim.fresh is not None
                else claim.detail[:60]
            )
            note = (
                "  (differed before the re-run)"
                if claim.reading is Reading.ALREADY_MISMATCHED
                else ""
            )
            print(f"  {'':<11}   {claim.name:<{width}}  {values}{note}")

    print(
        f"\n  {', '.join(f'{v} {SHOWN[Regeneration(k)]}' for k, v in sorted(report.counts.items()))}"
    )
    print(
        f"  policy {policy.name}: {'passed' if assessment.passed else 'FAILED'}"
        f"  ({len(assessment.errors)} errors, {len(assessment.warnings)} warnings)"
    )
    print(f"  recorded in {recorded.relative_to(path.resolve().parent).as_posix()}")
    return 0 if assessment.passed else 1


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
    if found.cause is StaleCause.INPUT_CHANGED:
        return f"{cause}: {_named(found.artifact, paths)}: {digests('read')}"
    if found.cause is StaleCause.OUTPUT_CHANGED:
        return f"{cause}: {_named(found.artifact, paths)}: {digests('wrote')}"
    if found.cause is StaleCause.COMMAND_CHANGED:
        return f"{cause} since the re-run of {found.rerun_at}"
    if found.cause is StaleCause.CYCLE:
        return f"{cause}: {found.regeneration} is upstream of itself"
    if found.cause is StaleCause.LATER_RERUN_DID_NOT_REPRODUCE:
        wrote = f"wrote {found.observed[:12]}" if found.observed else "wrote no output"
        return (
            f"{cause}: the re-run of {found.rerun_at} read the same inputs and {wrote}, "
            f"on disk {(found.on_disk or 'nothing')[:12]}"
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

    print(f"{path}\n")
    if not report.reruns:
        print(f"  {RECORD.as_posix()} holds no re-run; `repro reproduce` records one.\n")
    print("\n".join([*_stale_lines(report), *_stale_summary(report)]))
    print(
        f"  policy {policy.name}: {'passed' if assessment.passed else 'FAILED'}"
        f"  ({len(assessment.errors)} errors, {len(assessment.warnings)} warnings)"
    )
    return 0 if assessment.passed else 1


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
    written = EXPORTS[args.target](check_records(load(path)))
    if args.output:
        atomic_write(Path(args.output), written)
    else:
        print(written, end="")
    return 0


def cmd_check(args) -> int:
    """Run every applicable tool and report them together."""
    root = pathlib.Path(args.directory or ".").resolve()
    outcomes = delegate_check(root, args.only or ())
    print(f"{root}\n")
    for o in outcomes:
        print(o.line)
        if o.used and o.code != 0:
            for line in o.output.rstrip().splitlines():
                print(f"      {line}")
    # The cross-tool part, which is the reason `check` exists rather than four commands. Each
    # of these reads two tools' records and reports something neither can see alone.
    crossed = 0
    if stray := crosscheck.unmatched(root):
        crossed += len(stray)
        print("\n  claims naming a freeze that no frozen plan records:")
        for c in stray:
            print(f"      {c.claim[:58]}  cites {c.ref}")
        print("      `results` checks that the reference resolves to a commit, not that a plan")
        print("      was frozen at it, so a citation like this passes every tool on its own.")
    if unplanned := crosscheck.confirmatory_without_a_plan(root):
        print("\n  confirmatory claims, and no frozen plan in this project:")
        for text in unplanned[:10]:
            print(f"      {text[:70]}")
        if len(unplanned) > 10:
            print(f"      ... and {len(unplanned) - 10} more")
        print("      Reported, not failed: a plan frozen elsewhere or registered on OSF is a")
        print(
            "      real arrangement this cannot see. What it can say is nothing here records one."
        )

    ran = [o for o in outcomes if o.used]
    bad = [o for o in ran if o.code != 0]
    if crossed and not bad:
        print(f"\n{crossed} cross-tool problem(s); every tool passed on its own.")
        return 1
    print()
    if not ran:
        print("no tool applies to this project. `repro demo` writes one that does.")
        return 1
    if bad:
        print(f"{len(bad)} of {len(ran)} failed.")
        return 1
    print(f"{len(ran)} of {len(ran)} passed.")
    return 0


def main(argv: list[str] | None = None, local_record: bool = True) -> int:
    parser = argparse.ArgumentParser(
        prog="repro",
        description=(
            "Verify declared evidence assertions against pinned artifacts, and run the other "
            "tools in this workspace over one project."
        ),
        epilog=(
            "`repro citations verify` and `citations verify` are the same command. Each tool "
            "keeps its own, installs on its own, and is not deprecated. What only exists here "
            "is `repro check`, which runs the ones a project uses together. If you use one "
            "tool, use it directly -- for preregistration alone this adds nothing at all."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command")

    p_init = sub.add_parser(
        "init",
        help="scaffold an experiment directory, or set up the project here",
        description=(
            "With a name, scaffold a new experiment directory: a plan, a results ledger, a "
            f"citations library and a starter {DEFAULT_NAME}. With no name, run inside an "
            "existing project, create whichever of those four it lacks at the top of the "
            "project and leave the ones it has untouched."
        ),
    )
    p_init.add_argument("name", nargs="?", help="a new directory (default: set up this project)")
    p_init.add_argument("--directory", "-d", help="target directory (default: ./<name>)")
    p_init.set_defaults(func=cmd_init)

    p_demo = sub.add_parser(
        "demo", help="write a worked example and run the workflow over it, failures included"
    )
    p_demo.add_argument("directory", nargs="?", help="where to write it (default: ./repro-demo)")
    p_demo.add_argument(
        "--force",
        action="store_true",
        help="replace the demo's own files in a directory that already holds them",
    )
    p_demo.set_defaults(func=cmd_demo)

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
    p_manifest_init.set_defaults(func=cmd_manifest_init)

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
    p_verify.set_defaults(func=cmd_verify)

    p_reproduce = sub.add_parser(
        "reproduce",
        help="run the declared commands again and check the numbers still hold",
        description=(
            f"Run each command declared under `regenerations` in {DEFAULT_NAME}, in a directory "
            "holding only its declared inputs, and check every claim that reads its output "
            "against the file it wrote. A record is `reproduced` when every number the "
            "manuscript prints from it still holds, whether or not the bytes match. This "
            "executes what the manifest names: read a manifest before running it. Each "
            f"invocation is appended to {RECORD.as_posix()}."
        ),
    )
    p_reproduce.add_argument("manifest", nargs="?", help=f"path to {DEFAULT_NAME}")
    p_reproduce.add_argument(
        "--only", action="append", metavar="ID", help="run this record; repeatable"
    )
    p_reproduce.add_argument(
        "--skip", action="append", metavar="ID", help="leave this record out; repeatable"
    )
    p_reproduce.add_argument("--policy", choices=sorted(PROFILES), default="publication")
    p_reproduce.add_argument("--format", choices=("text", "json"), default="text")
    p_reproduce.set_defaults(func=cmd_reproduce)

    p_stale = sub.add_parser(
        "stale",
        help="say which claims read a file changed since its recorded re-run",
        description=(
            f"Compare each command declared under `regenerations` in {DEFAULT_NAME} with the "
            f"re-runs `repro reproduce` recorded in {RECORD.as_posix()}, and say for every claim "
            "whether the files it reads are still the ones a re-run that reproduced was made "
            "over. Executes nothing and writes nothing. `current` means consistent with a "
            "recorded re-run, and a file the manifest does not declare as an input is not "
            "compared."
        ),
    )
    p_stale.add_argument("manifest", nargs="?", help=f"path to {DEFAULT_NAME}")
    p_stale.add_argument("--policy", choices=sorted(PROFILES), default="publication")
    p_stale.add_argument("--format", choices=("text", "json"), default="text")
    p_stale.set_defaults(func=cmd_stale)

    p_why = sub.add_parser(
        "why",
        help="say what the record establishes for one claim, and what it does not",
        description=(
            f"For one claim in {DEFAULT_NAME}: each assertion as `repro verify` evaluates it now, "
            "each file the claim reads and each file upstream of one as `repro stale` finds it, "
            "and then what the record does not cover. Executes nothing and writes nothing. Exits "
            "0 whatever it finds; `repro verify` and `repro stale` are the checks that fail. With "
            "no claim, lists the claim ids."
        ),
    )
    p_why.add_argument("claim", nargs="?", help="a claim id (default: list the ids)")
    p_why.add_argument("manifest", nargs="?", help=f"path to {DEFAULT_NAME}")
    p_why.add_argument("--format", choices=("text", "json"), default="text")
    p_why.set_defaults(func=cmd_why)

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
    p_numbers.set_defaults(func=cmd_numbers)

    p_export = sub.add_parser(
        "export",
        help="write one record per checked assertion, for another program to read",
        description=(
            f"Check every assertion in {DEFAULT_NAME} as `repro verify` does and write what was "
            "found in another format. `record` is JSON Lines, one object per assertion: the "
            "file read and its digests, the address, the value stored there, the value the "
            "manuscript reports, the comparison and the outcome. Experimental: each record "
            "names its version. Executes nothing, writes only what it is asked for, and exits "
            "0 whatever the outcomes; `repro verify` is the check that fails."
        ),
    )
    p_export.add_argument("target", choices=sorted(EXPORTS))
    p_export.add_argument("manifest", nargs="?", help=f"path to {DEFAULT_NAME}")
    p_export.add_argument("--output", "-o", help="write to this file (default: standard output)")
    p_export.set_defaults(func=cmd_export)

    p_check = sub.add_parser(
        "check",
        help="run every tool this project uses, in one pass",
        description=(
            "One pass over the project, one report, one exit code. A tool the project does "
            "not use is named as unused and not run: reporting it as passing would be a clean "
            "line standing for a check that never happened. This is the only command that "
            "does not exist in the tools themselves."
        ),
    )
    p_check.add_argument("directory", nargs="?", help="project root (default: .)")
    p_check.add_argument(
        "--only", action="append", choices=sorted(BY_NAME), help="restrict to one tool; repeatable"
    )
    p_check.set_defaults(func=cmd_check)

    # An audit runs these inside a clone of someone else's repository, and keeps no record of
    # its checks in that clone's git directory.
    entries = {t.name: functools.partial(delegate_run, t) for t in TOOLS} | {
        "repro": functools.partial(main, local_record=False)
    }
    audit.add_parser(sub).set_defaults(func=functools.partial(audit.command, entries=entries))

    # One subcommand per tool, each forwarding its arguments untouched. `parse_known_args`
    # below is what lets `repro citations verify --strict` reach citations with `--strict`
    # rather than having this parser reject a flag it has never heard of.
    for tool in TOOLS:
        p_tool = sub.add_parser(
            tool.name, help=f"run `{tool.name}`: {tool.summary}", add_help=False
        )
        p_tool.set_defaults(func=None, tool=tool.name)

    args, rest = parser.parse_known_args(argv)
    if getattr(args, "tool", None):
        return delegate_run(BY_NAME[args.tool], rest)
    if rest:
        parser.error(f"unrecognized arguments: {' '.join(rest)}")
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
