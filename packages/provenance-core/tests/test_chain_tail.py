"""An append that reads only the chain's last line, and what it still refuses."""

from __future__ import annotations

import json

import pytest

from provenance_core import chain
from provenance_core.chain import ChainError, ChainStatus


def written(path, n):
    for i in range(n):
        chain.append_event(path, {"event": "e", "i": i})
    return path


def lines(path):
    return path.read_text().splitlines()


def test_a_tail_append_writes_the_bytes_a_whole_chain_append_writes(
    tmp_path, monkeypatch
):
    one, other = tmp_path / "one" / "ledger.jsonl", tmp_path / "other" / "ledger.jsonl"
    for path in (one, other):
        path.parent.mkdir()
    written(one, 5)
    other.write_bytes(one.read_bytes())
    chain.anchor_path(other).write_bytes(chain.anchor_path(one).read_bytes())
    monkeypatch.setattr(chain, "now_iso", lambda: "2026-01-02T00:00:00+00:00")
    for event in ({"event": "a"}, {"event": "b", "x": [1, 2]}):
        chain.append_event(one, event)
        chain.append_event(other, event, whole_chain=False)
    assert other.read_bytes() == one.read_bytes()
    assert json.loads(chain.anchor_path(other).read_text())["count"] == 7
    assert chain.verify(other) == (ChainStatus.INTACT, [])


def test_a_tail_append_hashes_two_lines_and_reads_no_line_but_the_last(
    tmp_path, monkeypatch
):
    path = written(tmp_path / "ledger.jsonl", 300)
    hashed = []
    real = chain.sha256_of_text

    def counted(text):
        hashed.append(text)
        return real(text)

    def refused(_):
        raise AssertionError("the whole chain was read")

    monkeypatch.setattr(chain, "sha256_of_text", counted)
    monkeypatch.setattr(chain, "_lines", refused)
    made = chain.append_event(path, {"event": "last"}, whole_chain=False)
    # The last line, to compare with the anchor, and the new one, to anchor it.
    assert len(hashed) == 2
    assert made["seq"] == 300
    monkeypatch.undo()
    assert chain.verify(path) == (ChainStatus.INTACT, [])


def test_the_last_line_is_read_whole_across_blocks_and_blank_lines(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(chain, "_TAIL_BLOCK", 7)
    path = tmp_path / "ledger.jsonl"
    path.write_text('{"a": 1}\r\n' + '{"b": "' + "x" * 50 + '"}\r\n\n  \n')
    assert chain.last_line(path) == '{"b": "' + "x" * 50 + '"}'
    path.write_text('{"only": true}')
    assert chain.last_line(path) == '{"only": true}'
    path.write_text("\n\n")
    assert chain.last_line(path) is None
    assert chain.last_line(tmp_path / "absent.jsonl") is None


@pytest.mark.parametrize("whole_chain", [True, False])
def test_an_edited_last_line_is_refused_and_left_as_it_was(tmp_path, whole_chain):
    path = written(tmp_path / "ledger.jsonl", 10)
    held = lines(path)
    held[-1] = held[-1].replace('"i":9', '"i":90')
    path.write_text("\n".join(held) + "\n")
    with pytest.raises(
        ChainError, match="refusing to append to a chain reported as edited"
    ):
        chain.append_event(path, {"event": "x"}, whole_chain=whole_chain)
    assert lines(path) == held


@pytest.mark.parametrize("whole_chain", [True, False])
def test_a_cut_tail_is_refused(tmp_path, whole_chain):
    path = written(tmp_path / "ledger.jsonl", 10)
    path.write_text("\n".join(lines(path)[:8]) + "\n")
    with pytest.raises(
        ChainError, match="refusing to append to a chain reported as truncated"
    ):
        chain.append_event(path, {"event": "x"}, whole_chain=whole_chain)


def test_a_line_written_without_its_anchor_is_built_on_as_before(tmp_path):
    path = written(tmp_path / "ledger.jsonl", 3)
    stale = chain.anchor_path(path).read_bytes()
    chain.append_event(path, {"event": "crashed before its anchor"})
    chain.anchor_path(path).write_bytes(stale)
    assert chain.verify(path)[0] is ChainStatus.EXTENDED
    made = chain.append_event(path, {"event": "next"}, whole_chain=False)
    assert made["seq"] == 4
    assert chain.verify(path) == (ChainStatus.INTACT, [])


def test_an_edit_further_back_is_appended_past_and_still_found_by_verify(tmp_path):
    path = written(tmp_path / "ledger.jsonl", 10)
    held = lines(path)
    held[2] = held[2].replace('"i":2', '"i":20')
    path.write_text("\n".join(held) + "\n")
    # The `results` ledger keeps the whole-chain check, which refuses.
    with pytest.raises(ChainError, match="edited"):
        chain.append_event(path, {"event": "x"})
    chain.append_event(path, {"event": "x"}, whole_chain=False)
    status, problems = chain.verify(path)
    assert status is ChainStatus.EDITED
    assert problems[0].startswith("line 4: prev_hash expected")
    assert lines(path)[2] == held[2]


def test_a_chain_with_no_anchor_or_another_canon_takes_the_whole_chain_check(tmp_path):
    path = written(tmp_path / "ledger.jsonl", 4)
    chain.anchor_path(path).unlink()
    assert chain.append_event(path, {"event": "x"}, whole_chain=False)["seq"] == 4
    assert chain.verify(path) == (ChainStatus.INTACT, [])

    anchor = json.loads(chain.anchor_path(path).read_text())
    chain.anchor_path(path).write_text(json.dumps(anchor | {"canon_version": 0}))
    with pytest.raises(ChainError, match="corrupt"):
        chain.append_event(path, {"event": "y"}, whole_chain=False)


def test_a_last_line_whose_position_is_not_the_anchors_count_is_not_built_on(tmp_path):
    path = written(tmp_path / "ledger.jsonl", 5)
    anchor = json.loads(chain.anchor_path(path).read_text())
    # The head names the last line, and the count says it is at another position.
    chain.anchor_path(path).write_text(json.dumps(anchor | {"count": 9}))
    with pytest.raises(ChainError, match="truncated"):
        chain.append_event(path, {"event": "x"}, whole_chain=False)
