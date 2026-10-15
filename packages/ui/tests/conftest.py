"""A small project the page is built from: one data file, a script that turns it into a result,
a manuscript sentence printing the result, and a manifest declaring the claim and the step."""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import shutil
import subprocess

import pytest
import yaml
from repro_ui import graph

SCRIPT = """import json
data = json.load(open("data.json"))
json.dump({"total": sum(data["values"])}, open("results.json", "w"))
"""


def digest(path: pathlib.Path) -> dict:
    return {
        "algorithm": "sha256",
        "value": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def write_project(root: pathlib.Path, with_step: bool) -> pathlib.Path:
    (root / "data.json").write_text(json.dumps({"values": [1, 2, 3]}))
    (root / "make.py").write_text(SCRIPT)
    (root / "results.json").write_text(json.dumps({"total": 6}))
    (root / "paper.txt").write_text("We count the values. The total is 6.\n")
    files = {
        "data": ("data.json", "application/json"),
        "make": ("make.py", "text/x-python"),
        "results": ("results.json", "application/json"),
        "manuscript-text": ("paper.txt", "text/plain"),
    }
    manifest = {
        "schema_version": "repro/1",
        "project": "a small project",
        "artifacts": [
            {
                "id": aid,
                "path": path,
                "media_type": media,
                "digest": digest(root / path),
            }
            for aid, (path, media) in files.items()
        ],
        "claims": [
            {
                "id": "total",
                "where": "Section 1",
                "text": "The total is 6.",
                "evidence": [
                    {
                        "kind": "quote",
                        "artifact": "manuscript-text",
                        "text": "The total is 6.",
                    },
                    {
                        "kind": "metric",
                        "artifact": "results",
                        "name": "total",
                        "reported": "6",
                        "pointer": "/total",
                    },
                ],
            }
        ],
    }
    if with_step:
        manifest["regenerations"] = [
            {
                "id": "results",
                "command": ["python3", "make.py"],
                "inputs": [
                    {"artifact": "data", "digest": digest(root / "data.json")},
                    {"artifact": "make", "digest": digest(root / "make.py")},
                ],
                "output": {
                    "artifact": "results",
                    "digest": digest(root / "results.json"),
                },
            }
        ]
    (root / "repro.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False))
    return root


@pytest.fixture
def project(tmp_path: pathlib.Path) -> pathlib.Path:
    (tmp_path / "project").mkdir()
    return write_project(tmp_path / "project", with_step=True)


@pytest.fixture
def project_without_steps(tmp_path: pathlib.Path) -> pathlib.Path:
    (tmp_path / "project").mkdir()
    return write_project(tmp_path / "project", with_step=False)


def clean_env() -> dict[str, str]:
    """The environment without GIT_ variables, so an inherited GIT_INDEX_FILE or GIT_DIR cannot
    send these commits into the repository running the suite; and no timestamp calendars, so
    `prereg freeze` reaches no network."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    return {**env, "PROVENANCE_CALENDARS": ""}


def git(root: pathlib.Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
        cwd=root,
        env=clean_env(),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def cli(root: pathlib.Path, name: str, *args: str) -> None:
    """One of the tools, installed beside the page, run in `root`."""
    done = subprocess.run(
        [graph.tool(name), *args], cwd=root, env=clean_env(), capture_output=True, text=True
    )
    assert done.returncode == 0, f"{name} {' '.join(args)}: {done.stdout}{done.stderr}"


SOURCE = "The quick brown fox jumps over the lazy dog.\nA second sentence of the source.\n"
BINARY = bytes(range(256)) * 4


@pytest.fixture
def sealed_blob() -> bytes:
    """The bytes `kept` seals in blob.bin; the file on disk is then these bytes reversed."""
    return BINARY


@pytest.fixture(scope="session")
def kept_once(tmp_path_factory: pytest.TempPathFactory) -> pathlib.Path:
    """`kept`, made once: the tools it runs take seconds, and each test gets its own copy."""
    return make_kept(tmp_path_factory.mktemp("kept"))


@pytest.fixture
def kept(kept_once: pathlib.Path, tmp_path: pathlib.Path) -> pathlib.Path:
    return pathlib.Path(shutil.copytree(kept_once, tmp_path / "project", symlinks=True))


def make_kept(tmp_path: pathlib.Path) -> pathlib.Path:
    """The small project, in git, keeping all three records, each with one kind of problem:
    a frozen plan edited after its freeze; sealed files changed after the seal (a text file
    and a binary one a commit holds, and a text file no commit holds); and a quotation its
    pinned source does not contain. The claim itself still verifies."""
    root = tmp_path / "project"
    root.mkdir()
    write_project(root, with_step=False)
    git(root, "init", "-q")
    (root / "source.txt").write_text(SOURCE)
    (root / "claims").mkdir()
    (root / "claims" / "fox.yaml").write_text(
        yaml.safe_dump(
            {
                "source": {
                    "citation": "fox2020",
                    "local": "source.txt",
                    "sha256": hashlib.sha256(SOURCE.encode()).hexdigest(),
                },
                "claims": {
                    "jumps": {
                        "statement": "The fox jumps.",
                        "quotes": [{"exact": "The quick brown fox jumps over the lazy dog."}],
                    },
                    "sleeps": {
                        "statement": "The fox sleeps.",
                        "quotes": [{"exact": "The fox sleeps all day under the old tree."}],
                    },
                },
            },
            sort_keys=False,
        )
    )
    (root / "blob.bin").write_bytes(BINARY)
    (root / "scratch.txt").write_text("never committed\n")
    cli(root, "prereg", "new", ".", "--title", "study")
    cli(root, "results", "init")
    git(root, "add", "-A")
    git(root, "reset", "-q", "scratch.txt")
    git(root, "commit", "-q", "-m", "project")
    cli(root, "results", "seal", "data.json", "blob.bin", "scratch.txt")
    cli(root, "results", "run", "--run-id", "count", "--note", "make.py", "results.json")
    git(root, "add", "-A")
    git(root, "reset", "-q", "scratch.txt")
    git(root, "commit", "-q", "-m", "seal and run")
    cli(root, "prereg", "freeze", "PREREG.md", "--allow-tracked-sources")
    git(root, "add", "-A")
    git(root, "reset", "-q", "scratch.txt")
    git(root, "commit", "-q", "-m", "freeze")

    plan = root / "PREREG.md"
    plan.chmod(0o644)
    plan.write_text(plan.read_text() + "\nA line added after the freeze.\n")
    (root / "data.json").write_text(json.dumps({"values": [1, 2, 3, 4]}))
    (root / "blob.bin").write_bytes(BINARY[::-1])
    (root / "scratch.txt").write_text("changed, and never committed\n")
    return root
