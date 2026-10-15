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

import os
import re
import urllib.parse
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as package_version
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from citations.text import surname_variants

#: Crossref and OpenAlex ask for a contact address and offer politeness-pool rate limits in
#: return, so the header carries one when the operator sets it. Two modules hardcoded the
#: author's address, which sent one person's email to every server that every user of this
#: package queried, and named the wrong party as the operator besides.
CONTACT_ENV = "CITATIONS_CONTACT"


def contact() -> str:
    """The operator's address for polite-pool requests, or empty where none is set."""
    return os.environ.get(CONTACT_ENV, "").strip()


def product() -> str:
    """`citations/<installed version>`, the product token every request names."""
    try:
        return f"citations/{package_version('citations')}"
    except PackageNotFoundError:  # a source tree with nothing installed
        return "citations/0+unknown"


def user_agent() -> str:
    """The `User-Agent` for outbound metadata requests, with a contact only if one is set."""
    return f"{product()} (mailto:{contact()})" if contact() else product()


def polite(params: dict) -> dict:
    """`params` with a `mailto` added only where the operator set one.

    OpenAlex reads `mailto` as the request's owner and routes it to the polite pool. An address
    written in here makes every user's lookups claim to be one person's, so it is opt-in.
    """
    return {**params, "mailto": contact()} if contact() else params


class Work(Protocol):
    """What a search reads off the thing it is looking up: a library `Record`, or one entry of
    a bibliography under `citations audit`. One matching rule serves both because both are
    read through these four fields and no others."""

    @property
    def title(self) -> str: ...

    @property
    def authors(self) -> list[str]: ...

    @property
    def year(self) -> str: ...

    @property
    def venue(self) -> str: ...


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
    """Journal, conference or repository, used to break ties between versions."""

    venues: tuple[str, ...] = ()
    """Every name the service gives the venue: `venue`, and short and alternate names where the
    service has them. `citations audit` compares an entry's venue with these."""

    venue_kind: str = ""
    """`journal`, `proceedings`, `preprint`, `series`, or empty where the service does not say."""

    venue_ids: tuple[str, ...] = ()
    """Identifiers of the venue the service files the work under: `issn:...`,
    `openalex:S...`."""

    series_ids: tuple[str, ...] = ()
    """Identifiers of a book series the work is in, such as Lecture Notes in Computer Science.
    A series is not the venue, so these can confirm a venue and never contradict one."""

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

    url: Callable[[Work], str]
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


def _crossref_url(rec: Work) -> str:
    q = urllib.parse.urlencode({"query.bibliographic": rec.title, "rows": 8})
    return f"https://api.crossref.org/works?{q}"


#: Crossref work types, read as the kind of venue the work appeared in.
CROSSREF_KINDS = {
    "journal-article": "journal",
    "proceedings-article": "proceedings",
    "posted-content": "preprint",
}


def crossref_venue_ids(item: dict) -> tuple[list[str], list[str]]:
    """The ISSNs a Crossref work carries: the journal's for an article, the book series' for
    a chapter or a proceedings paper deposited with an ISBN."""
    issns = [f"issn:{i}" for i in item.get("ISSN") or [] if i]
    if item.get("type") == "journal-article":
        return issns, []
    return [], issns


def crossref_venues(item: dict) -> list[str]:
    """Every venue name a Crossref work carries: container titles, short titles, the event.

    A Springer conference paper has two container titles, the series (`Lecture Notes in
    Computer Science`) and the volume (`Computer Vision – ECCV 2020`), and an ACM one names its
    event's acronym (`KDD '16`) only under `event`. A preprint names its server only under
    `institution`.
    """
    event = item.get("event") or {}
    names = [
        *(item.get("container-title") or []),
        *(item.get("short-container-title") or []),
        event.get("name") or "",
        event.get("acronym") or "",
    ]
    if item.get("type") == "posted-content":
        names += [i.get("name") or "" for i in item.get("institution") or []]
    return [n for n in dict.fromkeys(names) if n]


def _crossref_candidates(payload) -> Iterator[Candidate]:
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
            venues=tuple(crossref_venues(item)),
            venue_kind=CROSSREF_KINDS.get(item.get("type") or "", ""),
            venue_ids=tuple(crossref_venue_ids(item)[0]),
            series_ids=tuple(crossref_venue_ids(item)[1]),
            identifier=("doi", doi) if doi else None,
        )


# --------------------------------------------------------------------------------------------
# Semantic Scholar -- indexes preprints and workshop papers Crossref has never seen
# --------------------------------------------------------------------------------------------


def _s2_url(rec: Work) -> str:
    q = urllib.parse.urlencode(
        {
            "query": rec.title[:250],
            "limit": 6,
            "fields": "title,externalIds,authors,year,venue,publicationVenue,journal",
        }
    )
    return f"https://api.semanticscholar.org/graph/v1/paper/search?{q}"


#: Semantic Scholar's `publicationVenue.type`, read as a kind of venue.
S2_KINDS = {"journal": "journal", "conference": "proceedings"}


def s2_venues(item: dict) -> tuple[list[str], str]:
    """Every venue name a Semantic Scholar paper carries, and the kind of venue.

    `publicationVenue.alternate_names` is where the short forms live: `NeurIPS`, `NIPS` and
    `Neural Inf Process Syst` for `Neural Information Processing Systems`.
    """
    pv = item.get("publicationVenue") or {}
    names = [
        item.get("venue") or "",
        pv.get("name") or "",
        *(pv.get("alternate_names") or []),
        (item.get("journal") or {}).get("name") or "",
    ]
    return [n for n in dict.fromkeys(names) if n], S2_KINDS.get(pv.get("type") or "", "")


#: OpenAlex `source.type`, read as a kind of venue. A book series is not a venue.
OPENALEX_KINDS = {
    "journal": "journal",
    "conference": "proceedings",
    "repository": "preprint",
    "book series": "series",
}


def openalex_venue_ids(work: dict) -> tuple[list[str], list[str]]:
    """The identifiers of an OpenAlex work's primary source: venue ids, or series ids where
    OpenAlex types the source as a book series."""
    source = (work.get("primary_location") or {}).get("source") or {}
    oid = (source.get("id") or "").rsplit("/", 1)[-1]
    ids = [f"openalex:{oid}"] if oid else []
    ids += [
        f"issn:{i}" for i in dict.fromkeys([source.get("issn_l"), *(source.get("issn") or [])]) if i
    ]
    if source.get("type") == "book series":
        return [], ids
    return ids, []


def openalex_venues(work: dict) -> tuple[list[str], str, str]:
    """The venue names of an OpenAlex work's primary location, its kind, and the source id.

    The source id is where the alternate titles are: a work carries only the display name.
    """
    loc = work.get("primary_location") or {}
    source = loc.get("source") or {}
    names = [source.get("display_name") or "", loc.get("raw_source_name") or ""]
    return (
        [n for n in dict.fromkeys(names) if n],
        OPENALEX_KINDS.get(source.get("type") or "", ""),
        (source.get("id") or "").rsplit("/", 1)[-1],
    )


def s2_venue_ids(item: dict) -> list[str]:
    """The ISSNs Semantic Scholar gives the paper's venue."""
    pv = item.get("publicationVenue") or {}
    return [f"issn:{i}" for i in [pv.get("issn"), *(pv.get("alternate_issns") or [])] if i]


def _s2_candidates(payload) -> Iterator[Candidate]:
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
            venues=tuple(s2_venues(item)[0]),
            venue_kind=s2_venues(item)[1],
            venue_ids=tuple(s2_venue_ids(item)),
            identifier=ident,
        )


# --------------------------------------------------------------------------------------------
# OpenAlex -- books, reports and preprints Crossref does not carry
# --------------------------------------------------------------------------------------------


def _openalex_url(rec: Work) -> str:
    q = urllib.parse.urlencode(polite({"filter": f"title.search:{rec.title}", "per-page": 5}))
    return f"https://api.openalex.org/works?{q}"


def _openalex_candidates(payload) -> Iterator[Candidate]:
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
            venues=tuple(openalex_venues(work)[0]),
            venue_kind=openalex_venues(work)[1],
            venue_ids=tuple(openalex_venue_ids(work)[0]),
            series_ids=tuple(openalex_venue_ids(work)[1]),
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


def _arxiv_url(rec: Work) -> str:
    q = urllib.parse.urlencode({"search_query": f'ti:"{rec.title}"', "max_results": 4})
    return f"https://export.arxiv.org/api/query?{q}"


def _arxiv_candidates(payload) -> Iterator[Candidate]:
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
            venues=("arXiv",),
            venue_kind="preprint",
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


# --------------------------------------------------------------------------------------------
# Lookup by identifier -- the reverse question
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Registry:
    """One source that answers who wrote the work an identifier names.

    `Service` above searches by title for a work whose identifier we do not have, and needs the
    whole matching rule to decide whether what came back is the right paper. This asks the
    reverse question and needs none of it: the identifier names one work, and the only field
    read back is the author list, in the order the registry publishes it.
    """

    name: str
    """Shown in output and stored beside a cached list, so a reader can see who said it."""

    kinds: tuple[str, ...]
    """Identifier kinds this registry answers for: `doi`, `arxiv`, or both."""

    url: Callable[[str, str], str]
    """`(kind, identifier)` turned into a request URL."""

    authors: Callable[[object], list[str]]
    """A decoded payload turned into author names in publication order, each written however
    the registry writes it. An unusable payload is an empty list, which the caller reads as
    `answered, had nothing` rather than as a work with no authors."""

    json: bool = True
    """Whether the payload is JSON. arXiv answers in Atom XML and is parsed as text."""


def _crossref_work_url(_kind: str, identifier: str) -> str:
    return f"https://api.crossref.org/works/{urllib.parse.quote(identifier, safe='')}"


def _crossref_work_authors(payload) -> list[str]:
    names = []
    for a in ((payload or {}).get("message") or {}).get("author") or []:
        family = (a.get("family") or "").strip()
        if not family:
            # A consortium is deposited with `name` and neither family nor given. Dropping it
            # shortens the registry's list by one and reports the bibliography as carrying a
            # name too many, which is the opposite of what is wrong.
            group = (a.get("name") or "").strip()
            if group:
                names.append(group)
            continue
        given = (a.get("given") or "").strip()
        names.append(f"{family}, {given}".strip().rstrip(","))
    return names


def _openalex_work_url(kind: str, identifier: str) -> str:
    """OpenAlex keys works by DOI, so an arXiv id is asked as the DOI arXiv mints for it.

    arXiv has minted those only since 2022, so this reaches a recent preprint and answers 404
    for an older one. It is a fallback for when arXiv itself refuses, not a route around it.
    """
    doi = identifier if kind == "doi" else f"10.48550/arXiv.{identifier}"
    q = urllib.parse.urlencode(polite({}))
    return (
        f"https://api.openalex.org/works/doi:{doi}?{q}"
        if q
        else (f"https://api.openalex.org/works/doi:{doi}")
    )


def _openalex_work_authors(payload) -> list[str]:
    # OpenAlex stops at 100 authorships. On a work with more than that it is the one registry
    # that cannot tell a truncated bibliography from a complete one, which is why it is asked
    # after the registry that issued the identifier rather than before it.
    return [
        name
        for a in (payload or {}).get("authorships") or []
        if (name := ((a.get("author") or {}).get("display_name") or "").strip())
    ]


def _arxiv_work_url(_kind: str, identifier: str) -> str:
    return f"https://export.arxiv.org/api/query?{urllib.parse.urlencode({'id_list': identifier})}"


def _arxiv_work_authors(payload) -> list[str]:
    entries = _ENTRY.findall(payload or "")
    if len(entries) != 1:
        # `id_list` names one work. A feed carrying none is arXiv's error document, and one
        # carrying several answers a query this did not make; reading names out of either
        # would compare a bibliography against the wrong paper.
        return []
    return [" ".join(n.split()) for n in _NAME.findall(entries[0])]


#: Asked in this order, and the first list that comes back is used. Each identifier is put to
#: the body that issued it before the aggregator: Crossref registers the DOIs, arXiv publishes
#: its own metadata, and OpenAlex covers what falls between them.
#:
#: Semantic Scholar is not here. Its anonymous quota is low enough that a refusal is ordinary,
#: and a refusal read as "this work has no authors" turns a check into silence.
REGISTRIES: tuple[Registry, ...] = (
    Registry("crossref", ("doi",), _crossref_work_url, _crossref_work_authors),
    Registry("arxiv", ("arxiv",), _arxiv_work_url, _arxiv_work_authors, json=False),
    Registry("openalex", ("doi", "arxiv"), _openalex_work_url, _openalex_work_authors),
)
