"""Check the specification's claim about the suite beside it, twice.

Writes `doc_claims.json`, the record every number reported from this example is read from, and
`doc_claims.log`, the verbatim output of every command.

Two runs, because a check that only ever passes is not evidence that it can fail, and a check
that only ever fails is not evidence that it can pass:

  * against the working tree, where the sentence and the count agree;
  * against `origin/main`, where the specification says *eighteen* and the suite held nineteen
    case directories. Both sides are read at that revision, so the disagreement stays
    reproducible after the working tree is corrected.

Neither manifest contains either number. The second run is the reason the kind exists: with a
`metric` the same claim needs `reported: "18"` in the manifest, and rewriting that field to the
measured value makes the manifest pass while the specification stays wrong.

    python3 run.py
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import pathlib
import subprocess
import tempfile
from datetime import UTC, datetime

import build as build_manifest
import probe as probe_commands
import yaml

HERE = pathlib.Path(__file__).resolve().parent
ROOT = build_manifest.ROOT
MANIFEST = HERE / "docclaims.yaml"
RECORD = HERE / "doc_claims.json"
LOG = HERE / "doc_claims.log"

VERIFY = ["repro", "verify"]


def step(name: str, argv: list[str], cwd: pathlib.Path, note: str = "") -> dict:
    proc = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=600)
    return {
        "name": name,
        "command": " ".join(argv),
        "exit": proc.returncode,
        "note": note,
        "output": (proc.stdout + proc.stderr).rstrip("\n"),
    }


def called(name: str, entry_point, note: str = "") -> dict:
    """One step run in this process, recorded in the same shape as a subprocess."""
    captured = io.StringIO()
    with contextlib.redirect_stdout(captured):
        code = entry_point()
    return {
        "name": name,
        "command": f"python {name}.py",
        "exit": code,
        "note": note,
        "output": captured.getvalue().rstrip("\n"),
    }


def at_origin_main(scratch: pathlib.Path) -> pathlib.Path:
    """The same claim, over the specification and the count as they were at `origin/main`.

    The sentence is read out of the blob rather than copied into this file, and the count comes
    from `git ls-tree` over the same revision, so both sides of the historical claim are read
    exactly as both sides of the live one are.
    """
    spec = scratch / "SPEC.md"
    spec.write_bytes(
        subprocess.run(
            ["git", "show", "origin/main:docs/SPEC.md"],
            cwd=ROOT,
            capture_output=True,
            check=True,
        ).stdout
    )
    probe = scratch / "probe.json"
    probe.write_text(json.dumps(json.loads((HERE / "probe.json").read_text()), indent=2) + "\n")

    document = build_manifest.manifest(spec, "/probes/fixtures_at_origin_main/value")
    document["project"] = "the same claim, at origin/main"
    for artifact in document["artifacts"]:
        artifact["path"] = os.path.relpath(scratch / pathlib.Path(artifact["path"]).name, scratch)
        artifact["digest"]["value"] = build_manifest.Digest.of_file(
            scratch / pathlib.Path(artifact["path"]).name
        ).value
    # The specification wrote the count as a word at that revision, and reading a word as a
    # number is a decision the manifest has to make rather than the engine.
    side = document["claims"][0]["evidence"][0]["sides"][0]
    side["locator"]["form"] = "cardinal_word"
    side["locator"]["after"] = "fixtures, each"

    out = scratch / "docclaims.yaml"
    out.write_text(yaml.safe_dump(document, sort_keys=False, width=110))
    return out


def main() -> int:
    steps = [
        called("probe", probe_commands.main, "counts the fixtures at HEAD and at origin/main"),
        called("build", build_manifest.main, "pins the specification and the probe output"),
        step(
            "verify",
            [*VERIFY, MANIFEST.name, "--policy", "publication"],
            HERE,
            "what the specification says, against what the command returned",
        ),
    ]

    with tempfile.TemporaryDirectory(prefix="docclaims-") as name:
        scratch = pathlib.Path(name)
        steps.append(
            step(
                "verify.at_origin_main",
                [*VERIFY, at_origin_main(scratch).name, "--policy", "publication"],
                scratch,
                "the specification said eighteen and the suite held nineteen; neither number "
                "is in the manifest",
            )
        )

    record = {
        "generated": datetime.now(UTC).isoformat(timespec="seconds"),
        "probes": json.loads((HERE / "probe.json").read_text())["probes"],
        "manifest": yaml.safe_load(MANIFEST.read_text()),
        "steps": {s["name"]: s for s in steps},
    }
    RECORD.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")

    lines = [f"# the specification's claim about the suite beside it, {record['generated']}", ""]
    for s in steps:
        lines += [f"$ {s['command']}", s["output"], f"[exit {s['exit']}]", ""]
    LOG.write_text("\n".join(lines))

    print(f"wrote {RECORD.name} and {LOG.name}")
    for s in steps:
        print(f"  {s['name']:<22} exit {s['exit']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
