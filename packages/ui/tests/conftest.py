"""A small project the page is built from: one data file, a script that turns it into a result,
a manuscript sentence printing the result, and a manifest declaring the claim and the step."""

from __future__ import annotations

import hashlib
import json
import pathlib

import pytest
import yaml

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
