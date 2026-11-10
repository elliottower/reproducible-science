"""A manual check keeps the computed outcome, prints nothing unless asked, and is on record."""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading

import pytest
import yaml
from citations import manual_checks as MC
from citations import verify as V
from citations.cli import main

TEXT = "The quick brown fox jumps over the lazy dog near the quiet river bank at dawn.\n"
QUOTE = "quick brown fox jumps over the lazy dog"
ABSENT = "a sentence the source does not contain anywhere in its text at all"
SHA = hashlib.sha256(TEXT.encode()).hexdigest()


def fp(quote, sha=SHA, reader=None, reading=SHA):
    """A `.txt` source is read as its bytes, so with no `derived_sha256` the reading's digest is
    the file's own."""
    return MC.fingerprint(quote, sha, reader, reading)


@pytest.fixture(autouse=True)
def _alone(monkeypatch):
    monkeypatch.setenv("CITATIONS_NO_CACHE", "1")
    monkeypatch.setenv("REPRO_NO_HINT", "1")
    V.clear_caches()


def pin(root, quotes, text=TEXT, **source):
    (root / "sources").mkdir(exist_ok=True)
    (root / "claims").mkdir(exist_ok=True)
    (root / "sources" / "fox.txt").write_text(text)
    sha = hashlib.sha256(text.encode()).hexdigest()
    source = {"citation": "fox", "local": "sources/fox.txt", "sha256": sha} | source
    claims = {
        cid: {"quotes": [{"exact": q} for q in ([quote] if isinstance(quote, str) else quote)]}
        for cid, quote in quotes.items()
    }
    (root / "claims" / "fox.yaml").write_text(yaml.safe_dump({"source": source, "claims": claims}))


def listed(root, text):
    (root / "claims" / "fox.manual.txt").write_text(text)


def verify(root, *extra):
    wrote = root / "verify.json"
    code = main(["verify", "--claims", str(root / "claims"), "--json", str(wrote), *extra])
    return code, json.loads(wrote.read_text())["manual_checks"]


def test_a_manual_check_never_turns_a_quotation_not_found_into_a_pass(tmp_path, capsys):
    pin(tmp_path, {"here": QUOTE, "absent": ABSENT})
    listed(
        tmp_path,
        f"here    {fp(QUOTE)}  p.1\nabsent  {fp(ABSENT)}  # compared against the page\n",
    )
    code, hand = verify(tmp_path, "--show-manual")
    assert code == 1
    assert {c["id"]: c["state"] for c in hand["covered"]} == {
        "here": "found",
        "absent": "not found",
    }
    assert hand["outcomes"] == {"found": 1, "not found": 1}
    out = capsys.readouterr().out
    assert "manual checks: 2 of 2 passages, list sha256 " in out
    assert re.search(r"^  not found +1$", out, re.M)
    assert "1 not found. read the source" in out


def test_editing_the_quotation_after_listing_it_leaves_the_manual_check_stale(tmp_path):
    edited = QUOTE.replace("lazy", "sleepy")
    pin(tmp_path, {"here": edited})
    was = fp(QUOTE)
    listed(tmp_path, f"here  {was}\n")
    _, hand = verify(tmp_path)
    assert hand["covered"] == []
    assert hand["stale"] == [{"claim": "fox:here", "id": "here", "listed": was, "now": fp(edited)}]


def test_an_id_naming_no_quotation_is_reported(tmp_path, capsys):
    pin(tmp_path, {"here": QUOTE})
    listed(tmp_path, f"here  {fp(QUOTE)}\nhere/2\nnowhere\n")
    _, hand = verify(tmp_path, "--show-manual")
    assert [u["id"] for u in hand["unknown"]] == ["here/2", "nowhere"]
    assert len(hand["covered"]) == 1
    assert "  unknown  nowhere  in " in capsys.readouterr().out


def test_the_digest_changes_when_the_list_does(tmp_path):
    pin(tmp_path, {"here": QUOTE})
    line = f"here  {fp(QUOTE)}"
    listed(tmp_path, line + "\n")
    _, first = verify(tmp_path)
    listed(tmp_path, line + "  # against the printed page\n")
    _, second = verify(tmp_path)
    assert first["lists"][0]["sha256"] == hashlib.sha256((line + "\n").encode()).hexdigest()
    assert first["lists"][0]["sha256"] != second["lists"][0]["sha256"]
    assert first["sha256"] != second["sha256"]
    assert len(first["covered"]) == len(second["covered"]) == 1


def test_changing_the_reader_after_listing_leaves_the_manual_check_stale(tmp_path):
    pin(tmp_path, {"here": QUOTE})
    listed(tmp_path, f"here  {fp(QUOTE)}\n")
    assert len(verify(tmp_path)[1]["covered"]) == 1
    pin(tmp_path, {"here": QUOTE}, extract_cmd="cat")
    code, hand = verify(tmp_path, "--allow-extractor", "cat")
    assert code == 0
    assert hand["covered"] == []
    assert [(s["listed"], s["now"]) for s in hand["stale"]] == [
        (fp(QUOTE), fp(QUOTE, reader="cat"))
    ]


def test_pinning_the_source_again_leaves_the_manual_check_stale(tmp_path):
    pin(tmp_path, {"here": QUOTE})
    listed(tmp_path, f"here  {fp(QUOTE)}\n")
    again = TEXT + "A second edition adds this line.\n"
    pin(tmp_path, {"here": QUOTE}, text=again)
    _, hand = verify(tmp_path)
    new = hashlib.sha256(again.encode()).hexdigest()
    assert hand["covered"] == []
    assert hand["stale"][0]["now"] == fp(QUOTE, sha=new, reading=new)


def test_a_recorded_derived_sha256_names_the_reading_where_the_source_is_not_here(tmp_path):
    derived = "d" * 64
    pin(tmp_path, {"here": QUOTE, "there": ABSENT}, derived_sha256=derived)
    (tmp_path / "sources" / "fox.txt").unlink()
    listed(tmp_path, f"here  {fp(QUOTE, reading=derived)}\n")
    _, hand = verify(tmp_path)
    assert [(c["id"], c["state"]) for c in hand["covered"]] == [("here", "unchecked")]


def test_with_no_derived_sha256_an_unread_source_is_unverifiable_not_stale(tmp_path, capsys):
    pin(tmp_path, {"here": QUOTE})
    (tmp_path / "sources" / "fox.txt").unlink()
    listed(tmp_path, f"here  {fp(QUOTE)}\n")
    _, hand = verify(tmp_path, "--show-manual")
    assert (hand["covered"], hand["stale"]) == ([], [])
    assert hand["unverifiable"] == [{"claim": "fox:here", "id": "here", "listed": fp(QUOTE)}]
    assert "unverifiable  fox:here" in capsys.readouterr().out


def test_a_list_beside_no_claims_file_is_reported(tmp_path, capsys):
    pin(tmp_path, {"here": QUOTE})
    stray = tmp_path / "claims" / "renamed.manual.txt"
    stray.write_text(f"here  {fp(QUOTE)}\n")
    code, hand = verify(tmp_path, "--show-manual")
    assert code == 0
    assert hand["orphans"] == [str(stray.resolve())]
    assert hand["lists"] == []
    assert f"beside no claims file read  {stray.resolve()}" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("quotes", "text", "line"),
    [
        ({"here": QUOTE}, "here\n# a note\nhere\n", 3),
        ({"here": QUOTE}, "here\nhere/1\n", 2),
    ],
)
def test_a_quotation_listed_twice_is_recorded_with_the_line(tmp_path, quotes, text, line):
    pin(tmp_path, quotes)
    listed(tmp_path, text)
    code, hand = verify(tmp_path)
    assert code == 0
    assert [p.split(": ")[0].rsplit(":", 1)[1] for p in hand["problems"]] == [str(line)]
    assert len(hand["stale"]) == 1


def test_a_claim_id_that_is_another_quotations_position_names_that_quotation(tmp_path):
    other = "near the quiet river bank at dawn"
    pin(tmp_path, {"x": [QUOTE, "The quick brown fox"], "x/1": other})
    listed(tmp_path, f"x/1  {fp(QUOTE)}\nx/1/1  {fp(other)}\n")
    _, hand = verify(tmp_path)
    assert sorted((c["claim"], c["quote"]) for c in hand["covered"]) == [
        ("fox:x", QUOTE),
        ("fox:x/1", other),
    ]
    assert hand["unknown"] == hand["stale"] == []


def test_an_uppercase_fingerprint_is_recorded_as_not_lowercase(tmp_path):
    pin(tmp_path, {"here": QUOTE})
    listed(tmp_path, f"here  {fp(QUOTE).upper()}\n")
    code, hand = verify(tmp_path)
    assert code == 0
    assert "fox.manual.txt:1: fingerprints are lowercase" in hand["problems"][0]
    assert hand["covered"] == []


@pytest.mark.parametrize(
    "text",
    [
        "",
        "here  p.4  # compared\nnowhere\n",
        "here  not-a-fingerprint\nhere\n",
        "here  " + "A" * 12 + "\n",
    ],
)
def test_default_output_and_exit_code_are_the_same_with_and_without_a_list(tmp_path, capsys, text):
    pin(tmp_path, {"here": QUOTE, "absent": ABSENT})
    args = ["verify", "--claims", str(tmp_path / "claims")]
    without = main(args), capsys.readouterr().out
    listed(tmp_path, text or f"here  {fp(QUOTE)}\nabsent  {fp(ABSENT)}\n")
    (tmp_path / "claims" / "stray.manual.txt").write_text("here\n")
    assert (main(args), capsys.readouterr().out) == without
    assert without[0] == 1


def manual_check(root, *args):
    return main(["manual-check", str(root / "claims" / "fox.yaml"), *args])


def test_manual_check_appends_the_line_with_the_fingerprint_verify_will_compute(tmp_path, capsys):
    pin(tmp_path, {"here": QUOTE, "other": ABSENT})
    listed(tmp_path, "# compared against the printed page\n")
    assert manual_check(tmp_path, "here", "--page", "4", "--note", "Table 2") == 0
    out = capsys.readouterr().out
    assert f"quote   {QUOTE}" in out
    assert (tmp_path / "claims" / "fox.manual.txt").read_text() == (
        f"# compared against the printed page\nhere  {fp(QUOTE)}  p.4  # Table 2\n"
    )
    _, hand = verify(tmp_path)
    assert [(c["id"], c["page"], c["note"]) for c in hand["covered"]] == [("here", 4, "Table 2")]


def test_manual_check_refuses_an_id_naming_no_quotation(tmp_path, capsys):
    pin(tmp_path, {"here": QUOTE})
    assert manual_check(tmp_path, "nowhere") == 2
    assert "no quotation has the id `nowhere`" in capsys.readouterr().out
    assert not (tmp_path / "claims" / "fox.manual.txt").exists()


def test_manual_check_refuses_a_quotation_listed_with_its_current_fingerprint(tmp_path, capsys):
    pin(tmp_path, {"here": QUOTE})
    listed(tmp_path, f"here/1  {fp(QUOTE)}\n")
    assert manual_check(tmp_path, "here") == 2
    assert manual_check(tmp_path, "here", "--again") == 2
    assert "listed already, as `here/1`" in capsys.readouterr().out
    assert (tmp_path / "claims" / "fox.manual.txt").read_text() == f"here/1  {fp(QUOTE)}\n"


def test_manual_check_replaces_a_stale_line_only_when_asked_again(tmp_path, capsys):
    pin(tmp_path, {"here": QUOTE, "other": ABSENT})
    old = f"here  {fp('an earlier wording')}  p.2"
    listed(tmp_path, f"other  {fp(ABSENT)}\n{old}\n")
    assert manual_check(tmp_path, "here") == 2
    assert "rerun with --again" in capsys.readouterr().out
    assert manual_check(tmp_path, "here", "--again") == 0
    assert f"replaces the earlier check on line 2: {old}" in capsys.readouterr().out
    assert (tmp_path / "claims" / "fox.manual.txt").read_text() == (
        f"other  {fp(ABSENT)}\nhere  {fp(QUOTE)}  p.2\n"
    )


def test_again_keeps_the_earlier_page_and_note_unless_new_ones_are_given(tmp_path):
    pin(tmp_path, {"here": QUOTE})
    listed(tmp_path, f"here  {fp('an earlier wording')}  p.2  # Table 2\n")
    assert manual_check(tmp_path, "here", "--again") == 0
    assert (tmp_path / "claims" / "fox.manual.txt").read_text() == (
        f"here  {fp(QUOTE)}  p.2  # Table 2\n"
    )
    listed(tmp_path, f"here  {fp('an earlier wording')}  p.2  # Table 2\n")
    assert manual_check(tmp_path, "here", "--again", "--page", "5", "--note", "") == 0
    assert (tmp_path / "claims" / "fox.manual.txt").read_text() == f"here  {fp(QUOTE)}  p.5\n"


@pytest.mark.parametrize("ending", ["\r\n", "\r"])
@pytest.mark.parametrize("bom", [b"", b"\xef\xbb\xbf"])
def test_manual_check_keeps_the_lists_line_endings_and_byte_order_mark(tmp_path, ending, bom):
    pin(tmp_path, {"here": QUOTE, "other": ABSENT, "third": "near the quiet river bank"})
    old = f"here  {fp('an earlier wording')}"
    head = f"# compared{ending}other  {fp(ABSENT)}{ending}{old}"
    (tmp_path / "claims" / "fox.manual.txt").write_bytes(bom + head.encode())
    assert manual_check(tmp_path, "here", "--again") == 0
    assert manual_check(tmp_path, "third") == 0
    want = f"# compared{ending}other  {fp(ABSENT)}{ending}here  {fp(QUOTE)}{ending}"
    want += f"third  {fp('near the quiet river bank')}{ending}"
    assert (tmp_path / "claims" / "fox.manual.txt").read_bytes() == bom + want.encode()


@pytest.mark.parametrize(
    ("quotes", "args"),
    [
        ({"two words": QUOTE}, ["two words"]),
        ({"a#b": QUOTE}, ["a#b"]),
        *[
            ({"here": QUOTE}, ["here", "--note", f"a{c}b"])
            for c in "\f\v\x1c\x1d\x1e\x85\u2028\u2029"
        ],
        ({"here": QUOTE}, ["here", "--page", "-3"]),
        ({"here": QUOTE}, ["here", "--page", "0"]),
    ],
)
def test_manual_check_refuses_a_line_the_list_would_not_read_back(tmp_path, capsys, quotes, args):
    pin(tmp_path, quotes)
    listed(tmp_path, "# compared\n")
    assert manual_check(tmp_path, *args) == 2
    assert "not written" in capsys.readouterr().out or args[-2] == "--page"
    assert (tmp_path / "claims" / "fox.manual.txt").read_text() == "# compared\n"


def test_manual_check_refuses_arguments_it_does_not_take(tmp_path, capsys):
    pin(tmp_path, {"here": QUOTE, "other": ABSENT})
    for extra in (["other"], ["--pgae", "4"]):
        with pytest.raises(SystemExit) as e:
            manual_check(tmp_path, "here", *extra)
        assert e.value.code == 2
        assert "unrecognized arguments" in capsys.readouterr().err
    assert not (tmp_path / "claims" / "fox.manual.txt").exists()


def test_concurrent_manual_checks_each_keep_their_line(tmp_path):
    n = 16
    pin(tmp_path, {f"c{i}": QUOTE for i in range(n)})
    listed(tmp_path, "")
    start = threading.Barrier(n)
    codes: list[int] = []

    def one(i):
        start.wait()
        codes.append(manual_check(tmp_path, f"c{i}"))

    threads = [threading.Thread(target=one, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    ids = [
        line.split()[0]
        for line in (tmp_path / "claims" / "fox.manual.txt").read_text().splitlines()
    ]
    assert codes == [0] * n
    assert sorted(ids) == sorted(f"c{i}" for i in range(n))


def unreadable_directory(path):
    path.mkdir()


def unreadable_mode(path):
    path.write_text("here\n")
    path.chmod(0)


def unreadable_size(path):
    path.write_bytes(b"# padding\n" * (MC.MAX_BYTES // 10 + 1))


@pytest.mark.parametrize("make", [unreadable_directory, unreadable_mode, unreadable_size])
def test_a_list_that_cannot_be_read_is_recorded_and_changes_nothing_else(tmp_path, capsys, make):
    pin(tmp_path, {"here": QUOTE, "absent": ABSENT})
    args = ["verify", "--claims", str(tmp_path / "claims")]
    without = main(args), capsys.readouterr().out
    target = tmp_path / "claims" / "fox.manual.txt"
    make(target)
    if make is unreadable_mode and os.access(target, os.R_OK):
        target.chmod(0o644)
        pytest.skip("this user reads a file whatever its mode")
    try:
        assert (main(args), capsys.readouterr().out) == without
        code, hand = verify(tmp_path, "--strict")
        assert code == 1
        assert [p.split(": ")[0] for p in hand["problems"]] == [str(target.resolve())]
        assert hand["lists"][0]["sha256"] == ""
        assert manual_check(tmp_path, "here") == 2
    finally:
        if target.is_file():
            target.chmod(0o644)
