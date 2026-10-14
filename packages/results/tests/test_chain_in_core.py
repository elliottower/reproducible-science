"""The chain's writer and reader live in `provenance_core.chain`, and nothing they write moved.

`fixtures/chain/` was written by `results.ledger` as it stood before the move, under a clock
that ticks one second a call: `before.*` is a ledger of three events and its head file, and
`after.*` the same ledger with two more appended. Appending those two to a copy of `before.*`
must give `after.*` byte for byte, by the name the ledger has always had and by the new one.
"""

from __future__ import annotations

import itertools
import pathlib
import shutil

import pytest
from provenance_core import chain
from results import cli, ledger

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "chain"

#: The two events `after.*` holds beyond `before.*`.
APPENDED = (
    {"event": "claim", "text": "The total is 6.", "value": 6},
    {"z": 1, "a": {"b": [1, 2.5, None, True]}},
)

MOVED = (
    "ANCHOR",
    "CANON_VERSION",
    "ChainError",
    "ChainStatus",
    "anchor_path",
    "append_event",
    "canonical",
    "last_hash",
    "line_hashes",
    "now_iso",
    "read_anchor",
    "read_ledger",
    "reanchor",
    "verify",
    "verify_chain",
    "write_anchor",
)


def copied(tmp_path, monkeypatch):
    """A copy of the three-event ledger, and the clock set to where its writer left it."""
    target = tmp_path / ledger.LEDGER
    shutil.copy(FIXTURES / "before.jsonl", target)
    shutil.copy(FIXTURES / "before.head", tmp_path / ledger.ANCHOR)
    ticks = (f"2026-01-01T00:00:{n:02d}+00:00" for n in itertools.count(6))
    monkeypatch.setattr(chain, "now_iso", lambda: next(ticks))
    return target


@pytest.mark.parametrize("module", [ledger, chain], ids=["results.ledger", "provenance_core.chain"])
def test_appending_by_either_name_writes_the_bytes_the_ledger_wrote_before_the_move(
    tmp_path, monkeypatch, module
):
    target = copied(tmp_path, monkeypatch)
    assert module.verify(target) == (module.ChainStatus.INTACT, [])
    for event in APPENDED:
        module.append_event(target, event)
    assert target.read_bytes() == (FIXTURES / "after.jsonl").read_bytes()
    assert (tmp_path / "ledger.head").read_bytes() == (FIXTURES / "after.head").read_bytes()
    assert module.verify(target) == (module.ChainStatus.INTACT, [])


def test_the_fixture_is_a_chain_the_reader_accepts_and_a_cut_one_it_does_not(tmp_path):
    shutil.copy(FIXTURES / "after.jsonl", tmp_path / "ledger.jsonl")
    shutil.copy(FIXTURES / "after.head", tmp_path / "ledger.head")
    assert chain.verify(tmp_path / "ledger.jsonl") == (chain.ChainStatus.INTACT, [])
    shutil.copy(FIXTURES / "before.jsonl", tmp_path / "ledger.jsonl")
    status, problems = ledger.verify(tmp_path / "ledger.jsonl")
    assert status is ledger.ChainStatus.TRUNCATED
    assert problems == ["anchor records 5 events, ledger holds 3"]


def test_every_name_the_ledger_had_is_the_object_the_chain_holds():
    for name in MOVED:
        assert getattr(ledger, name) is getattr(chain, name), name
    assert ledger.sha256_of_str("x") == chain.sha256_of_text("x")
    assert (ledger.LEDGER, ledger.ANCHOR) == ("ledger.jsonl", "ledger.head")


def test_a_chain_error_reads_as_it_did_and_the_command_still_catches_it(
    tmp_path, monkeypatch, capsys
):
    error = ledger.ChainError(tmp_path / "ledger.jsonl", "line 2 is not valid JSON: x")
    assert str(error) == f"{tmp_path / 'ledger.jsonl'}: line 2 is not valid JSON: x"
    assert (error.ledger, error.detail) == (
        tmp_path / "ledger.jsonl",
        "line 2 is not valid JSON: x",
    )
    assert isinstance(error, chain.ChainError)
    assert issubclass(ledger.NoLedgerRootError, ledger.ResultsError)

    # An edited chain refuses an append, and `results` turns that into exit 2 and one line.
    root = tmp_path / ".results"
    root.mkdir()
    shutil.copy(FIXTURES / "before.jsonl", root / "ledger.jsonl")
    shutil.copy(FIXTURES / "before.head", root / "ledger.head")
    lines = (root / "ledger.jsonl").read_text().splitlines()
    (root / "ledger.jsonl").write_text("\n".join([lines[0], lines[2], lines[1]]) + "\n")
    with pytest.raises(ledger.ChainError, match="refusing to append to a chain reported as"):
        ledger.append_event(root / "ledger.jsonl", {"event": "x"})
    (tmp_path / "out.json").write_text("{}")
    monkeypatch.chdir(tmp_path)
    assert cli.main(["run", "out.json", "--run-id", "r1"]) == 2
    assert "refusing to append to a chain reported as" in capsys.readouterr().out
