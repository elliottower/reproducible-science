"""Verifying a repository must not change it.

`repro verify` is published as a pre-commit hook, so it runs inside other people's
repositories, against their manifests, on every commit they make. A verifier that writes to
the tree it is checking would be intolerable there: it would dirty a working tree mid-commit,
and worse, a tool that can modify an artifact is a tool that could be made to modify one into
agreeing with the claim.

The one thing that does write is the adduce rule's sidecar, which exists because a single
adduce `Finding` cannot carry thousands of per-assertion outcomes. That is a different entry
point, invoked by a different tool, and it writes only under `.adduce/`.
"""

from __future__ import annotations

import hashlib
import json
import pathlib

import pytest
from repro import load, verify
from repro.policy import PUBLICATION, STRICT
from repro.renderers.sarif import to_sarif


def snapshot(root: pathlib.Path) -> dict[str, str]:
    """Every file under root, by content digest, so any write is visible."""
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


@pytest.fixture
def project(tmp_path):
    results = tmp_path / "results.json"
    body = json.dumps({"delta": 3.2, "other": "text"}, indent=2)
    results.write_text(body)
    source = tmp_path / "source.txt"
    source.write_text("The delta was 3.2 in the primary comparison.\n")
    (tmp_path / "repro.yaml").write_text(
        "schema_version: repro/1\n"
        "project: read-only\n"
        "artifacts:\n"
        "- id: res\n"
        "  path: results.json\n"
        "  digest:\n"
        "    algorithm: sha256\n"
        f"    value: {hashlib.sha256(body.encode()).hexdigest()}\n"
        "claims:\n"
        "- id: c\n"
        "  text: t\n"
        "  evidence:\n"
        "  - kind: metric\n"
        "    artifact: res\n"
        "    name: delta\n"
        "    reported: '3.2'\n"
        "    pointer: /delta\n"
    )
    return tmp_path


def test_verifying_writes_nothing(project):
    before = snapshot(project)
    verify(load(project / "repro.yaml"))
    assert snapshot(project) == before


def test_assessing_and_rendering_write_nothing(project):
    before = snapshot(project)
    report = verify(load(project / "repro.yaml"))
    PUBLICATION.assess(report)
    STRICT.assess(report)
    to_sarif(report)
    assert snapshot(project) == before


def test_verifying_creates_no_new_files(project):
    before = set(snapshot(project))
    verify(load(project / "repro.yaml"))
    assert set(snapshot(project)) == before, "a verifier must not leave anything behind"


def test_a_failing_verification_also_writes_nothing(project):
    """The interesting case: a tool that repaired what it found would be worse than useless."""
    results = project / "results.json"
    results.write_text(json.dumps({"delta": 9.9}, indent=2))
    before = snapshot(project)
    report = verify(load(project / "repro.yaml"))
    assert any(d.outcome.value != "verified" for c in report.claims for d in c.decisions)
    assert snapshot(project) == before


def test_regeneration_is_off_unless_asked(project):
    """`verify` never runs a declared command by default, and the sandbox never touches the
    tree even when it does."""
    before = snapshot(project)
    verify(load(project / "repro.yaml"), regenerate=True)
    assert snapshot(project) == before
