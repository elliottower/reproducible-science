"""The version a record carries is the version of the code that ran: `claims-cli`'s.

A full install names `reproducible-science` as the tool that read an artifact, as every record
has. The version beside that name is this distribution's, so a `claims-cli` 0.5.7 installed
beside a `reproducible-science` 0.5.6 records 0.5.7. The mismatch is made by putting metadata
for a `reproducible-science` 9.9.9 first on the path of a fresh interpreter: `importlib.metadata`
answers with the first it finds, and nothing else is installed or changed.
"""

from __future__ import annotations

import importlib.metadata
import json
import multiprocessing.spawn
import os
import pathlib
import subprocess

CASES = pathlib.Path(__file__).parent / "conformance" / "cases"
OURS = importlib.metadata.version("claims-cli")
THEIRS = "9.9.9"


def fresh(tmp_path, program: str, *args: str) -> subprocess.CompletedProcess:
    """Run `program` in an interpreter that sees a `reproducible-science` of another version."""
    shadow = tmp_path / "shadow"
    info = shadow / f"reproducible_science-{THEIRS}.dist-info"
    info.mkdir(parents=True, exist_ok=True)
    (info / "METADATA").write_text(
        f"Metadata-Version: 2.1\nName: reproducible-science\nVersion: {THEIRS}\n"
    )
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join([str(shadow), os.environ.get("PYTHONPATH", "")]),
    }
    python = multiprocessing.spawn.get_executable()
    return subprocess.run(
        [python, "-c", program, *args], capture_output=True, text=True, env=env, check=True
    )


def test_the_shadow_is_seen_so_the_versions_really_differ(tmp_path):
    seen = fresh(
        tmp_path, "import importlib.metadata as m; print(m.version('reproducible-science'))"
    )
    assert seen.stdout.strip() == THEIRS != OURS


def test_a_decision_names_the_wrapper_and_carries_this_package_s_version(tmp_path):
    program = (
        "import json, sys\n"
        "from claims import load, verify, __version__\n"
        "from claims.record import check_records\n"
        "manifest = load(sys.argv[1])\n"
        "d = verify(manifest).decisions[0]\n"
        "r = check_records(manifest)[0]\n"
        "print(json.dumps([d.tool, d.tool_version, r.checker.name, r.checker.version, __version__]))\n"
    )
    found = json.loads(fresh(tmp_path, program, str(CASES / "value_match" / "repro.yaml")).stdout)
    assert found == ["reproducible-science", OURS, "repro", OURS, OURS]


def test_the_command_and_its_sarif_log_carry_this_package_s_version(tmp_path):
    version = fresh(tmp_path, "import claims; print(claims.__version__)").stdout.strip()
    assert version == OURS
    sarif = fresh(
        tmp_path,
        "import sys; from claims.cli import main; main(sys.argv[1:])",
        "verify",
        str(CASES / "value_match" / "repro.yaml"),
        "--format",
        "sarif",
    )
    driver = json.loads(sarif.stdout)["runs"][0]["tool"]["driver"]
    assert (driver["name"], driver["version"]) == ("repro", OURS)
