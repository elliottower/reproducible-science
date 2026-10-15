"""`repro ui` reaches the page's own distribution by name, and says how to install it."""

from __future__ import annotations

import importlib

from repro import cli


def test_without_the_page_installed_repro_ui_prints_the_install_line(monkeypatch, capsys):
    real = importlib.import_module

    def missing(name, *args, **kwargs):
        if name.startswith("repro_ui"):
            raise ModuleNotFoundError(f"No module named {name!r}", name="repro_ui")
        return real(name, *args, **kwargs)

    monkeypatch.setattr(importlib, "import_module", missing)
    assert cli.main(["ui"]) == 2
    assert 'pip install "reproducible-science[ui]"' in capsys.readouterr().out


def test_repro_ui_passes_its_arguments_to_the_page_untouched(monkeypatch):
    seen = []

    class Server:
        @staticmethod
        def main(argv):
            seen.append(argv)
            return 0

    real = importlib.import_module
    monkeypatch.setattr(
        importlib,
        "import_module",
        lambda name, *a, **k: Server if name == "repro_ui.server" else real(name, *a, **k),
    )
    assert cli.main(["ui", "some/project", "--port", "5191", "--offline"]) == 0
    assert seen == [["some/project", "--port", "5191", "--offline"]]
