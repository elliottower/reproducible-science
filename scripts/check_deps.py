"""Run deptry over each package, since it takes one project at a time."""

from __future__ import annotations

import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
PACKAGES = sorted(p.name for p in (ROOT / "packages").iterdir() if (p / "pyproject.toml").is_file())


def main() -> int:
    failed = []
    for package in PACKAGES:
        # deptry resolves the dependency specification from its working directory, so it is
        # run inside each package rather than pointed at one from the workspace root.
        result = subprocess.run(
            ["deptry", "."], cwd=ROOT / "packages" / package, capture_output=True, text=True
        )
        status = "ok" if result.returncode == 0 else "FAIL"
        print(f"  {status:4s} {package}")
        if result.returncode != 0:
            failed.append(package)
            print((result.stdout + result.stderr).strip()[-1200:])
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
