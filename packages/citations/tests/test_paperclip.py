"""What a remote full-text service must never be allowed to do to a check.

Three ways this integration could quietly corrupt a report, and they are what these pin:

    a prefix of a document pinned as a whole one, so real quotations read `not found`
    a source that could not be fetched reported as a source that contradicts a quote
    a line range from a remote parse treated as an address a result is computed from

The fixtures are Paperclip's own output, recorded from live responses. Nothing here reaches the
network or needs a credential.
"""

from __future__ import annotations

import hashlib

import pytest
import yaml
from citations import import_paperclip, paperclip
from citations import verify as V
from citations.models import load_claim_file
from citations.paperclip import (
    Document,
    PaperclipUnavailableError,
    Resolution,
)

# Recorded from `ls /papers/PMC7254001/`.
LISTING = (
    "meta.json  content.lines  (1626 lines)  sections/  supplements/  figures/\n"
    "  (read-only — use /.gxl/ for writable storage)\n"
    "[360ms]"
)

# Recorded from `lookup doi ... -n 1`. Three id spellings occur across commands.
LOOKUP = """\
Found 1 papers

  1. Sparse Autoencoders Reveal Interpretable Features in Single-Cell Foundation Models
     Flavia Pedrocchi; Florian Barkmann; Amir Joudaki; Valentina Boeva
     22c1bebd-6dc0-1014-8e0e-900874d71cd6 · bioRxiv · 2026-01-01
     https://doi.org/10.1101/2025.10.22.681631

[24ms]"""

PASSAGE = "sparse autoencoders were trained on the hidden representations of three models"


def content(n: int, body: str = "line") -> list[str]:
    return [f"L{i}: {body} {i}" for i in range(1, n + 1)]


class FakeClient:
    """A Paperclip that answers from what it was handed."""

    name = "fake"

    def __init__(self, document: Document | None = None, repo=None, fail: str = "") -> None:
        self._document = document
        self._repo = repo
        self._fail = fail
        self.asked: list[str] = []

    def fetch(self, identifier: str) -> Document:
        self.asked.append(identifier)
        if self._fail:
            raise PaperclipUnavailableError(self._fail)
        return self._document or Document(identifier=identifier)

    def repo(self, name: str):
        if self._fail:
            raise PaperclipUnavailableError(self._fail)
        return self._repo


def pinned_client(text: str = PASSAGE + "\n") -> FakeClient:
    return Document(
        identifier="10.1101/x",
        document_id="doc-1",
        path="/papers/doc-1/content.lines",
        text=text,
        lines=text.count("\n"),
    )


# --- a document that arrived short is never pinned ---------------------------------------------


def test_gutter_is_removed_from_the_text_that_gets_hashed():
    # A gutter left in place lands inside every passage spanning a line break, so a quotation
    # that is genuinely in the paper stops resolving against the copy of it on disk.
    assert paperclip.plain_text(["L1: first", "L2: second"], 2) == "first\nsecond\n"


def test_paperclips_own_truncation_is_refused():
    # Paperclip cuts at 250,000 characters, mid-sentence, and appends this marker. One
    # 2,485-line article arrives as 2,179 lines that way. Pinning the prefix would report
    # every quotation past the cut as `not found`.
    with pytest.raises(paperclip.PaperclipResponseError) as e:
        paperclip.plain_text([*content(2179), "", "[output truncated at 250000 chars]"], 2485)
    assert "2179" in str(e.value)


def test_a_short_body_is_refused_even_with_no_marker():
    # The marker is Paperclip saying so. The extent is what would catch a cut that did not.
    with pytest.raises(paperclip.PaperclipResponseError) as e:
        paperclip.plain_text(content(829), extent=1626)
    assert "829" in str(e.value) and "1626" in str(e.value)


def test_a_document_with_a_hole_in_it_is_refused():
    with pytest.raises(paperclip.PaperclipResponseError):
        paperclip.plain_text(["L1: a", "L2: b", "L9: c"], 3)


def test_a_whole_document_is_accepted():
    # The negative half: a refusal that can never be lifted would be turned off.
    assert paperclip.plain_text(content(3), extent=3) == "line 1\nline 2\nline 3\n"


def test_an_unknown_extent_does_not_block_a_contiguous_document():
    # Nothing saying how long the file is means the completeness check cannot run, which is
    # different from the file being empty.
    assert paperclip.plain_text(content(2), extent=0) == "line 1\nline 2\n"


# --- response furniture is not content ---------------------------------------------------------


def test_the_timing_line_is_not_part_of_the_document():
    lines, status = paperclip.body("L1: real text\n[23ms]")
    assert lines == ["L1: real text"]
    assert status == 0


def test_a_failed_command_reports_its_status_and_reason():
    lines, status = paperclip.body("ERR: vsh: cat: Slab service unavailable\n[exit 1]\n[1.7s]")
    assert status == 1
    assert paperclip.failure(lines) == "vsh: cat: Slab service unavailable"


def test_the_extent_is_the_files_last_line_and_not_what_ls_prints():
    # `ls` prints 1626 for PMC7254001; `tail -n 1` on the same file answers L829, and 829 is
    # what `cat --full` delivers. Believing `ls` refuses a whole document as truncated, and
    # for bioRxiv the two numbers agree, which is what makes the mistake easy to keep.
    assert paperclip.listed_length(LISTING) == 1626
    assert paperclip.last_line_number("L829: the final line of the file\n[30ms]") == 829
    assert paperclip.last_line_number("[30ms]") == 0


def test_every_spelling_of_a_document_id_is_recognized():
    # `search` prints `bio_22c1bebd6dc0` and `lookup` prints the uuid for the same document.
    # Matching only the prefixed form made every bioRxiv DOI resolve to nothing, which reads
    # exactly like a paper nobody indexes.
    assert paperclip.document_ids(LOOKUP) == ["22c1bebd-6dc0-1014-8e0e-900874d71cd6"]
    assert paperclip.document_ids("  PMC8371605 · PMC · 2021") == ["PMC8371605"]
    assert paperclip.document_ids("  bio_22c1bebd6dc0 · bioRxiv") == ["bio_22c1bebd6dc0"]
    assert paperclip.document_ids("https://example.org/PMC8371605") == []


# --- what could not be fetched is unchecked, never a failed citation ---------------------------


def test_a_document_paperclip_does_not_index_is_unresolved(tmp_path):
    r = paperclip.resolve_document("10.1016/paywalled", tmp_path, client=FakeClient())
    assert r.state == "unresolved"
    assert not r.checkable


def test_a_service_that_refused_is_unavailable_and_does_not_raise(tmp_path):
    r = paperclip.resolve_document(
        "10.1/x", tmp_path, client=FakeClient(fail="Slab service unavailable")
    )
    assert r.state == "unavailable"
    assert "Slab" in r.detail


@pytest.mark.parametrize("state", ["unresolved", "unavailable"])
def test_an_unpinnable_source_names_no_local_copy(state):
    # Naming a file that was never fetched is what turns `unchecked` into `not found`: the
    # path would resolve to nothing, or worse to something else, and every quotation under it
    # would read as a passage the source does not contain.
    block = paperclip.source_block(Resolution("10.1/x", state, "why"))
    assert "local" not in block
    assert "sha256" not in block
    assert state in block["note"]


def test_a_quotation_against_an_unpinnable_source_reads_unchecked(tmp_path):
    claims = tmp_path / "claims"
    claims.mkdir()
    block = paperclip.source_block(Resolution("10.1016/paywalled", "unresolved", "no full text"))
    paperclip.write_claim_file(
        claims / "s.yaml",
        block,
        {"c1": {"statement": "x", "quotes": [{"exact": "a passage nobody has a copy to check"}]}},
    )
    cf = load_claim_file(claims / "s.yaml")
    quote = cf.claims["c1"].quotes[0]
    result = V.check_one(quote.text, cf.artifact())
    assert result.state == "unchecked", "no artifact was read, so nothing is absent from one"
    assert result.state != "not found"
    assert V.check_pin(cf.artifact(), cf.source.sha256).state == "missing"


def test_an_unchecked_source_does_not_fail_a_report_but_does_fail_strict():
    # The whole point of keeping the two apart: an unfetchable reference is unremarkable in a
    # draft and unacceptable in a submission, and only the second is `--strict`'s business.
    report = V.Report(checked=1, counts={"unchecked": 1})
    assert report.ok
    assert not report.strict_ok


# --- the extra is optional, and its absence establishes nothing --------------------------------


def test_without_the_extra_the_resolver_reports_unavailable_rather_than_crashing(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(paperclip, "requests", None)
    monkeypatch.delenv(paperclip.KEY_VAR, raising=False)
    r = paperclip.resolve_document("10.1/x", tmp_path)
    assert r.state == "unavailable"
    assert paperclip.EXTRA in r.detail, "the message has to say what to install"
    assert not (tmp_path / "10-1-x.txt").exists()


def test_without_the_extra_a_client_cannot_be_built_and_says_why(monkeypatch):
    monkeypatch.setattr(paperclip, "requests", None)
    with pytest.raises(PaperclipUnavailableError) as e:
        paperclip.default_client()
    assert paperclip.EXTRA in str(e.value)


def test_without_a_credential_the_resolver_reports_unavailable(tmp_path, monkeypatch):
    monkeypatch.setattr(paperclip, "requests", object())
    monkeypatch.delenv(paperclip.KEY_VAR, raising=False)
    r = paperclip.resolve_document("10.1/x", tmp_path)
    assert r.state == "unavailable"
    assert paperclip.KEY_VAR in r.detail


# --- a pinned source is pinned to the bytes on disk --------------------------------------------


def test_a_pinned_source_carries_the_digest_of_the_file_that_was_written(tmp_path):
    text = PASSAGE + "\nand a second line of it\n"
    r = paperclip.resolve_document("10.1101/x", tmp_path, client=FakeClient(pinned_client(text)))
    assert r.state == "pinned"
    assert r.artifact.read_text() == text
    assert r.digest == hashlib.sha256(text.encode()).hexdigest()


def test_a_quotation_from_the_pinned_text_resolves_offline(tmp_path):
    r = paperclip.resolve_document(
        "10.1101/x", tmp_path, client=FakeClient(pinned_client(PASSAGE + "\n"))
    )
    V.extract.cache_clear()
    assert V.check_one(PASSAGE, r.artifact).state == "found"


def test_a_passage_that_is_not_in_the_pinned_text_is_not_found(tmp_path):
    r = paperclip.resolve_document(
        "10.1101/x", tmp_path, client=FakeClient(pinned_client(PASSAGE + "\n"))
    )
    V.extract.cache_clear()
    absent = "the authors conclude that sparse autoencoders are useless for biology"
    assert V.check_one(absent, r.artifact).state == "not found"


def test_editing_the_fetched_file_breaks_its_pin(tmp_path):
    r = paperclip.resolve_document(
        "10.1101/x", tmp_path, client=FakeClient(pinned_client(PASSAGE + "\n"))
    )
    V.sha256.cache_clear()
    r.artifact.write_text("something else entirely")
    V.sha256.cache_clear()
    assert V.check_pin(r.artifact, r.digest).state == "broken"


def test_the_provenance_records_what_was_fetched_and_when(tmp_path):
    r = paperclip.resolve_document(
        "10.1101/x", tmp_path, client=FakeClient(pinned_client(PASSAGE + "\n"))
    )
    block = paperclip.source_block(r, local="sources/paperclip/x.txt")
    stored = paperclip.provenance_of(block)
    assert stored.identifier == "10.1101/x"
    assert stored.document == "doc-1"
    assert stored.path == "/papers/doc-1/content.lines"
    assert stored.fetched.endswith("+00:00")
    assert stored.client == "fake"


def test_the_provenance_survives_a_round_trip_through_the_claims_file(tmp_path):
    r = paperclip.resolve_document(
        "10.1101/x", tmp_path, client=FakeClient(pinned_client(PASSAGE + "\n"))
    )
    path = tmp_path / "claims" / "x.yaml"
    paperclip.write_claim_file(path, paperclip.source_block(r, local="s/x.txt"), {})
    reread = paperclip.provenance_of(load_claim_file(path).source)
    assert reread.identifier == "10.1101/x"
    assert reread.fetched == r.provenance.fetched


# --- a line range is a hint and cannot reach a verified result ---------------------------------


REPO = paperclip.Repo(
    name="review",
    branch="main",
    papers=[
        paperclip.RepoPaper(
            paper_id="doc-1",
            doi="10.1101/x",
            title="A paper with claims committed against it",
            claims=[
                paperclip.RepoClaim(text="Features are polysemantic.", lines="L45-L52"),
                paperclip.RepoClaim(text="Steering changes the output.", lines="L120"),
            ],
        )
    ],
)


def imported(tmp_path, text: str = PASSAGE + "\n"):
    claims = tmp_path / "claims"
    import_paperclip.import_paper(REPO.papers[0], claims, client=FakeClient(pinned_client(text)))
    return claims / "10-1101-x.yaml"


def test_a_line_range_is_recorded_as_a_hint(tmp_path):
    written = yaml.safe_load(imported(tmp_path).read_text())
    hints = {c.get("hint") for c in written["claims"].values()}
    assert hints == {"L45-L52", "L120"}


def test_a_line_range_never_lands_in_the_field_that_is_verified(tmp_path):
    # `page` is the one locator `verify` checks. A line number written there becomes a claim
    # about a page nobody looked at, and every quotation picks up a spurious `page` warning
    # from a scan of a document that has no pages.
    raw = imported(tmp_path).read_text()
    assert "page" not in raw
    for claim in yaml.safe_load(raw)["claims"].values():
        for quote in claim["quotes"]:
            assert "page" not in quote


def test_the_hint_does_not_change_what_verify_concludes(tmp_path):
    # If the range were an address, moving it would move the answer. It is not, so it cannot.
    path = imported(tmp_path)
    document = yaml.safe_load(path.read_text())
    artifact = load_claim_file(path).artifact()
    V.extract.cache_clear()
    for hint in ("L1-L2", "L9999-L10000", None):
        document["claims"]["present"] = {
            "statement": "s",
            "hint": hint,
            "quotes": [{"exact": PASSAGE}],
        }
        path.write_text(yaml.safe_dump(document))
        quote = load_claim_file(path).claims["present"].quotes[0]
        assert V.check_one(quote.text, artifact).state == "found"


def test_an_accurate_hint_does_not_rescue_a_passage_that_is_absent(tmp_path):
    path = imported(tmp_path)
    document = yaml.safe_load(path.read_text())
    document["claims"]["absent"] = {
        "statement": "s",
        "hint": "L1-L1",
        "quotes": [{"exact": "a sentence that is nowhere in the pinned document at all"}],
    }
    path.write_text(yaml.safe_dump(document))
    cf = load_claim_file(path)
    V.extract.cache_clear()
    assert V.check_one(cf.claims["absent"].quotes[0].text, cf.artifact()).state == "not found"


def test_the_hint_is_carried_through_the_model_and_stays_unverified(tmp_path):
    claim = load_claim_file(imported(tmp_path)).claims[
        import_paperclip.claim_id("Features are polysemantic.")
    ]
    assert claim.hint == "L45-L52"
    assert claim.quotes == [], "a committed claim is a statement, not a passage from the paper"


# --- an imported claim is a statement, never a quotation ---------------------------------------


def test_a_committed_claim_becomes_a_statement(tmp_path):
    # Paperclip's repo holds the claim as its author wrote it and no verbatim passage. Writing
    # it under `quotes` would have the tool search the source for a sentence nobody says is in
    # it, and report a misquotation invented by a format conversion.
    written = yaml.safe_load(imported(tmp_path).read_text())
    statements = {c["statement"] for c in written["claims"].values()}
    assert statements == {"Features are polysemantic.", "Steering changes the output."}
    assert all(c["quotes"] == [] for c in written["claims"].values())


def test_an_import_never_produces_a_not_found(tmp_path):
    path = imported(tmp_path)
    cf = load_claim_file(path)
    V.extract.cache_clear()
    results = [V.check_one(q.text, cf.artifact()) for c in cf.claims.values() for q in c.quotes]
    assert results == [], "nothing was quoted, so nothing can have failed to resolve"


def test_the_imported_source_is_pinned_relative_to_the_claims_directory(tmp_path):
    path = imported(tmp_path)
    cf = load_claim_file(path)
    assert cf.source.local == f"{paperclip.SOURCES}/10-1101-x.txt"
    assert cf.artifact().exists()
    assert V.check_pin(cf.artifact(), cf.source.sha256).state == "ok"


def test_re_importing_keeps_quotations_somebody_wrote_by_hand(tmp_path):
    path = imported(tmp_path)
    document = yaml.safe_load(path.read_text())
    document["claims"]["mine"] = {"statement": "mine", "quotes": [{"exact": PASSAGE}]}
    path.write_text(yaml.safe_dump(document))

    import_paperclip.import_paper(
        REPO.papers[0], tmp_path / "claims", client=FakeClient(pinned_client())
    )
    again = yaml.safe_load(path.read_text())
    assert again["claims"]["mine"]["quotes"] == [{"exact": PASSAGE}]
    assert again["source"]["sha256"], "the source block is still refreshed"


def test_a_claim_key_does_not_move_when_another_claim_is_inserted():
    first = import_paperclip.claim_id("Features are polysemantic.")
    ids = {import_paperclip.claim_id(c.text) for c in REPO.papers[0].claims}
    assert first in ids
    assert len(ids) == len(REPO.papers[0].claims)


# --- reading a repo's papers -------------------------------------------------------------------


def test_claims_are_read_out_of_a_repo_status_payload():
    papers = paperclip.papers_from_status(
        {
            "papers": {
                "doc-1": {
                    "title": "T",
                    "doi": "10.1/x",
                    "annotations": [
                        {"note": "a claim", "lines": "L4-L9"},
                        {"note": "another", "source_locations": []},
                    ],
                }
            }
        }
    )
    assert [c.text for c in papers[0].claims] == ["a claim", "another"]
    assert [c.lines for c in papers[0].claims] == ["L4-L9", ""]


def test_a_paper_carrying_one_legacy_note_still_imports_its_claim():
    # Reading only the list spelling makes a repo written the other way import as papers with
    # no claims, which looks exactly like a repo nobody has annotated.
    papers = paperclip.papers_from_status({"papers": {"doc-1": {"note": "the only claim"}}})
    assert [c.text for c in papers[0].claims] == ["the only claim"]


def test_a_paper_with_no_doi_is_resolved_by_its_document_id():
    assert paperclip.RepoPaper(paper_id="PMC1").identifier == "PMC1"
    assert paperclip.RepoPaper(paper_id="PMC1", doi="10.1/x").identifier == "10.1/x"


def test_an_empty_annotation_contributes_no_claim():
    papers = paperclip.papers_from_status(
        {"papers": {"doc-1": {"annotations": [{"note": ""}, {"lines": "L1"}]}}}
    )
    assert papers[0].claims == []


# --- the transport, without a network ----------------------------------------------------------


class FakeResponse:
    def __init__(self, payload, status: int = 200) -> None:
        self._payload = payload
        self.status_code = status

    def json(self):
        return self._payload


class FakeSession:
    """Answers the MCP endpoint from a table of command -> printed output."""

    def __init__(self, outputs: dict[str, str], status: int = 200) -> None:
        self.outputs = outputs
        self.status = status
        self.requests: list[dict] = []

    def post(self, url, json, headers, timeout):
        self.requests.append({"url": url, "json": json, "headers": headers})
        command = json["params"]["arguments"]["command"]
        text = next((v for k, v in self.outputs.items() if command.startswith(k)), "")
        return FakeResponse({"result": {"content": [{"type": "text", "text": text}]}}, self.status)

    def get(self, url, timeout, params=None, headers=None):
        return FakeResponse({"version": "0.7.38"}, self.status)


def http(outputs, status: int = 200) -> paperclip.HttpClient:
    return paperclip.HttpClient("secret-key", session=FakeSession(outputs, status))


def test_the_client_learns_the_extent_before_it_judges_the_body():
    session = FakeSession(
        {
            "lookup": LOOKUP,
            "tail -n 1": "L2: second line\n[10ms]",
            "cat --full": "L1: first line\nL2: second line\n[30ms]",
        }
    )
    doc = paperclip.HttpClient("k", session=session).fetch("10.1101/2025.10.22.681631")
    commands = [r["json"]["params"]["arguments"]["command"] for r in session.requests]
    assert commands[1].startswith("tail -n 1 "), "the extent comes from the file, not from `ls`"
    assert not any(c.startswith("ls ") for c in commands), "`ls` counts something else"
    assert commands[2].startswith("cat --full "), "plain `cat` is a preview, not the document"
    assert doc.text == "first line\nsecond line\n"
    assert doc.document_id == "22c1bebd-6dc0-1014-8e0e-900874d71cd6"


def test_a_pmc_document_whose_listing_over_reports_is_still_pinned():
    # The regression this cost: `ls` says 1626, the file ends at L829, and `cat --full`
    # delivers all 829. Reading the extent from `ls` reported a complete document as
    # truncated and refused every PubMed Central paper in a bibliography.
    session = FakeSession(
        {
            "lookup": LOOKUP,
            "ls": "meta.json  content.lines  (1626 lines)\n[10ms]",
            "tail -n 1": "L829: the last line\n[10ms]",
            "cat --full": "\n".join(content(829)) + "\n[30ms]",
        }
    )
    doc = paperclip.HttpClient("k", session=session).fetch("10.1101/x")
    assert doc.lines == 829
    assert doc.text.count("\n") == 829


def test_the_client_refuses_a_truncated_body_rather_than_returning_it():
    client = http(
        {
            "lookup": LOOKUP,
            "tail -n 1": "L2485: the last line\n[10ms]",
            "cat --full": "\n".join(content(2179)) + "\n[output truncated at 250000 chars]\n[30ms]",
        }
    )
    with pytest.raises(paperclip.PaperclipResponseError):
        client.fetch("10.1101/x")


def test_a_document_paperclip_has_never_heard_of_comes_back_empty():
    client = http({"lookup": "No documents found. Exact DOI match not found.\n[29ms]"})
    assert client.fetch("10.9999/nope").text == ""


def test_a_document_id_is_used_directly_without_a_lookup():
    session = FakeSession({"tail -n 1": "L1: only\n[1ms]", "cat --full": "L1: only\n[1ms]"})
    paperclip.HttpClient("k", session=session).fetch("PMC8371605")
    commands = [r["json"]["params"]["arguments"]["command"] for r in session.requests]
    assert not any(c.startswith("lookup") for c in commands)


def test_a_rejected_credential_says_which_variable_carries_it():
    with pytest.raises(PaperclipUnavailableError) as e:
        http({}, status=401).fetch("10.1/x")
    assert paperclip.KEY_VAR in str(e.value)


def test_the_credential_travels_in_the_header_and_nowhere_else():
    session = FakeSession({"lookup": "No documents found.\n[1ms]"})
    paperclip.HttpClient("secret-key", session=session).fetch("10.1/x")
    sent = session.requests[0]
    assert sent["headers"]["X-API-Key"] == "secret-key"
    assert "secret-key" not in yaml.safe_dump(sent["json"])


def test_a_version_endpoint_that_will_not_answer_does_not_sink_the_fetch(tmp_path):
    class NoVersion(FakeSession):
        def get(self, url, timeout, params=None, headers=None):
            raise OSError("no route to host")

    session = NoVersion({"ls": "content.lines  (1 lines)\n[1ms]", "cat --full": "L1: only\n[1ms]"})
    client = paperclip.HttpClient("k", session=session)
    r = paperclip.resolve_document("PMC1", tmp_path, client=client)
    assert r.state == "pinned", "a label nobody could read is not a reason to drop the source"
    assert r.provenance.service_version == ""


def test_a_slug_is_a_filename_and_keeps_the_identifier_legible():
    assert paperclip.slug_for("10.1038/s41586-021-03819-2") == "10-1038-s41586-021-03819-2"
    assert paperclip.slug_for("  ") == "unidentified"


def test_an_unverified_extent_is_recorded_rather_than_inferred():
    # The completeness check cannot run without a declared last line, and a reader of the claims
    # file has to be able to tell that from a fetch where it ran and passed. `lines` cannot carry
    # that: it holds a number either way.
    doc = paperclip.Document(identifier="x", text="a\nb\n", lines=2, extent_verified=False)
    assert doc.extent_verified is False
    assert paperclip.Document(identifier="x", text="a\n", lines=1).extent_verified is True
