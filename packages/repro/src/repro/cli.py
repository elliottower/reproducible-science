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
    repro ci              run the checks in a workflow, with a summary on the run page
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
import functools
import importlib
import json
import pathlib
import subprocess
from pathlib import Path

from provenance_core import atomic_write
from provenance_core.gitref import try_run

from repro import __version__, audit, ci, crosscheck
from repro.checks import LOCAL as LOCAL_CHECKS
from repro.checks import RECORD as CHECKS
from repro.checks import SET_ASIDE

# The commands of the claims side, each under the name it had in this module.
from repro.cli_claims import SYMBOL as SYMBOL
from repro.cli_claims import _assertion_lines as _assertion_lines
from repro.cli_claims import _chain_lines as _chain_lines
from repro.cli_claims import _checked_said as _checked_said
from repro.cli_claims import _count_said as _count_said
from repro.cli_claims import _finding_said as _finding_said
from repro.cli_claims import _history_lines as _history_lines
from repro.cli_claims import _named as _named
from repro.cli_claims import _numbers_lines as _numbers_lines
from repro.cli_claims import _record_lines as _record_lines
from repro.cli_claims import _said as _said
from repro.cli_claims import _stale_lines as _stale_lines
from repro.cli_claims import _stale_summary as _stale_summary
from repro.cli_claims import _stale_text as _stale_text
from repro.cli_claims import _steps as _steps
from repro.cli_claims import _verify_text as _verify_text
from repro.cli_claims import _why_lines as _why_lines
from repro.cli_claims import cmd_export as cmd_export
from repro.cli_claims import cmd_manifest_init as cmd_manifest_init
from repro.cli_claims import cmd_numbers as cmd_numbers
from repro.cli_claims import cmd_stale as cmd_stale
from repro.cli_claims import cmd_verify as cmd_verify
from repro.cli_claims import cmd_why as cmd_why
from repro.delegate import BY_NAME, TOOLS
from repro.delegate import check as delegate_check
from repro.delegate import run as delegate_run
from repro.demo import demo
from repro.exceptions import ReproError
from repro.export import EXPORTS
from repro.export.rocrate import METADATA_FILE
from repro.manifest import DEFAULT_NAME, find, load
from repro.models import (
    Reading,
    Regeneration,
    ReproductionReport,
)
from repro.policy import PROFILES, Assessment, Policy
from repro.reproduce import RECORD
from repro.reproduce import append as append_reproduction
from repro.reproduce import reproduce as run_reproduce
from repro.starter import CONVENTIONAL, MAX_DISCOVERED, project_root
from repro.starter import write as write_starter

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

    _reproduce_text(path, report, policy, assessment, recorded)
    return 0 if assessment.passed else 1


def _reproduce_text(
    path: Path,
    report: ReproductionReport,
    policy: Policy,
    assessment: Assessment,
    recorded: Path,
) -> None:
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
    if report.witness is not None:
        print(f"  witnessed {report.witness.said}, as the environment said")


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
            "0 whatever the outcomes; `repro verify` is the check that fails. `sarif` is a "
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

    ci.add_parser(sub, verify=_verify_text, reproduce=_reproduce_text, stale=_stale_text)

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
