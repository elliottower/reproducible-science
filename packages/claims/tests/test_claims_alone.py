"""`claims` imports nothing of `repro`, `results` or `prereg`, and its command names itself.

`claims-cli` installs without `reproducible-science`. A fresh interpreter that imports every
module of this package must therefore hold no module of the wrapper, of the ledger or of the
plan, and a message that tells the user what to type must name a command they have.
"""

from __future__ import annotations

import json
import multiprocessing.spawn
import pkgutil
import subprocess

import claims
import pytest
from claims.cli import CLAIMS, REPRO, _reproduce, main

#: Every module, but `claims.__main__`, which runs the command when it is imported.
MODULES = sorted(
    name
    for _, name, _ in pkgutil.walk_packages(claims.__path__, prefix="claims.")
    if name != "claims.__main__"
)

#: Top-level packages a claims-only installation does not have.
NOT_INSTALLED_ALONE = ("repro", "results", "prereg")


def loaded_after(*modules: str) -> set[str]:
    """Every module a fresh interpreter holds after importing these."""
    program = (
        f"import {', '.join(modules)}\nimport json, sys\nprint(json.dumps(sorted(sys.modules)))\n"
    )
    # The interpreter running the tests, which is the one that has the package installed.
    python = multiprocessing.spawn.get_executable()
    done = subprocess.run([python, "-c", program], capture_output=True, text=True, check=True)
    return set(json.loads(done.stdout))


def test_importing_every_module_of_claims_loads_nothing_it_does_not_install():
    assert len(MODULES) > 40
    loaded = loaded_after("claims", *MODULES)
    assert set(MODULES) <= loaded
    foreign = sorted(name for name in loaded if name.split(".")[0] in NOT_INSTALLED_ALONE)
    assert foreign == []


def test_the_check_can_fail():
    """The same reading finds a package it was asked to load, so an empty list above is a
    finding and not a reading that cannot see. `citations` is installed wherever this is."""
    loaded = loaded_after("citations.verify")
    assert "citations.verify" in loaded
    assert sorted(name for name in loaded if name.split(".")[0] == "citations")


def project(root, claims_declared=True):
    (root / "results.json").write_text(json.dumps({"n": 6}))
    evidence = "{kind: metric, artifact: results, name: n, reported: '6', pointer: /n}"
    body = "artifacts:\n  - {id: results, path: results.json}\n"
    if claims_declared:
        body += f"claims:\n  - id: c\n    text: Six.\n    evidence:\n      - {evidence}\n"
    (root / "repro.yaml").write_text(body)
    return root / "repro.yaml"


@pytest.mark.parametrize("command", ["verify", "stale", "why", "numbers", "export"])
def test_with_no_manifest_the_command_to_write_one_is_claims_own(
    tmp_path, monkeypatch, capsys, command
):
    monkeypatch.chdir(tmp_path)
    argv = [command, "record"] if command == "export" else [command]
    assert main(argv) == 2
    out = capsys.readouterr().out
    assert "    claims manifest init\n" in out
    assert "repro manifest init" not in out
    assert "no repro.yaml here or above." in out


def test_manifest_init_says_what_to_run_next_under_its_own_name(tmp_path, monkeypatch, capsys):
    (tmp_path / "results").mkdir()
    (tmp_path / "results" / "metrics.json").write_text(json.dumps({"n": 6}))
    monkeypatch.chdir(tmp_path)
    assert main(["manifest", "init"]) == 0
    out = capsys.readouterr().out
    assert out.rstrip().endswith("next: claims verify")
    assert "      claims manifest init <file> ..." in out
    assert "repro verify" not in out and "repro manifest" not in out
    assert main(["verify", "--policy", "exploratory"]) == 0


def test_the_command_that_reruns_is_named_with_the_distribution_that_has_it():
    assert _reproduce(REPRO) == "`repro reproduce`"
    assert _reproduce(CLAIMS) == (
        "`repro reproduce` (from the `reproducible-science` distribution)"
    )


def test_the_command_checks_a_manifest_and_prints_what_repro_prints(tmp_path, capsys):
    path = project(tmp_path)
    assert main(["verify", str(path), "--policy", "exploratory"]) == 0
    out = capsys.readouterr().out
    assert "  ok    c            metric   /n = 6" in out
    assert main(["why", "c", str(path)]) == 0
    assert "    the manuscript prints 6: verified\n" in capsys.readouterr().out
    assert main(["why", str(path)]) == 0
    assert capsys.readouterr().out == "c\n"


def test_the_help_names_claims_for_its_own_commands_and_repro_for_the_rest(capsys):
    for command in ("why", "export", "stale"):
        with pytest.raises(SystemExit):
            main([command, "--help"] if command != "export" else ["export", "--help"])
    shown = " ".join(capsys.readouterr().out.split())
    assert "as `claims verify` evaluates it now" in shown
    assert "`claims verify` is the check that fails" in shown
    assert "`repro verify`" not in shown and "`repro stale`" not in shown
    assert "`repro reproduce` (from the `reproducible-science` distribution) recorded in" in shown

    with pytest.raises(SystemExit):
        main(["--version"])
    assert capsys.readouterr().out == f"claims {claims.__version__}\n"

    assert main([]) == 1
    listed = capsys.readouterr().out
    assert "{manifest,verify,stale,why,numbers,export,origins,from-clew,open-items}" in listed
    for absent in ("reproduce", "check", "audit", "demo"):
        assert f"\n    {absent} " not in listed


def git(root, *args):
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def test_a_broken_record_of_checks_is_kept_by_claims_own_command(tmp_path, monkeypatch, capfd):
    path = project(tmp_path)
    git(tmp_path, "init", "-q")
    monkeypatch.chdir(tmp_path)
    assert main(["verify", str(path), "--policy", "exploratory"]) == 0
    record = tmp_path / ".git" / "repro" / "checks.jsonl"
    record.write_text(record.read_text().replace('"seq":0', '"seq":7'))
    (tmp_path / "results.json").write_text(json.dumps({"n": 7}))
    main(["verify", str(path), "--policy", "exploratory"])
    err = capfd.readouterr().err
    assert "record not written:" in err
    assert "`claims verify --set-aside-record` keeps it and starts anew" in err
    assert "repro verify" not in err


def test_the_sarif_export_s_help_names_claims_own_command(tmp_path, capsys):
    path = project(tmp_path)
    (tmp_path / "results.json").write_text(json.dumps({"n": 7}))
    assert main(["export", "sarif", str(path)]) == 0
    rules = json.loads(capsys.readouterr().out)["runs"][0]["tool"]["driver"]["rules"]
    helps = [rule["help"]["text"] for rule in rules]
    assert any("`claims why <claim>` prints the stored value" in text for text in helps)
    assert not any("repro why" in text for text in helps)


def test_the_starter_claims_writes_names_claims_where_it_names_a_command(tmp_path, monkeypatch):
    (tmp_path / "results").mkdir()
    (tmp_path / "results" / "metrics.json").write_text(json.dumps({"n": 6}))
    monkeypatch.chdir(tmp_path)
    assert main(["manifest", "init"]) == 0
    text = (tmp_path / "repro.yaml").read_text()
    assert "read by `claims verify`." in text
    assert "were written by `claims manifest init` to show" in text
    assert "#     claims verify\n" in text
    assert "repro verify" not in text and "repro manifest init" not in text
