"""CLI for reproducible-science: scaffold an experiment directory."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

CLAUDE_MD = """\
# {name}

## Reproducible science tools

This experiment uses three CLI tools for reproducibility:

- `prereg` — freeze a plan before running, record amendments/deviations
- `citations` — verify quotations resolve in pinned source artifacts
- `results` — seal inputs, record outputs, bind claims to runs, verify the chain

## Workflow

```bash
prereg freeze                         # lock the plan
results seal PREREG.md analysis.py    # hash inputs
results access "read metadata" --level "metadata only"

# run the computation

results run output.json --run-id exp_001
results claim "ICC = 0.42" --run-id exp_001 --confirmatory --location "Table 2"
results verify --files
citations verify --claims claims/
```
"""


def _run(cmd: list[str], cwd: Path) -> bool:
    try:
        subprocess.run(cmd, cwd=cwd, check=True)
        return True
    except FileNotFoundError:
        print(f"  skipped: {cmd[0]} not installed", file=sys.stderr)
        return False
    except subprocess.CalledProcessError:
        print(f"  warning: {' '.join(cmd)} failed", file=sys.stderr)
        return False


def init(args: argparse.Namespace) -> None:
    name = args.name
    target = Path(args.directory) if args.directory else Path.cwd() / name

    target.mkdir(parents=True, exist_ok=True)
    print(f"initializing {target}")

    _run(["prereg", "new", name], cwd=target)
    _run(["results", "init"], cwd=target)
    _run(["citations", "init"], cwd=target)

    for d in ["claims", "data", "scripts", "figures"]:
        (target / d).mkdir(exist_ok=True)

    claude_md = target / "CLAUDE.md"
    if not claude_md.exists():
        claude_md.write_text(CLAUDE_MD.format(name=name))
        print(f"  wrote {claude_md.relative_to(Path.cwd())}")

    print("done.")


def verify(args: argparse.Namespace) -> None:
    cwd = Path.cwd()
    ok = True
    ok &= _run(["prereg", "check"], cwd=cwd)
    ok &= _run(["results", "verify", "--files"], cwd=cwd)
    ok &= _run(["citations", "verify", "--claims", "claims/"], cwd=cwd)
    if not ok:
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="repro",
        description="Scaffold reproducible science workflows",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__import__('repro').__version__}")
    sub = parser.add_subparsers(dest="command")

    p_init = sub.add_parser("init", help="scaffold an experiment directory")
    p_init.add_argument("name", help="experiment name")
    p_init.add_argument("--directory", "-d", help="target directory (default: ./<name>)")
    p_init.set_defaults(func=init)

    p_verify = sub.add_parser("verify", help="run all three verification tools")
    p_verify.set_defaults(func=verify)

    args = parser.parse_args()
    if not hasattr(args, "func"):
        parser.print_help()
        sys.exit(1)
    args.func(args)
