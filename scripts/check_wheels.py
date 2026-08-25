"""Install the built wheels outside the workspace and check they work together.

The workspace resolves the four packages from source, so the test suite never exercises the
combination a user installs. Two things that only show up here: a sibling API that drifted
without a version bump, and a dependency floor that lets pip resolve an older release than
the one the tests ran against.

    uv run python scripts/check_wheels.py

Builds every package, installs the four wheels into a throwaway environment with third-party
dependencies resolved from PyPI, and runs the manifest the repository audits itself with.
"""

from __future__ import annotations

import pathlib
import shutil
import subprocess
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
#: Every distribution a release ships. `provenance-core` is first because the others
#: declare it: a check that installs the four without it proves only that a broken
#: release resolves against a directory it will not have on PyPI.
DISTS = ("provenance-core", "citations", "prereg", "results-cli", "reproducible-science")


def run(*command: str, cwd: pathlib.Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(command, cwd=cwd, capture_output=True, text=True)


def main() -> int:
    scratch = pathlib.Path(tempfile.mkdtemp(prefix="repro-wheels-"))
    wheels, venv = scratch / "wheels", scratch / "venv"
    try:
        for dist in DISTS:
            built = run("uv", "build", "--package", dist, "--out-dir", str(wheels), cwd=ROOT)
            if built.returncode:
                print(f"  FAIL build {dist}\n{built.stderr}")
                return 1
        found = sorted(wheels.glob("*.whl"))
        print(f"  built {len(found)} wheels")

        run("uv", "venv", "--python", "3.13", str(venv))
        python = venv / "bin" / "python"
        install = run("uv", "pip", "install", "--python", str(python), *[str(w) for w in found])
        if install.returncode:
            print(f"  FAIL install\n{install.stderr}")
            return 1

        # Nothing may resolve from the workspace: the point is to test the artifacts.
        versions = run(
            str(python),
            "-c",
            "import importlib.metadata as m;"
            f"print(' '.join(f'{{d}}={{m.version(d)}}' for d in {DISTS!r}))",
        )
        print(f"  installed {versions.stdout.strip()}")

        smoke = run(
            str(venv / "bin" / "repro"),
            "verify",
            str(ROOT / "paper" / "repro.yaml"),
            "--policy",
            "strict",
        )
        tail = [ln for ln in smoke.stdout.splitlines() if ln.strip()][-1:] or [""]
        print(f"  repro verify --policy strict -> exit {smoke.returncode}: {tail[0].strip()}")
        if smoke.returncode != 0:
            print(smoke.stdout[-2000:])
            return 1

        quote = run(
            str(python), "-c", "from citations.verify import check_one; print('quote backend: ok')"
        )
        if quote.returncode:
            print(f"  FAIL quote backend\n{quote.stderr}")
            return 1
        print(f"  {quote.stdout.strip()}")
        print("  wheels install and interoperate")
        return 0
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
