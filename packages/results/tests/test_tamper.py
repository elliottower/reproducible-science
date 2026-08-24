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
    status, problems = L.verify(chain)
    assert status is L.ChainStatus.TRUNCATED
    # The status alone is the same verdict a ledger that was never written gets. What makes
    # this actionable is the anchor's count: five events existed and none are here.
    assert any("5 events" in p for p in problems), problems


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
    # Swapping two lines breaks the hash chain as well as the sequence, and the first
    # structural fault is the one reported.
    assert status is L.ChainStatus.EDITED


def rechain(path, events):
    """Write `events` as a ledger whose prev_hash links are all correct, and anchor it.

    Every other way of disturbing the order also breaks a hash, so the earlier fault is what
    verification reports. Rebuilding the links is the only way to reach the sequence check.
    """
    lines, prev = [], L.ZERO
    for event in events:
        line = L.canonical({**event, "prev_hash": prev})
        lines.append(line)
        prev = L.sha256_of_str(line)
    path.write_text("\n".join(lines) + "\n")
    L.write_anchor(path, len(lines), prev)


def test_a_sequence_that_does_not_match_the_position_is_reordered(chain):
    events = [json.loads(line) for line in chain.read_text().splitlines()]
    events[2]["seq"] = 99
    rechain(chain, events)
    status, problems = L.verify(chain)
    assert status is L.ChainStatus.REORDERED, problems
    assert any("line 3" in p and "99" in p for p in problems), problems


def test_rechaining_alone_leaves_the_ledger_intact(chain):
    # The control for the helper: rebuilding the links without touching a `seq` has to verify,
    # or the test above would pass for the wrong reason.
    events = [json.loads(line) for line in chain.read_text().splitlines()]
    rechain(chain, events)
    assert L.verify(chain)[0] is L.ChainStatus.INTACT


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


def test_an_anchor_from_another_canonicalization_rule_is_not_intact(chain):
    """Recording the version is pointless if a mismatch still verifies.

    A ledger written under one rule for serializing a line hashes differently under another,
    so every comparison in this module is against the wrong bytes. The chain may be perfect
    and the verdict still means nothing.
    """
    path = L.anchor_path(chain)
    anchor = json.loads(path.read_text())
    anchor["canon_version"] = L.CANON_VERSION + 1
    path.write_text(json.dumps(anchor, indent=2, sort_keys=True) + "\n")
    status, problems = L.verify(chain)
    assert status is L.ChainStatus.CORRUPT
    assert any("canon_version" in p for p in problems), problems


def test_appending_to_a_damaged_chain_is_refused(chain):
    """The anchor is the only witness to the last line, and appending overwrites it.

    An edited tail was reported once and then became invisible: the next ordinary command
    re-anchored over the evidence, and the ledger verified clean forever after.
    """
    lines = chain.read_text().splitlines()
    event = json.loads(lines[2])
    event["i"] = 99
    lines[2] = L.canonical(event)
    chain.write_text("\n".join(lines) + "\n")

    with pytest.raises(L.ChainError) as e:
        L.append_event(chain, {"event": "run", "i": 5})
    assert "edited" in str(e.value)
    assert len(chain.read_text().splitlines()) == 5, "the refused event must not be on disk"
    assert L.verify(chain)[0] is L.ChainStatus.EDITED, "the evidence has to survive the refusal"


def test_appending_to_a_healthy_chain_still_works(chain):
    # The control: the refusal has to be about the damage, not about appending.
    L.append_event(chain, {"event": "run", "i": 5})
    assert L.verify(chain)[0] is L.ChainStatus.INTACT
    assert len(chain.read_text().splitlines()) == 6
