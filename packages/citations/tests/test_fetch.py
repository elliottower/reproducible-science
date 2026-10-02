"""A reader who clones a repository has every pin and no source.

`fetch` downloads what a claims directory pins and installs a copy only when its sha256 is the
pinned one. The property under test throughout is that the pinned path never ends up holding
bytes the pin does not name, whatever a server answers.
"""

from __future__ import annotations

import hashlib

import pytest
import yaml
from citations import fetch as F
from citations.models import load_claim_file

PAPER = b"%PDF-1.7 the bytes of the paper the author read"
OTHER = b"<html>a landing page, or the same paper stamped with a download date</html>"


def claim_file(tmp_path, body=PAPER, **source):
    claims = tmp_path / "claims"
    claims.mkdir(exist_ok=True)
    fields = {"local": "reading/paper.pdf", "sha256": hashlib.sha256(body).hexdigest()} | source
    path = claims / "paper.yaml"
    path.write_text(yaml.safe_dump({"source": fields, "claims": {}}))
    return load_claim_file(path)


@pytest.fixture
def served(monkeypatch):
    """What each URL answers with, and a record of every URL that was asked."""
    bodies: dict[str, bytes | None] = {}
    asked: list[str] = []

    def download(url):
        asked.append(url)
        return bodies.get(url)

    monkeypatch.setattr(F, "download", download)
    monkeypatch.setattr(F.resolve, "get", lambda url, as_json: None)
    return bodies, asked


def test_bytes_matching_the_pin_are_installed_at_the_pinned_path(tmp_path, served):
    bodies, _ = served
    bodies["https://example.org/paper.pdf"] = PAPER
    cf = claim_file(tmp_path, url="https://example.org/paper.pdf")

    assert F.fetch_one(cf).state == "fetched"
    assert cf.artifact().read_bytes() == PAPER


def test_bytes_that_differ_from_the_pin_are_never_written(tmp_path, served):
    bodies, _ = served
    bodies["https://example.org/paper.pdf"] = OTHER
    cf = claim_file(tmp_path, url="https://example.org/paper.pdf")

    outcome = F.fetch_one(cf)

    assert outcome.state == "differs"
    assert hashlib.sha256(OTHER).hexdigest()[:12] in outcome.detail
    assert not cf.artifact().exists()


def test_a_later_location_is_used_when_an_earlier_one_differs(tmp_path, served, monkeypatch):
    bodies, asked = served
    bodies["https://publisher.example/landing"] = OTHER
    bodies["https://europepmc.org/articles/PMC1?pdf=render"] = PAPER
    monkeypatch.setattr(
        F.resolve,
        "get",
        lambda url, as_json: (
            {"resultList": {"result": [{"pmcid": "PMC1"}]}} if "europepmc" in url else None
        ),
    )
    cf = claim_file(tmp_path, url="https://publisher.example/landing", doi="10.1000/x")

    outcome = F.fetch_one(cf)

    assert outcome.state == "fetched"
    assert outcome.detail.startswith("europepmc")
    assert asked == [
        "https://publisher.example/landing",
        "https://europepmc.org/articles/PMC1?pdf=render",
    ]
    assert cf.artifact().read_bytes() == PAPER


def test_a_source_already_on_disk_is_not_requested(tmp_path, served):
    _, asked = served
    cf = claim_file(tmp_path, url="https://example.org/paper.pdf")
    cf.artifact().parent.mkdir(parents=True)
    cf.artifact().write_bytes(PAPER)

    assert F.fetch_one(cf).state == "present"
    assert asked == []


def test_a_file_that_breaks_its_pin_is_reported_and_left_alone(tmp_path, served):
    bodies, asked = served
    bodies["https://example.org/paper.pdf"] = PAPER
    cf = claim_file(tmp_path, url="https://example.org/paper.pdf")
    cf.artifact().parent.mkdir(parents=True)
    cf.artifact().write_bytes(OTHER)

    assert F.fetch_one(cf).state == "broken"
    assert cf.artifact().read_bytes() == OTHER
    assert asked == []


def test_a_source_with_no_digest_is_never_downloaded(tmp_path, served):
    _, asked = served
    cf = claim_file(tmp_path, url="https://example.org/paper.pdf", sha256="")

    assert F.fetch_one(cf).state == "unpinned"
    assert asked == []


def test_no_answer_from_any_location_is_unavailable_not_differs(tmp_path, served):
    cf = claim_file(tmp_path, url="https://example.org/gone.pdf")

    assert F.fetch_one(cf).state == "unavailable"
    assert not cf.artifact().exists()


def test_a_dry_run_downloads_and_writes_nothing(tmp_path, served):
    bodies, asked = served
    bodies["https://example.org/paper.pdf"] = PAPER
    cf = claim_file(tmp_path, url="https://example.org/paper.pdf")

    assert F.fetch_one(cf, dry_run=True).state == "absent"
    assert asked == []
    assert not cf.artifact().exists()


def test_only_open_pdf_links_are_read_from_europe_pmc():
    payload = {
        "resultList": {
            "result": [
                {
                    "pmcid": "PMC42",
                    "fullTextUrlList": {
                        "fullTextUrl": [
                            {
                                "documentStyle": "pdf",
                                "availabilityCode": "OA",
                                "url": "https://a/open.pdf",
                            },
                            {
                                "documentStyle": "pdf",
                                "availabilityCode": "S",
                                "url": "https://a/paywalled.pdf",
                            },
                            {
                                "documentStyle": "html",
                                "availabilityCode": "OA",
                                "url": "https://a/page",
                            },
                        ]
                    },
                }
            ]
        }
    }

    assert F.europepmc_pdfs(payload) == [
        "https://a/open.pdf",
        "https://europepmc.org/articles/PMC42?pdf=render",
    ]
    assert F.europepmc_pdfs(None) == []


def test_openalex_locations_without_a_pdf_are_skipped():
    payload = {
        "best_oa_location": {"pdf_url": "https://b/best.pdf"},
        "locations": [{"pdf_url": None}, {"pdf_url": "https://b/repository.pdf"}],
    }

    assert F.openalex_pdfs(payload) == ["https://b/best.pdf", "https://b/repository.pdf"]
    assert F.openalex_pdfs({"best_oa_location": None}) == []


def test_an_arxiv_minted_doi_yields_the_arxiv_pdf(tmp_path, served):
    cf = claim_file(tmp_path, doi="10.48550/arXiv.2301.04709")

    assert ("arxiv", "https://arxiv.org/pdf/2301.04709") in F.locate(cf.source)


def test_the_command_fails_while_a_pinned_source_is_missing_and_passes_once_fetched(
    tmp_path, served, capsys
):
    bodies, _ = served
    cf = claim_file(tmp_path, url="https://example.org/paper.pdf")
    claims = str(cf.path.parent)

    assert F.main(["--claims", claims]) == 1
    bodies["https://example.org/paper.pdf"] = PAPER
    assert F.main(["--claims", claims]) == 0
    assert "every pinned source is on disk and matches its pin." in capsys.readouterr().out


@pytest.mark.parametrize(
    "url",
    [
        "https://arxiv.org/abs/2309.08600",
        "https://arxiv.org/abs/2309.08600v2",
        "https://arxiv.org/pdf/2309.08600.pdf",
    ],
)
def test_an_arxiv_page_is_asked_for_as_its_pdf_and_never_as_html(tmp_path, served, url):
    cf = claim_file(tmp_path, url=url)
    expected = "https://arxiv.org/pdf/" + url.rsplit("/", 1)[-1].removesuffix(".pdf")

    assert F.locate(cf.source) == [("arxiv", expected)]


def test_a_source_recording_nowhere_to_ask_is_reported_as_such(tmp_path, served):
    _, asked = served
    cf = claim_file(tmp_path, note="FDA guidance PDF, fda.gov/media/71147/download")

    outcome = F.fetch_one(cf)

    assert outcome.state == "no location"
    assert "url" in outcome.detail and "doi" in outcome.detail
    assert asked == []
    assert F.main(["--claims", str(cf.path.parent)]) == 1
