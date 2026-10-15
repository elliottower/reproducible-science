"""Does the metadata match the record the identifier resolves to?

    citations audit                     every record in the library that has an identifier
    citations audit --bib refs.bib      a BibTeX file directly
    citations audit --only <paper>      records one paper cites
    citations audit --json report.json  machine-readable, one object per entry
    citations audit --strict            exit 1 on any disagreement or unlisted not found, for CI
    citations audit --checked list.txt  keys checked by hand (default: <stem>.checked.txt beside the bib)
    citations audit --no-search         leave entries with no DOI or PMID unchecked

This is a different question from the three the library already asks, and no combination of
them answers it:

    verify              is the quotation actually in the source?
    resolve             does this work have an identifier at all?
    resolve --verify    does the identifier still resolve to something?

A real DOI carrying an invented author list passes all three. It resolves, the link is live,
and the quotations pinned to it are genuine, because the DOI does point at the right paper --
it is the names, year, volume and pages written down beside it that belong to no one. Nothing
reads those fields back against the registry, so nothing catches it, and the reference list
ships with authors who did not write the paper.

Found in the wild: four entries in one 75-entry bibliography carried an author list belonging
to nobody on the cited paper, one PMID resolved to an unrelated article in another field, and
four author lists stopped early with no `and others` marker, which is invisible because a
truncated list looks complete.

An entry with no DOI and no PMID is searched for by title, under the rule `citations resolve`
accepts a match on: title, first author's surname and year together. One that is found is
compared like any other, against an identifier the report prints so it can be added. One that
no service has is reported as not found, and so is an entry whose own DOI or PMID resolves to
no record at any registry asked.

Under `--strict` a not found fails the run, because a book, a report and a thesis land in that
row beside a reference to a work that does not exist, and nothing in the report tells them
apart. An author who has checked such an entry by hand lists its key in a plain file beside
the bibliography (`references.checked.txt` for `references.bib`, or `--checked PATH`). A listed
key is still reported as not found, marked as checked, and does not fail the run. The list
excuses nothing else: a listed key that is found and disagrees fails as any other does, and
the file's SHA-256 is written into the report so its use is on record.

A registry lookup that failed -- a refusal, a rate limit, a timeout, a 5xx -- is `could not
check`. A title search is `not found` only when Crossref or OpenAlex answered, whatever the
other services did; otherwise it too is `could not check`. A service that rejected the query (a
400 or 422) is counted as neither answering nor refusing. Under `--strict` a `could not check`,
or an audit that checked nothing, exits 2 rather than 1, so a CI job can retry instead of
blaming the citation. A disagreement or an unlisted not found exits 1 whatever else could not
be checked.

The venue is compared by identifier, under `venue.decide`: the record's venue is the ISSNs and
source ids its registries give it, the entry's is whatever registry venue the cited name
resolves to (`venue_registry`), and a real paper cited at the wrong journal is a field
disagreement like a wrong year. A venue that registries cannot settle is not comparable, and
the report prints both names so a person can compare them.

Responses are cached, so a re-run is offline and the report is reproducible from what was
fetched.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
import pathlib
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Callable

from provenance_core import atomic_write
from pydantic import BaseModel, ConfigDict, Field

from citations import bibtex, paths, resolve
from citations.exceptions import CitationsError
from citations.models import load_record
from citations.services import (
    CROSSREF_KINDS,
    SERVICES,
    Candidate,
    Service,
    crossref_venue_ids,
    crossref_venues,
    openalex_venue_ids,
    openalex_venues,
    user_agent,
)
from citations.text import name_fold, tokens, variants
from citations.venue import (
    MISMATCH,
    NOT_COMPARABLE,
    Resolution,
    VenueCheck,
    decide,
    folded_names,
)
from citations.venue_registry import Ask, identify, openalex_work, resolve_name, typed

#: Crossref's polite-pool rate limit is 50 requests a second; this is far under it and keeps
#: a full-library audit from looking like a scrape.
DELAY = 0.34

#: Between two title searches, as `citations resolve` paces them.
SEARCH_DELAY = 1.5

#: Attempts at one search before the service counts as having refused. `resolve` makes four,
#: which is half a minute of backoff for each service that is down; an audit that is offline
#: should say so sooner than that.
SEARCH_TRIES = 2

#: Entries in a row that every service refused before the rest are left unsearched. Offline,
#: each further entry would wait out every service's backoff to learn the same thing.
GIVE_UP_AFTER = 2

#: Errors that mean a request did not complete, as distinct from a registry that answered and
#: had nothing. `HTTPError` subclasses `URLError` and is caught first where the code matters.
NETWORK_ERRORS = (
    urllib.error.URLError,
    socket.timeout,
    TimeoutError,
    ConnectionError,
    UnicodeDecodeError,
)

#: A field runs to the next `name =`, wherever that sits. The lookahead once required a
#: newline before it, so an entry writing several fields onto one line -- which BibTeX
#: permits and reference managers emit -- gave the first of them a value swallowing every
#: field after it, and the entry then disagreed with its registry record on a value nobody
#: had typed wrong.
BIB_FIELD = re.compile(r"(\w+)\s*=\s*[{\"](.*?)[}\"]\s*,?\s*(?=\s*\w+\s*=|\Z)", re.DOTALL)


#: Generational suffixes are filed with the surname by some publishers and dropped by others.
SUFFIXES = {"jr", "sr", "ii", "iii", "iv"}

Person = tuple[tuple[str, ...], tuple[str, ...]]


def split_authors(names: list[str]) -> tuple[list[Person], bool]:
    """(family, given) token pairs, plus whether the list ends in an `and others` marker."""
    parts = [n.strip() for n in names if n and n.strip()]
    truncated = bool(parts) and name_fold(parts[-1]) in ("others", "et al")
    if truncated:
        parts = parts[:-1]
    people: list[Person] = []
    for part in parts:
        if "," in part:
            family, given = part.split(",", 1)
        else:
            words = part.split()
            family, given = (words[-1], " ".join(words[:-1])) if len(words) > 1 else (part, "")
        people.append((tokens(family), tokens(given)))
    return people, truncated


def disagreement(mine: Person, theirs: Person) -> str | None:
    """What the two renderings of one name disagree about, or None if they are the same name."""
    (mf, mg), (yf, yg) = mine, theirs
    ours_family = [t for t in mf if t not in SUFFIXES]
    their_family = [t for t in yf if t not in SUFFIXES]
    # Hölscher-Obermaier is `holscher obermaier` in one record and `hoelscher obermaier` in
    # the other. Both spell one name, so the comparison is on every form each can take.
    same_family = ours_family == their_family or bool(
        variants(" ".join(ours_family)) & variants(" ".join(their_family))
    )
    if not same_family:
        # A particle filed under the given name in one record and the family name in the
        # other is one name written two ways: Del Tredici, Kelly against Tredici, Kelly Del.
        if sorted(mf + mg) == sorted(yf + yg):
            return None
        return f"surname: ours {' '.join(mf)!r} vs registry {' '.join(yf)!r}"
    if not mg or not yg:
        return None
    # Compare name part against name part, abbreviating only where one side already has.
    # P. T. and Peter T. are one person, and so are Marcos B. and M. Bosi. Reducing the
    # whole given name to initials instead would make Andrew J. S. and Alastair J. S. agree,
    # which is the error this command exists to catch. A side that carries a middle name the
    # other omits is not a disagreement about the parts both of them name.
    for our_part, their_part in zip(mg, yg, strict=False):
        if len(our_part) == 1 or len(their_part) == 1:
            if our_part[0] != their_part[0]:
                return f"given name: ours {' '.join(mg)!r} vs registry {' '.join(yg)!r}"
        elif our_part != their_part:
            return f"given name: ours {' '.join(mg)!r} vs registry {' '.join(yg)!r}"
    return None


# --------------------------------------------------------------------------------- shapes


class Entry(BaseModel):
    """One thing to check: what we wrote down, and what identifies it."""

    model_config = ConfigDict(extra="allow")

    key: str
    """Citation key or record slug. Identifies the entry in the report, nothing else."""

    title: str = ""
    authors: list[str] = Field(default_factory=list)
    year: str = ""
    venue: str = ""
    volume: str = ""
    pages: str = ""
    doi: str = ""
    pmid: str = ""

    et_al: bool = False
    """A bibliography marks a shortened list with a trailing "and others"; a library record
    marks it with this field. Both say the same thing, and a check that reads only the first
    calls every marked record truncated."""

    venue_kind: str = ""
    """`journal` where the venue came from a `journal` field, `proceedings` from a `booktitle`,
    `preprint` where the entry names only a preprint server, empty where nothing says."""

    series: str = ""
    """A proceedings series (`Proceedings of Machine Learning Research`, `Lecture Notes in
    Computer Science`), compared only where the entry names no journal or booktitle."""

    issn: str = ""
    """An ISSN the entry gives, used as the venue's identifier without a name lookup."""

    @property
    def identified(self) -> bool:
        return bool(self.doi.strip() or self.pmid.strip())


class RegistryRecord(BaseModel):
    """What a registry says about a work, in the one shape `compare` reads."""

    model_config = ConfigDict(frozen=True)

    source: str
    """Which registry answered: `crossref` or `pubmed`."""

    title: str = ""
    venue: str = ""

    venues: list[str] = Field(default_factory=list)
    """Every name the record gives the venue: container titles, short titles, an event's name
    and acronym. `venue` is the first of them."""

    venue_kind: str = ""
    """`journal`, `proceedings`, `preprint`, or empty where the registry does not say."""

    venue_ids: list[str] = Field(default_factory=list)
    """Identifiers of the venue the record carries: a journal article's ISSNs, PubMed's NLM id,
    a DataCite container's ISSN."""

    series_ids: list[str] = Field(default_factory=list)
    """ISSNs of a book series a chapter or proceedings paper is in. A series is not the venue,
    so these can confirm a venue and never contradict one."""

    years: list[str] = Field(default_factory=list)
    """Every year the registry reports. A journal publishing online ahead of print carries two
    legitimate years, and accepting only one reports the other as an error."""

    volume: str = ""
    pages: str = ""
    authors: list[Person] = Field(default_factory=list)


class EntryAudit(BaseModel):
    """The verdict on one entry."""

    status: str
    """`ok`, `mismatch`, `could not check`, `no identifier`, `not found` or `found`.

    `could not check` is a check that was not made: a registry or every search service refused,
    rate-limited, timed out or failed. `not found` is a lookup that was answered and matched
    nothing: a title search, or the entry's own identifier, which `not_found_by` says. `found`
    is a search that matched a record carrying no DOI, so nothing was compared."""

    not_found_by: str = ""
    """`title search` or `identifier`, when the status is `not found`."""

    rejected: list[str] = Field(default_factory=list)
    """The search services that rejected the title query (a 400 or 422). Such a service is
    counted neither among those a `not found` rests on nor among those that refused."""

    refused: list[str] = Field(default_factory=list)
    """The registries or search services that did not answer. On `could not check`, every one
    asked, or none when no service was asked after several entries in a row were refused. On a
    `not found` by title search, the services that refused while the others answered: the
    verdict rests on the ones under `searched`. A venue lookup that was refused is recorded on
    `venue.why` instead, and leaves the venue not comparable, never the entry unchecked."""

    checked_by_hand: bool = False
    """The key is on the list of entries the author checked by hand. Changes no status; a
    `not found` so marked does not fail `--strict`, and nothing else is excused."""

    checked_against: str | None = None
    """Which registry the comparison was made against, when one answered."""

    doi: str = ""
    pmid: str = ""

    problems: list[str] = Field(default_factory=list)
    """One message per disagreeing field. Empty when the status is not `mismatch`."""

    found_kind: str = ""
    """`doi`, `arxiv` or `openalex`, when the entry named no identifier and a title search
    found one. `doi` and `pmid` above stay what the entry itself carries."""

    found_id: str = ""
    """The identifier the search found: the suggestion to add to the entry."""

    found_by: str = ""
    """The service whose answer matched."""

    venue: VenueCheck | None = None
    """The venue comparison, when a record was compared. `not comparable` is reported here and
    is never a disagreement; a `mismatch` is also one of `problems`."""

    searched: list[str] = Field(default_factory=list)
    """The services that answered the title search. One that refused is not listed, so a `not
    found` says which services it rests on."""


class CheckedList(BaseModel):
    """The keys an author checked by hand, and the file they were read from."""

    path: str
    sha256: str
    """Of the file's bytes, so the report records which list it was read against."""

    keys: list[str] = Field(default_factory=list)

    stale: list[str] = Field(default_factory=list)
    """Listed keys the audited entries do not have."""

    identifier_does_not_resolve: list[str] = Field(default_factory=list)
    """Listed keys whose own DOI or PMID every registry asked answered 404 for. The list
    excuses them, as a DOI registered with neither Crossref nor DataCite is real, but a
    mistyped DOI looks the same, so each is warned about."""


#: The list beside a bibliography `references.bib` is `references.checked.txt`; in a library,
#: `checked.txt` at its root.
CHECKED_SUFFIX = ".checked.txt"
LIBRARY_CHECKED = "checked.txt"


def read_checked(path: pathlib.Path) -> list[str]:
    """The keys in a checked list: one per line, `#` to the end of a line is a comment.

    A line holding two words before any `#` is refused rather than read as one key, because
    the second word would be silently dropped and the entry it named left unexcused, or the
    first excused for a note about the second.
    """
    keys: list[str] = []
    try:
        # `utf-8-sig`, so a byte-order mark an editor wrote is not read into the first key.
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as e:
        raise CitationsError(
            f"{path}: not UTF-8 (byte {e.start}); save the checked list as UTF-8"
        ) from e
    for n, line in enumerate(text.splitlines(), start=1):
        words = line.split("#", 1)[0].split()
        if len(words) > 1:
            raise CitationsError(
                f"{path}:{n}: one key per line, with any note after a `#`; read {line.strip()!r}"
            )
        if words and words[0] not in keys:
            keys.append(words[0])
    return keys


def load_checked(path: pathlib.Path, audited: list[str]) -> CheckedList:
    keys = read_checked(path)
    present = set(audited)
    return CheckedList(
        path=str(path),
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        keys=keys,
        stale=[k for k in keys if k not in present],
    )


class AuditReport(BaseModel):
    """Every entry's verdict, plus where they came from.

    Returned rather than printed, so the same audit can render a report, write JSON, or be
    read by a caller that imported this package instead of running it.
    """

    entries: dict[str, EntryAudit] = Field(default_factory=dict)
    where: str = ""

    checked_list: CheckedList | None = None
    """The list of keys checked by hand this audit was read against, when there was one."""

    def by(self, status: str) -> list[str]:
        return [k for k, v in self.entries.items() if v.status == status]

    @property
    def venue_not_comparable(self) -> dict[str, VenueCheck]:
        """Each entry whose venue could not be compared, with the check that says why."""
        return {
            k: v.venue
            for k, v in self.entries.items()
            if v.venue is not None and v.venue.outcome == NOT_COMPARABLE
        }

    @property
    def mismatched(self) -> list[str]:
        return self.by("mismatch")

    @property
    def could_not_check(self) -> list[str]:
        return self.by("could not check")

    @property
    def unidentified(self) -> list[str]:
        return self.by("no identifier")

    @property
    def not_found(self) -> list[str]:
        return self.by("not found")

    @property
    def not_found_unchecked(self) -> list[str]:
        """Not found, and not on the list of entries checked by hand: what `--strict` fails."""
        return [k for k in self.not_found if not self.entries[k].checked_by_hand]

    @property
    def listed_but_found(self) -> list[str]:
        """On the checked list, yet a registry had the record and it was compared or found."""
        return [
            k
            for k, v in self.entries.items()
            if v.checked_by_hand and v.status in ("ok", "mismatch", "found")
        ]

    @property
    def found_only(self) -> list[str]:
        return self.by("found")

    @property
    def checked(self) -> int:
        """Entries compared with a registry record, whoever supplied the identifier."""
        return len(self.by("ok")) + len(self.mismatched)

    @property
    def ok(self) -> bool:
        """Whether the audit passes `--strict`. An audit that checked nothing is not a pass.

        A not found fails it unless the key is on the checked list: a book with no DOI and a
        reference to a work that does not exist land in the same row."""
        return (
            bool(self.measured)
            and not self.mismatched
            and not self.not_found_unchecked
            and not self.could_not_check
        )

    @property
    def measured(self) -> list[str]:
        """Entries some registry or search service answered for: compared, found or not found.

        `no identifier` and `could not check` are not among them, so an audit made of nothing
        else checked nothing, whatever it prints."""
        return [
            k
            for k, v in self.entries.items()
            if v.status in ("ok", "mismatch", "found", "not found")
        ]

    @property
    def strict_exit(self) -> int:
        """1 for a disagreement or an unlisted not found, 2 where nothing else failed but a
        lookup did, or nothing was measured; 0 otherwise.

        A failed lookup is 2 rather than 1 so that CI can retry it instead of blaming the
        citation, and a known failure outranks it: no retry changes a disagreement."""
        if self.mismatched or self.not_found_unchecked:
            return 1
        return 2 if (self.could_not_check or not self.measured) else 0


# --------------------------------------------------------------------------------- entries


def entries_from_bib(path: pathlib.Path) -> list[Entry]:
    out = []
    for _kind, key, body in bibtex.entries(bibtex.read(path)):
        f = {name.lower(): " ".join(value.split()) for name, value in BIB_FIELD.findall(body)}
        venue = f.get("journal") or f.get("booktitle", "")
        kind = "journal" if f.get("journal") else "proceedings" if venue else ""
        out.append(
            Entry(
                key=key,
                title=f.get("title", ""),
                authors=[a for a in re.split(r"\s+and\s+", f.get("author", "")) if a],
                year=f.get("year", ""),
                venue=venue,
                venue_kind=kind,
                series=f.get("series", ""),
                issn=f.get("issn", ""),
                volume=f.get("volume", ""),
                pages=f.get("pages", ""),
                doi=f.get("doi", ""),
                pmid=f.get("pmid", ""),
            )
        )
    return sorted(out, key=lambda e: e.key)


def entries_from_library(only: str | None) -> list[Entry]:
    out = []
    for p in sorted(paths.records().glob("*.yaml")):
        rec = load_record(p)
        if only and only not in rec.cited_by:
            continue
        extra = rec.model_extra or {}
        out.append(
            Entry(
                key=rec.slug,
                title=rec.title,
                authors=rec.authors,
                year=rec.year,
                venue=rec.venue,
                volume=str(extra.get("volume") or ""),
                pages=str(extra.get("pages") or ""),
                doi=rec.doi,
                pmid=str(extra.get("pmid") or ""),
                et_al=rec.et_al,
            )
        )
    return out


# --------------------------------------------------------------------------------- sources


#: Bumped when the envelope's shape changes, so an older cache is refetched rather than
#: misread.
CACHE_VERSION = 1


def fetch(url: str, cache: pathlib.Path, name: str) -> str | None:
    """A cached registry response, or None when the registry answered that it has no record.

    Raises `resolve.Throttled` when the request did not complete: a 401, 403 or 429, a 5xx, a
    timeout, a dropped connection. A 404 or 410 is an answer, and so is a 400 or 422, which
    rejects the identifier itself as malformed. Returning None for both was
    how a rate-limited Crossref and a DOI that resolves to nothing became one row.

    Each entry is wrapped in an envelope naming the URL it answers and a digest of the body.
    A bare file is not a cache hit.

    This matters because `.audit-cache/` sits beside the bibliography and gets committed. When
    the entry was the response body alone, a hand-written file was indistinguishable from a
    fetched one, so a fabricated record -- a real DOI carrying an invented title and authors --
    could be made to verify offline, with no network touched. That is precisely the failure
    this module exists to catch.

    A local cache can never be an attestation: anyone able to write the file can write a
    correct envelope too. What the envelope buys is that an entry cannot be repurposed for a
    different request, and that a file dropped in by hand is ignored rather than trusted.
    """
    hit = cached(url, cache, name)
    if hit is not None:
        return hit or None

    req = urllib.request.Request(url, headers={"User-Agent": user_agent()})
    time.sleep(DELAY)
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            body = r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        # A 400 or 422 on an identifier lookup is the registry rejecting the identifier itself as
        # malformed: an answer that it names no record, which asking again will not change.
        if exc.code in resolve.ABSENT_CODES + resolve.REJECTED_CODES:
            return None
        print(f"    could not fetch {name}: {exc}")
        raise resolve.Throttled(url) from exc
    except NETWORK_ERRORS as exc:
        print(f"    could not fetch {name}: {exc}")
        raise resolve.Throttled(url) from exc
    store(url, cache, name, body)
    return body


def cached(url: str, cache: pathlib.Path, name: str) -> str | None:
    """The body stored under `name` for exactly this URL, or None when there is no such entry."""
    hit = cache / name
    if not hit.exists():
        return None
    try:
        envelope = json.loads(hit.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    if (
        isinstance(envelope, dict)
        and envelope.get("cache_version") == CACHE_VERSION
        and envelope.get("url") == url
        and isinstance(envelope.get("body"), str)
        and hashlib.sha256(envelope["body"].encode()).hexdigest() == envelope.get("sha256")
    ):
        return envelope["body"]
    # Anything else -- a bare body, a mismatched URL, a broken digest -- is not a hit.
    # Fetching again is the only way to answer the question that was asked.
    return None


def store(url: str, cache: pathlib.Path, name: str, body: str) -> None:
    cache.mkdir(parents=True, exist_ok=True)
    (cache / name).write_text(
        json.dumps(
            {
                "cache_version": CACHE_VERSION,
                "url": url,
                "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "sha256": hashlib.sha256(body.encode()).hexdigest(),
                "body": body,
            },
            indent=2,
        )
    )


def from_crossref(doi: str, cache: pathlib.Path) -> RegistryRecord | None:
    """The Crossref record, None where Crossref has none, `resolve.Throttled` where it did not
    answer or answered with a body that is not a record."""
    url = f"https://api.crossref.org/works/{urllib.parse.quote(doi, safe='')}"
    body = fetch(url, cache, f"crossref_{re.sub(r'[^A-Za-z0-9]', '_', doi)}.json")
    if not body:
        return None
    try:
        m = json.loads(body)["message"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise resolve.Throttled(url) from exc
    years = []
    for field in ("published-print", "published-online", "issued", "created"):
        parts = (m.get(field) or {}).get("date-parts") or []
        if parts and parts[0] and parts[0][0]:
            years.append(str(parts[0][0]))
    return RegistryRecord(
        source="crossref",
        title=(m.get("title") or [""])[0],
        venue=(m.get("container-title") or [""])[0],
        venues=crossref_venues(m),
        venue_kind=CROSSREF_KINDS.get(m.get("type") or "", ""),
        venue_ids=crossref_venue_ids(m)[0],
        series_ids=crossref_venue_ids(m)[1],
        years=years,
        volume=str(m.get("volume") or ""),
        pages=str(m.get("page") or m.get("article-number") or ""),
        authors=[
            (tokens(a.get("family", "")), tokens(a.get("given", "")))
            for a in m.get("author", [])
            if a.get("family")
        ],
    )


#: DOI prefixes registered with DataCite rather than Crossref. Crossref answers 404 for these,
#: which reads as an entry whose identifier does not resolve when the identifier is fine.
DATACITE_PREFIXES = ("10.48550/", "10.5281/", "10.5061/", "10.6084/", "10.17605/", "10.7910/")


def is_datacite(doi: str) -> bool:
    return doi.strip().lower().startswith(DATACITE_PREFIXES)


def from_datacite(doi: str, cache: pathlib.Path) -> RegistryRecord | None:
    """The DataCite record for a DOI, in the shape `compare` reads.

    arXiv preprints (10.48550), Zenodo deposits (10.5281), Dryad, figshare and OSF register
    with DataCite. Consulting only Crossref reports every one of them as an identifier that
    did not resolve, which is a false accusation against a correct bibliography -- the checker
    asked the wrong registry.
    """
    url = f"https://api.datacite.org/dois/{urllib.parse.quote(doi, safe='')}"
    body = fetch(url, cache, f"datacite_{re.sub(r'[^A-Za-z0-9]', '_', doi)}.json")
    if not body:
        return None
    try:
        attrs = json.loads(body)["data"]["attributes"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise resolve.Throttled(url) from exc

    titles = attrs.get("titles") or []
    year = attrs.get("publicationYear")
    container = (attrs.get("container") or {}).get("title") or attrs.get("publisher") or ""
    if isinstance(container, dict):
        container = container.get("name", "")

    authors = []
    for c in attrs.get("creators") or []:
        family = c.get("familyName")
        given = c.get("givenName") or ""
        if not family:
            # DataCite often carries only `name`, as "Family, Given" or "Given Family".
            name = (c.get("name") or "").strip()
            if not name:
                continue
            family, given = (
                (x.strip() for x in name.split(",", 1))
                if "," in name
                else (name.split()[-1], " ".join(name.split()[:-1]))
            )
        authors.append((tokens(family), tokens(given)))

    preprint = (attrs.get("types") or {}).get("resourceTypeGeneral") == "Preprint"
    held = attrs.get("container") or {}
    issns = (
        [held["identifier"]]
        if held.get("identifierType") == "ISSN" and held.get("identifier")
        else []
    )
    return RegistryRecord(
        source="datacite",
        title=(titles[0].get("title", "") if titles else ""),
        venue=str(container),
        venues=[str(container)] if container else [],
        venue_kind="preprint" if preprint else "",
        venue_ids=[f"issn:{i}" for i in issns],
        years=[str(year)] if year else [],
        volume=str((attrs.get("container") or {}).get("volume") or ""),
        pages="",
        authors=authors,
    )


def from_pubmed(pmid: str, cache: pathlib.Path) -> RegistryRecord | None:
    url = (
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
        f"?db=pubmed&id={urllib.parse.quote(pmid)}&retmode=xml"
    )
    body = fetch(url, cache, f"pubmed_{pmid}.xml")
    if not body:
        return None
    try:
        art = ET.fromstring(body).find(".//PubmedArticle")
    except ET.ParseError as exc:
        raise resolve.Throttled(url) from exc
    # A well-formed answer holding no article is PubMed saying it has no such PMID.
    if art is None:
        return None
    title = art.find(".//ArticleTitle")
    journal = art.find(".//Journal")
    year = journal.findtext(".//Year") if journal is not None else ""
    names = (
        [journal.findtext("ISOAbbreviation") or "", journal.findtext("Title") or ""]
        if journal is not None
        else []
    )
    ids = [f"issn:{i.text.strip()}" for i in art.findall(".//Journal/ISSN") if i.text]
    ids += [
        f"issn:{i.text.strip()}" for i in art.findall(".//MedlineJournalInfo/ISSNLinking") if i.text
    ]
    ids += [
        f"nlm:{i.text.strip()}" for i in art.findall(".//MedlineJournalInfo/NlmUniqueID") if i.text
    ]
    return RegistryRecord(
        source="pubmed",
        title="".join(title.itertext()) if title is not None else "",
        venue=next((n for n in names if n), ""),
        venues=[n for n in names if n],
        venue_kind="journal",
        venue_ids=list(dict.fromkeys(ids)),
        years=[year] if year else [],
        volume=(journal.findtext(".//Volume") or "") if journal is not None else "",
        pages=art.findtext(".//MedlinePgn") or "",
        authors=[
            (tokens(a.findtext("LastName") or ""), tokens(a.findtext("ForeName") or ""))
            for a in art.findall(".//Author")
            if a.findtext("LastName")
        ],
    )


# ------------------------------------------------------------------------------ comparison


def compare(entry: Entry, record: RegistryRecord, venue: VenueCheck | None = None) -> list[str]:
    """Every field of `entry` that disagrees with `record`, as one message each.

    `venue` is the venue verdict `audit` reached with registry lookups this function does not
    make; without one, the venue is not compared."""
    problems = []

    our_title = name_fold(entry.title)
    their_title = name_fold(record.title.rstrip("."))
    if our_title and their_title and our_title != their_title:
        if their_title.startswith(our_title) or our_title.startswith(their_title):
            problems.append(f"title (one is a prefix of the other): registry has {record.title!r}")
        else:
            problems.append(f"title: ours {entry.title!r} vs registry {record.title!r}")

    years = [y for y in record.years if y]
    if entry.year and years and entry.year not in years:
        problems.append(f"year: ours {entry.year} vs registry {'/'.join(dict.fromkeys(years))}")

    if entry.volume and record.volume and entry.volume != record.volume:
        problems.append(f"volume: ours {entry.volume} vs registry {record.volume}")

    if venue is not None and venue.outcome == MISMATCH:
        problems.append(venue.line())

    # PubMed abbreviates end pages (1214-24 for 1214-1224), so only the start page is
    # comparable across sources.
    ours_p = re.sub(r"[^0-9a-zA-Z]", "", entry.pages.split("-")[0])
    theirs_p = re.sub(r"[^0-9a-zA-Z]", "", record.pages.split("-")[0])
    if ours_p and theirs_p and ours_p != theirs_p:
        problems.append(f"pages: ours {entry.pages!r} vs registry {record.pages!r}")

    mine, truncated = split_authors(entry.authors)
    truncated = truncated or entry.et_al
    yours = record.authors
    if mine and yours:
        for i, (ours, theirs) in enumerate(zip(mine, yours, strict=False), start=1):
            said = disagreement(ours, theirs)
            if said:
                problems.append(f"author {i} {said}")
        if len(mine) < len(yours) and not truncated:
            problems.append(
                f"author list stops at {len(mine)} of {len(yours)} with no "
                "'and others' marker, so it reads as complete"
            )
        if len(mine) > len(yours):
            problems.append(f"author list has {len(mine)} names, registry has {len(yours)}")
    return problems


# ---------------------------------------------------------------------------------- venues


#: Attempts at each registry lookup of a venue before the registry counts as having refused.
VENUE_TRIES = 3

#: Sent to Wikidata, whose User-Agent policy asks a client to say where it comes from. A
#: project address, not a person's.
WIKIDATA_AGENT = "citations/1.0 (https://github.com/elliottower/reproducible-science)"


def _ask(url: str, cache: pathlib.Path, name: str, headers: dict | None = None) -> dict | None:
    """A cached JSON answer, an empty one when the service had nothing, or None when it
    refused or could not be reached.

    Paced and retried as a title search is, because the services asked here are the ones that
    rate-limit. A refusal is not cached, so the next run asks again; an empty answer is.
    """
    body = cached(url, cache, name)
    if body is None:
        try:
            body = resolve.get(url, as_json=False, tries=VENUE_TRIES, headers=headers)
        except resolve.Throttled:
            return None
        except resolve.Rejected:
            body = None  # an answer about the query, which adds no names
        finally:
            time.sleep(DELAY)
        # An answer that had nothing is cached too, so a re-run reads it rather than asking
        # again; only a refusal is left to be asked again.
        store(url, cache, name, body or "")
    try:
        answer = json.loads(body) if body else {}
    except json.JSONDecodeError:
        return {}
    return answer if isinstance(answer, dict) else {}


def asker(cache: pathlib.Path) -> Ask:
    """`_ask` bound to a cache, in the shape `venue_registry` calls."""

    def ask(url: str, name: str) -> dict | None:
        wikidata = urllib.parse.urlsplit(url).hostname == "www.wikidata.org"
        return _ask(url, cache, name, headers={"User-Agent": WIKIDATA_AGENT} if wikidata else None)

    return ask


def record_venue(record: RegistryRecord, found: Candidate | None, doi: str, ask: Ask) -> Resolution:
    """What registries say the record's venue is.

    The identifiers the record carries come first, then those the title search's answer
    carried, then the OpenAlex work's primary source. Only where none is known is the record's
    venue name resolved like an entry's, and a verdict resting on that is never a mismatch.
    """
    ids = set(record.venue_ids)
    series = set(record.series_ids)
    names = list(record.venues or [record.venue])
    repository = record.venue_kind == "preprint"
    if found is not None and found.venue_kind != "preprint":
        # A title search's answer can name the published venue of a preprint record. One
        # that names a preprint server names no venue: its ids are the server's.
        ids |= set(found.venue_ids)
        series |= set(found.series_ids)
        names += [n for n in found.venues if n not in names]
        repository = repository and not found.venue_ids
    label = ""
    if repository and found is not None and found.venue_kind in ("journal", "proceedings"):
        # A preprint record whose search answer names the venue it was published in: that
        # venue, by name, so it can confirm the entry's and never contradict it.
        name = next((n for n in found.venues if n), "")
        if name:
            return resolve_name(ask, name)
    if not ids and doi and not repository:
        work = openalex_work(ask, doi)
        if work is None:
            return Resolution(status="refused", label=record.venue)
        venue_ids, series_ids = openalex_venue_ids(work)
        ids |= set(venue_ids)
        series |= set(series_ids)
        source_names, source_kind, _source = openalex_venues(work)
        label = source_names[0] if source_names else ""
        repository = source_kind == "preprint"
    if repository:
        return Resolution(status="none", label=record.venue, repository=True)
    if ids:
        theirs = identify(ask, frozenset(ids), frozenset(series), label or record.venue)
        # The record's own container titles are registry names of its venue too.
        return theirs.model_copy(update={"names": theirs.names | folded_names(names)})
    # No venue identifier on the record: each of its venue names is resolved, and every venue
    # they resolve to may confirm the entry's. Resting on names, it never contradicts it.
    shelf = identify(ask, frozenset(), frozenset(series)) if series else Resolution(status="none")
    found_by_name = [resolve_name(ask, n) for n in dict.fromkeys(names) if n]
    options = [o for r in found_by_name for o in (r.options or [r]) if r.ids or r.options]
    refused = shelf.status == "refused" or any(r.status == "refused" for r in found_by_name)
    return Resolution(
        status="refused" if refused else ("resolved" if options or series else "none"),
        ids=frozenset().union(*(o.ids for o in options)),
        links=shelf.links.union(*(o.links for o in options)),
        series=frozenset().union(*(o.series for o in options)),
        label=label or record.venue,
        direct=False,
    )


# ------------------------------------------------------------------------------------- run


#: A title search is `not found` only when one of these answered: most indexed works are in
#: Crossref or OpenAlex, and arXiv or Semantic Scholar alone answering nothing is not enough.
NOT_FOUND_RESTS_ON = {"crossref", "openalex"}

#: How the report names a search service in prose.
SERVICE_NAMES = {
    "semanticscholar": "Semantic Scholar",
    "crossref": "Crossref",
    "openalex": "OpenAlex",
    "arxiv": "arXiv",
    "datacite": "DataCite",
    "pubmed": "PubMed",
}


def _identifier(v: EntryAudit, kind_only: bool = False) -> str:
    """The identifier a verdict rests on: the entry's own, or the one a title search found.

    `kind_only` names the entry's own as `DOI` or `PMID` alone; a found one is always given in
    full, since the entry does not carry it."""
    if v.doi or v.pmid:
        kind, ident = ("DOI", v.doi) if v.doi else ("PMID", v.pmid)
        return kind if kind_only else f"{kind.lower()} {ident}"
    kind = {"doi": "DOI", "arxiv": "arXiv id"}.get(v.found_kind, v.found_kind)
    return f"{kind} {v.found_id}, found by title search,"


def _unasked(v: EntryAudit) -> str:
    """`; X could not be asked; Y rejected the query`, for the services a verdict lacks."""
    said = ""
    if v.refused:
        said += f"; {', '.join(SERVICE_NAMES.get(r, r) for r in v.refused)} could not be asked"
    if v.rejected:
        said += f"; {', '.join(SERVICE_NAMES.get(r, r) for r in v.rejected)} rejected the query"
    return said


def _search_file(service: Service, entry: Entry) -> tuple[str, str]:
    """The URL one service is asked about one entry, and the cache file its answer lives in."""
    url = service.url(entry)
    return url, f"search_{service.name}_{hashlib.sha256(url.encode()).hexdigest()[:16]}.json"


def find(
    entry: Entry, cache: pathlib.Path
) -> tuple[Candidate | None, str, list[str], list[str], list[str]]:
    """Search for an entry by title: (the work found, the service that had it, services that
    answered, services that rejected the query, services that refused).

    Each service is asked on its own, as `citations resolve` asks them, and a candidate is
    accepted by `resolve.match` and by nothing else. Empty third and fourth elements mean every
    service refused, which is a search that was not made rather than one that found nothing. A
    service that rejected the query (a 400 or 422) answered nothing about the work, so it is in
    neither the services that answered nor those that refused.

    Answers are cached like registry payloads. A service whose answer is already held is read
    first, so a re-run reaches the match it reached before without asking again a service that
    refused the first time. A refusal is never cached.
    """
    answered: list[str] = []
    rejected: list[str] = []
    refused: list[str] = []
    for service in sorted(SERVICES, key=lambda s: not (cache / _search_file(s, entry)[1]).exists()):
        url, name = _search_file(service, entry)
        body = cached(url, cache, name)
        if body is None:
            key = os.environ.get(service.needs_key or "", "")
            try:
                body = resolve.get(
                    url,
                    as_json=False,
                    tries=SEARCH_TRIES,
                    headers={"x-api-key": key} if key else None,
                )
                if body and service.json:
                    json.loads(body)
            except resolve.Rejected:
                rejected.append(service.name)
                continue
            except (resolve.Throttled, json.JSONDecodeError):
                refused.append(service.name)
                continue
            finally:
                time.sleep(SEARCH_DELAY)
            if body:
                store(url, cache, name, body)
        answered.append(service.name)
        if not body:
            continue
        hit = resolve.best(entry, service.candidates(json.loads(body) if service.json else body))
        if hit:
            return hit, service.name, answered, rejected, refused
    return None, "", answered, rejected, refused


def registry_lookup(
    doi: str, pmid: str, cache: pathlib.Path
) -> tuple[RegistryRecord | None, list[str]]:
    """The registry record for an identifier, and the registries that did not answer.

    A record of None with nothing refused is every registry asked answering that it has no
    such identifier. A record of None with a refusal is a lookup that was not made: the
    registry that did not answer may be the one holding the record.
    """
    asks: list[tuple[str, Callable[[str, pathlib.Path], RegistryRecord | None], str]] = []
    # Ask the registry the DOI is actually registered with. Asking Crossref about an arXiv or
    # Zenodo DOI returns 404, which is a fact about the registry rather than about the entry.
    if doi and is_datacite(doi):
        asks.append(("datacite", from_datacite, doi))
    elif doi:
        asks += [("crossref", from_crossref, doi), ("datacite", from_datacite, doi)]
    if pmid:
        asks.append(("pubmed", from_pubmed, pmid))
    refused: list[str] = []
    for name, lookup, ident in asks:
        try:
            record = lookup(ident, cache)
        except resolve.Throttled:
            refused.append(name)
            continue
        if record is not None:
            return record, refused
    return None, refused


def venue_verdict(
    e: Entry,
    record: RegistryRecord,
    found: Candidate | None,
    doi: str,
    ask: Ask,
    resolved: dict[tuple[str, ...], Resolution],
) -> VenueCheck:
    """The entry's venue against the record's, as registries identify both."""
    ours = e.venue or e.series
    theirs = record_venue(record, found, doi, ask)
    if found is not None:
        theirs = theirs.model_copy(update={"searched": True})
    shown = record.venue or (found.venue if found is not None else "")
    if not ours.strip() or theirs.repository or (not theirs.ids and not theirs.links):
        # Nothing on the record side to compare with: the entry's venue is not looked up.
        return decide(ours, shown, Resolution(status="unresolved"), theirs)
    key = (ours, e.issn)
    if key not in resolved:
        resolved[key] = resolve_name(ask, ours, e.issn)
    check = decide(ours, shown, resolved[key], theirs)
    if check.outcome != "match" and any(i.startswith("openalex:") for i in theirs.ids):
        # The record's venue is an OpenAlex source, and a conference's often is only that: the
        # name is asked of OpenAlex too, which can confirm the venue or leave it ambiguous.
        both = (ours, e.issn, "both")
        if both not in resolved:
            resolved[both] = resolve_name(ask, ours, e.issn, both=True)
        check = decide(ours, shown, resolved[both], theirs)
        key = both
    if check.outcome == MISMATCH:
        # Before a venue is called wrong: is the entry's venue a preprint server?
        resolved[key] = typed(ask, resolved[key])
        check = decide(ours, shown, resolved[key], theirs)
    return check


def audit(
    entries: list[Entry],
    cache: pathlib.Path,
    where: str = "",
    search: bool = True,
    checked: CheckedList | None = None,
) -> AuditReport:
    """Check every entry against the registry record of its identifier.

    An entry that names none is searched for by title unless `search` is off, and compared
    against the record of whatever identifier the search found. A key on `checked` is marked
    as checked by hand, which changes no verdict.
    """
    report = AuditReport(where=where, checked_list=checked)
    by_hand = set(checked.keys) if checked else set()
    refused_in_a_row = 0
    ask = asker(cache)
    # One lookup per distinct cited venue in a run: a bibliography cites one journal many times.
    resolved: dict[tuple[str, ...], Resolution] = {}
    for e in entries:
        # Could not check until something below establishes otherwise: no branch that leaves
        # early without a measurement can report one.
        verdict = report.entries[e.key] = EntryAudit(
            status="could not check", doi=e.doi, pmid=e.pmid, checked_by_hand=e.key in by_hand
        )
        doi = e.doi
        found: Candidate | None = None
        if not e.identified:
            if not search or not e.title.strip():
                verdict.status = "no identifier"
                continue
            asked = refused_in_a_row < GIVE_UP_AFTER
            hit, by, answered, rejected, refused = (
                find(e, cache) if asked else (None, "", [], [], [])
            )
            # A search that matched stopped at the match: a service refusing before it is
            # recorded, and the services after it were not asked.
            verdict.searched, verdict.rejected, verdict.refused = answered, rejected, refused
            # A rejected query is an answer about the query, made again on every run, so it never
            # counts toward giving up on the services.
            refused_in_a_row = refused_in_a_row + 1 if not (answered or rejected) else 0
            if hit is None:
                if not set(answered) & NOT_FOUND_RESTS_ON:
                    # Nobody was asked, or the services most indexed works are in did not
                    # answer. That is not a work nobody has.
                    continue
                verdict.status, verdict.not_found_by = "not found", "title search"
                continue
            found = hit
            # `resolve.best` accepts no candidate without an identifier.
            kind, ident = hit.identifier or ("", "")
            verdict.found_kind, verdict.found_id = kind, ident
            verdict.found_by = by
            if verdict.found_kind == "openalex":
                # An OpenAlex work with no DOI has no registry record to read back.
                verdict.status = "found"
                continue
            # arXiv registers every preprint with DataCite under this DOI.
            doi = ident if kind == "doi" else f"10.48550/arXiv.{ident}"
        record, refused = registry_lookup(doi, e.pmid, cache)
        if record is None:
            if refused:
                # After a title search, its refusals stay beside the registries'.
                verdict.refused = list(dict.fromkeys([*verdict.refused, *refused]))
            else:
                verdict.status, verdict.not_found_by = "not found", "identifier"
            continue
        check = venue_verdict(e, record, found, doi, ask, resolved)
        verdict.checked_against = record.source
        verdict.venue = check
        verdict.problems = compare(e, record, check)
        verdict.status = "mismatch" if verdict.problems else "ok"
    if report.checked_list is not None:
        report.checked_list.identifier_does_not_resolve = [
            k
            for k, v in report.entries.items()
            if v.checked_by_hand and v.not_found_by == "identifier"
        ]
    return report


def render(report: AuditReport, quiet: bool) -> int:
    """Print a report. The only place this module writes to stdout about results."""
    print(f"{report.where}\n")
    if not report.entries:
        print("nothing to check.\n")
        print("point at a bibliography, or run inside a library:")
        print("    citations audit --bib <path>")
        return 2

    mismatched = report.mismatched
    by_search = {k: v for k, v in report.entries.items() if v.found_id}
    compared = [k for k, v in by_search.items() if v.status in ("ok", "mismatch")]
    disagree = [k for k in compared if k in mismatched]
    if not quiet:
        for key in mismatched:
            v = report.entries[key]
            via = f", {v.found_kind} {v.found_id} found by title search" if v.found_id else ""
            print(f"  mismatch   {key}  (vs {v.checked_against}{via})")
            for problem in report.entries[key].problems:
                print(f"               {problem}")
        if mismatched:
            print()

    n = len(report.entries)
    print(f"{n:,} entr{'y' if n == 1 else 'ies'}\n")
    print(f"  checked     {report.checked:>7,}")
    print(f"  agree       {report.checked - len(mismatched):>7,}")
    print(f"  disagree    {len(mismatched):>7,}")
    if report.venue_not_comparable:
        print(
            f"  venue n/c   {len(report.venue_not_comparable):>7,}   of those checked, the venue "
            "could not be compared; never a disagreement"
        )
    if compared:
        print(
            f"  by search   {len(compared):>7,}   of those checked, named no identifier and "
            f"were found by title: {len(compared) - len(disagree)} agree, {len(disagree)} disagree"
        )
    if report.found_only:
        print(
            f"  found       {len(report.found_only):>7,}   found by title in a record with no "
            "DOI; nothing was compared"
        )
    if report.not_found:
        print(
            f"  not found   {len(report.not_found):>7,}   a title search, or the entry's own DOI "
            "or PMID, matched no record; usual for a book, report or thesis"
        )
    marked = [k for k in report.not_found if report.entries[k].checked_by_hand]
    if marked:
        print(
            f"  marked      {len(marked):>7,}   of those not found, on the list of entries "
            "checked by hand"
        )
    if report.could_not_check:
        print(
            f"  could not check{len(report.could_not_check):>4,}   a registry or every search "
            "service refused or did not answer; no measurement was made"
        )
    if report.unidentified:
        print(
            f"  no id       {len(report.unidentified):>7,}   nothing can check these until "
            "they have a DOI or PMID"
        )

    if by_search and not quiet:
        print("\nidentifiers found by title search, to add once read")
        for key, v in by_search.items():
            print(f"  {key}  {v.found_kind} {v.found_id}  ({v.found_by})")

    if report.not_found and not quiet:
        print("\nnot found")
        for key in report.not_found:
            v = report.entries[key]
            if v.not_found_by == "identifier":
                said = f"{_identifier(v)} resolves to no record"
            else:
                said = f"not found by title search ({', '.join(v.searched)})"
                said += _unasked(v)
            print(f"  {key}  {said}{'  (marked as checked)' if v.checked_by_hand else ''}")

    if report.could_not_check and not quiet:
        print("\ncould not check")
        for key in report.could_not_check:
            v = report.entries[key]
            if v.found_id:
                said = f"{_identifier(v)} could not be read back{_unasked(v)}"
            elif v.searched:
                said = f"searched ({', '.join(v.searched)}){_unasked(v)}"
            elif v.refused or v.rejected:
                said = _unasked(v).removeprefix("; ")
            else:
                said = "not asked"
            print(f"  {key}  {said}")

    if report.venue_not_comparable and not quiet:
        # Both names, side by side: only an identifier comparison may call a venue right or
        # wrong, so what registries could not settle is left for a person to read.
        print("\nvenue not compared by identifier")
        for key, check in report.venue_not_comparable.items():
            print(f"  {key}  {check.line()}")

    if mismatched:
        kinds: collections.Counter = collections.Counter()
        for key in mismatched:
            for problem in report.entries[key].problems:
                label = re.sub(r"^author \d+ ", "", problem)
                if "stops at" in label:
                    label = "author list truncated with no marker"
                elif "names, registry" in label:
                    label = "author list longer than the registry's"
                elif "prefix" in label:
                    label = "title (one continues the other)"
                kinds[label.split(":")[0][:38]] += 1
        print("\nwhat disagrees")
        for kind, count in kinds.most_common():
            print(f"  {count:>7,}  {kind}")

    listed = report.checked_list
    if listed is not None:
        print(f"\nchecked by hand  {listed.path}  sha256 {listed.sha256[:12]}")
        for key in report.listed_but_found:
            status = report.entries[key].status
            print(f"  warning: {key} is on the list, but a registry has it ({status})")
        for key in listed.identifier_does_not_resolve:
            print(
                f"  warning: {key} is listed as checked, but its "
                f"{_identifier(report.entries[key], kind_only=True)} does not resolve; "
                "check it isn't mistyped"
            )
        if listed.stale:
            print(f"  warning: {len(listed.stale)} listed key(s) not in what was audited:")
            for key in listed.stale:
                print(f"    {key}")

    print()
    if mismatched:
        print(f"{len(mismatched)} disagree with the record their own identifier resolves to.")
        print("a wrong author list on a right DOI is invisible to every other check.")
        if disagree:
            print(
                f"{len(disagree)} of them against an identifier found by title search, which "
                "can be another version of the work."
            )
    unlisted = report.not_found_unchecked
    if unlisted:
        print(
            f"{len(unlisted)} not found and not on the list of entries checked by hand; "
            "--strict fails on these."
        )
    if report.could_not_check:
        print(
            f"{len(report.could_not_check)} could not be checked, because a lookup failed; "
            "run again. --strict exits 2 on these when nothing else fails."
        )
    if not report.measured and not report.could_not_check:
        print(
            "nothing was checked: no entry was compared with a registry record or searched for. "
            "--strict exits 2."
        )
    elif not (mismatched or unlisted or report.could_not_check):
        if report.checked:
            print("every checked entry matches its registry record.")
        elif report.not_found:
            print(
                "no entry was compared with a registry record; each one not found is on the "
                "list of entries checked by hand."
            )
        else:
            print("no entry was compared with a registry record.")
    return report.strict_exit


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="citations audit", description=__doc__.split("\n")[0])
    ap.add_argument("--bib", help="a BibTeX file, instead of the library's records")
    ap.add_argument("--only", help="restrict to records cited by this paper")
    ap.add_argument(
        "--cache", help="where fetched payloads live (default: .audit-cache beside what is audited)"
    )
    ap.add_argument("--json", dest="json_out", help="write the full report here")
    ap.add_argument(
        "--strict",
        action="store_true",
        help="exit 1 on any disagreement, and on any entry not found that is not on the "
        "checked list; exit 2 when nothing else fails but a lookup could not be made, so CI "
        "can retry (default: report everything and exit 0)",
    )
    ap.add_argument(
        "--checked",
        help="a file of keys checked by hand, one per line, `#` for a note: a listed key not "
        "found does not fail --strict (default: <bib stem>.checked.txt beside the bibliography, "
        f"or {LIBRARY_CHECKED} in the library, when it exists)",
    )
    ap.add_argument(
        "--no-search",
        action="store_true",
        help="do not search by title for entries with no DOI or PMID; they are counted as "
        "`no id` and no search service is asked (default: search)",
    )
    ap.add_argument("--quiet", action="store_true", help="counts only")
    a = ap.parse_args(argv)

    if a.bib:
        bib = pathlib.Path(a.bib).expanduser().resolve()
        if not bib.exists():
            raise CitationsError(f"no such file: {bib}")
        entries = entries_from_bib(bib)
        # Beside the bibliography, not in the library. $CITATIONS_HOME may point at a shared
        # library with nothing to do with this paper, and the payloads an audit rests on
        # belong with the file they were fetched for.
        cache = pathlib.Path(a.cache or bib.parent / ".audit-cache").expanduser()
        default_checked = bib.with_name(bib.stem + CHECKED_SUFFIX)
        where = f"bibtex  {bib}"
    else:
        library = paths.home()
        entries = entries_from_library(a.only)
        cache = pathlib.Path(a.cache or library / ".audit-cache").expanduser()
        default_checked = library / LIBRARY_CHECKED
        where = f"library {library}"
    where += f"\ncache   {cache}"

    keys = [e.key for e in entries]
    if a.checked:
        listed = pathlib.Path(a.checked).expanduser()
        if not listed.is_file():
            raise CitationsError(f"no such file: {listed}")
        checked: CheckedList | None = load_checked(listed, keys)
    else:
        listed = default_checked
        checked = load_checked(listed, keys) if listed.is_file() else None

    report = audit(entries, cache, where, search=not a.no_search, checked=checked)
    out = pathlib.Path(a.json_out).expanduser() if a.json_out else None
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        # Written before the report is printed, so a failure while rendering loses nothing.
        # Replaced rather than truncated and refilled. A CI job reads this file rather than the
        # printed report, and a run killed partway through the write leaves invalid JSON where the
        # previous audit's verdicts were: the next reader gets a parse error whose cause is a
        # killed process, not anything the bibliography did.
        atomic_write(out, report.model_dump_json(indent=2) + "\n")
    code = render(report, a.quiet)
    if out is not None:
        print(f"\nwrote {out}")
    if a.strict or not report.entries:
        return code
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
