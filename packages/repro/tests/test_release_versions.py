"""`scripts/versions.py` reads and rewrites the dependency array of every manifest.

The array is written two ways in this workspace -- one line, and one entry per line -- and a
pattern that ended at a line-initial `]` handled neither reliably. It missed `prereg`, whose
array is a single line with no later array to close on, so `bump` moved every package but that
one and `check` could not see the disagreement because it read the same way. The wheels refused
to install together, which is where it was caught.
"""

from __future__ import annotations

import importlib.util
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location("versions", ROOT / "scripts" / "versions.py")
versions = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(versions)


ONE_LINE = """[project]
name = "prereg"
version = "0.3.0"
dependencies = [ "provenance-core>=0.3,<0.4" ]
urls.Homepage = "https://example.org"
"""

ONE_LINE_THEN_ANOTHER_ARRAY = """[project]
name = "citations"
version = "0.3.0"
dependencies = [ "platformdirs>=3", "provenance-core>=0.3,<0.4" ]
classifiers = [
  "Programming Language :: Python",
]
"""

MULTI_LINE = """[project]
name = "repro"
version = "0.3.0"
dependencies = [
  "citations>=0.3,<0.4",
  # A comment, which is part of the array's text.
  "provenance-core>=0.3,<0.4",
]
keywords = [ "provenance" ]
"""


@pytest.mark.parametrize("text", [ONE_LINE, ONE_LINE_THEN_ANOTHER_ARRAY, MULTI_LINE])
def test_the_dependency_array_is_found_however_it_is_written(text):
    span = versions.dependencies_span(text)
    assert span is not None
    assert "provenance-core" in text[span[0] : span[1]]


def test_the_span_stops_at_its_own_bracket_and_does_not_swallow_the_next_array():
    # The regression: the span ran past the array's own `]` to the one closing `classifiers`,
    # so a substitution meant for a dependency could reach a classifier or an ignore list.
    span = versions.dependencies_span(ONE_LINE_THEN_ANOTHER_ARRAY)
    assert "classifiers" not in ONE_LINE_THEN_ANOTHER_ARRAY[span[0] : span[1]]


def test_a_manifest_with_no_dependency_array_has_no_span():
    assert versions.dependencies_span('[project]\nname = "x"\nversion = "0.3.0"\n') is None


@pytest.mark.parametrize("text", [ONE_LINE, ONE_LINE_THEN_ANOTHER_ARRAY, MULTI_LINE])
def test_a_sibling_is_read_out_of_every_form_of_the_array(text):
    assert versions.cross_refs(text).get("provenance-core") == ">=0.3,<0.4"


def test_a_sibling_named_only_in_keywords_is_not_read_as_a_dependency():
    # `keywords` legitimately lists "provenance"; reading it as an unpinned dependency would
    # report a problem that is not one, and teach the reader to ignore this check.
    assert "provenance-core" not in versions.cross_refs(
        '[project]\nname = "x"\nversion = "0.3.0"\nkeywords = [ "provenance-core" ]\n'
    )


def test_every_manifest_in_this_workspace_declares_the_same_sibling_series():
    # The end-to-end invariant the wheels enforce: four packages pinning one series and a
    # fifth pinning the previous one is an unsatisfiable install, not a lint nit.
    series = {}
    for name, path in versions.PACKAGES.items():
        for dep, spec in versions.cross_refs(path.read_text()).items():
            if dep != name:
                series.setdefault(spec, []).append(f"{name} -> {dep}")
    assert len(series) <= 1, f"sibling ranges disagree: {series}"


def test_the_citation_record_carries_the_release_version():
    """`CITATION.cff` sat at 0.2.0 while the distributions were at 0.4.0 -- three releases.
    Nothing owned it, so nothing could say it was stale, and it is the file a reader cites
    from. Surfaced by an anonymized artifact drop rather than by any check here."""
    import re

    cff = (ROOT / "CITATION.cff").read_text()
    cited = re.search(r'^version:\s*"([^"]+)"', cff, re.M).group(1)
    packaged = re.search(
        r'^version = "([^"]+)"',
        (ROOT / "packages" / "citations" / "pyproject.toml").read_text(),
        re.M,
    ).group(1)
    assert cited == packaged


def test_versions_check_reports_a_stale_citation_record(tmp_path, monkeypatch):
    """The check has to fail on the defect, not merely pass on a repaired tree."""
    cff = tmp_path / "CITATION.cff"
    cff.write_text('version: "0.1.0"\ndate-released: "2020-01-01"\n')
    monkeypatch.setattr(versions, "CITATION", cff)
    assert any("CITATION.cff" in problem for problem in versions.check())

    cff.write_text(f'version: "{versions.declared()["citations"]}"\ndate-released: "2020-01-01"\n')
    assert not any("CITATION.cff" in problem for problem in versions.check())


def test_a_bump_writes_the_citation_version_and_the_date(tmp_path, monkeypatch):
    import datetime

    cff = tmp_path / "CITATION.cff"
    cff.write_text('title: "x"\nversion: "0.1.0"\ndate-released: "2020-01-01"\n')
    monkeypatch.setattr(versions, "CITATION", cff)
    monkeypatch.setattr(versions, "PACKAGES", {})
    monkeypatch.setattr(versions, "PLUGIN_MANIFESTS", ())
    monkeypatch.setattr(versions, "HOOKS", tmp_path / "absent.yaml")

    # Every path `bump` writes has to be redirected, and the list grew after this test was
    # written: adding HOOKS as a target left this test writing 9.9.9 into the repository's own
    # `.pre-commit-hooks.yaml`, which the next commit then carried. Reading the real files back
    # is what turns the next such omission into a failure here rather than into a commit.
    untouched = {
        p: p.read_bytes() for p in (ROOT / ".pre-commit-hooks.yaml", ROOT / "CITATION.cff")
    }

    versions.bump("9.9.9", realign=True)

    for path, before in untouched.items():
        assert path.read_bytes() == before, f"bump wrote to {path.name} outside the test"
    written = cff.read_text()
    assert 'version: "9.9.9"' in written
    assert datetime.date.today().isoformat() in written
    assert 'title: "x"' in written, "a bump must not disturb the rest of the record"


def test_the_published_hook_snippet_pins_the_current_release():
    """`.pre-commit-hooks.yaml` shows people a `rev:` to copy. It read `repro-v0.3.0` against a
    0.4.0 release, so following the documentation pinned a version behind."""
    import re

    snippet = (ROOT / ".pre-commit-hooks.yaml").read_text()
    pinned = re.search(r"^#\s+rev:\s*v(\S+)", snippet, re.M).group(1)
    packaged = re.search(
        r'^version = "([^"]+)"',
        (ROOT / "packages" / "citations" / "pyproject.toml").read_text(),
        re.M,
    ).group(1)
    assert pinned == packaged


def test_versions_check_reports_a_stale_hook_snippet(tmp_path, monkeypatch):
    hooks = tmp_path / ".pre-commit-hooks.yaml"
    hooks.write_text("#       rev: v0.0.1\n- id: repro-verify\n")
    monkeypatch.setattr(versions, "HOOKS", hooks)
    assert any(".pre-commit-hooks.yaml" in problem for problem in versions.check())

    hooks.write_text(f"#       rev: v{versions.declared()['citations']}\n- id: repro-verify\n")
    assert not any(".pre-commit-hooks.yaml" in problem for problem in versions.check())


def test_this_repository_declares_and_verifies_its_own_claims():
    """The hook is published for other repositories and was never run against this one, which
    left the verifier as the only project here whose claims nothing checked."""
    import yaml

    manifest = ROOT / "repro.yaml"
    assert manifest.is_file(), "the verifier declares no claims of its own"
    declared = yaml.safe_load(manifest.read_text())
    assert declared["claims"], "a manifest with no claims verifies nothing"

    config = (ROOT / ".pre-commit-config.yaml").read_text()
    assert "repro verify" in config, "the manifest exists but no hook runs it"
