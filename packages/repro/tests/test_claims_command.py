"""`claims <command>` and `repro <command>` are one function, and differ only where a message
names a command.

The same handlers answer to both names. Under `repro` every message is what it was. Under
`claims` a message names `claims` for a command that package holds and says who provides
`repro reproduce`. What is written for a program to read, the JSON of each command, does not
depend on the name at all.
"""

from __future__ import annotations

import importlib
import json

import pytest
from claims.cli import main as claims_main
from repro import cli as repro_cli
from repro.cli import main as repro_main


def project(root):
    (root / "results.json").write_text(json.dumps({"n": 6, "rate": 0.0425}))
    (root / "paper.txt").write_text("We counted 6 sites, and attrition was 4.3% of them.\n")
    (root / "make.py").write_text("print('made')\n")
    (root / "repro.yaml").write_text(
        "artifacts:\n"
        "  - {id: results, path: results.json}\n"
        "  - {id: paper, path: paper.txt}\n"
        "  - {id: make, path: make.py}\n"
        "claims:\n"
        "  - id: sites\n"
        "    text: We counted 6 sites\n"
        "    evidence:\n"
        "      - {kind: quote, artifact: paper, text: We counted 6 sites}\n"
        "      - {kind: metric, artifact: results, name: n, reported: '6', pointer: /n}\n"
        "  - id: attrition\n"
        "    text: attrition was 4.3% of them\n"
        "    evidence:\n"
        "      - {kind: metric, artifact: results, name: rate, reported: '4.3', pointer: /rate,"
        " conversion: percent}\n"
        "      - {kind: metric, artifact: results, name: gone, reported: '1', pointer: /gone}\n"
        "regenerations:\n"
        "  - id: build\n"
        "    command: [python, make.py]\n"
        "    inputs: [make]\n"
        "    output: results\n"
    )
    return str(root / "repro.yaml")


COMMANDS = [
    ["verify"],
    ["verify", "--policy", "strict"],
    ["stale"],
    ["why", "sites"],
    ["why", "attrition"],
    ["numbers"],
]


def run(main, argv, capsys):
    code = main(argv)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


@pytest.mark.parametrize("command", COMMANDS, ids=" ".join)
def test_the_json_of_a_command_is_the_same_under_either_name(tmp_path, capsys, command):
    path = project(tmp_path)
    head, *options = command
    argv = [*command[:2], path, *command[2:]] if head == "why" else [head, path, *options]
    under_repro = run(repro_main, [*argv, "--format", "json"], capsys)
    under_claims = run(claims_main, [*argv, "--format", "json"], capsys)
    assert under_claims == under_repro
    json.loads(under_repro[1])


@pytest.mark.parametrize("target", ["record", "sarif", "ro-crate"])
def test_an_export_is_the_same_under_either_name(tmp_path, capsys, target):
    path = project(tmp_path)
    under_repro = run(repro_main, ["export", target, path], capsys)
    under_claims = run(claims_main, ["export", target, path], capsys)
    assert under_repro[0] == under_claims[0] == 0
    # A record carries when it was checked, to the second; everything else is one document.
    assert len(under_repro[1]) == len(under_claims[1])


@pytest.mark.parametrize("command", [c for c in COMMANDS if c[0] != "stale"], ids=" ".join)
def test_the_text_of_a_command_that_names_no_command_is_the_same(tmp_path, capsys, command):
    path = project(tmp_path)
    head, *options = command
    argv = [*command[:2], path, *command[2:]] if head == "why" else [head, path, *options]
    assert run(claims_main, argv, capsys) == run(repro_main, argv, capsys)


def test_stale_differs_only_in_how_it_names_the_command_that_reruns(tmp_path, capsys):
    path = project(tmp_path)
    code, under_repro, _ = run(repro_main, ["stale", path], capsys)
    again, under_claims, _ = run(claims_main, ["stale", path], capsys)
    assert code == again
    line = "  .repro/reproductions.jsonl holds no re-run; `repro reproduce` records one.\n"
    assert line in under_repro
    assert under_claims == under_repro.replace(
        "`repro reproduce` records one",
        "`repro reproduce` (from the `reproducible-science` distribution) records one",
    )


@pytest.mark.parametrize("command", ["verify", "stale", "why", "numbers", "export"])
def test_with_no_manifest_each_name_tells_the_user_its_own_command(
    tmp_path, monkeypatch, capsys, command
):
    monkeypatch.chdir(tmp_path)
    argv = [command, "record"] if command == "export" else [command]
    code, under_repro, _ = run(repro_main, argv, capsys)
    again, under_claims, _ = run(claims_main, argv, capsys)
    assert code == again == 2
    assert under_repro == (
        "no repro.yaml here or above.\n\n"
        "write one that pins this project's result files, with example claims to edit:\n\n"
        "    repro manifest init\n"
    )
    assert under_claims == under_repro.replace("repro manifest init", "claims manifest init")


def test_manifest_init_differs_only_in_the_commands_it_names(tmp_path, monkeypatch, capsys):
    outputs = {}
    for name, main in (("repro", repro_main), ("claims", claims_main)):
        root = tmp_path / name / "project"
        (root / "results").mkdir(parents=True)
        (root / "results" / "metrics.json").write_text(json.dumps({"n": 6}))
        monkeypatch.chdir(root)
        assert main(["manifest", "init"]) == 0
        outputs[name] = capsys.readouterr().out.replace(f"/{name}/project", "/P")
    assert "next: repro verify" in outputs["repro"]
    assert "      repro manifest init <file> ..." in outputs["repro"]
    assert outputs["claims"] == outputs["repro"].replace(
        "repro manifest init", "claims manifest init"
    ).replace("next: repro verify", "next: claims verify")
    # The same file, but for the three comment lines that name a command.
    written = {name: (tmp_path / name / "project" / "repro.yaml").read_text() for name in outputs}
    assert "read by `repro verify`." in written["repro"]
    assert "#     repro verify\n" in written["repro"]
    assert written["claims"] == (
        written["repro"]
        .replace("read by `repro verify`.", "read by `claims verify`.")
        .replace("written by `repro manifest init`", "written by `claims manifest init`")
        .replace("#     repro verify\n", "#     claims verify\n")
    )
    assert written["claims"] != written["repro"]


def test_the_handlers_are_the_same_functions():
    claims_cli = __import__("claims.cli", fromlist=["cli"])
    for name in (
        "cmd_verify",
        "cmd_stale",
        "cmd_why",
        "cmd_numbers",
        "cmd_export",
        "cmd_manifest_init",
        "_verify_text",
        "_stale_text",
        "SYMBOL",
    ):
        assert getattr(repro_cli, name) is getattr(claims_cli, name), name


def test_the_repro_starter_is_the_file_main_wrote():
    """`repro manifest init` writes the header as it stood, naming `repro`: the three places
    that name a command are the only ones that vary, and under `repro` they read as before."""
    header = importlib.import_module("claims.starter").HEADER
    assert header.count("{program}") == 3
    shown = header.format(project="P", program="repro")
    assert shown.startswith("# The evidence manifest for P, read by `repro verify`.\n")
    assert "were written by `repro manifest init` to show" in shown
    assert "#     repro verify\n#\n" in shown


def test_a_sarif_export_s_help_names_repro_under_repro(tmp_path, capsys):
    path = project(tmp_path)
    (tmp_path / "results.json").write_text(json.dumps({"n": 7, "rate": 0.0425}))
    assert repro_main(["export", "sarif", path]) == 0
    rules = json.loads(capsys.readouterr().out)["runs"][0]["tool"]["driver"]["rules"]
    assert any(
        rule["help"]["text"]
        == (
            "Either the manuscript or the file is out of date. `repro why <claim>` prints the "
            "stored value beside the reported one, and what produced the file."
        )
        for rule in rules
    )
