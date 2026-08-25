"""Is the adduce integration still true of the adduce people actually install?

`repro` publishes a rule that adduce discovers through an entry point. Nothing here imports
adduce at runtime, so its releases cannot break an install -- but they can quietly falsify the
adapter, and the interop claim in `docs/SPEC.md` and the paper along with it.

The awkward part is whose schedule governs. Blocking every commit on a third party's release
makes an unrelated pull request red for a reason its author cannot fix. Never checking means
the claim rots and nobody learns until a reviewer tries it. So the same check reports two ways:

    --advisory   never fails; says what changed. For every push.
    (default)    fails on a new version or a broken adapter. For a release.

`[tool.interop] adduce = "..."` records the version the adapter was last verified against. A
newer release is not a failure in itself -- it is a prompt to run the tests, then either move
that pin forward or cap the dependency.

    python scripts/check_interop.py --advisory
    python scripts/check_interop.py
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import tomllib
import urllib.error
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PACKAGE = "adduce"


class InteropError(Exception):
    """The interop claim could not be evaluated."""


def verified_version() -> str:
    data = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text())
    try:
        return data["tool"]["interop"][PACKAGE]
    except KeyError as e:
        raise InteropError(
            f'pyproject.toml has no [tool.interop] {PACKAGE} = "..."; '
            f"nothing records which version the adapter was verified against"
        ) from e


def latest_on_pypi() -> str:
    try:
        with urllib.request.urlopen(f"https://pypi.org/pypi/{PACKAGE}/json", timeout=30) as r:
            return json.loads(r.read().decode("utf-8", "replace"), strict=False)["info"]["version"]
    except (urllib.error.URLError, OSError, ValueError, KeyError) as e:
        raise InteropError(f"could not ask PyPI for {PACKAGE}: {e}") from e


SUMMARY = re.compile(r"^\d+ (passed|failed|error)", re.M)
COLLECTED = re.compile(r"(\d+) (?:passed|failed)")


def run_integration_tests(version: str) -> tuple[bool, str]:
    """Install that exact version and run the tests marked `integration`.

    A run that collected nothing is a failure, not a pass. `-m integration` selects by marker,
    and a renamed or dropped marker would otherwise report a green interop check that executed
    no code -- which is the shape of every defect this repository's gates exist to catch.
    """
    proc = subprocess.run(
        [
            "uv",
            "run",
            "--isolated",
            "--all-packages",
            "--group",
            "dev",
            "--with",
            f"{PACKAGE}=={version}",
            "pytest",
            "-q",
            "-m",
            "integration",
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    output = (proc.stdout + proc.stderr).strip()
    line = SUMMARY.search(output)
    summary = line.group(0) if line else "pytest printed no summary"
    if proc.returncode != 0:
        return False, output
    ran = COLLECTED.search(summary)
    if not ran or int(ran.group(1)) == 0:
        return False, f"{output}\n\nno test carrying the `integration` marker ran"
    return True, summary


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="check-interop", description=__doc__.split("\n")[0])
    ap.add_argument(
        "--advisory",
        action="store_true",
        help="report and always exit 0; for every push rather than for a release",
    )
    a = ap.parse_args(argv)

    try:
        pinned, latest = verified_version(), latest_on_pypi()
    except InteropError as e:
        print(f"  {e}")
        return 0 if a.advisory else 1

    print(f"  {PACKAGE}: verified against {pinned}, latest on PyPI is {latest}")
    ok, output = run_integration_tests(latest)
    tail = output.splitlines()[-1] if output else "(no output)"

    if ok and latest == pinned:
        print(f"  ok    the adapter holds against {latest}  ({tail})")
        return 0

    if ok:
        print(f"  NEW   {PACKAGE} {latest} is newer than the verified {pinned}")
        print(f"        the integration tests still pass against it  ({tail})")
        print(f'        move the record forward: [tool.interop] {PACKAGE} = "{latest}"')
        return 0 if a.advisory else 1

    print(f"  BROKEN {PACKAGE} {latest} fails the integration tests")
    for line in output.splitlines()[-12:]:
        print(f"         {line}")
    print()
    print("  Two ways out, and they are different claims:")
    print(f"    - cap the dependency: adduce>=,<{latest} , and say the adapter targets {pinned}")
    print(f"    - fix packages/repro/src/repro/integrations/adduce.py for {latest}")
    print("  Shipping neither leaves an interop claim in SPEC.md that is no longer true.")
    return 0 if a.advisory else 1


if __name__ == "__main__":
    raise SystemExit(main())
