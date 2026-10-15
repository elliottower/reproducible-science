"""An operator's API key is sent where it is needed, and recorded nowhere.

A key in a URL ends up in a cache file's name and envelope, in a printed line and in an
exception, and `.audit-cache/` is committed beside the bibliography. OpenAlex's key travels as
a bearer header and Semantic Scholar's as `x-api-key`, so neither is ever part of a URL. The
OpenAlex key is a fallback: sent only on the retry of a request OpenAlex refused unkeyed.
"""

from __future__ import annotations

import io
import json
import pathlib
import urllib.error
import urllib.parse

from citations import audit as A
from citations import resolve as R

OPENALEX_KEY = "oa-FAKE-key-3141592653"
S2_KEY = "s2-FAKE-key-2718281828"


def _everything_recorded(cache: pathlib.Path, *texts: str) -> str:
    recorded = list(texts)
    for f in sorted(cache.rglob("*")):
        recorded.append(f.name)
        if f.is_file():
            recorded.append(f.read_text(errors="replace"))
    return "\n".join(recorded)


def test_keys_are_sent_and_never_recorded(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("OPENALEX_API_KEY", OPENALEX_KEY)
    monkeypatch.setenv("SEMANTIC_SCHOLAR_API_KEY", S2_KEY)
    monkeypatch.setattr(A.time, "sleep", lambda _: None)
    monkeypatch.setattr(R.time, "sleep", lambda _: None)
    sent: list[tuple[str, dict]] = []

    def urlopen(req, timeout=None):
        url = req.full_url
        sent.append((url, dict(req.header_items())))
        host = urllib.parse.urlsplit(url).hostname
        if host == "api.semanticscholar.org":
            # A refusal: the path that raises and is retried.
            raise urllib.error.HTTPError(url, 429, "Too Many Requests", None, io.BytesIO())
        if host == "api.openalex.org" and "Authorization" not in dict(req.header_items()):
            # OpenAlex refuses every unkeyed request: the fallback is what answers.
            raise urllib.error.HTTPError(url, 429, "Too Many Requests", None, io.BytesIO())
        if host == "api.openalex.org" and "/sources" in url:
            body = {"results": []}
        elif host == "api.openalex.org":
            body = {
                "results": [
                    {
                        "id": "https://openalex.org/W1",
                        "doi": "https://doi.org/10.1234/x",
                        "display_name": "A Title",
                        "publication_year": 2020,
                        "authorships": [{"author": {"display_name": "Ann Smith"}}],
                        "primary_location": {
                            "source": {
                                "id": "https://openalex.org/S1",
                                "display_name": "Some Journal",
                                "issn_l": "1234-5678",
                                "type": "journal",
                            }
                        },
                    }
                ]
            }
        elif host == "api.crossref.org" and "/works/" in url:
            body = {
                "message": {
                    "title": ["A Title"],
                    "type": "journal-article",
                    "ISSN": ["1234-5678"],
                    "container-title": ["Some Journal"],
                    "issued": {"date-parts": [[2020]]},
                    "author": [{"family": "Smith", "given": "Ann"}],
                }
            }
        elif host == "www.wikidata.org":
            body = {"search": [], "query": {"search": []}, "entities": {}}
        else:
            body = {"message": {"items": []}}
        return io.BytesIO(json.dumps(body).encode())

    monkeypatch.setattr(R.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(A.urllib.request, "urlopen", urlopen)
    cache = tmp_path / "cache"
    entry = A.Entry(
        key="k", title="A Title", authors=["Smith, Ann"], year="2020", venue="Some Journal"
    )

    report = A.audit([entry], cache)
    A.render(report, quiet=False)
    out = tmp_path / "report.json"
    out.write_text(report.model_dump_json(indent=2))
    refusal = ""
    try:
        R.get(
            "https://api.semanticscholar.org/graph/v1/paper/x",
            as_json=True,
            tries=1,
            headers={"x-api-key": S2_KEY},
        )
    except R.Throttled as exc:
        refusal = f"{exc!r} {exc}"

    openalex = [h for u, h in sent if urllib.parse.urlsplit(u).hostname == "api.openalex.org"]
    s2 = [h for u, h in sent if urllib.parse.urlsplit(u).hostname == "api.semanticscholar.org"]
    unkeyed = [h for h in openalex if "Authorization" not in h]
    keyed = [h for h in openalex if h.get("Authorization") == f"Bearer {OPENALEX_KEY}"]
    assert unkeyed and keyed and len(unkeyed) + len(keyed) == len(openalex)
    assert s2 and all(h.get("X-api-key") == S2_KEY for h in s2)
    captured = capsys.readouterr()
    recorded = _everything_recorded(
        cache, out.read_text(), captured.out, captured.err, refusal, *(u for u, _ in sent)
    )
    assert OPENALEX_KEY not in recorded
    assert S2_KEY not in recorded


def test_an_unkeyed_answer_never_sends_the_key(monkeypatch):
    monkeypatch.setenv("OPENALEX_API_KEY", OPENALEX_KEY)
    sent: list[dict] = []

    def urlopen(req, timeout=None):
        sent.append(dict(req.header_items()))
        return io.BytesIO(b'{"results": []}')

    monkeypatch.setattr(R.urllib.request, "urlopen", urlopen)
    assert R.get("https://api.openalex.org/sources?search=x", as_json=True) == {"results": []}
    assert sent and all("Authorization" not in h for h in sent)


def test_no_key_is_sent_where_none_is_set_or_to_another_host(monkeypatch):
    monkeypatch.delenv("OPENALEX_API_KEY", raising=False)
    assert R.credentials("https://api.openalex.org/works?search=x") == {}
    monkeypatch.setenv("OPENALEX_API_KEY", OPENALEX_KEY)
    assert R.credentials("https://api.crossref.org/works?query=x") == {}
    assert R.credentials("https://www.wikidata.org/w/api.php") == {}
