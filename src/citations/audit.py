"""Does the metadata match the record the identifier resolves to?

    citations audit                     every record in the library that has an identifier
    citations audit --bib refs.bib      a BibTeX file directly
    citations audit --only <paper>      records one paper cites
    citations audit --json report.json  machine-readable, one object per entry
    citations audit --strict            exit 1 on any disagreement, for CI

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

Responses are cached, so a re-run is offline and the report is reproducible from what was
fetched.
"""
from __future__ import annotations

import argparse
import collections
import html
import json
import pathlib
import re
import socket
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from pydantic import BaseModel, ConfigDict, Field

from citations import paths
from citations.exceptions import CitationsError
from citations.models import load_record
from citations.text import fold, surname, surname_variants, tokens, variants

UA = "citations/1.0 (mailto:elliot@elliottower.ai)"

#: Crossref's polite-pool rate limit is 50 requests a second; this is far under it and keeps
#: a full-library audit from looking like a scrape.
DELAY = 0.34

#: Errors that mean a request did not complete, as distinct from a registry that answered and
#: had nothing. `HTTPError` subclasses `URLError` and is caught first where the code matters.
NETWORK_ERRORS = (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError,
                  UnicodeDecodeError)

BIB_ENTRY = re.compile(r"@(\w+)\s*\{\s*([^,\s]+)\s*,(.*?)\n\}", re.DOTALL)
BIB_FIELD = re.compile(r"(\w+)\s*=\s*[{\"](.*?)[}\"]\s*,?\s*(?=\n\s*\w+\s*=|\Z)", re.DOTALL)


#: Generational suffixes are filed with the surname by some publishers and dropped by others.
SUFFIXES = {"jr", "sr", "ii", "iii", "iv"}

Person = tuple[tuple[str, ...], tuple[str, ...]]


def split_authors(names: list[str]) -> tuple[list[Person], bool]:
    """(family, given) token pairs, plus whether the list ends in an `and others` marker."""
    parts = [n.strip() for n in names if n and n.strip()]
    truncated = bool(parts) and fold(parts[-1]) in ("others", "et al")
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
        variants(" ".join(ours_family)) & variants(" ".join(their_family)))
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
    for our_part, their_part in zip(mg, yg):
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

    years: list[str] = Field(default_factory=list)
    """Every year the registry reports. A journal publishing online ahead of print carries two
    legitimate years, and accepting only one reports the other as an error."""

    volume: str = ""
    pages: str = ""
    authors: list[Person] = Field(default_factory=list)


class EntryAudit(BaseModel):
    """The verdict on one entry."""

    status: str
    """`ok`, `mismatch`, `unresolved`, or `no identifier`."""

    checked_against: str | None = None
    """Which registry the comparison was made against, when one answered."""

    doi: str = ""
    pmid: str = ""

    problems: list[str] = Field(default_factory=list)
    """One message per disagreeing field. Empty when the status is not `mismatch`."""


class AuditReport(BaseModel):
    """Every entry's verdict, plus where they came from.

    Returned rather than printed, so the same audit can render a report, write JSON, or be
    read by a caller that imported this package instead of running it.
    """

    entries: dict[str, EntryAudit] = Field(default_factory=dict)
    where: str = ""

    def by(self, status: str) -> list[str]:
        return [k for k, v in self.entries.items() if v.status == status]

    @property
    def mismatched(self) -> list[str]:
        return self.by("mismatch")

    @property
    def unresolved(self) -> list[str]:
        return self.by("unresolved")

    @property
    def unidentified(self) -> list[str]:
        return self.by("no identifier")

    @property
    def checked(self) -> int:
        return len(self.entries) - len(self.unresolved) - len(self.unidentified)

    @property
    def ok(self) -> bool:
        """An audit that resolved nothing is not a pass; it made no measurement."""
        return bool(self.entries) and not self.mismatched and not self.unresolved


# --------------------------------------------------------------------------------- entries

def entries_from_bib(path: pathlib.Path) -> list[Entry]:
    out = []
    for _kind, key, body in BIB_ENTRY.findall(path.read_text()):
        f = {name.lower(): " ".join(value.split()) for name, value in BIB_FIELD.findall(body)}
        out.append(Entry(
            key=key, title=f.get("title", ""),
            authors=[a for a in re.split(r"\s+and\s+", f.get("author", "")) if a],
            year=f.get("year", ""), venue=f.get("journal") or f.get("booktitle", ""),
            volume=f.get("volume", ""), pages=f.get("pages", ""),
            doi=f.get("doi", ""), pmid=f.get("pmid", "")))
    return sorted(out, key=lambda e: e.key)


def entries_from_library(only: str | None) -> list[Entry]:
    out = []
    for p in sorted(paths.records().glob("*.yaml")):
        rec = load_record(p)
        if only and only not in rec.cited_by:
            continue
        extra = rec.model_extra or {}
        out.append(Entry(
            key=rec.slug, title=rec.title, authors=rec.authors, year=rec.year,
            venue=rec.venue, volume=str(extra.get("volume") or ""),
            pages=str(extra.get("pages") or ""), doi=rec.doi,
            pmid=str(extra.get("pmid") or ""), et_al=rec.et_al))
    return out


# --------------------------------------------------------------------------------- sources

def fetch(url: str, cache: pathlib.Path, name: str) -> str | None:
    """A cached registry response, or None when the request did not complete."""
    cache.mkdir(parents=True, exist_ok=True)
    hit = cache / name
    if hit.exists():
        return hit.read_text() or None
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    time.sleep(DELAY)
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            body = r.read().decode("utf-8", "replace")
    except NETWORK_ERRORS as exc:
        print(f"    could not fetch {name}: {exc}")
        return None
    hit.write_text(body)
    return body


def from_crossref(doi: str, cache: pathlib.Path) -> RegistryRecord | None:
    body = fetch(f"https://api.crossref.org/works/{urllib.parse.quote(doi, safe='')}",
                 cache, f"crossref_{re.sub(r'[^A-Za-z0-9]', '_', doi)}.json")
    if not body:
        return None
    try:
        m = json.loads(body)["message"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return None
    years = []
    for field in ("published-print", "published-online", "issued", "created"):
        parts = (m.get(field) or {}).get("date-parts") or []
        if parts and parts[0] and parts[0][0]:
            years.append(str(parts[0][0]))
    return RegistryRecord(
        source="crossref",
        title=(m.get("title") or [""])[0],
        venue=(m.get("container-title") or [""])[0],
        years=years,
        volume=str(m.get("volume") or ""),
        pages=str(m.get("page") or m.get("article-number") or ""),
        authors=[(tokens(a.get("family", "")), tokens(a.get("given", "")))
                 for a in m.get("author", []) if a.get("family")])


def from_pubmed(pmid: str, cache: pathlib.Path) -> RegistryRecord | None:
    body = fetch("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
                 f"?db=pubmed&id={urllib.parse.quote(pmid)}&retmode=xml",
                 cache, f"pubmed_{pmid}.xml")
    if not body:
        return None
    try:
        art = ET.fromstring(body).find(".//PubmedArticle")
    except ET.ParseError:
        return None
    if art is None:
        return None
    title = art.find(".//ArticleTitle")
    journal = art.find(".//Journal")
    year = journal.findtext(".//Year") if journal is not None else ""
    return RegistryRecord(
        source="pubmed",
        title="".join(title.itertext()) if title is not None else "",
        venue=((journal.findtext("ISOAbbreviation") or journal.findtext("Title") or "")
               if journal is not None else ""),
        years=[year] if year else [],
        volume=(journal.findtext(".//Volume") or "") if journal is not None else "",
        pages=art.findtext(".//MedlinePgn") or "",
        authors=[(tokens(a.findtext("LastName")), tokens(a.findtext("ForeName") or ""))
                 for a in art.findall(".//Author") if a.findtext("LastName")])


# ------------------------------------------------------------------------------ comparison

def compare(entry: Entry, record: RegistryRecord) -> list[str]:
    """Every field of `entry` that disagrees with `record`, as one message each."""
    problems = []

    our_title = fold(entry.title)
    their_title = fold(record.title.rstrip("."))
    if our_title and their_title and our_title != their_title:
        if their_title.startswith(our_title) or our_title.startswith(their_title):
            problems.append("title (one is a prefix of the other): registry has "
                            f"{record.title!r}")
        else:
            problems.append(f"title: ours {entry.title!r} vs registry {record.title!r}")

    years = [y for y in record.years if y]
    if entry.year and years and entry.year not in years:
        problems.append(f"year: ours {entry.year} vs registry "
                        f"{'/'.join(dict.fromkeys(years))}")

    if entry.volume and record.volume and entry.volume != record.volume:
        problems.append(f"volume: ours {entry.volume} vs registry {record.volume}")

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
        for i, (ours, theirs) in enumerate(zip(mine, yours), start=1):
            said = disagreement(ours, theirs)
            if said:
                problems.append(f"author {i} {said}")
        if len(mine) < len(yours) and not truncated:
            problems.append(f"author list stops at {len(mine)} of {len(yours)} with no "
                            "'and others' marker, so it reads as complete")
        if len(mine) > len(yours):
            problems.append(f"author list has {len(mine)} names, registry has {len(yours)}")
    return problems


# ------------------------------------------------------------------------------------- run

def audit(entries: list[Entry], cache: pathlib.Path, where: str = "") -> AuditReport:
    """Check every entry against the registry its own identifier points at."""
    report = AuditReport(where=where)
    for e in entries:
        if not e.identified:
            report.entries[e.key] = EntryAudit(status="no identifier")
            continue
        record = from_crossref(e.doi, cache) if e.doi else None
        if record is None and e.pmid:
            record = from_pubmed(e.pmid, cache)
        if record is None:
            report.entries[e.key] = EntryAudit(status="unresolved", doi=e.doi, pmid=e.pmid)
            continue
        problems = compare(e, record)
        report.entries[e.key] = EntryAudit(
            status="mismatch" if problems else "ok", checked_against=record.source,
            doi=e.doi, pmid=e.pmid, problems=problems)
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
    if not quiet:
        for key in mismatched:
            print(f"  mismatch   {key}  (vs {report.entries[key].checked_against})")
            for problem in report.entries[key].problems:
                print(f"               {problem}")
        if mismatched:
            print()

    n = len(report.entries)
    print(f"{n:,} entr{'y' if n == 1 else 'ies'}\n")
    print(f"  checked     {report.checked:>7,}")
    print(f"  agree       {report.checked - len(mismatched):>7,}")
    print(f"  disagree    {len(mismatched):>7,}")
    if report.unresolved:
        print(f"  unresolved  {len(report.unresolved):>7,}   the identifier did not fetch; "
              "no measurement was made")
    if report.unidentified:
        print(f"  no id       {len(report.unidentified):>7,}   nothing can check these until "
              "they have a DOI or PMID")

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

    print()
    if mismatched:
        print(f"{len(mismatched)} disagree with the record their own identifier resolves to.")
        print("a wrong author list on a right DOI is invisible to every other check.")
    elif report.unresolved:
        print(f"nothing disagreed. {len(report.unresolved)} unresolved — "
              "no measurement for those.")
    else:
        print("every checked entry matches its registry record.")
    return 1 if (mismatched or report.unresolved) else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="citations audit", description=__doc__.split("\n")[0])
    ap.add_argument("--bib", help="a BibTeX file, instead of the library's records")
    ap.add_argument("--only", help="restrict to records cited by this paper")
    ap.add_argument("--cache", help="where fetched payloads live "
                                    "(default: .audit-cache beside what is audited)")
    ap.add_argument("--json", dest="json_out", help="write the full report here")
    ap.add_argument("--strict", action="store_true", help="exit 1 on any disagreement")
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
        where = f"bibtex  {bib}"
    else:
        library = paths.home()
        entries = entries_from_library(a.only)
        cache = pathlib.Path(a.cache or library / ".audit-cache").expanduser()
        where = f"library {library}"
    where += f"\ncache   {cache}"

    report = audit(entries, cache, where)
    code = render(report, a.quiet)
    if a.json_out:
        out = pathlib.Path(a.json_out).expanduser()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(report.model_dump_json(indent=2) + "\n")
        print(f"\nwrote {out}")
    return code if a.strict else (2 if code == 2 else 0)


if __name__ == "__main__":
    raise SystemExit(main())
