"""Where the `citations` command starts: it reads which subcommand was asked for, and loads that.

`citations verify` and `citations coverage` read sources, and reading a source needs the PDF
and spreadsheet libraries, which take most of a second to import. Every other subcommand has a
module and a parser of its own and reads no source. Starting all of them in `cli`, which
imports the checker at its top, made `citations lint` and `citations add` pay for libraries
they never call, and `prereg freeze` runs `citations lint` on every freeze.

So this module imports nothing of the checker. A subcommand with its own module is handed its
arguments directly; anything else, including no subcommand and `--help`, goes to `cli` with
the arguments exactly as they came, and `cli` does what it always did.
"""

from __future__ import annotations

import argparse
import importlib

from provenance_core import hint

from citations.exceptions import CitationsError

#: Each subcommand that has a module and a parser of its own, and the module.
DELEGATED = {
    "init": "init",
    "audit": "audit",
    "resolve": "resolve",
    "build": "build",
    "lint": "lint",
    "add": "add",
    "pin": "pin",
    "restore": "restore",
    "projects": "projects",
    "tags": "tags",
    "link": "link_pdfs",
    "fetch": "fetch",
    "import-paperclip": "import_paperclip",
}


def delegate(module: str, argv: list[str]) -> int:
    """Hand the remaining arguments to a subcommand's own parser.

    `argv` is passed, never assigned to `sys.argv`: a function whose behavior depends on a
    global cannot be called twice, tested without monkeypatching, or run from anything that is
    not a terminal.
    """
    return importlib.import_module(f"citations.{module}").main(argv)


def main(argv: list[str] | None = None) -> int:
    first = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    first.add_argument("cmd", nargs="?")
    asked, rest = first.parse_known_args(argv)
    if asked.cmd not in DELEGATED:
        return importlib.import_module("citations.cli").main(argv)
    try:
        code = delegate(DELEGATED[asked.cmd], rest)
    except CitationsError as e:
        print(str(e))
        code = 2
    # After the work, as `cli.main` does it.
    hint.note("citations")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
