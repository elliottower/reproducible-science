"""Build the changelog for a release, in a form the repository's own linter accepts.

`towncrier build` writes runs of blank lines between sections, and `markdownlint` rejects
them (MD012). Left as two commands, the second is the one that gets forgotten: the release
where it was forgotten is the release where `make release-check` fails after the fragments
have already been consumed, which is an awkward state to be in and a tempting one to fix by
disabling the lint.

    uv run python scripts/changelog.py 0.4.0

Consumes the fragments under `changes/` and rewrites `CHANGELOG.md`. Idempotent only in the
sense that there is nothing left to consume afterwards; run it once per release.
"""

from __future__ import annotations

import argparse
import pathlib
import re
import subprocess
import sys

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
CHANGELOG = PROJECT_ROOT / "CHANGELOG.md"

#: Two or more blank lines, which is what MD012 objects to.
BLANK_RUN = re.compile(r"\n{3,}")


def normalize(text: str) -> str:
    """One blank line between blocks, and exactly one newline at the end of the file."""
    return BLANK_RUN.sub("\n\n", text).rstrip("\n") + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="changelog", description=__doc__.split("\n")[0])
    ap.add_argument("version", help="the release this section is titled with")
    a = ap.parse_args(argv)

    built = subprocess.run(
        ["uv", "run", "towncrier", "build", "--yes", "--version", a.version],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )
    if built.returncode != 0:
        sys.stderr.write(built.stdout + built.stderr)
        return built.returncode

    before = CHANGELOG.read_text()
    after = normalize(before)
    if after != before:
        CHANGELOG.write_text(after)
    entries = sum(1 for line in after.splitlines() if line.startswith("- "))
    print(f"CHANGELOG.md: {a.version} written, {entries} entries in the file")
    return 0


if __name__ == "__main__":
    sys.exit(main())
