"""A quotation is pinned against a web page by its URL, and the page stays in `retrieved`.

The store, the index, the denylist and the pacing are `retrieved`'s own, unreplaced. What is
replaced is the request: `capture.fetch` answers from memory, name resolution answers with one
public address, and opening a connection is an error. So a test that passes here did not
depend on a remote host, and a refusal it sees is the denylist's.
"""

from __future__ import annotations

import builtins
import dataclasses
import hashlib
import pathlib
import re
import socket
import types

import httpx
import pytest
import yaml
from citations import cli, paths, pin, web
from citations import fetch as F
from citations import verify as V
from citations.models import ClaimSource, load_claim_file
from pydantic import ValidationError
from retrieved import capture, politeness
from retrieved.store import Library

URL = "https://docs.example.org/guide"
PASSAGE = "A capture is refused where the host names a private network."
PAGE = f"<html><body><p>{PASSAGE}</p><p>Every refusal is recorded.</p></body></html>".encode()
LATER = "A capture is refused where the address is not public, and the refusal is recorded."
CHANGED = f"<html><body><p>{LATER}</p></body></html>".encode()
LONG_AGO = "2026-01-05T09:30:00+00:00"

RICH_URL = "https://docs.example.org/denylist"
RICH = b"""<!DOCTYPE html>
<html><head><title>Denylist</title>
<style>.note::after { content: "styled words nobody is shown"; }</style>
<script>var hidden = "scripted words nobody is shown";</script></head>
<body>
<p>The denylist is the <a href="/security">security boundary</a>, and it is
<em>checked twice</em> on every capture.</p>
<p>Fish &amp; chips aren&rsquo;t refused by the denylist.</p>
<ul><li>The first item of the list ends here</li><li>The second item of the list starts here</li></ul>
<table><tr><th>Hosts refused in the sample</th><td>12 of 40</td></tr></table>
</body></html>
"""


def sha(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


@pytest.fixture(autouse=True)
def _no_cache():
    V.clear_caches()


@pytest.fixture
def site(tmp_path, monkeypatch):
    """A `retrieved` library, what each URL answers with, and every URL that was fetched."""
    home = tmp_path / "library"
    monkeypatch.setenv("RETRIEVED_HOME", str(home))
    library = Library(home)
    pages: dict[str, bytes] = {}
    types_sent: dict[str, str] = {}
    asked: list[str] = []

    def refuse_to_connect(self, address):
        raise AssertionError(f"a test opened a connection to {address}")

    monkeypatch.setattr(socket.socket, "connect", refuse_to_connect)
    monkeypatch.setattr(
        socket, "getaddrinfo", lambda host, *a, **k: [(2, 1, 6, "", ("93.184.216.34", 0))]
    )
    monkeypatch.setattr(politeness, "_robots_for", lambda *a, **k: None)
    real = capture.fetch

    def answering(body: bytes | None) -> httpx.Client:
        def handler(request):
            return httpx.Response(
                404 if body is None else 200,
                content=b"no such page" if body is None else body,
                headers={"content-type": types_sent.get(str(request.url), "text/html")},
                request=request,
            )

        return httpx.Client(transport=httpx.MockTransport(handler))

    def offline(url, *, timeout=30.0, client=None):
        asked.append(url)
        with answering(pages.get(url)) as mock:
            return real(url, timeout=timeout, client=mock)

    def hold(url: str, body: bytes, at: str = LONG_AGO) -> None:
        with answering(body) as mock:
            library.write(dataclasses.replace(real(url, client=mock), fetched_at=at))

    monkeypatch.setattr(capture, "fetch", offline)
    return types.SimpleNamespace(
        library=library, pages=pages, types_sent=types_sent, asked=asked, hold=hold
    )


@pytest.fixture
def claims(tmp_path) -> pathlib.Path:
    return tmp_path / "paper" / "claims"


def pin_url(file: pathlib.Path, quote: str, *more: str, url: str = URL, id: str = "refusal") -> int:
    return pin.main([str(file), "--url", url, "--id", id, "--quote", quote, *more])


def read(file: pathlib.Path) -> dict:
    return yaml.safe_load(file.read_text())


def verify(claims: pathlib.Path, capsys) -> tuple[int, str]:
    capsys.readouterr()
    code = cli.main(["verify", "--strict", "--no-cache", "--claims", str(claims)])
    return code, capsys.readouterr().out


def count(outcome: str, out: str) -> int | None:
    row = re.search(rf"^  {outcome}\s+(\d+)", out, re.M)
    return int(row.group(1)) if row else None


def test_a_page_the_library_holds_is_pinned_from_it_and_nothing_is_fetched(site, claims, capsys):
    site.hold(URL, PAGE)

    assert pin_url(claims / "guide.yaml", PASSAGE) == 0

    assert site.asked == []
    doc = read(claims / "guide.yaml")
    assert doc["source"] == {
        "url": URL,
        "sha256": sha(PAGE),
        "retrieved": f"store/{sha(PAGE)}",
        "retrieved_at": LONG_AGO,
        "extractor": "html-text",
        "extractor_version": 1,
        "derived_sha256": sha(f"{PASSAGE}\nEvery refusal is recorded.".encode()),
    }
    assert doc["claims"]["refusal"]["quotes"] == [{"exact": PASSAGE}]
    out = capsys.readouterr().out
    assert LONG_AGO in out and "already in the library" in out


def test_a_page_the_library_lacks_is_captured_once_stored_and_pinned(site, claims, capsys):
    site.pages[URL] = PAGE

    assert pin_url(claims / "guide.yaml", PASSAGE) == 0
    assert "captured now" in capsys.readouterr().out
    assert pin_url(claims / "guide.yaml", "Every refusal is recorded.", id="recorded") == 0

    assert site.asked == [URL]
    assert (site.library.store / sha(PAGE)).read_bytes() == PAGE
    assert [digest for _, digest, _ in site.library.history(URL)] == [sha(PAGE)]
    doc = read(claims / "guide.yaml")
    assert doc["source"]["sha256"] == sha(PAGE)
    assert set(doc["claims"]) == {"refusal", "recorded"}


def test_a_quotation_the_page_lacks_is_refused_and_no_claims_file_is_written(site, claims, capsys):
    site.hold(URL, PAGE)

    assert pin_url(claims / "guide.yaml", "A capture is always made, whatever the host.") == 1

    assert not claims.exists()
    out = capsys.readouterr().out
    assert "not found" in out and "nothing written" in out
    assert "not found by any of" not in out, "no PDF reader is asked about a page of text"


def test_a_quotation_the_page_lacks_leaves_a_claims_file_as_it_was(site, claims):
    site.hold(URL, PAGE)
    assert pin_url(claims / "guide.yaml", PASSAGE) == 0
    before = (claims / "guide.yaml").read_text()

    assert pin_url(claims / "guide.yaml", "Every refusal is forgotten.", id="forgotten") == 1

    assert (claims / "guide.yaml").read_text() == before


@pytest.mark.parametrize(
    ("url", "reason"),
    [
        ("http://localhost/admin", "private network"),
        ("http://169.254.169.254/latest/meta-data/", "metadata"),
        ("https://docs.example.org/guide?token=4f1c9a", "token, credential or identifier"),
        ("file:///etc/hosts", "not http or https"),
    ],
)
def test_a_url_retrieved_refuses_fails_with_its_reason_and_writes_nothing(
    site, claims, capsys, url, reason
):
    assert pin_url(claims / "guide.yaml", PASSAGE, url=url) == 1

    out = capsys.readouterr().out
    assert reason in out and "nothing written" in out
    assert site.asked == []
    assert not claims.exists()
    assert not site.library.root.exists()


def test_a_server_that_answers_no_page_is_refused_and_nothing_is_stored(site, claims, capsys):
    assert pin_url(claims / "guide.yaml", "no such page") == 1

    assert "HTTP 404" in capsys.readouterr().out
    assert site.asked == [URL]
    assert not claims.exists()
    assert list(site.library.store.iterdir()) == []


def test_without_the_extra_the_install_is_named_and_nothing_is_written(
    site, claims, capsys, monkeypatch
):
    site.hold(URL, PAGE)
    real = builtins.__import__

    def absent(name, *args, **kwargs):
        if name.split(".")[0] == "retrieved":
            raise ImportError(f"No module named {name!r}")
        return real(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", absent)

    assert pin_url(claims / "guide.yaml", PASSAGE) == 1

    out = capsys.readouterr().out
    assert 'retrieved is not installed -- pip install "citations[web]"' in out
    assert "nothing written" in out
    assert not claims.exists()


def test_verify_finds_the_quotation_in_the_store(site, claims, capsys):
    site.hold(URL, PAGE)
    assert pin_url(claims / "guide.yaml", PASSAGE) == 0

    code, out = verify(claims, capsys)

    assert code == 0, out
    assert count("found", out) == 1
    assert "all found." in out


def test_verify_without_the_bytes_is_unchecked_and_names_the_store(
    site, claims, capsys, tmp_path, monkeypatch
):
    site.hold(URL, PAGE)
    assert pin_url(claims / "guide.yaml", PASSAGE) == 0
    elsewhere = tmp_path / "a-readers-machine"
    monkeypatch.setenv("RETRIEVED_HOME", str(elsewhere))

    code, out = verify(claims, capsys)

    assert code == 1
    assert count("unchecked", out) == 1
    assert count("found", out) is None
    assert count("not found", out) == 0
    assert f"not in the retrieved store at {elsewhere / 'store'}" in out
    assert not elsewhere.exists()


def test_a_store_file_with_other_bytes_is_a_broken_pin_and_never_a_pass(site, claims, capsys):
    site.hold(URL, PAGE)
    assert pin_url(claims / "guide.yaml", PASSAGE) == 0
    (site.library.store / sha(PAGE)).write_bytes(PAGE + b"<!-- served again -->")

    code, out = verify(claims, capsys)

    assert code == 1
    assert "1 source changed since being pinned" in out


def test_the_claims_file_names_no_directory_of_the_machine_that_wrote_it(site, claims, tmp_path):
    site.hold(URL, PAGE)
    assert pin_url(claims / "guide.yaml", PASSAGE) == 0

    text = (claims / "guide.yaml").read_text()
    assert str(tmp_path) not in text
    assert str(pathlib.Path.home()) not in text
    source = load_claim_file(claims / "guide.yaml").source
    assert source.local is None
    assert not pathlib.PurePosixPath(source.retrieved).is_absolute()


@pytest.mark.parametrize("path", ["/home/someone/.retrieved/store/abc", "store/../../secrets"])
def test_a_retrieved_path_that_leaves_the_library_is_not_a_claims_file(path):
    with pytest.raises(ValidationError, match="inside the retrieved library"):
        ClaimSource(retrieved=path)


def test_recapturing_a_changed_page_pins_the_new_bytes_and_the_old_claims_still_verify(
    site, claims, capsys
):
    site.hold(URL, PAGE)
    assert pin_url(claims / "guide.yaml", PASSAGE) == 0
    site.pages[URL] = CHANGED

    assert pin_url(claims / "guide-later.yaml", LATER, "--recapture") == 0

    assert site.asked == [URL]
    assert read(claims / "guide.yaml")["source"]["sha256"] == sha(PAGE)
    later = read(claims / "guide-later.yaml")["source"]
    assert later["sha256"] == sha(CHANGED)
    assert later["retrieved_at"] > LONG_AGO
    code, out = verify(claims, capsys)
    assert code == 0, out
    assert count("found", out) == 2


def test_a_claims_file_is_not_given_a_second_retrieval_of_its_page(site, claims, capsys):
    site.hold(URL, PAGE)
    assert pin_url(claims / "guide.yaml", PASSAGE) == 0
    before = (claims / "guide.yaml").read_text()
    site.hold(URL, CHANGED, at="2026-02-01T00:00:00+00:00")
    capsys.readouterr()

    assert pin_url(claims / "guide.yaml", LATER, id="later") == 1

    assert (claims / "guide.yaml").read_text() == before
    out = capsys.readouterr().out
    assert sha(PAGE)[:12] in out and sha(CHANGED)[:12] in out
    assert "Leave out --url" in out
    assert (
        pin.main(
            [
                str(claims / "guide.yaml"),
                "--id",
                "recorded",
                "--quote",
                "Every refusal is recorded.",
            ]
        )
        == 0
    )


def test_a_claims_file_that_pins_a_file_is_not_given_a_page(site, claims, capsys):
    site.pages[URL] = PAGE
    claims.mkdir(parents=True)
    (claims.parent / "notes.txt").write_text(PASSAGE)
    file = claims / "notes.yaml"
    file.write_text("source:\n  local: notes.txt\nclaims: {}\n")

    assert pin_url(file, PASSAGE) == 1

    assert "already pins notes.txt" in capsys.readouterr().out
    assert site.asked == []
    assert read(file) == {"source": {"local": "notes.txt"}, "claims": {}}


def test_check_with_a_url_resolves_and_writes_no_claims_file(site, claims, capsys):
    site.hold(URL, PAGE)

    assert pin_url(claims / "guide.yaml", PASSAGE, "--check") == 0

    assert "would add refusal" in capsys.readouterr().out
    assert not claims.exists()


@pytest.mark.parametrize(
    ("body", "content_type", "reading"),
    [
        (PAGE, "text/html; charset=utf-8", {"extractor": "html-text"}),
        (RICH, "", {"extractor": "html-text"}),
        (PAGE, "text/plain", {"extract_cmd": "cat {}"}),
        (PASSAGE.encode(), "", {"extract_cmd": "cat {}"}),
        (b"%PDF-1.7 the bytes of a paper", "application/pdf", {}),
        (b"%PDF-1.7 the bytes of a paper", "", {}),
    ],
)
def test_the_reading_a_page_declares_follows_its_content_type_and_then_its_bytes(
    tmp_path, body, content_type, reading
):
    (tmp_path / "blob").write_bytes(body)
    block = web.Page(URL, sha(body), LONG_AGO, tmp_path / "blob", False, content_type).source()

    assert {k: v for k, v in block.items() if k in ("extractor", "extract_cmd")} == reading


@pytest.mark.parametrize(
    "quote",
    [
        "The denylist is the security boundary, and it is checked twice on every capture.",
        "Fish & chips aren\u2019t refused by the denylist.",
        "Fish & chips aren't refused by the denylist.",
    ],
    ids=["across a link and emphasis", "entities as characters", "a straight apostrophe"],
)
def test_a_quotation_resolves_through_inline_tags_and_character_entities(
    site, claims, capsys, quote
):
    site.hold(RICH_URL, RICH)

    assert pin_url(claims / "denylist.yaml", quote, url=RICH_URL) == 0

    assert "normalized" not in capsys.readouterr().out
    code, out = verify(claims, capsys)
    assert code == 0, out
    assert "html-text@1" in out


@pytest.mark.parametrize(
    "words", ["scripted words nobody is shown", "styled words nobody is shown"]
)
def test_the_text_of_a_script_or_a_stylesheet_satisfies_no_quotation(site, claims, capsys, words):
    assert words.encode() in RICH
    site.hold(RICH_URL, RICH)

    assert pin_url(claims / "denylist.yaml", words, url=RICH_URL) == 1

    assert "not found" in capsys.readouterr().out
    assert not claims.exists()


def test_a_block_boundary_is_a_line_break_and_a_cell_boundary_is_a_separator(site, claims):
    site.hold(RICH_URL, RICH)
    file = claims / "denylist.yaml"
    across_items = "The first item of the list ends here The second item of the list starts here"

    assert pin_url(file, across_items, url=RICH_URL, id="items") == 0
    assert pin_url(file, "Hosts refused in the sample 12 of 40", url=RICH_URL, id="cells") == 1
    assert pin_url(file, "Hosts refused in the sample | 12 of 40", url=RICH_URL, id="row") == 0

    text = V.extract(site.library.store / sha(RICH), None, "html-text")
    assert "ends here\nThe second item" in text
    assert set(read(file)["claims"]) == {"items", "row"}


def test_a_page_served_as_plain_text_is_read_as_its_bytes(site, claims):
    site.types_sent[RICH_URL] = "text/plain"
    site.pages[RICH_URL] = RICH
    file = claims / "denylist.yaml"

    assert pin_url(file, "it is <em>checked twice</em> on every capture", url=RICH_URL) == 0
    assert pin_url(file, "it is checked twice on every capture", url=RICH_URL, id="read") == 1

    source = read(file)["source"]
    assert source["extract_cmd"] == "cat {}"
    assert "extractor" not in source and "derived_sha256" not in source


def test_verify_reads_a_pinned_page_with_retrieved_not_importable(
    site, claims, capsys, monkeypatch
):
    site.hold(RICH_URL, RICH)
    quote = "The denylist is the security boundary, and it is checked twice on every capture."
    assert pin_url(claims / "denylist.yaml", quote, url=RICH_URL) == 0
    real = builtins.__import__

    def absent(name, *args, **kwargs):
        if name.split(".")[0] == "retrieved":
            raise ImportError(f"No module named {name!r}")
        return real(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", absent)

    code, out = verify(claims, capsys)

    assert code == 0, out
    assert count("found", out) == 1


def test_a_local_html_file_is_read_as_its_source_unless_it_names_the_extractor(tmp_path, capsys):
    (tmp_path / "page.html").write_bytes(RICH)
    folder = tmp_path / "claims"
    folder.mkdir()
    raw = "it is\n<em>checked twice</em> on every capture"
    shown = "it is checked twice on every capture"
    (folder / "as-source.yaml").write_text("source:\n  local: page.html\nclaims: {}\n")
    (folder / "as-text.yaml").write_text(
        "source:\n  local: page.html\n  extractor: html-text\nclaims: {}\n"
    )

    assert pin.main([str(folder / "as-source.yaml"), "--id", "raw", "--quote", raw]) == 0
    assert pin.main([str(folder / "as-source.yaml"), "--id", "shown", "--quote", shown]) == 1
    assert pin.main([str(folder / "as-text.yaml"), "--id", "shown", "--quote", shown]) == 0
    assert pin.main([str(folder / "as-text.yaml"), "--id", "raw", "--quote", raw]) == 1


def test_with_no_library_anywhere_one_is_made_beside_the_claims_directory(
    site, claims, tmp_path, monkeypatch
):
    monkeypatch.delenv("RETRIEVED_HOME")
    site.pages[URL] = PAGE
    cwd = tmp_path / "somewhere-else"
    cwd.mkdir()
    monkeypatch.chdir(cwd)

    assert pin_url(claims / "guide.yaml", PASSAGE) == 0

    assert (claims.parent / ".retrieved" / "store" / sha(PAGE)).read_bytes() == PAGE
    assert not (cwd / ".retrieved").exists()
    assert load_claim_file(claims / "guide.yaml").artifact() == (
        claims.parent / ".retrieved" / "store" / sha(PAGE)
    )


@pytest.mark.parametrize("where", ["named by the variable", "above the project", "nowhere"])
def test_the_library_is_the_one_retrieved_resolves_from_the_project(tmp_path, monkeypatch, where):
    project = tmp_path / "group" / "paper"
    project.mkdir(parents=True)
    monkeypatch.delenv("RETRIEVED_HOME", raising=False)
    expected = project / ".retrieved"
    if where == "named by the variable":
        expected = tmp_path / "shared"
        monkeypatch.setenv("RETRIEVED_HOME", str(expected))
    if where == "above the project":
        expected = tmp_path / "group" / ".retrieved"
        expected.mkdir()

    assert paths.retrieved_library(project) == expected.resolve()
    assert paths.retrieved_library(project) == Library.resolve(project).root


@pytest.fixture
def downloads(monkeypatch):
    bodies: dict[str, bytes] = {}
    monkeypatch.setattr(F, "download", lambda url: bodies.get(url))
    monkeypatch.setattr(F.resolve, "get", lambda url, as_json: None)
    return bodies


def test_fetch_says_a_page_that_no_longer_matches_may_have_changed_and_keeps_nothing(
    site, claims, downloads
):
    site.hold(URL, PAGE)
    assert pin_url(claims / "guide.yaml", PASSAGE) == 0
    blob = site.library.store / sha(PAGE)
    blob.unlink()
    downloads[URL] = CHANGED

    outcome = F.fetch_one(load_claim_file(claims / "guide.yaml"))

    assert outcome.state == "differs"
    assert f"may have changed since it was retrieved at {LONG_AGO}" in outcome.detail
    assert sha(CHANGED)[:12] in outcome.detail
    assert list(site.library.store.iterdir()) == []


def test_fetch_keeps_a_page_that_still_has_the_pinned_bytes_and_verify_reads_it(
    site, claims, downloads, capsys, tmp_path, monkeypatch
):
    site.hold(URL, PAGE)
    assert pin_url(claims / "guide.yaml", PASSAGE) == 0
    elsewhere = tmp_path / "a-readers-machine"
    monkeypatch.setenv("RETRIEVED_HOME", str(elsewhere))
    downloads[URL] = PAGE

    assert F.fetch_one(load_claim_file(claims / "guide.yaml")).state == "fetched"

    assert (elsewhere / "store" / sha(PAGE)).read_bytes() == PAGE
    code, out = verify(claims, capsys)
    assert code == 0, out
