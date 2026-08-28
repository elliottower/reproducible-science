"""The `repro` command.

    repro init <name>     scaffold an experiment directory
    repro demo            write a worked example and run the workflow over it
    repro verify          check every evidence assertion in repro.yaml

A renderer over the library and nothing more. `verify` calls `repro.verify()` and
`Policy.assess()`, both of which return values, so anything this prints can also be obtained
by importing the package. `main` returns an exit code; the process boundary is the only place
that exits.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from repro import __version__
from repro.demo import demo
from repro.exceptions import ReproError
from repro.manifest import DEFAULT_NAME, find, load
from repro.models import (
    Availability,
    Ordering,
    Outcome,
    Regeneration,
    RegenerationReason,
    Validity,
)
from repro.policy import PROFILES
from repro.renderers import to_sarif
from repro.verify import verify as run_verify

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


def cmd_init(args: argparse.Namespace) -> int:
    name = args.name
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
    print("done.")
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    return demo(args.directory, force=args.force)


def cmd_verify(args: argparse.Namespace) -> int:
    path = Path(args.manifest) if args.manifest else find()
    if path is None:
        print(f"no {DEFAULT_NAME} here or above.\n")
        print("declare the artifacts and claims to check:\n")
        print(f"    {DEFAULT_NAME}:\n      artifacts: [...]\n      claims: [...]")
        return 2

    report = run_verify(load(path), regenerate=getattr(args, "regenerate", False))
    policy = PROFILES[args.policy]
    assessment = policy.assess(report)

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

    # Built as a list and printed once. Printing the separator whenever the manifest declares a
    # regeneration put a blank line under a section that had printed nothing, since the
    # ordinary state -- not requested -- is the one state this block says nothing about.
    regenerations = []
    for state in report.regenerations:
        if state.state is Regeneration.REPRODUCED:
            regenerations.append(f"  reproduced  {state.artifact_id}")
        elif state.state is Regeneration.DIVERGED:
            regenerations.append(f"  DIVERGED    {state.artifact_id}: {state.detail[:48]}")
        elif state.reason is not RegenerationReason.NOT_REQUESTED:
            regenerations.append(f"  regen?      {state.artifact_id}: {state.reason.value}")
    if regenerations:
        print("\n".join(regenerations) + "\n")

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
            print(
                f"  {SYMBOL[d.outcome]}  {d.claim_id:<12} {d.kind:<8} {d.detail[:52]}{note}{mark}"
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="repro", description="Verify declared evidence assertions against pinned artifacts"
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command")

    p_init = sub.add_parser("init", help="scaffold an experiment directory")
    p_init.add_argument("name")
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

    p_verify = sub.add_parser("verify", help="check every evidence assertion in repro.yaml")
    p_verify.add_argument("manifest", nargs="?", help=f"path to {DEFAULT_NAME}")
    p_verify.add_argument("--policy", choices=sorted(PROFILES), default="publication")
    p_verify.add_argument("--format", choices=("text", "json", "sarif"), default="text")
    p_verify.add_argument(
        "--regenerate",
        action="store_true",
        help="run declared regeneration commands in a sandbox (executes them)",
    )
    p_verify.set_defaults(func=cmd_verify)

    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 1
    try:
        return args.func(args)
    except ReproError as e:
        print(str(e))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
