"""Venue identifiers, looked up in registries.

Two questions, both answered by registries rather than by rules written here:

    what is the record's venue?   the identifiers the record carries (ISSNs, the OpenAlex
                                  source, PubMed's NLM id), widened through Wikidata to the
                                  items that hold them and the items those point at
    what venue does the entry     the cited name looked up where venue names and their
    name?                         abbreviations are indexed: Wikidata labels, aliases, short
                                  names and ISO 4 abbreviations, and OpenAlex sources' display
                                  names, abbreviated titles and alternate titles

A name only picks candidates. A registry venue is a candidate when one of its own names folds
to the cited one; candidates that share an identifier, or that Wikidata links as a
conference and its proceedings, are one venue; and the name resolves only when exactly one
venue is left.

Sources, all unkeyed and sent no contact address:

    Wikidata    https://www.wikidata.org/w/api.php (wbsearchentities, wbgetentities, and
                CirrusSearch `haswbstatement`); CC0. Requests are paced and a descriptive
                User-Agent is sent, as the Wikimedia User-Agent policy asks.
    OpenAlex    https://api.openalex.org/sources and /works; CC0. An unkeyed client has a
                small daily budget per IP address, so OpenAlex is asked only where Wikidata
                knew no venue by the name, and once spent every lookup is refused until it
                resets at midnight UTC.

DBLP's venue search would serve conferences, and Wikidata carries DBLP venue keys (P8926), so
those keys are compared when Wikidata holds them. DBLP's own API is not asked: it answers with
a proof-of-work page meant for browsers, which an automated client must not work around.
"""

from __future__ import annotations

import hashlib
import re
import urllib.parse
from collections.abc import Callable

from pydantic import BaseModel, ConfigDict, Field

from citations.venue import GARBLED, Resolution, folded_names, forms, same_name

#: `(url, cache file name)` to a decoded JSON object, an empty one when the service had
#: nothing, or None when it refused. `audit._ask` is the one used: cached, paced, retried.
Ask = Callable[[str, str], dict | None]

WIKIDATA = "https://www.wikidata.org/w/api.php"
OPENALEX = "https://api.openalex.org"

#: Wikidata properties read as venue identifiers.
IDENTIFIERS = {
    "P236": "issn",
    "P7363": "issn",
    "P10283": "openalex",
    "P1055": "nlm",
    "P8926": "dblp",
}

#: Wikidata properties read as names: ISO 4 abbreviation and short name.
NAMES = ("P1160", "P1813")

#: Wikidata properties that make an item part of a series: an edition's `part of the series`,
#: a proceedings' `is proceedings from`. Two items of one series are one venue.
SERIES = ("P179", "P4745")

#: Wikidata properties that link a journal to the title it replaced or was replaced by. Followed
#: one hop only: two journals that replaced one title are siblings, not one venue.
LINEAGE = ("P1365", "P1366")


class Venue(BaseModel):
    """One registry venue: an item or source, its identifiers and its names."""

    model_config = ConfigDict(frozen=True)

    ids: frozenset[str]
    links: frozenset[str] = frozenset()
    series: frozenset[str] = frozenset()
    names: tuple[str, ...] = ()
    label: str = ""
    repository: bool = False
    typed: bool = False
    """The registry that gave this venue says whether it is a repository: OpenAlex does."""


class Looked(BaseModel):
    """What a set of lookups found, and whether every service answered."""

    venues: list[Venue] = Field(default_factory=list)
    refused: bool = False


def _file(prefix: str, url: str) -> str:
    return f"{prefix}_{hashlib.sha256(url.encode()).hexdigest()[:20]}.json"


# ------------------------------------------------------------------------------- Wikidata


def _wikidata(ask: Ask, params: dict) -> dict | None:
    url = f"{WIKIDATA}?{urllib.parse.urlencode({**params, 'format': 'json'})}"
    return ask(url, _file("wikidata", url))


def _snak_values(claims: dict, prop: str) -> list[str]:
    out = []
    for statement in claims.get(prop) or []:
        value = (statement.get("mainsnak") or {}).get("datavalue", {}).get("value")
        if isinstance(value, dict):
            value = value.get("id") or value.get("text")
        if isinstance(value, str) and value:
            out.append(value)
    return out


def _item_venue(qid: str, entity: dict) -> Venue | None:
    """A Wikidata item as a venue, or None where it carries no venue identifier: an item a
    name search found that is a person, a place or a file format is not a venue."""
    claims = entity.get("claims") or {}
    ids = {
        f"{kind}:{v}"
        for p, kind in IDENTIFIERS.items()
        for v in _snak_values(claims, p)
        # Wikidata's OpenAlex property also holds topic, author and institution ids; only a
        # source id (`S...`) names a venue.
        if kind != "openalex" or v.startswith("S")
    }
    if not ids:
        return None
    series = {f"wikidata:{v}" for p in SERIES for v in _snak_values(claims, p)}
    links = {f"wikidata:{v}" for p in LINEAGE for v in _snak_values(claims, p)} | series
    names = [v.get("value", "") for v in (entity.get("labels") or {}).values()]
    names += [a.get("value", "") for al in (entity.get("aliases") or {}).values() for a in al]
    names += [v for p in NAMES for v in _snak_values(claims, p)]
    label = ((entity.get("labels") or {}).get("en") or {}).get("value", "") or next(
        (n for n in names if n), ""
    )
    return Venue(
        ids=frozenset({f"wikidata:{qid}", *ids}),
        links=frozenset(links),
        series=frozenset(series),
        names=tuple(n for n in dict.fromkeys(names) if n),
        label=label,
    )


def _entities(ask: Ask, qids: list[str]) -> Looked:
    found = Looked()
    for start in range(0, len(qids), 50):
        chunk = qids[start : start + 50]
        answer = _wikidata(
            ask,
            {
                "action": "wbgetentities",
                "ids": "|".join(chunk),
                "props": "claims|labels|aliases",
                "languages": "en|mul",
            },
        )
        if answer is None:
            found.refused = True
            continue
        for qid, entity in (answer.get("entities") or {}).items():
            venue = _item_venue(qid, entity)
            if venue:
                found.venues.append(venue)
    return found


def _search_titles(answer: dict | None) -> list[str]:
    return [h["title"] for h in ((answer or {}).get("query") or {}).get("search") or []]


def wikidata_by_name(ask: Ask, name: str) -> Looked:
    """Items whose label, alias, short name or ISO 4 abbreviation is this name."""
    refused = False
    qids: list[str] = []
    answer = _wikidata(
        ask,
        {
            "action": "wbsearchentities",
            "search": name[:250],
            "language": "en",
            "uselang": "en",
            "type": "item",
            "limit": 10,
        },
    )
    if answer is None:
        refused = True
    qids += [r["id"] for r in (answer or {}).get("search") or [] if r.get("id")]
    # An ISO 4 abbreviation is a statement, not an alias, and the label search misses it:
    # `Comput. Netw.` is found only this way.
    exact = name.replace('"', "")
    answer = _wikidata(
        ask,
        {"action": "query", "list": "search", "srsearch": f'haswbstatement:"P1160={exact}"'},
    )
    if answer is None:
        refused = True
    qids += _search_titles(answer)
    found = _entities(ask, list(dict.fromkeys(qids))) if qids else Looked()
    found.venues = [v for v in found.venues if same_name(name, list(v.names))]
    found.refused = found.refused or refused
    return found


def wikidata_by_ids(ask: Ask, ids: frozenset[str]) -> Looked:
    """Items holding any of these identifiers."""
    props = {"issn": ("P236", "P7363"), "openalex": ("P10283",), "nlm": ("P1055",)}
    clauses = [
        f"{p}={value}"
        for i in sorted(ids)
        for kind, value in [i.split(":", 1)]
        for p in props.get(kind, ())
    ]
    if not clauses:
        return Looked()
    answer = _wikidata(
        ask,
        {"action": "query", "list": "search", "srsearch": "haswbstatement:" + "|".join(clauses)},
    )
    if answer is None:
        return Looked(refused=True)
    qids = _search_titles(answer)
    return _entities(ask, qids) if qids else Looked()


# -------------------------------------------------------------------------------- OpenAlex


def _source_venue(source: dict) -> Venue | None:
    oid = (source.get("id") or "").rsplit("/", 1)[-1]
    if not oid:
        return None
    issns = {f"issn:{i}" for i in [source.get("issn_l"), *(source.get("issn") or [])] if i}
    names = [
        source.get("display_name") or "",
        source.get("abbreviated_title") or "",
        *(source.get("alternate_titles") or []),
    ]
    return Venue(
        ids=frozenset({f"openalex:{oid}", *issns}),
        names=tuple(n for n in dict.fromkeys(names) if n),
        label=source.get("display_name") or "",
        repository=source.get("type") == "repository",
        typed=True,
    )


def openalex_by_name(ask: Ask, name: str) -> Looked:
    """OpenAlex sources one of whose names is this name."""
    query = urllib.parse.urlencode(
        {
            "search": name[:250],
            "per-page": 10,
            "select": "id,display_name,abbreviated_title,alternate_titles,issn_l,issn,type",
        }
    )
    url = f"{OPENALEX}/sources?{query}"
    answer = ask(url, _file("openalex_sources", url))
    if answer is None:
        return Looked(refused=True)
    venues = [_source_venue(s) for s in answer.get("results") or []]
    return Looked(venues=[v for v in venues if v and same_name(name, list(v.names))])


def openalex_source(ask: Ask, oid: str) -> Looked:
    url = f"{OPENALEX}/sources/{oid}"
    answer = ask(url, _file("openalex_source", url))
    if answer is None:
        return Looked(refused=True)
    venue = _source_venue(answer)
    return Looked(venues=[venue] if venue else [])


def openalex_work(ask: Ask, doi: str) -> dict | None:
    """The OpenAlex work for a DOI, or None when OpenAlex refused."""
    url = f"{OPENALEX}/works/doi:{urllib.parse.quote(doi, safe='/')}"
    return ask(url, _file("openalex_work", url))


# ------------------------------------------------------------------------------- resolving


def _clusters(venues: list[Venue]) -> list[list[Venue]]:
    """Venues joined where they share an identifier, one links to the other, or both are
    part of one series."""

    def joins(v: Venue, w: Venue) -> bool:
        return bool(v.ids & (w.ids | w.links) or w.ids & v.links or v.series & w.series)

    groups: list[list[Venue]] = []
    for v in venues:
        joined = [g for g in groups if any(joins(v, w) for w in g)]
        merged = [v, *(w for g in joined for w in g)]
        groups = [g for g in groups if g not in joined] + [merged]
    return groups


def _resolution(group: list[Venue], status: str, direct: bool = False) -> Resolution:
    return Resolution(
        status=status,
        ids=frozenset().union(*(v.ids for v in group)),
        links=frozenset().union(*(v.links for v in group)),
        series=frozenset().union(*(v.series for v in group)),
        label=next((v.label for v in group if v.label), ""),
        names=folded_names(n for v in group for n in v.names),
        direct=direct,
        repository=any(v.repository for v in group),
    )


def resolve_name(ask: Ask, name: str, issn: str = "", both: bool = False) -> Resolution:
    """The registry venue a cited venue name is, or why there is not exactly one.

    An ISSN the entry gives is used directly and widened through Wikidata like a record's.
    With `both`, OpenAlex is asked even where Wikidata knew the name, and the venues the two
    give are clustered together: `audit` asks so when the record's venue is an OpenAlex source
    the Wikidata venue did not match.
    """
    if issn.strip():
        return identify(
            ask, frozenset({f"issn:{i}" for i in re.findall(r"\d{4}-\d{3}[\dXx]", issn)})
        )
    if not name.strip() or GARBLED in name:
        return Resolution(status="unresolved")
    looked = Looked()
    # The name as cited first, then the shorter forms inside it, stopping at the first that
    # some registry venue goes by: `International Conference on Learning Representations
    # (ICLR)` is the conference, though `ICLR` alone is also two law reviews. OpenAlex is
    # asked only where Wikidata knew no venue by any form: it gives an unkeyed client a small
    # daily budget.
    for lookup in (wikidata_by_name, openalex_by_name):
        for form in forms(name):
            found = lookup(ask, form)
            looked.refused = looked.refused or found.refused
            if found.venues:
                looked.venues += found.venues
                break
        if looked.venues and not both:
            break
    groups = _clusters(looked.venues)
    if len(groups) > 1:
        options = [_resolution(g, "resolved") for g in groups]
        return Resolution(
            status="refused" if looked.refused else "ambiguous",
            candidates=sorted({o.label for o in options if o.label}),
            options=options,
        )
    if not groups:
        return Resolution(status="refused" if looked.refused else "unresolved")
    group = groups[0]
    return _resolution(group, "refused" if looked.refused else "resolved")


def typed(ask: Ask, resolution: Resolution) -> Resolution:
    """`resolution`, with whether OpenAlex types the venue as a repository.

    Asked only before a mismatch would be reported, so that an entry citing arXiv is never
    compared as a journal, and so that a venue that matched costs no request.
    """
    oids = sorted(i.split(":", 1)[1] for i in resolution.ids if i.startswith("openalex:"))
    if not oids or resolution.repository:
        return resolution
    source = openalex_source(ask, oids[0])
    if source.refused:
        return resolution.model_copy(update={"status": "refused"})
    return resolution.model_copy(update={"repository": any(v.repository for v in source.venues)})


def identify(
    ask: Ask,
    ids: frozenset[str],
    series: frozenset[str] = frozenset(),
    label: str = "",
    repository: bool = False,
) -> Resolution:
    """A record's venue from the identifiers it carries, widened through Wikidata to the items
    that hold them and the items those link to.

    A book series' identifiers, and the items that hold them, only link: a chapter in Lecture
    Notes in Computer Science confirms an entry naming that series and contradicts none.
    """
    if not ids and not series:
        return Resolution(status="none", label=label, repository=repository, direct=True)
    found = wikidata_by_ids(ask, ids)
    shelf = wikidata_by_ids(ask, series)
    group = [
        Venue(ids=ids, label=label, names=(label,) if label else (), repository=repository),
        *found.venues,
    ]
    refused = found.refused or shelf.refused
    resolved = _resolution(group, "refused" if refused else "resolved", direct=True)
    links = resolved.links | series | frozenset().union(*(v.ids | v.links for v in shelf.venues))
    return resolved.model_copy(update={"label": label or resolved.label, "links": links})


__all__ = [
    "Ask",
    "Looked",
    "Venue",
    "identify",
    "openalex_by_name",
    "openalex_source",
    "openalex_work",
    "resolve_name",
    "typed",
    "wikidata_by_ids",
    "wikidata_by_name",
]
