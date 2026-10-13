"""`citations verify --json PATH` and `citations fetch --json PATH` write their counts."""

from __future__ import annotations

import hashlib
import json

import pytest
import yaml
from citations import verify as V
from citations.cli import main

TEXT = "The quick brown fox jumps over the lazy dog near the quiet river bank at dawn.\n"
QUOTE = "quick brown fox jumps over the lazy dog"
ABSENT = "a sentence the source does not contain anywhere in its text at all"


@pytest.fixture(autouse=True)
def _alone(monkeypatch):
    monkeypatch.setenv("CITATIONS_NO_CACHE", "1")
    monkeypatch.setenv("REPRO_NO_HINT", "1")
    V.clear_caches()


def pin(root, name, quotes, there=True):
    (root / "sources").mkdir(exist_ok=True)
    (root / "claims").mkdir(exist_ok=True)
    if there:
        (root / "sources" / f"{name}.txt").write_text(TEXT)
    source = {
        "citation": name,
        "local": f"sources/{name}.txt",
        "sha256": hashlib.sha256(TEXT.encode()).hexdigest(),
    }
    claims = {"c1": {"quotes": [{"exact": quote} for quote in quotes]}}
    (root / "claims" / f"{name}.yaml").write_text(
        yaml.safe_dump({"source": source, "claims": claims})
    )


def test_verify_writes_each_outcome_and_the_outcomes_add_up_to_the_quotations(tmp_path, capsys):
    pin(tmp_path, "here", [QUOTE, ABSENT])
    pin(tmp_path, "gone", [QUOTE, QUOTE, QUOTE], there=False)
    wrote = tmp_path / "counts.json"
    code = main(["verify", "--claims", str(tmp_path / "claims"), "--json", str(wrote)])
    account = json.loads(wrote.read_text())
    assert code == 1
    assert account["quotes"] == 5 == sum(account["counts"].values())
    assert account["counts"] == {
        "found": 1,
        "not found": 1,
        "ambiguous": 0,
        "indeterminate": 0,
        "unchecked": 3,
    }
    assert account["sources"] == 2 and account["absent_sources"] == 1
    assert "5 quotes" in capsys.readouterr().out


def test_fetch_writes_how_many_sources_had_each_outcome(tmp_path):
    pin(tmp_path, "here", [QUOTE])
    pin(tmp_path, "gone", [QUOTE], there=False)
    wrote = tmp_path / "fetch.json"
    code = main(["fetch", "--claims", str(tmp_path / "claims"), "--json", str(wrote)])
    account = json.loads(wrote.read_text())
    assert code == 1
    assert account["sources"] == 2 == sum(account["counts"].values())
    assert account["counts"]["present"] == 1 and account["counts"]["no location"] == 1
    assert account["counts"]["fetched"] == 0
