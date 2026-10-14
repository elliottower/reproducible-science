"""A release from this tree opens a new series, and `scripts/versions.py` refuses any other.

`reproducible-science` and `results-cli` import `provenance_core.chain`. A sibling range names
a series, `>=0.5,<0.6`, so a further 0.5 release of either would install beside a
`provenance-core` published before the module existed and fail on import.
"""

from __future__ import annotations

import importlib.util
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location("versions", ROOT / "scripts" / "versions.py")
versions = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(versions)


@pytest.mark.parametrize("version", ["0.5.7", "0.5.10", "0.5.0", "0.4.9"])
def test_a_version_below_the_floor_is_refused_by_check_and_by_bump(version, monkeypatch):
    assert versions.below_floor(version) is not None
    before = {name: path.read_text() for name, path in versions.PACKAGES.items()}
    with pytest.raises(versions.VersionError, match=r"provenance_core\.chain"):
        versions.bump(version, realign=True)
    assert {name: path.read_text() for name, path in versions.PACKAGES.items()} == before

    monkeypatch.setattr(versions, "declared", lambda: dict.fromkeys(versions.PACKAGES, version))
    assert any("provenance_core.chain" in problem for problem in versions.check())


@pytest.mark.parametrize("version", ["0.5.6", "0.6.0", "0.6.1", "0.10.0", "1.0.0"])
def test_the_version_already_published_and_the_new_series_are_not(version):
    assert versions.below_floor(version) is None


def test_the_tree_as_it_stands_passes():
    assert not [p for p in versions.check() if "provenance_core.chain" in p]
    assert (ROOT / "packages/provenance-core/src/provenance_core/chain.py").is_file()
