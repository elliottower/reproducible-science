"""The claims side is importable without the side that runs commands.

The claims side checks what a manifest declares and reads the record of re-runs. The wrapper
side runs commands, writes that record and drives the other tools. An import-linter contract
forbids the first from importing the second; this starts a fresh interpreter and looks at what
was loaded, which is what a distribution holding only the claims side would have to survive.
"""

from __future__ import annotations

import json
import multiprocessing.spawn
import subprocess

import pytest

#: Modules of the claims side that a reader of a manifest and of a record imports.
CLAIMS = (
    "repro.verify",
    "repro.stale",
    "repro.why",
    "repro.numbers",
    "repro.checks",
    "repro.record",
    "repro.export",
    "repro.renderers",
    "repro.policy",
    "repro.manifest",
    "repro.reruns",
    "repro.starter",
    "repro.corpus",
    "repro.regression",
    "repro.provenance",
    "repro.cli_claims",
)

#: Modules that run a command, write the record of re-runs, or drive another tool.
WRAPPER = (
    "repro.reproduce",
    "repro.regenerate",
    "repro.ci",
    "repro.audit",
    "repro.delegate",
    "repro.demo",
    "repro.crosscheck",
    "repro.cli",
)


def loaded_after(*modules: str) -> set[str]:
    """Every module a fresh interpreter holds after importing these."""
    program = (
        f"import {', '.join(modules)}\nimport json, sys\nprint(json.dumps(sorted(sys.modules)))\n"
    )
    # The interpreter running the tests, which is the one that has the package installed.
    python = multiprocessing.spawn.get_executable()
    done = subprocess.run([python, "-c", program], capture_output=True, text=True, check=True)
    return set(json.loads(done.stdout))


def test_importing_the_claims_side_loads_nothing_of_the_wrapper_side():
    loaded = loaded_after(*CLAIMS)
    assert set(CLAIMS) <= loaded
    assert sorted(loaded & set(WRAPPER)) == []
    assert "results" not in loaded and not any(name.startswith("results.") for name in loaded)


@pytest.mark.parametrize("module", CLAIMS)
def test_each_claims_side_module_alone_loads_nothing_of_the_wrapper_side(module):
    assert sorted(loaded_after(module) & set(WRAPPER)) == []


def test_the_check_can_fail():
    assert "repro.reproduce" in loaded_after("repro.reproduce")
    assert {"repro.ci", "repro.reproduce", "repro.delegate"} <= loaded_after("repro.cli")


def test_the_names_that_moved_are_still_where_they_were():
    # `repro.resolve` the attribute is the function the package exports, so the modules are
    # taken by name.
    program = (
        "from importlib import import_module as m\n"
        "old, new = m('repro.reproduce'), m('repro.reruns')\n"
        "print(old.RECORD is new.RECORD,\n"
        "      old.stored is m('repro.resolve').stored,\n"
        "      m('repro.stale').reruns is new.reruns,\n"
        "      m('repro.stale').RecordUnreadableError is new.RecordUnreadableError,\n"
        "      m('repro.regenerate').canonical_digest is new.canonical_digest,\n"
        "      m('repro.regenerate').upstream is new.upstream,\n"
        "      old.RECORD.as_posix())\n"
    )
    python = multiprocessing.spawn.get_executable()
    done = subprocess.run([python, "-c", program], capture_output=True, text=True, check=True)
    assert done.stdout.split() == ["True"] * 6 + [".repro/reproductions.jsonl"]
