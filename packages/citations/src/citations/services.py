"""The sources a missing identifier can be looked up in, declared rather than coded.

Each service differs in three ways and no others: the URL a record turns into, the format the
answer arrives in, and where the fields live inside it. Everything after that -- how close a
title has to be, whether the first author's surname has to appear, whether the year has to
agree, how the venue breaks a tie -- is one rule applied to every service alike.

Writing that rule four times is how the four copies drift. `try_crossref` checked the year and
`try_arxiv` did not, so an arXiv lookup would accept a paper from any year with a close enough
title. Here the rule lives in `match()` and a service supplies only `Candidate`s.

Adding a service is a `Service(...)` literal: build a URL, turn a payload into candidates.
"""

from __future__ import annotations

import re
import urllib.parse
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict

from citations.models import Record
from citations.text import surname_variants


class Candidate(BaseModel):
    """One work a service offered, in the only shape the matcher reads.

    Normalizing here rather than in the matcher is what lets one rule serve every service: a
    Crossref author list, an arXiv `<name>` element and an OpenAlex authorship object are three
    payloads and one set of surnames.
    """

    model_config = ConfigDict(frozen=True)

    title: str = ""
    """The work's title, as the service returned it."""

    surnames: frozenset[str] = frozenset()
    """Normalized family names of every listed author."""

    year: int | None = None
    """Publication year, where the service reports one."""

    venue: str = ""
    """Journal, conference or repository, used only to break ties between versions."""

    identifier: tuple[str, str] | None = None
    """`(kind, value)` -- e.g. `("doi", "10.1145/3442188")`. A candidate without one cannot be
    accepted no matter how well it matches, since there would be nothing to store."""


@dataclass(frozen=True)
class Service:
    """One lookup source.

    A plain dataclass rather than a pydantic model: the fields are functions, which is code
    rather than data, and there is no external payload here to validate. Pydantic guards the
    boundary where YAML and HTTP responses come in -- `Candidate` above, and `models.py`.
    """

    name: str
    """Shown in output and used to report which service answered."""

    url: Callable[[Record], str]
    """The record turned into a request URL."""

    candidates: Callable[[object], Iterable[Candidate]]
    """A decoded payload turned into candidates. Raises nothing; an unusable payload is
    an empty iterable, which the caller reads as `answered, had nothing`."""

    json: bool = True
    """Whether the payload is JSON. arXiv answers in Atom XML and is parsed as text."""

    needs_key: str | None = None
    """Environment variable holding an API key, where anonymous quota is too low to trust an
    empty answer."""


# --------------------------------------------------------------------------------------------
# Crossref
# --------------------------------------------------------------------------------------------


def _crossref_url(rec: Record) -> str:
    q = urllib.parse.urlencode({"query.bibliographic": rec.title, "rows": 8})
    return f"https://api.crossref.org/works?{q}"


def _crossref_candidates(payload) -> list[Candidate]:
    for item in (payload or {}).get("message", {}).get("items", []):
        parts = ((item.get("issued") or {}).get("date-parts") or [[None]])[0]
        doi = item.get("DOI")
        yield Candidate(
            title=(item.get("title") or [""])[0],
            surnames=frozenset().union(
                *(surname_variants(a.get("family", "")) for a in item.get("author", []))
                or [frozenset()]
            ),
            year=parts[0] if parts else None,
            venue=(item.get("container-title") or [""])[0],
            identifier=("doi", doi) if doi else None,
        )


# --------------------------------------------------------------------------------------------
# Semantic Scholar -- indexes preprints and workshop papers Crossref has never seen
# --------------------------------------------------------------------------------------------


def _s2_url(rec: Record) -> str:
    q = urllib.parse.urlencode(
        {"query": rec.title[:250], "limit": 6, "fields": "title,externalIds,authors,year,venue"}
    )
    return f"https://api.semanticscholar.org/graph/v1/paper/search?{q}"


def _s2_candidates(payload) -> list[Candidate]:
    for item in (payload or {}).get("data") or []:
        ext = item.get("externalIds") or {}
        ident = (
            ("doi", ext["DOI"])
            if ext.get("DOI")
            else ("arxiv", ext["ArXiv"])
            if ext.get("ArXiv")
            else None
        )
        yield Candidate(
            title=item.get("title") or "",
            surnames=frozenset().union(
                *(surname_variants(a.get("name", "")) for a in (item.get("authors") or []))
                or [frozenset()]
            ),
            year=item.get("year"),
            venue=item.get("venue") or "",
            identifier=ident,
        )


# --------------------------------------------------------------------------------------------
# OpenAlex -- books, reports and preprints Crossref does not carry
# --------------------------------------------------------------------------------------------


def _openalex_url(rec: Record) -> str:
    q = urllib.parse.urlencode(
        {"filter": f"title.search:{rec.title}", "per-page": 5, "mailto": "elliot@elliottower.ai"}
    )
    return f"https://api.openalex.org/works?{q}"


def _openalex_candidates(payload) -> list[Candidate]:
    for work in (payload or {}).get("results", []):
        doi = (work.get("doi") or "").replace("https://doi.org/", "")
        if doi.startswith("10.48550/arxiv."):
            ident = ("arxiv", doi.split("arxiv.")[-1])
        elif doi:
            ident = ("doi", doi)
        else:
            oid = (work.get("id") or "").rsplit("/", 1)[-1]
            ident = ("openalex", oid) if oid else None
        yield Candidate(
            title=work.get("display_name") or "",
            surnames=frozenset().union(
                *(
                    surname_variants((a.get("author") or {}).get("display_name", ""))
                    for a in (work.get("authorships") or [])
                )
                or [frozenset()]
            ),
            year=work.get("publication_year"),
            venue=((work.get("primary_location") or {}).get("source") or {}).get("display_name")
            or "",
            identifier=ident,
        )


# --------------------------------------------------------------------------------------------
# arXiv -- Atom XML, not JSON
# --------------------------------------------------------------------------------------------

_ENTRY = re.compile(r"<entry>(.*?)</entry>", re.S)
_TITLE = re.compile(r"<title>(.*?)</title>", re.S)
_ID = re.compile(r"<id>(.*?)</id>")
_NAME = re.compile(r"<name>(.*?)</name>")
_PUBLISHED = re.compile(r"<published>(\d{4})-")


def _arxiv_url(rec: Record) -> str:
    q = urllib.parse.urlencode({"search_query": f'ti:"{rec.title}"', "max_results": 4})
    return f"https://export.arxiv.org/api/query?{q}"


def _arxiv_candidates(payload) -> list[Candidate]:
    for entry in _ENTRY.findall(payload or ""):
        tm, im = _TITLE.search(entry), _ID.search(entry)
        if not (tm and im):
            continue
        ym = _PUBLISHED.search(entry)
        yield Candidate(
            title=" ".join(tm.group(1).split()),
            surnames=frozenset().union(
                *(surname_variants(n) for n in _NAME.findall(entry)) or [frozenset()]
            ),
            # The year was not checked here before, so an arXiv lookup would accept a paper
            # from any year whose title was close enough. It is checked now, like every other
            # service, because the rule lives in one place.
            year=int(ym.group(1)) if ym else None,
            venue="arXiv",
            identifier=("arxiv", re.sub(r"v\d+$", "", im.group(1).split("/abs/")[-1])),
        )


#: Tried in this order for each record. The refusal threshold is this tuple's length, so
#: adding a service cannot leave a stale literal behind.
SERVICES: tuple[Service, ...] = (
    Service("semanticscholar", _s2_url, _s2_candidates, needs_key="SEMANTIC_SCHOLAR_API_KEY"),
    Service("crossref", _crossref_url, _crossref_candidates),
    Service("openalex", _openalex_url, _openalex_candidates),
    Service("arxiv", _arxiv_url, _arxiv_candidates, json=False),
)
