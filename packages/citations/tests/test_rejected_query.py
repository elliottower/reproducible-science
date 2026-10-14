"""A 400 answers the query, not the work, and it is not a refusal either.

`resolve.get` has three outcomes besides a payload: the service answered that it has nothing
(404, 410), it rejected the query as malformed or naming nothing it can look up (400, 422), or
it did not answer (401, 403, 429, a 5xx, a timeout). A rejected query is permanent, so it must
never stop a batch as though the services were refusing, and never tell the author to try
again later.
"""

from __future__ import annotations

import email.message
import io
import urllib.error

import pytest
from citations import add as ADD
from citations import fetch as FETCH
from citations import lint as LINT
from citations import resolve as R
from citations.exceptions import CitationsError
from citations.models import ClaimSource

ARXIV_ERROR = (
    '<feed xmlns="http://www.w3.org/2005/Atom"><entry>'
    "<id>http://arxiv.org/api/errors#incorrect_id_format_for_not-an-id</id>"
    "<title>Error</title><summary>incorrect id format for not-an-id</summary>"
    "</entry></feed>"
)


def serve(monkeypatch, routes: dict[str, object]) -> list[str]:
    """Answer from `routes`, first key found in the URL; an int is an HTTP status, a tuple a
    status and its body. An unrouted URL is a 404."""
    asked: list[str] = []

    def urlopen(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else req
        asked.append(url)
        answer = next((v for k, v in routes.items() if k in url), 404)
        code, body = answer if isinstance(answer, tuple) else (answer, "")
        if isinstance(code, int):
            raise urllib.error.HTTPError(
                url, code, f"HTTP {code}", email.message.Message(), io.BytesIO(body.encode())
            )
        return io.BytesIO(str(code).encode())

    monkeypatch.setattr(R.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(R.time, "sleep", lambda _: None)
    return asked


@pytest.mark.parametrize("code", [400, 422])
def test_a_rejected_query_is_neither_absent_nor_refused(monkeypatch, code):
    serve(monkeypatch, {"example.org": (code, "bad query")})
    with pytest.raises(R.Rejected) as caught:
        R.get("https://example.org/q", as_json=True)
    assert caught.value.body == "bad query"


def test_a_batch_whose_queries_are_all_rejected_is_never_stopped(tmp_path, monkeypatch, capsys):
    home = tmp_path / "lib"
    (home / "records").mkdir(parents=True)
    for i in range(6):
        (home / "records" / f"r{i}.yaml").write_text(
            f"slug: r{i}\ntitle: 'A title: with (parens) {i}'\nauthors: [Doe, Jane]\nyear: '2019'\n"
        )
    monkeypatch.setenv("CITATIONS_HOME", str(home))
    asked = serve(monkeypatch, {"": 400})

    assert R.main(["--check"]) == 0

    printed = capsys.readouterr().out
    assert len(asked) == 6 * len(R.SERVICES), "a rejected query counted toward the stop"
    assert "BLOCKED" not in printed
    assert "Re-run later" not in printed
    assert "resolved 0 of 6\n" in printed


def test_add_says_a_rejected_doi_is_malformed_or_unknown(tmp_path, monkeypatch):
    serve(monkeypatch, {"api.crossref.org": 400, "api.datacite.org": 404})
    bib = tmp_path / "references.bib"
    bib.write_text("")
    with pytest.raises(CitationsError) as caught:
        ADD.main([str(bib), "--check", "--doi", "10.1000/<bad>"])
    said = str(caught.value)
    assert "rejected the identifier as malformed or unknown" in said
    assert "try again" not in said


def test_add_reads_the_arxiv_error_feed_a_malformed_identifier_gets(tmp_path, monkeypatch):
    serve(monkeypatch, {"export.arxiv.org": (400, ARXIV_ERROR)})
    bib = tmp_path / "references.bib"
    bib.write_text("")
    with pytest.raises(CitationsError) as caught:
        ADD.main([str(bib), "--check", "--arxiv", "not-an-id"])
    said = str(caught.value)
    assert "arXiv rejected the identifier as malformed or unknown" in said
    assert "incorrect id format for not-an-id" in said
    assert "try again" not in said
    assert bib.read_text() == ""


def test_add_still_says_try_again_for_a_refusal(tmp_path, monkeypatch):
    serve(monkeypatch, {"api.crossref.org": 403})
    bib = tmp_path / "references.bib"
    bib.write_text("")
    with pytest.raises(CitationsError, match="try again later"):
        ADD.main([str(bib), "--check", "--doi", "10.1000/x"])


def test_lint_authors_reads_a_rejected_identifier_as_no_names(tmp_path, monkeypatch):
    serve(monkeypatch, {"": 400})
    bib = tmp_path / "refs.bib"
    bib.write_text(
        "@article{a2012,\n  title = {T},\n  author = {Doe, Jane},\n  doi = {10.1/a}\n}\n"
    )
    report = LINT.check_authors(bib)
    assert (report.checked, report.unresolved, report.findings) == (0, 1, [])


def test_fetch_locate_reads_a_rejected_identifier_as_no_copies(monkeypatch):
    serve(monkeypatch, {"": 400})
    assert FETCH.locate(ClaimSource(doi="10.1093/hmg/dds213", citation="x")) == []
