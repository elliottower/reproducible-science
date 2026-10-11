"""A command that reads no source does not load the libraries that read one.

Checking a quotation needs the PDF and spreadsheet readers, and they take most of a second to
import. `citations lint` reads no source, and `prereg freeze` runs it on every freeze. So the
package imports a public name when it is asked for, and the command starts in `entry`, which
loads the subcommand asked for and nothing else. Every name the package exported still resolves.
"""

from __future__ import annotations

import ast
import contextlib
import importlib
import io
import json
import os
import pathlib
import re
import shutil
import subprocess
import sysconfig

import citations
import pytest
from citations import cli, entry

#: What only reading a source needs. A module of ours is named as Python imports it.
HEAVY = {
    "pdfplumber",
    "pypdf",
    "openpyxl",
    "xlrd",
    "docx",
    "citations.verify",
    "citations.readers",
    "citations.extractors",
    "citations.cli",
}


IMPORTED = re.compile(r"^import '([^']+)' # ", re.M)


def imported(tmp_path: pathlib.Path, program: str, *argv: str) -> tuple[int, str, set[str]]:
    """Run an installed program with `argv`: its exit code, its stdout, and every module the
    interpreter imported.

    Read from what the import system says of itself under `PYTHONVERBOSE`. `-X importtime` is
    not enough: it times the `import` statement, and a module loaded by
    `importlib.import_module` never passes through one.
    """
    found = shutil.which(program, path=sysconfig.get_path("scripts"))
    assert found, f"the workspace installs {program}"
    done = subprocess.run(
        [found, *argv],
        cwd=tmp_path,
        env={**os.environ, "PYTHONVERBOSE": "1", "CITATIONS_HOME": str(tmp_path)},
        capture_output=True,
        text=True,
        check=False,
    )
    return done.returncode, done.stdout, set(IMPORTED.findall(done.stderr))


@pytest.fixture
def claims(tmp_path):
    folder = tmp_path / "claims"
    folder.mkdir()
    (tmp_path / "source.txt").write_text("the measured angle matches the expectation\n")
    (folder / "angle.yaml").write_text(
        json.dumps(
            {
                "source": {"citation": "x", "local": "source.txt"},
                "claims": {"c1": {"quotes": [{"exact": "matches the expectation"}]}},
            }
        )
    )
    return folder


def test_lint_loads_none_of_what_reads_a_source(claims, tmp_path):
    code, out, modules = imported(tmp_path, "citations", "lint", "--claims", str(claims), "--json")
    assert code == 0
    assert json.loads(out) == {"sources": 1, "tracked": []}
    assert "citations.lint" in modules, "the control: the listing names what was imported"
    assert modules & HEAVY == set()


def test_verify_loads_the_checker_so_the_listing_can_tell(claims, tmp_path):
    code, out, modules = imported(tmp_path, "citations", "verify", "--claims", str(claims))
    assert code == 0
    assert "all found." in out
    assert {"citations.verify", "citations.readers", "citations.extractors"} <= modules


def test_importing_the_package_loads_no_module_of_it_that_reads_a_source(tmp_path):
    code, out, modules = imported(
        tmp_path, "python", "-c", "import citations; print(citations.__version__)"
    )
    assert (code, out.strip()) == (0, citations.__version__)
    assert "citations" in modules
    assert modules & HEAVY == set()


def checked_by_a_type_checker() -> dict[str, tuple[str, ...]]:
    """The imports under `if TYPE_CHECKING:` in the package, as module to names."""
    tree = ast.parse(pathlib.Path(citations.__file__).read_text())
    block = next(
        node
        for node in tree.body
        if isinstance(node, ast.If) and ast.unparse(node.test) == "TYPE_CHECKING"
    )
    return {
        node.module: tuple(sorted(alias.name for alias in node.names))
        for node in block.body
        if isinstance(node, ast.ImportFrom) and node.module
    }


def test_the_names_exported_the_names_a_type_checker_reads_and_where_each_lives_are_one_set():
    defined = {m: tuple(sorted(names)) for m, names in citations._DEFINED_IN.items()}
    assert defined == checked_by_a_type_checker()
    names = [name for group in defined.values() for name in group]
    assert sorted([*names, "__version__"]) == sorted(citations.__all__)
    assert len(names) == len(set(names)) == 45


@pytest.mark.parametrize("name", [n for n in citations.__all__ if n != "__version__"])
def test_each_public_name_is_the_object_its_module_defines(name):
    module = next(m for m, names in citations._DEFINED_IN.items() if name in names)
    defined = getattr(importlib.import_module(module), name)
    assert getattr(citations, name) is defined
    assert vars(citations)[name] is defined, "kept after the first lookup"


def test_a_star_import_and_dir_carry_every_public_name():
    namespace: dict = {}
    exec("from citations import *", namespace)
    assert set(citations.__all__) <= set(namespace)
    assert set(citations.__all__) <= set(dir(citations))


@pytest.mark.parametrize("name", sorted(citations._SUBMODULES))
def test_a_module_the_package_used_to_import_is_still_an_attribute_of_it(name):
    assert getattr(citations, name).__name__ == f"citations.{name}"


def test_a_name_the_package_does_not_have_is_an_attribute_error():
    with pytest.raises(AttributeError, match="no attribute 'no_such_name'"):
        _ = citations.no_such_name  # type: ignore[attr-defined]
    with pytest.raises(ImportError):
        exec("from citations import no_such_name", {})


def said(main, argv: list[str]) -> tuple[int, str]:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        try:
            code = main(argv)
        except SystemExit as e:
            code = e.code
    return code, out.getvalue()


@pytest.mark.parametrize(
    "argv",
    [
        ["lint", "--claims", "claims", "--json"],
        ["lint", "--claims", "nowhere"],
        ["lint", "--help"],
        ["projects"],
        ["tags", "--no-such-flag"],
        ["verify", "--claims", "claims"],
        ["verify", "--claims", "claims", "--strict"],
        ["coverage", "nowhere.tex"],
        ["no-such-command"],
        ["--help"],
        [],
    ],
)
def test_the_command_started_in_entry_answers_as_the_one_started_in_cli(
    claims, tmp_path, monkeypatch, argv
):
    monkeypatch.chdir(tmp_path)
    # A library that is not there, so `projects` is refused the same way on every machine.
    monkeypatch.setenv("CITATIONS_HOME", str(tmp_path / "no-library"))
    assert said(entry.main, argv) == said(cli.main, argv)


def test_the_installed_command_starts_in_entry():
    program = shutil.which("citations", path=sysconfig.get_path("scripts"))
    assert program
    assert "citations.entry" in pathlib.Path(program).read_text()
    assert cli.DELEGATED is entry.DELEGATED
    assert set(entry.DELEGATED) == {
        "init",
        "audit",
        "resolve",
        "build",
        "lint",
        "add",
        "pin",
        "restore",
        "projects",
        "tags",
        "link",
        "fetch",
        "import-paperclip",
    }
