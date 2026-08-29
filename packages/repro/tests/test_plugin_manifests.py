"""The Claude Code plugin manifests, and whether they describe what is actually here.

Nothing read these. They sat at `0.2.0` through two releases while the distributions went to
0.3.1, so a reader comparing the plugin to PyPI found a mismatch and nothing in the repository
could have told them. `scripts/versions.py` now writes and checks the version; these check the
rest of the manifest, which a version bump cannot keep honest: a marketplace entry pointing at
a directory that does not exist, or a plugin whose name does not match the one the marketplace
advertises, fails only when somebody tries to install it.
"""

from __future__ import annotations

import json
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[3]
MARKETPLACE = ROOT / ".claude-plugin" / "marketplace.json"
SEMVER = re.compile(r"^\d+\.\d+\.\d+([ab]\d+|rc\d+)?$")


def marketplace() -> dict:
    return json.loads(MARKETPLACE.read_text())


def entries() -> list[dict]:
    return marketplace()["plugins"]


def manifest_of(entry: dict) -> pathlib.Path:
    return (ROOT / entry["source"]).resolve() / ".claude-plugin" / "plugin.json"


def test_the_marketplace_is_readable_json_naming_at_least_one_plugin():
    assert entries(), "a marketplace advertising nothing is a marketplace nobody can install"


@pytest.mark.parametrize("entry", entries(), ids=lambda e: e["name"])
def test_every_advertised_plugin_has_a_manifest_where_the_marketplace_says(entry):
    """`source` is a relative path a client resolves. A wrong one fails at install time."""
    assert manifest_of(entry).is_file(), f"{entry['source']} has no .claude-plugin/plugin.json"


@pytest.mark.parametrize("entry", entries(), ids=lambda e: e["name"])
def test_a_plugin_answers_to_the_name_the_marketplace_advertises(entry):
    assert json.loads(manifest_of(entry).read_text())["name"] == entry["name"]


@pytest.mark.parametrize("entry", entries(), ids=lambda e: e["name"])
def test_every_plugin_carries_the_release_version(entry):
    """One release, one version. These drifted to two releases behind because nothing looked."""
    declared = json.loads(manifest_of(entry).read_text())["version"]
    assert SEMVER.match(declared), f"{declared!r} is not a version"
    assert declared == marketplace()["metadata"]["version"]


def test_the_marketplace_version_matches_the_distributions():
    """The manifests and the packages are one release. `scripts/versions.py` writes both."""
    pyproject = (ROOT / "packages" / "citations" / "pyproject.toml").read_text()
    packaged = re.search(r'^version = "([^"]+)"$', pyproject, re.M).group(1)
    assert marketplace()["metadata"]["version"] == packaged


def test_every_plugin_directory_present_is_advertised():
    """The reverse of the source check: a plugin nobody can find is a plugin nobody installs."""
    on_disk = {p.parents[2].name for p in ROOT.glob("packages/*/plugin/.claude-plugin/plugin.json")}
    advertised = {(ROOT / e["source"]).resolve().parent.name for e in entries()}
    assert on_disk == advertised, f"in the tree but not the marketplace: {on_disk - advertised}"
