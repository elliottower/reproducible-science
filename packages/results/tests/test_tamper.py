"""Each way of damaging a ledger gets its own status.

Before anchoring, truncating the file to any line boundary left a valid chain, and emptying it
entirely verified clean. A hash chain proves each line follows the previous one; it says
nothing about whether the last line is the last line ever written.
"""

from __future__ import annotations

import json

import pytest
from results import ledger as L


@pytest.fixture
def chain(tmp_path):
    lp = tmp_path / L.LEDGER
    for i in range(5):
        L.append_event(lp, {"event": "run", "i": i})
    return lp


def test_an_untouched_chain_is_intact(chain):
    status, problems = L.verify(chain)
    assert status is L.ChainStatus.INTACT, problems
    assert problems == []


def test_truncating_the_file_is_detected(chain):
    lines = chain.read_text().splitlines()
    chain.write_text("\n".join(lines[:3]) + "\n")
    status, problems = L.verify(chain)
    assert status is L.ChainStatus.TRUNCATED
    assert any("5" in p and "3" in p for p in problems), problems
    assert not L.verify_chain(chain)[0]


def test_emptying_the_file_is_not_a_clean_run(chain):
    chain.write_text("")
    status, _ = L.verify(chain)
    assert status is L.ChainStatus.TRUNCATED


def test_deleting_the_ledger_is_not_a_clean_run(chain):
    chain.unlink()
    status, _ = L.verify(chain)
    assert status is L.ChainStatus.ABSENT
    assert not L.verify_chain(chain)[0]


def test_editing_a_line_is_detected(chain):
    lines = chain.read_text().splitlines()
    ev = json.loads(lines[2])
    ev["i"] = 99
    lines[2] = L.canonical(ev)
    chain.write_text("\n".join(lines) + "\n")
    status, problems = L.verify(chain)
    assert status is L.ChainStatus.EDITED
    assert any("line 4" in p for p in problems), problems


def test_reordering_lines_is_detected(chain):
    lines = chain.read_text().splitlines()
    lines[1], lines[2] = lines[2], lines[1]
    chain.write_text("\n".join(lines) + "\n")
    status, _ = L.verify(chain)
    assert status in (L.ChainStatus.EDITED, L.ChainStatus.REORDERED)


def test_a_corrupt_line_names_itself(chain):
    lines = chain.read_text().splitlines()
    lines[3] = "{not json"
    chain.write_text("\n".join(lines) + "\n")
    status, problems = L.verify(chain)
    assert status is L.ChainStatus.CORRUPT
    assert any("line 4" in p for p in problems), problems


def test_appending_without_updating_the_anchor_reads_as_extended(chain):
    with chain.open("a") as f:
        f.write(
            L.canonical(
                {
                    "event": "sneaked",
                    "seq": 5,
                    "prev_hash": L.sha256_of_str(chain.read_text().splitlines()[-1]),
                    "timestamp": L.now_iso(),
                }
            )
            + "\n"
        )
    status, _ = L.verify(chain)
    assert status is L.ChainStatus.EXTENDED


def test_a_ledger_with_no_anchor_is_not_reported_intact(chain):
    # How every ledger written before anchoring existed looks. The chain is consistent; its
    # length is unattested, so truncation cannot be ruled out.
    L.anchor_path(chain).unlink()
    status, problems = L.verify(chain)
    assert status is L.ChainStatus.NO_ANCHOR
    assert any("unattested" in p for p in problems), problems
    assert not L.verify_chain(chain)[0]


def test_reanchoring_a_legacy_ledger_makes_it_verifiable(chain):
    L.anchor_path(chain).unlink()
    L.reanchor(chain)
    assert L.verify(chain)[0] is L.ChainStatus.INTACT


def test_reanchoring_cannot_launder_a_truncation(chain):
    lines = chain.read_text().splitlines()
    chain.write_text("\n".join(lines[:2]) + "\n")
    L.reanchor(chain)
    # Re-anchoring records the shortened chain, which is why it is a deliberate call and not
    # something verification does on its own.
    assert L.verify(chain)[0] is L.ChainStatus.INTACT
    assert len(L.read_ledger(chain)) == 2, "the events are gone; the anchor cannot bring them back"


def test_append_does_not_mutate_the_callers_event(tmp_path):
    lp = tmp_path / L.LEDGER
    original = {"event": "init"}
    returned = L.append_event(lp, original)
    assert original == {"event": "init"}, "the caller's dict must not gain chain fields"
    assert returned["seq"] == 0 and returned["prev_hash"] == L.ZERO


def test_a_corrupt_line_raises_rather_than_escaping_as_a_json_error(chain):
    chain.write_text(chain.read_text() + "{not json\n")
    with pytest.raises(L.ChainError) as e:
        L.read_ledger(chain)
    assert "line 6" in str(e.value)
