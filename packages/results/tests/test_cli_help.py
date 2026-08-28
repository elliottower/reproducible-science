"""The command list a reader sees must be the one the parser has."""

from __future__ import annotations

import pytest


def test_the_docstring_names_exactly_the_commands_the_parser_offers(capsys):
    """`results bib` was documented for months and was never a command, while `pin` and
    `projects` were commands nobody had written down. The docstring is the first thing a
    reader of this module sees, and nothing compared it to the parser."""
    import re

    from results import cli

    with pytest.raises(SystemExit):
        cli.main(["--help"])
    offered = set(re.search(r"\{([a-z0-9,\-]+)\}", capsys.readouterr().out).group(1).split(","))

    documented = set()
    for line in (cli.__doc__ or "").splitlines():
        m = re.match(r"\s*results\s+([a-z][a-z0-9-]*)(?=\s)", line)
        if m and "  " in line[m.end() :]:  # the description column, not prose
            documented.add(m.group(1))

    assert documented == offered, (
        f"documented but absent: {sorted(documented - offered)}; "
        f"present but undocumented: {sorted(offered - documented)}"
    )
