"""Every name `repro` had before the checking code moved to `claims` is still the same object.

The modules that check a manifest are the `claims` package now, and each `repro.<module>` that
moved is a module of the same name that hands back that package's attributes. Code written
against `from repro import load, verify`, `from repro.models import Claim` or
`repro.verify._agree` must go on getting the one object there is, or two copies of a model
would stop comparing equal and an `except` would stop catching.
"""

from __future__ import annotations

import importlib
import pathlib
import pkgutil
import types

import claims
import pytest
import repro

#: Each module of `claims`, by its dotted name below the package. `cli` had another name here.
MOVED = sorted(
    name.removeprefix("claims.")
    for _, name, _ in pkgutil.walk_packages(claims.__path__, prefix="claims.")
    # `__main__` runs the command when imported, and each package has its own.
    if name != "claims.__main__"
)

#: What `repro` itself exported before, from its `__all__` as it stood.
EXPORTED = sorted(set(repro.__all__) - {"__version__"})


def old_name(module: str) -> str:
    return "repro.cli_claims" if module == "cli" else f"repro.{module}"


def test_every_module_of_claims_has_a_module_of_its_name_in_repro():
    assert len(MOVED) > 40
    for module in MOVED:
        importlib.import_module(old_name(module))


@pytest.mark.parametrize("module", MOVED)
def test_every_name_of_a_moved_module_is_the_object_claims_holds(module):
    home = importlib.import_module(f"claims.{module}")
    here = importlib.import_module(old_name(module))
    # A submodule of a package is the module of that name in `repro`, which is checked as a
    # module of its own; every other attribute is one object.
    names = [
        name
        for name, value in vars(home).items()
        if not name.startswith("__") and not isinstance(value, types.ModuleType)
    ]
    # A package that only holds modules has no names of its own.
    assert names or module in ("adapters", "core")
    for name in names:
        assert getattr(here, name) is getattr(home, name), name
    # Private names as well, which a star import leaves out.
    private = [name for name in names if name.startswith("_")]
    for name in private:
        assert getattr(here, name) is getattr(home, name), name
    assert set(names) <= set(dir(here))


@pytest.mark.parametrize("name", EXPORTED)
def test_every_name_repro_exported_is_the_one_claims_exports(name):
    assert getattr(repro, name) is getattr(claims, name)


def test_the_two_functions_that_share_a_name_with_a_module_stay_functions():
    """`import repro.verify` binds the module on the package. `repro.verify` has always been
    the function all the same, and still is after the submodule has been imported."""
    importlib.import_module("repro.verify")
    importlib.import_module("repro.resolve")
    assert callable(repro.verify) and repro.verify is claims.verify
    assert callable(repro.resolve) and repro.resolve is claims.resolve
    from repro import load, verify

    assert verify is claims.verify and load is claims.load


def test_the_names_the_paper_s_scripts_import_resolve(tmp_path):
    """The imports a repository that uses this package was found to make, every one."""
    from repro import load, verify
    from repro.corpus import Corpus, CorpusEntry, FindingState, Regression, Revision, ensure
    from repro.models import Claim, Manifest, MetricEvidence, Outcome
    from repro.policy import PUBLICATION
    from repro.provenance import of_tree
    from repro.regenerate import canonical_digest
    from repro.regression import _manifest_against, run
    from repro.renderers import to_sarif

    (tmp_path / "r.json").write_text('{"x": 1}')
    manifest = Manifest(
        path=tmp_path / "repro.yaml",
        artifacts=(claims.ArtifactRef(id="r", path=tmp_path / "r.json"),),
        claims=(
            Claim(
                id="c",
                text="t",
                evidence=(MetricEvidence(artifact="r", name="x", reported="1", pointer="/x"),),
            ),
        ),
    )
    manifest.path.write_text(manifest.model_dump_json())
    report = verify(load(manifest.path))
    assert report.decisions[0].outcome is Outcome.VERIFIED
    assert to_sarif(report, PUBLICATION.assess(report), version="0")["version"] == "2.1.0"

    corpus = importlib.import_module("claims.corpus")
    assert (Corpus, CorpusEntry, FindingState, Regression, Revision, ensure) == (
        corpus.Corpus,
        corpus.CorpusEntry,
        corpus.FindingState,
        corpus.Regression,
        corpus.Revision,
        corpus.ensure,
    )
    regression = importlib.import_module("claims.regression")
    assert (run, _manifest_against) == (regression.run, regression._manifest_against)
    assert of_tree is importlib.import_module("claims.provenance").of_tree
    assert canonical_digest is importlib.import_module("claims.reruns").canonical_digest
    assert repro.Digest is claims.Digest


def test_an_error_raised_by_claims_is_caught_under_the_name_repro_has_for_it(tmp_path):
    from repro.exceptions import ManifestError

    (tmp_path / "repro.yaml").write_text("claims: 3\n")
    with pytest.raises(ManifestError):
        claims.load(tmp_path / "repro.yaml")
    assert repro.ReproError is claims.exceptions.ReproError


def test_the_version_and_the_named_distribution_are_the_wrapper_s():
    metadata = importlib.import_module("importlib.metadata")
    assert repro.__version__ == metadata.version("reproducible-science")
    assert claims.__version__ == repro.__version__
    assert importlib.import_module("claims.verify").ADAPTER_DISTRIBUTION == "reproducible-science"


def test_the_shims_hold_no_code_of_their_own():
    source = pathlib.Path(repro.__file__).parent
    for module in MOVED:
        name = old_name(module).removeprefix("repro.").replace(".", "/")
        path = source / f"{name}.py"
        if not path.is_file():
            path = source / name / "__init__.py"
        text = path.read_text()
        assert f'importlib.import_module("claims.{module}")' in text, path
        assert len(text.splitlines()) < 25, path


#: Every name defined or imported at the top of `repro/cli.py` on `main` before the package
#: moved, read off that file. `ci.py`, the tests and anything that imported from it reach
#: these.
CLI_NAMES = (
    "Assessment",
    "BY_NAME",
    "CHECKS",
    "CLAUDE_MD",
    "CONVENTIONAL",
    "DEFAULT_NAME",
    "EXPORTS",
    "IGNORE_RULES",
    "LOCAL_CHECKS",
    "MAX_DISCOVERED",
    "METADATA_FILE",
    "PROFILES",
    "Path",
    "Policy",
    "RECORD",
    "Reading",
    "Regeneration",
    "ReproError",
    "ReproductionReport",
    "SET_ASIDE",
    "SHOWN",
    "SOURCES_DIR",
    "SYMBOL",
    "TOOLS",
    "__version__",
    "_assertion_lines",
    "_chain_lines",
    "_checked_said",
    "_count_said",
    "_finding_said",
    "_history_lines",
    "_ignore",
    "_init_here",
    "_named",
    "_numbers_lines",
    "_plan",
    "_record_lines",
    "_reproduce_text",
    "_run",
    "_said",
    "_shown",
    "_stale_lines",
    "_stale_summary",
    "_stale_text",
    "_steps",
    "_verify_text",
    "_why_lines",
    "append_reproduction",
    "argparse",
    "atomic_write",
    "audit",
    "badges",
    "ci",
    "cmd_check",
    "cmd_demo",
    "cmd_export",
    "cmd_init",
    "cmd_manifest_init",
    "cmd_numbers",
    "cmd_reproduce",
    "cmd_stale",
    "cmd_verify",
    "cmd_why",
    "crosscheck",
    "delegate_check",
    "delegate_run",
    "demo",
    "find",
    "functools",
    "importlib",
    "json",
    "load",
    "main",
    "pathlib",
    "project_root",
    "run_reproduce",
    "subprocess",
    "try_run",
    "write_starter",
)


@pytest.mark.parametrize("name", CLI_NAMES)
def test_every_name_repro_cli_had_it_still_has(name):
    cli = importlib.import_module("repro.cli")
    assert hasattr(cli, name), name


def test_the_names_repro_cli_shares_with_claims_cli_are_one_object():
    cli = importlib.import_module("repro.cli")
    claims_cli = importlib.import_module("claims.cli")
    # `main` is each command's own: `repro`'s and `claims`'s build different parsers.
    shared = [
        n for n in CLI_NAMES if hasattr(claims_cli, n) and not n.startswith("__") and n != "main"
    ]
    assert len(shared) > 20
    for name in shared:
        if isinstance(getattr(cli, name), types.ModuleType):
            continue
        assert getattr(cli, name) is getattr(claims_cli, name), name
