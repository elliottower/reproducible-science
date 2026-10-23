"""The ledger against the versions of it git history holds, and ledgers nested below it."""

from __future__ import annotations

import json
import os
import subprocess

import pytest
from results import cli, ledger


def git(root, *args):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
        cwd=root,
        env=env,
        check=True,
        capture_output=True,
    )


@pytest.fixture
def committed(tmp_path, monkeypatch):
    """A project whose ledger, holding an `outcomes seen` event, is committed."""
    monkeypatch.chdir(tmp_path)
    git(tmp_path, "init", "-q")
    assert cli.main(["init"]) == 0
    (tmp_path / "out.json").write_text(json.dumps({"icc": 0.4213}))
    assert cli.main(["run", "out.json", "--run-id", "r1"]) == 0
    assert cli.main(["access", "looked at the outcome", "--level", "outcomes seen"]) == 0
    assert cli.main(["claim", "The ICC was 0.4213", "--run-id", "r1"]) == 0
    git(tmp_path, "add", ".results", "out.json")
    git(tmp_path, "commit", "-q", "-m", "ledger")
    return tmp_path


def lp(root):
    return root / ".results" / "ledger.jsonl"


def rechain(path, keep):
    """Rewrite the ledger to the events `keep` accepts, recompute every link, and anchor it:
    the twenty lines an agent with write access needs."""
    events = [e for e in ledger.read_ledger(path) if keep(e)]
    lines, prev = [], ledger.ZERO
    for seq, event in enumerate(events):
        line = ledger.canonical({**event, "seq": seq, "prev_hash": prev})
        lines.append(line)
        prev = ledger.sha256_of_str(line)
    path.write_text("\n".join(lines) + "\n")
    ledger.write_anchor(path, len(lines), prev)


def test_a_chain_rewritten_without_an_event_is_caught_by_history(committed, capsys):
    rechain(lp(committed), lambda e: e.get("level") != "outcomes seen")
    assert ledger.verify(lp(committed))[0] is ledger.ChainStatus.INTACT
    capsys.readouterr()

    assert cli.main(["verify", "--files"]) == 1
    assert "LEDGER HISTORY REWRITTEN" in capsys.readouterr().out


def test_an_appended_ledger_still_extends_history(committed, capsys):
    assert cli.main(["access", "a second look", "--level", "metadata only"]) == 0
    capsys.readouterr()

    assert cli.main(["verify", "--files"]) == 0
    assert "LEDGER HISTORY REWRITTEN" not in capsys.readouterr().out


def test_reanchor_refuses_a_chain_shorter_than_the_committed_one(committed, capsys):
    path = lp(committed)
    lines = path.read_text().splitlines()
    path.write_text("\n".join(lines[:-1]) + "\n")
    ledger.anchor_path(path).rename(path.parent / "head.aside")
    assert ledger.verify(path)[0] is ledger.ChainStatus.NO_ANCHOR
    capsys.readouterr()

    assert cli.main(["reanchor"]) == 1
    assert "refusing to anchor" in capsys.readouterr().out
    assert not ledger.anchor_path(path).exists()


def test_reanchor_still_anchors_an_uncommitted_ledger(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert cli.main(["init"]) == 0
    ledger.anchor_path(lp(tmp_path)).unlink()

    assert cli.main(["reanchor"]) == 0


def test_a_deleted_timestamp_proof_is_reported_and_fails_only_under_strict(committed, capsys):
    proof = committed / ".results" / "timestamps" / "000004-0123456789abcdef.ots"
    proof.parent.mkdir()
    proof.write_bytes(b"proof")
    git(committed, "add", str(proof))
    git(committed, "commit", "-q", "-m", "stamp")
    proof.unlink()
    capsys.readouterr()

    assert cli.main(["verify", "--files"]) == 0
    assert "TIMESTAMP PROOF MISSING" in capsys.readouterr().out
    assert cli.main(["verify", "--files", "--strict"]) == 1


def test_a_nested_ledger_with_a_changed_file_fails_verify_at_the_top(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert cli.main(["init"]) == 0
    sub = tmp_path / "exp" / "a"
    sub.mkdir(parents=True)
    monkeypatch.chdir(sub)
    assert cli.main(["init"]) == 0
    (sub / "data.csv").write_text("1,2\n")
    assert cli.main(["seal", "data.csv"]) == 0
    (sub / "data.csv").write_text("1,3\n")
    monkeypatch.chdir(tmp_path)
    capsys.readouterr()

    assert cli.main(["verify", "--files", "--json", "found.json"]) == 1
    out = capsys.readouterr().out
    assert "nested ledger exp/a/.results" in out
    assert "CHANGED    data.csv" in out
    found = json.loads((tmp_path / "found.json").read_text())
    assert found["nested"][0]["exit"] == 1


def test_a_tree_holding_a_symlink_says_so_at_seal_and_at_verify(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert cli.main(["init"]) == 0
    data = tmp_path / "data"
    data.mkdir()
    (data / "a.csv").write_text("1\n")
    (tmp_path / "elsewhere.csv").write_text("2\n")
    (data / "b.csv").symlink_to(tmp_path / "elsewhere.csv")
    (data / "__pycache__").mkdir()
    (data / "__pycache__" / "x.pyc").write_bytes(b"\x00")
    capsys.readouterr()

    assert cli.main(["seal", "data"]) == 0
    sealed = capsys.readouterr().out
    assert "b.csv  (a symlink, not followed)" in sealed
    assert "__pycache__/x.pyc  (a cache directory)" in sealed

    assert cli.main(["verify", "--files"]) == 0
    assert "b.csv  (a symlink, not followed)" in capsys.readouterr().out
