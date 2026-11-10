"""A quotation listed as checked by hand keeps its computed outcome, and the list is on record."""

from __future__ import annotations

import hashlib
import json
import re

import pytest
import yaml
from citations import hand_checked as HC
from citations import verify as V
from citations.cli import main

TEXT = "The quick brown fox jumps over the lazy dog near the quiet river bank at dawn.\n"
QUOTE = "quick brown fox jumps over the lazy dog"
ABSENT = "a sentence the source does not contain anywhere in its text at all"
SHA = hashlib.sha256(TEXT.encode()).hexdigest()


@pytest.fixture(autouse=True)
def _alone(monkeypatch):
    monkeypatch.setenv("CITATIONS_NO_CACHE", "1")
    monkeypatch.setenv("REPRO_NO_HINT", "1")
    V.clear_caches()


def pin(root, quotes):
    (root / "sources").mkdir(exist_ok=True)
    (root / "claims").mkdir(exist_ok=True)
    (root / "sources" / "fox.txt").write_text(TEXT)
    source = {"citation": "fox", "local": "sources/fox.txt", "sha256": SHA}
    claims = {cid: {"quotes": [{"exact": quote}]} for cid, quote in quotes.items()}
    (root / "claims" / "fox.yaml").write_text(yaml.safe_dump({"source": source, "claims": claims}))


def listed(root, text):
    (root / "claims" / "fox.checked.txt").write_text(text)


def verify(root):
    wrote = root / "verify.json"
    code = main(["verify", "--claims", str(root / "claims"), "--json", str(wrote)])
    return code, json.loads(wrote.read_text())["checked_by_hand"]


def test_a_listed_passage_that_is_not_in_the_source_still_reports_not_found(tmp_path, capsys):
    pin(tmp_path, {"here": QUOTE, "absent": ABSENT})
    listed(
        tmp_path,
        f"here    {HC.fingerprint(QUOTE, SHA, None)}  p.1\n"
        f"absent  {HC.fingerprint(ABSENT, SHA, None)}  # compared against the page\n",
    )
    code, hand = verify(tmp_path)
    assert code == 1
    assert {c["id"]: c["state"] for c in hand["covered"]} == {
        "here": "found",
        "absent": "not found",
    }
    assert hand["outcomes"] == {"found": 1, "not found": 1}
    out = capsys.readouterr().out
    assert "checked by hand: 2 of 2 passages, list sha256 " in out
    assert re.search(r"^  not found +1$", out, re.M)
    assert "(checked by hand)" in out
    assert "1 not found. read the source" in out


def test_editing_the_quotation_after_listing_it_leaves_the_hand_check_stale(tmp_path, capsys):
    edited = QUOTE.replace("lazy", "sleepy")
    pin(tmp_path, {"here": edited})
    was = HC.fingerprint(QUOTE, SHA, None)
    listed(tmp_path, f"here  {was}\n")
    _, hand = verify(tmp_path)
    assert hand["covered"] == []
    assert hand["stale"] == [
        {"claim": "fox:here", "id": "here", "listed": was, "now": HC.fingerprint(edited, SHA, None)}
    ]
    assert "checked by hand: 0 of 1 passages" in capsys.readouterr().out


def test_an_id_naming_no_quotation_is_reported(tmp_path, capsys):
    pin(tmp_path, {"here": QUOTE})
    listed(tmp_path, f"here  {HC.fingerprint(QUOTE, SHA, None)}\nhere/2\nnowhere\n")
    _, hand = verify(tmp_path)
    assert [u["id"] for u in hand["unknown"]] == ["here/2", "nowhere"]
    assert len(hand["covered"]) == 1
    out = capsys.readouterr().out
    assert "2 listed id(s) name no quotation in their claims file" in out
    assert "nowhere  in " in out


def test_the_digest_changes_when_the_list_does(tmp_path):
    pin(tmp_path, {"here": QUOTE})
    line = f"here  {HC.fingerprint(QUOTE, SHA, None)}"
    listed(tmp_path, line + "\n")
    _, first = verify(tmp_path)
    listed(tmp_path, line + "  # against the printed page\n")
    _, second = verify(tmp_path)
    assert first["lists"][0]["sha256"] == hashlib.sha256((line + "\n").encode()).hexdigest()
    assert first["lists"][0]["sha256"] != second["lists"][0]["sha256"]
    assert first["sha256"] != second["sha256"]
    assert len(first["covered"]) == len(second["covered"]) == 1
