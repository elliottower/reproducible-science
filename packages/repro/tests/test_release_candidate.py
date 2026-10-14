"""A release candidate, `0.6.0rc1`, is a version `scripts/versions.py` can bump to and check.

The candidate exists to publish all six distributions once, as pre-releases a default install
never picks, before the release itself. That only works where every sibling range the bump
writes admits the version the six are released at: `>=0.6,<0.7` refuses `0.6.0rc1`, so a set
bumped that way would publish and not install. These run the bump on a copy of every file it
writes and read each range back with `packaging`, which is what pip and uv decide by.
"""

from __future__ import annotations

import importlib.util
import pathlib
import shutil

import pytest
from packaging.specifiers import SpecifierSet
from packaging.version import Version

ROOT = pathlib.Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location("versions", ROOT / "scripts" / "versions.py")
versions = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(versions)


@pytest.fixture
def tree(tmp_path, monkeypatch):
    """Every file `bump` writes, copied, and the script pointed at the copies."""

    def copied(path: pathlib.Path) -> pathlib.Path:
        target = tmp_path / path.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            shutil.copy(path, target)
        return target

    monkeypatch.setattr(
        versions, "PACKAGES", {name: copied(path) for name, path in versions.PACKAGES.items()}
    )
    monkeypatch.setattr(
        versions, "PLUGIN_MANIFESTS", tuple(copied(p) for p in versions.PLUGIN_MANIFESTS)
    )
    for name in ("CITATION", "HOOKS", "HOOK_README"):
        monkeypatch.setattr(versions, name, copied(getattr(versions, name)))
    # `bump` names what it touched relative to the root, so the root is the copy too.
    monkeypatch.setattr(versions, "PROJECT_ROOT", tmp_path)
    return versions.PACKAGES


def ranges(packages) -> list[tuple[str, str, str]]:
    """Every sibling range in every manifest, as (package, sibling, specifier)."""
    return [
        (name, sibling, spec)
        for name, path in packages.items()
        for sibling, spec in versions.cross_refs(path.read_text()).items()
        if sibling != name
    ]


@pytest.mark.parametrize("version", ["0.6.0rc1", "0.6.0rc2", "0.6.0", "0.6.1", "0.7.0b1"])
def test_every_sibling_range_admits_the_version_the_packages_are_bumped_to(tree, version):
    versions.bump(version)
    assert versions.check() == []
    found = ranges(tree)
    # Each of the five that depend on a sibling, and every sibling they name.
    assert len(found) >= 10
    for name, sibling, spec in found:
        assert Version(version) in SpecifierSet(spec), (name, sibling, spec)
    for path in tree.values():
        assert f'version = "{version}"' in path.read_text()


def test_the_ranges_a_candidate_writes_open_when_the_release_is_cut(tree):
    versions.bump("0.6.0rc1")
    candidate = {(n, s): spec for n, s, spec in ranges(tree)}
    assert set(candidate.values()) == {">=0.6.0rc1,<0.7"}
    versions.bump("0.6.0")
    final = {(n, s): spec for n, s, spec in ranges(tree)}
    assert set(final.values()) == {">=0.6,<0.7"}
    assert final.keys() == candidate.keys()
    # Named, because each was a range that would otherwise have stayed in 0.5.
    assert final["claims-cli", "provenance-core"] == ">=0.6,<0.7"
    assert final["results-cli", "prereg"] == ">=0.6,<0.7"
    assert final["reproducible-science", "claims-cli"] == ">=0.6,<0.7"
    # A final release does not admit the next series' candidates.
    assert Version("0.7.0rc1") not in SpecifierSet(final["claims-cli", "provenance-core"])


def test_a_released_range_refuses_a_candidate_which_is_why_a_candidate_writes_its_own():
    assert Version("0.6.0rc1") not in SpecifierSet(">=0.6,<0.7")
    assert Version("0.6.0rc1") in SpecifierSet(versions.series("0.6.0rc1"))
    assert Version("0.6.0") in SpecifierSet(versions.series("0.6.0rc1"))


@pytest.mark.parametrize(
    ("earlier", "later"),
    [
        ("0.5.6", "0.6.0rc1"),
        ("0.6.0a1", "0.6.0b1"),
        ("0.6.0b2", "0.6.0rc1"),
        ("0.6.0rc1", "0.6.0rc2"),
        ("0.6.0rc9", "0.6.0rc10"),
        ("0.6.0rc2", "0.6.0"),
        ("0.6.0", "0.6.1rc1"),
        ("0.9.0", "0.10.0rc1"),
    ],
)
def test_versions_are_ordered_as_pep_440_orders_them(earlier, later):
    assert versions.parts(earlier) < versions.parts(later)
    assert Version(earlier) < Version(later)


def test_a_candidate_may_go_on_to_its_release_and_a_release_may_not_go_back(tree):
    versions.bump("0.6.0rc1")
    versions.bump("0.6.0rc2")
    versions.bump("0.6.0")
    with pytest.raises(versions.VersionError, match="may not go backwards"):
        versions.bump("0.6.0rc3")


@pytest.mark.parametrize("version", ["0.5.7rc1", "0.5.7", "0.5.6rc1"])
def test_the_floor_refuses_a_candidate_below_it(tree, version):
    with pytest.raises(versions.VersionError, match=r"provenance_core\.chain"):
        versions.bump(version)


@pytest.mark.parametrize("version", ["0.6.0rc1", "0.6.0a1", "0.6.0"])
def test_the_floor_admits_a_candidate_of_its_own_series(version):
    assert versions.below_floor(version) is None


@pytest.mark.parametrize(
    "bad", ["0.6", "0.6.0-rc1", "0.6.0.rc1", "0.6.0rc", "v0.6.0", "0.6.0post1"]
)
def test_a_version_this_scheme_does_not_write_is_refused(bad):
    with pytest.raises(versions.VersionError, match="not a version this scheme writes"):
        versions.parts(bad)
