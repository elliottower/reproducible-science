"""Install the built wheels outside the workspace and check they work together.

The workspace resolves the four packages from source, so the test suite never exercises the
combination a user installs. Two things that only show up here: a sibling API that drifted
without a version bump, and a dependency floor that lets pip resolve an older release than
the one the tests ran against.

    uv run python scripts/check_wheels.py

Builds every package, installs the wheels into a throwaway environment with third-party
dependencies resolved from PyPI, and runs the manifest the repository audits itself with.

Then installs `claims-cli` by itself, with only the two wheels it declares, into a second
environment. That one must hold no `repro`, `results` or `prereg`, `claims verify` must check
a conformance case in it, and its own test suite must pass in it with pytest and nothing else
added: the distribution exists to be installed without the rest, and a workspace in which
everything is always present cannot show that it can be.
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
DISTS = (
    "provenance-core",
    "citations",
    "prereg",
    "results-cli",
    "claims-cli",
    "reproducible-science",
)

#: What `claims-cli` declares of ours, and so all that is installed beside it when it is
#: installed alone. The file names are the distributions' with underscores, as a wheel's is.
ALONE = ("provenance_core", "citations", "claims_cli")

#: What an environment holding only `claims-cli` must not be able to import.
ABSENT = ("repro", "results", "prereg")


def run(*command: str, cwd: pathlib.Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(command, cwd=cwd, capture_output=True, text=True)


def alone(scratch: pathlib.Path, found: list[pathlib.Path], cases: pathlib.Path) -> int:
    """Install `claims-cli` with nothing of ours it does not declare, and check a manifest."""
    venv = scratch / "venv-claims"
    wanted = [str(w) for w in found if w.name.split("-")[0] in ALONE]
    run("uv", "venv", "--python", "3.13", str(venv))
    python = venv / "bin" / "python"
    install = run("uv", "pip", "install", "--python", str(python), *wanted)
    if install.returncode:
        print(f"  FAIL install claims-cli alone\n{install.stderr}")
        return 1

    probe = run(
        str(python),
        "-c",
        "import importlib.util as u, importlib.metadata as m, claims, claims.cli\n"
        "from claims.verify import ADAPTER_DISTRIBUTION\n"
        f"present = [n for n in {ABSENT!r} if u.find_spec(n) is not None]\n"
        "print(present, ADAPTER_DISTRIBUTION, claims.__version__ == m.version('claims-cli'))",
    )
    if probe.returncode or probe.stdout.split("]")[0] != "[":
        print(f"  FAIL claims-cli alone\n{probe.stdout}{probe.stderr}")
        return 1
    if probe.stdout.strip() != "[] claims-cli True":
        print(f"  FAIL claims-cli alone names itself wrongly: {probe.stdout.strip()}")
        return 1
    print("  claims-cli alone: no repro, results or prereg; names itself claims-cli")

    for case in ("passage_present", "value_match", "table_cell_match"):
        smoke = run(
            str(venv / "bin" / "claims"),
            "verify",
            str(cases / case / "repro.yaml"),
            "--policy",
            "strict",
        )
        tail = [ln for ln in smoke.stdout.splitlines() if ln.strip()][-1:] or [""]
        print(f"  claims verify {case} -> exit {smoke.returncode}: {tail[0].strip()}")
        if smoke.returncode != 0:
            print(smoke.stdout[-2000:])
            return 1
    # The same check through the library, and the tool a decision names where the wrapper is
    # not installed.
    named = run(
        str(python),
        "-c",
        "from claims import load, verify\n"
        f"d = verify(load({str(cases / 'value_match' / 'repro.yaml')!r})).decisions[0]\n"
        "print(d.outcome.value, d.tool)",
    )
    if named.stdout.strip() != "verified claims-cli":
        print(f"  FAIL claims-cli alone: {named.stdout}{named.stderr}")
        return 1
    print("  claims-cli installs and checks a manifest by itself")

    # Its own tests, run in that environment with nothing added but pytest: a test that
    # passes only beside the wrapper, or only with an optional reader present, fails here.
    added = run("uv", "pip", "install", "--python", str(python), "pytest")
    if added.returncode:
        print(f"  FAIL install pytest beside claims-cli\n{added.stderr}")
        return 1
    suite = run(
        str(python),
        "-m",
        "pytest",
        "-q",
        "-p",
        "no:cacheprovider",
        str(ROOT / "packages" / "claims" / "tests"),
        cwd=ROOT / "packages" / "claims",
    )
    summary = [ln for ln in suite.stdout.splitlines() if ln.strip()][-1:] or [""]
    print(f"  claims-cli alone, its tests: {summary[0].strip()}")
    if suite.returncode:
        print(suite.stdout[-4000:])
        return 1
    return 0


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

        # One clean fixture per contract variant, so the installed engine is exercised on a
        # quote, a metric and a table rather than on whichever one a single manifest happens
        # to carry. These five cases are the conformance suite's passing ones; the rest assert
        # failures and would exit non-zero by design.
        cases = ROOT / "packages" / "claims" / "tests" / "conformance" / "cases"
        for case in ("passage_present", "value_match", "table_cell_match"):
            smoke = run(
                str(venv / "bin" / "repro"),
                "verify",
                str(cases / case / "repro.yaml"),
                "--policy",
                "strict",
            )
            tail = [ln for ln in smoke.stdout.splitlines() if ln.strip()][-1:] or [""]
            print(f"  repro verify {case} -> exit {smoke.returncode}: {tail[0].strip()}")
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
        return alone(scratch, found, cases)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
