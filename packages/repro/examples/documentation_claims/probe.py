"""Count the conformance fixtures, at the working tree and at a pinned baseline revision.

A documentation claim is settled by a command, and this runs the commands. Each record keeps
the argv, the exit status, a digest of the standard output, and the single number read out of
it, so the number and its provenance travel together and a later run that disagrees says which
command disagreed.

**No regeneration record declares this.** The thing measured is a directory, and a directory is
not a file a manifest can pin as an input: `Digest.of_file` raises on one. The regeneration
sandbox exists so that a command needing an undeclared file fails; a command whose subject
cannot be declared would report `reproduced` on grounds the sandbox never checked, so this
example declares no regeneration rather than collecting a guarantee it has not earned. See
SPEC.md 3.6.

    python3 probe.py
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import subprocess
from datetime import UTC, datetime

HERE = pathlib.Path(__file__).resolve().parent
OUT = HERE / "probe.json"

CASES = "packages/repro/tests/conformance/cases"

#: The revision whose specification says *eighteen* where the suite held nineteen case
#: directories. A literal commit rather than `origin/main`, because `main` is where this gets
#: corrected: reading the defect off a moving branch would demonstrate a check that passes,
#: and a check that only ever passes is not evidence that it can fail.
BASELINE = "2b4756b2c3fa14022772c4510d126ecd70b4e968"


def run(argv: list[str], cwd: pathlib.Path) -> tuple[int, str]:
    proc = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=120)
    return proc.returncode, proc.stdout


def lines(stdout: str) -> int:
    return len([line for line in stdout.splitlines() if line.strip()])


def main() -> int:
    root = pathlib.Path(
        subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=HERE,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    )

    probes = {}
    for name, argv in (
        # What the suite holds now.
        ("fixtures_at_head", ["ls", "-1", CASES]),
        # What it held at the revision whose specification says eighteen. `ls-tree` on the
        # directory lists its entries, one per fixture.
        ("fixtures_at_baseline", ["git", "ls-tree", "--name-only", f"{BASELINE}:{CASES}"]),
    ):
        code, stdout = run(argv, root)
        probes[name] = {
            "command": argv,
            "exit": code,
            "stdout_sha256": hashlib.sha256(stdout.encode()).hexdigest(),
            "value": lines(stdout),
        }

    OUT.write_text(
        json.dumps(
            {
                "generated": datetime.now(UTC).isoformat(timespec="seconds"),
                "revision": BASELINE,
                "probes": probes,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    for name, probe in sorted(probes.items()):
        print(f"  {name:<26} {probe['value']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
