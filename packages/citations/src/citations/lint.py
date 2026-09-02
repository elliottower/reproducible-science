"""Lint the records with papis doctor, and a `.bib` for repeated keys and wrong author lists.

    citations lint                     # the records, through papis
    citations lint --json              # machine-readable
    citations lint --bib refs.bib      # repeated keys and bare family names, papis not required
    citations lint --authors refs.bib  # author lists, against each entry's own identifier

The modes answer different questions about different artifacts. The records mode asks whether a
record carries the fields its entry type requires, and needs papis to know what those are. The
two `.bib` modes need nothing but the file and a cache, so they run where papis is not
installed, which is most continuous integration.

A repeated key is worth its own check because BibTeX's response to one is non-fatal and surfaces
somewhere else. It keeps the copy the file defines first, skips the repeat, and writes a `.bbl`
without it, so the reference list prints an entry nobody is looking at while the corrected one
sits in the `.bib`. See `add.py`, which refuses to write one.

`--bib` also reports an author list written as family names with no given names:

    author = {Bhaskar and Wettig and Friedman and Chen}

which prints as "Bhaskar, Wettig, Friedman, and Chen." in the reference list. The paper it was
found in carried five of these into a submission. `--authors` reports none of them, because it
compares family names and those four are the four arXiv:2406.16778 lists; the given names it
never reads are the ones that are missing. Nothing outside the file settles this, so it sits in
the offline mode, beside the repeated keys.

A name that is one word, carries no comma and is not braced has no given part for any reference
style to print. `{OpenAI}` and `{Open Science Collaboration}` are braced, which is how BibTeX is
told a name is complete as written, so neither is a finding.

`--authors` reads the author list back against the registry the entry's own identifier names. On
2026-08-31 two agents, in one session, attributed "Mediational E-values" (Epidemiology
30(6):835-837, 2019) to VanderWeele and Chiba while quoting the paper's own DOI,
10.1097/EDE.0000000000001064; Crossref gives the authors as Smith, Louisa H. and VanderWeele,
Tyler J. A VanderWeele and Chiba paper does exist -- on exposure-induced mediator-outcome
confounders, in Epidemiology, Biostatistics and Public Health 11(2), 2014 -- so the entry was
two real papers written as one. Every field named something that exists, because each field
belonged to one of them, which is why a reader of the reference list does not catch it. The
identifier was right both times. Only the names were wrong, and nothing in this toolchain read
them.

Four failure modes fall out of the one comparison, and the check reports which:

    wrong      a name that belongs to another paper, under a correct identifier
    dropped    a list that stops early with no marker, so it reads as complete
    marker     `and others` or `et al.` written into a `.bib`, which this project forbids
    order      the registry's names in another sequence, from a given/family swap

Comparison is on family names, folded, both ways an accent can be written, and with surname
particles stripped as well as kept -- a check that flags Krzyżosiak against Krzyzosiak, or
"de Mezer" against the "Mezer" OpenAlex files it under, is a check nobody leaves switched on.

Resolved lists are cached in `.author-cache.yaml` beside the bibliography, so a second run needs
no network and a pre-commit hook can call it. Anyone who can write that file can write anything
into it, so the cache is a convenience and never evidence; the same is true of `.audit-cache/`,
and `audit.py` says so at more length.

Papis encodes years of BibTeX edge cases -- which fields each entry type requires, which
BibLaTeX keys are aliases, what counts as junk in an author field. Rediscovering that one
reviewer complaint at a time is a bad use of anyone's time, so this borrows it.

Papis owns nothing. `records/` stays authoritative; this projects each record into the shape
papis expects, runs its checks against the projection, and reports. Nothing is written back.

Note that papis means something different by `cited_by` -- it fetches, from Crossref, the works
that cite a document. Ours records which of our own papers cite it. Same words, opposite
direction, which is why the projection drops the relationship entirely rather than trying to
map it.
"""

from __future__ import annotations

import argparse
import collections
import json
import pathlib
import re
import shutil
import subprocess
import tempfile
import time
from typing import Any

import yaml
from pydantic import BaseModel, Field

from citations import audit, bibtex, paths, resolve, services
from citations.exceptions import CitationsError
from citations.models import Record, load_record
from citations.text import fold, variants

#: Venue words that decide which BibTeX entry type a record projects to, and therefore which
#: fields papis will demand of it.
PROCEEDINGS_WORDS = (
    "proceedings",
    "conference",
    "workshop",
    "symposium",
    "neurips",
    "icml",
    "iclr",
    "acl",
    "emnlp",
    "aaai",
    "ijcai",
)
PUBLISHER_WORDS = ("press", "publisher", "wiley", "springer", "mifflin", "mcnally", "routledge")


def find_papis() -> pathlib.Path | None:
    """Wherever papis is, or None.

    Resolved from PATH rather than a fixed path inside this package: an interpreter-relative
    guess is wrong under every install that is not the one it was written for, and it fails
    by reporting that papis is missing rather than by looking in the wrong place out loud.
    """
    found = shutil.which("papis")
    return pathlib.Path(found) if found else None


def project(rec: Record) -> dict:
    """A record in the shape papis judges. Deliberately lossy."""
    authors = []
    for a in rec.authors:
        if "," in a:
            fam, giv = (x.strip() for x in a.split(",", 1))
        else:
            parts = a.split()
            fam, giv = (parts[-1], " ".join(parts[:-1])) if parts else (a, "")
        authors.append({"family": fam, "given": giv})

    doc: dict[str, Any] = {
        "ref": rec.slug,
        "title": rec.title,
        "author": " and ".join(rec.authors),
        "author_list": authors,
    }
    year = rec.year.strip()
    if year.isdigit():
        doc["year"] = int(year)  # papis wants an int; ours are strings from BibTeX

    venue = rec.venue.strip()
    lowered = venue.lower()
    if any(w in lowered for w in PROCEEDINGS_WORDS):
        doc["type"], doc["booktitle"] = "inproceedings", venue
    elif any(w in lowered for w in PUBLISHER_WORDS):
        doc["type"], doc["publisher"] = "book", venue
    elif venue:
        doc["type"], doc["journal"] = "article", venue
    else:
        doc["type"] = "misc"

    for key, value in (("doi", rec.doi), ("url", rec.url)):
        if value:
            doc[key] = value
    return doc


# --------------------------------------------------------------------------------------------
# Names, as a `.bib` writes them. Both `.bib` modes read them through here.
# --------------------------------------------------------------------------------------------

#: A shortened list, however it is written. `and others` is BibTeX's own marker and splits into
#: a name of its own; `et al.` arrives from reference managers and from hand-editing, glued to
#: the last name, where splitting on ` and ` never sees it.
MARKERS = ("others", "et al")
ET_AL = re.compile(r",?\s*\bet\.?\s*al\.?", re.IGNORECASE)

#: The two separators a name is read by. Each occurs inside a braced group meaning something
#: else, which is why `split_outside_braces` exists rather than `str.split`.
AND = re.compile(r"\s+and\s+")
SPACE = re.compile(r"\s+")


def split_outside_braces(text: str, separator: re.Pattern[str]) -> list[str]:
    """`text` cut wherever `separator` matches outside a braced group, empty pieces dropped.

    BibTeX reads a braced group as one unsplittable unit, and both separators that matter here
    occur inside one. `{President's Council of Advisors on Science and Technology}` is a single
    author rather than two, and `P{\\u a}s{\\u a}reanu` is a single word whose spaces sit inside
    the accent commands that spell it. Splitting brace-blind makes the first into a second
    author reading `Technology}` and the second into three words, so a corporate author is
    reported as a name with no given name and a real one is not reported at all.
    """
    parts: list[str] = []
    depth = start = i = 0
    while i < len(text):
        char = text[i]
        if char == "\\":
            i += 2  # an escaped brace, or an accent command whose argument follows
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
        elif depth < 1 and (match := separator.match(text, i)):
            parts.append(text[start:i])
            start = i = match.end()
            continue
        i += 1
    parts.append(text[start:])
    return [stripped for stripped in (p.strip() for p in parts) if stripped]


def split_authors(field: str) -> tuple[list[str], bool]:
    """The names a BibTeX `author` field lists, and whether it is marked as shortened."""
    names: list[str] = []
    marked = False
    for part in split_outside_braces(field or "", AND):
        if fold(part) in MARKERS:
            marked = True
            continue
        trimmed = ET_AL.sub("", part).strip().strip(",").strip()
        if trimmed != part:
            marked = True
        if trimmed:
            names.append(trimmed)
    return names, marked


def braced(name: str) -> bool:
    """Whether one whole name sits inside a single pair of braces.

    Braces are how BibTeX is told that a name has no given part and is to be printed as
    written: `{OpenAI}`, `{Open Science Collaboration}`, `{NASA}`. `Gon{\\c{c}}alves` is not
    this. Its braces spell one letter, and the name around them is a family name that has lost
    its given name.
    """
    if not (name.startswith("{") and name.endswith("}")):
        return False
    depth = 0
    for i, char in enumerate(name):
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return i == len(name) - 1
    return False


def bare_family_names(field: str) -> list[str]:
    """The names in one `author` field written as a family name with no given name.

    `Bhaskar` is one. `Bhaskar, Adithya` and `Adithya Bhaskar` are not, and neither is `{NASA}`.
    """
    names, _marked = split_authors(field)
    return [
        name
        for name in names
        if "," not in name and len(split_outside_braces(name, SPACE)) == 1 and not braced(name)
    ]


# --------------------------------------------------------------------------------------------
# --bib: what one file's own text is enough to settle
# --------------------------------------------------------------------------------------------


class BibFinding(BaseModel):
    """One defect in a bibliography that the file alone establishes."""

    file: str
    kind: str
    """`repeated` for a key the file defines more than once, `bare` for an author list written
    as family names with no given names."""
    keys: list[str]
    lines: list[int]
    names: list[str] = Field(default_factory=list)
    """`bare` only: the names that carry no given name."""


def numbered(lines: list[int]) -> str:
    """One line number or several, written the way BibTeX reports a repeat."""
    return ("lines " if len(lines) > 1 else "line ") + ", ".join(str(line) for line in lines)


def bib_findings(path: pathlib.Path) -> tuple[int, list[BibFinding]]:
    """`(entries, every defect)` for one bibliography.

    Repeated keys first, so the report opens on the defect that costs an entry its place in the
    reference list entirely.
    """
    if not path.is_file():
        raise CitationsError(f"no such file: {path}")
    text = bibtex.read(path)
    keys = bibtex.key_lines(text)
    findings = [
        BibFinding(
            file=str(path),
            kind="repeated",
            keys=[key for key, _line in occurrences],
            lines=[line for _key, line in occurrences],
        )
        for _folded, occurrences in sorted(bibtex.duplicate_keys(text).items())
    ]

    # Reversed, so a key defined twice reports the line it was defined on first. Which copy
    # BibTeX prints is the repeated-key finding's question, not this one's.
    lines = dict(reversed(keys))
    for _kind, key, body in bibtex.entries(text):
        fields = {n.lower(): " ".join(v.split()) for n, v in audit.BIB_FIELD.findall(body)}
        bare = bare_family_names(fields.get("author", ""))
        if bare:
            findings.append(
                BibFinding(
                    file=str(path), kind="bare", keys=[key], lines=[lines.get(key, 0)], names=bare
                )
            )
    return len(keys), findings


def bib_defects(files: list[pathlib.Path], as_json: bool) -> int:
    """Every repeated key and every author list with no given names. Exit 1 if any file has one.

    Exits 1 under `--json` as well. A machine-readable mode that reports findings and exits 0
    is a check that cannot fail, which is worse in continuous integration than no check: the
    pipeline goes green while the file it examined is broken.
    """
    entries = 0
    findings: list[BibFinding] = []
    for path in files:
        counted, found = bib_findings(path)
        entries += counted
        findings.extend(found)

    if as_json:
        print(json.dumps([f.model_dump() for f in findings], indent=1))
        return 1 if findings else 0

    # Findings sit under the file they were found in. Two bibliographies repeating the same key
    # is one finding each, and a flat list of keys names neither -- copies of one bibliography
    # in different repositories share a basename as well as their defects.
    for path in files:
        print(f"  bib  {path}")
        for f in (x for x in findings if x.file == str(path)):
            written = f.keys if len(set(f.keys)) > 1 else [f.keys[0]]
            print(f"    {' / '.join(written)[:36]:<38}{f.kind:<10}{numbered(f.lines)}")
            if f.names:
                listed = ", ".join(repr(n) for n in f.names)
                print(f"      no given name for {len(f.names)} of the authors: {listed}")

    repeated = [f for f in findings if f.kind == "repeated"]
    bare = [f for f in findings if f.kind == "bare"]
    print(
        f"\n  {entries} entries, {len(repeated)} repeated key(s), "
        f"{len(bare)} author list(s) with a bare family name"
    )
    if not findings:
        print("  no key is defined twice, and every author list carries given names.")
        return 0
    if repeated:
        print("\n  BibTeX keeps the copy a file defines first and skips the repeat, writing a")
        print("  .bbl without it: an entry appended below one that is already there never")
        print("  reaches the reference list, and the file gives no sign of which copy is being")
        print("  printed. Where two keys differ only in case, the citation goes undefined")
        print("  instead. Delete one, or give it another key.")
    if bare:
        print("\n  A family name with no given name prints without one: `Bhaskar, Wettig,")
        print("  Friedman, and Chen.` is what the reference list of a submitted paper carried.")
        print("  `--authors` agrees with an entry like that, because the family names are the")
        print("  ones the identifier resolves to and family names are all it compares. Write")
        print("  each author as `Family, Given`, or brace the name where it is a mononym or an")
        print("  institution and has no given part.")
    return 1


# --------------------------------------------------------------------------------------------
# --authors: the author list against the registry the entry's own identifier names
# --------------------------------------------------------------------------------------------

#: Where resolved lists are kept: beside the bibliography they were fetched for, not in the
#: library. `$CITATIONS_HOME` may point at a shared library with nothing to do with this paper.
CACHE_NAME = ".author-cache.yaml"

#: Well under Crossref's polite-pool limit of 50 requests a second, and enough that checking a
#: whole bibliography does not read as a scrape.
DELAY = 0.34

#: Filed with the family name by some publishers and with the given name by others. OpenAlex
#: indexes "de Mezer" under Mezer while Crossref keeps the particle, and both spell one name.
PARTICLES = frozenset(
    {
        "abu", "al", "bin", "da", "dal", "das", "de", "del", "della", "den", "der", "des", "di",
        "do", "dos", "du", "ibn", "la", "le", "mac", "mc", "st", "ten", "ter", "van", "vander",
        "von", "zu",
    }
)  # fmt: skip

#: An arXiv identifier deposited as a DOI. The prefix is DataCite's, so Crossref answers 404 for
#: these, which reads as an identifier that did not resolve when the identifier is fine.
ARXIV_DOI = re.compile(r"^10\.48550/arxiv\.(.+)$", re.IGNORECASE)

#: Written before the DOI in a `doi = {...}` field by about half of the reference managers.
DOI_PREFIX = re.compile(r"^(https?://(dx\.)?doi\.org/|doi:)", re.IGNORECASE)
ARXIV_URL = re.compile(r"arxiv\.org/abs/([^\s}/]+)", re.IGNORECASE)
ARXIV_VERSION = re.compile(r"v\d+$")


def family(name: str) -> str:
    """The family part of one name, written either way round, with its particles.

    `Family, Given` is unambiguous. `Given Family` is not: a family name may be several words,
    and taking the last one alone files "Anna de Mezer" under Mezer while the entry beside it
    writes de Mezer.

    Returned as it was written. Folding here instead deletes the accent that `variants` reads to
    offer the other spelling of it, so Hölscher-Obermaier could no longer reach `hoelscher` and
    every author whose name a registry transliterates came back a disagreement.
    """
    if "," in name:
        return name.split(",")[0].strip()
    words = split_outside_braces(name, SPACE)
    while words and fold(words[-1]) in audit.SUFFIXES:
        words = words[:-1]
    if not words:
        return ""
    start = len(words) - 1
    while start > 0 and fold(words[start - 1]) in PARTICLES:
        start -= 1
    return " ".join(words[start:])


def forms(name: str) -> frozenset[str]:
    """Every way one person's family name might be written, folded for comparison.

    Both foldings, because neither alone reads the two conventions as one name: Hölscher is
    `holscher` with the accent dropped and `hoelscher` written out, a bibliography carries one
    and a registry the other. Particles are stripped as well as kept, for the same reason in
    the other direction. A check that reports Krzyżosiak against Krzyzosiak cries wolf on most
    of a bibliography and is switched off within the week, which is worse than not having it.
    """
    out: set[str] = set()
    for spelling in variants(family(name)):
        words = [w for w in spelling.split() if w not in audit.SUFFIXES]
        out.add(" ".join(words))
        while len(words) > 1 and words[0] in PARTICLES:
            words = words[1:]
            out.add(" ".join(words))
    return frozenset(f for f in out if f)


def same_person(ours: str, theirs: str) -> bool:
    """Whether two renderings name one family. Two names agree when their forms intersect."""
    return bool(forms(ours) & forms(theirs))


def reordered(ours: list[str], theirs: list[str]) -> bool:
    """The same names in another sequence.

    Reported apart from a wrong name because it is a different defect with a different cause --
    a registry that returned given and family swapped, or an entry sorted alphabetically -- and
    because position-by-position it looks like every author being wrong at once.
    """
    if len(ours) != len(theirs):
        return False
    left = list(theirs)
    for name in ours:
        for i, other in enumerate(left):
            if same_person(name, other):
                left.pop(i)
                break
        else:
            return False
    return True


def identifier_of(fields: dict[str, str]) -> tuple[str, str]:
    """`(kind, value)` for the identifier an entry carries, or `("", "")` where it carries none.

    An arXiv id is read out of `eprint`, out of an `arxiv` field, or out of an arXiv URL,
    because the three conventions are all in use and an entry written in the second two is not
    an entry with no identifier.
    """
    doi = DOI_PREFIX.sub("", fields.get("doi", "").strip()).strip()
    if doi:
        deposited = ARXIV_DOI.match(doi)
        return ("arxiv", deposited.group(1)) if deposited else ("doi", doi)

    eprint = (fields.get("eprint") or fields.get("arxiv") or "").strip()
    if eprint and fields.get("archiveprefix", "").strip().lower() in ("", "arxiv"):
        bare = re.sub(r"^arxiv:", "", eprint, flags=re.IGNORECASE)
        return "arxiv", ARXIV_VERSION.sub("", bare)

    in_url = ARXIV_URL.search(fields.get("url", ""))
    return ("arxiv", ARXIV_VERSION.sub("", in_url.group(1))) if in_url else ("", "")


def compare(ours: list[str], marked: bool, theirs: list[str]) -> list[tuple[str, str]]:
    """`(kind, what)` for every way an entry's author list disagrees with the registry's."""
    if not ours:
        return [
            ("dropped", f"no author field; the registry lists {len(theirs)}, from {theirs[0]!r}")
        ]

    problems: list[tuple[str, str]] = []
    if marked:
        problems.append(
            (
                "marker",
                f"the list is shortened with `and others` / `et al.`; the registry lists "
                f"{len(theirs)}, and a shortened list reads as a complete one",
            )
        )

    wrong = [
        i
        for i, (mine, yours) in enumerate(zip(ours, theirs, strict=False), start=1)
        if not same_person(mine, yours)
    ]
    if wrong and reordered(ours, theirs):
        problems.append(
            (
                "order",
                f"the same {len(ours)} names in another sequence: ours opens {ours[0]!r}, the "
                f"registry opens {theirs[0]!r}",
            )
        )
    else:
        problems.extend(
            ("wrong", f"author {i}: ours {ours[i - 1]!r}, registry {theirs[i - 1]!r}")
            for i in wrong
        )

    if len(ours) < len(theirs) and not marked:
        problems.append(
            (
                "dropped",
                f"{len(ours)} names where the registry lists {len(theirs)}, with no marker, so "
                f"the list reads as complete; the rest start at {theirs[len(ours)]!r}",
            )
        )
    elif len(ours) > len(theirs):
        problems.append(("extra", f"{len(ours)} names where the registry lists {len(theirs)}"))
    return problems


def load_cache(path: pathlib.Path) -> dict:
    if not path.exists():
        return {}
    loaded = yaml.safe_load(path.read_text()) or {}
    return loaded if isinstance(loaded, dict) else {}


def save_cache(path: pathlib.Path, cache: dict) -> None:
    path.write_text(
        "# Author lists as the registries reported them, keyed by identifier, so a second\n"
        "# `citations lint --authors` needs no network and a pre-commit hook can call it.\n"
        "# Written by the tool. An edited row is believed by the next run, which makes this a\n"
        "# convenience and never evidence; delete a row to fetch it again.\n"
        + yaml.safe_dump(cache, sort_keys=True, allow_unicode=True)
    )


def registry_authors(
    kind: str, identifier: str, cache: dict, cache_path: pathlib.Path
) -> tuple[str, list[str]] | None:
    """`(registry, the names in order)` for one identifier, from the cache or from a registry.

    None where every registry that answers for this kind of identifier either had nothing or
    refused. That is not a finding: no measurement was made, and counting it as agreement is
    how a check comes to pass by examining nothing.
    """
    key = f"{kind}:{identifier}"
    hit = cache.get(key)
    if isinstance(hit, dict) and isinstance(hit.get("authors"), list) and hit["authors"]:
        return str(hit.get("source", "cache")), [str(n) for n in hit["authors"]]

    for registry in services.REGISTRIES:
        if kind not in registry.kinds:
            continue
        time.sleep(DELAY)
        try:
            payload = resolve.get(registry.url(kind, identifier), as_json=registry.json)
        except resolve.Throttled:
            continue  # refused, which is not the same as having nothing
        names = registry.authors(payload) if payload is not None else []
        if not names:
            continue
        cache[key] = {
            "source": registry.name,
            "fetched": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "authors": names,
        }
        save_cache(cache_path, cache)  # after each hit: a killed run keeps what it found
        return registry.name, names
    return None


class AuthorFinding(BaseModel):
    """One way an entry's author list disagrees with the registry its identifier names."""

    file: str
    key: str
    line: int = 0
    kind: str
    """`wrong`, `dropped`, `marker`, `order` or `extra`."""
    identifier: str
    registry: str
    detail: str


class AuthorReport(BaseModel):
    """One bibliography's verdict, and what in it was never examined.

    What was skipped and what did not fetch are carried because they change how the findings
    read: a file where nine entries in ten have no identifier has been examined a tenth of the
    way, and a report that prints only what it found does not say so.
    """

    file: str
    cache: str = ""
    entries: int = 0
    checked: int = 0
    skipped: int = 0
    """Entries carrying neither a DOI nor an arXiv id. Nothing can check those."""
    unresolved: int = 0
    """Entries whose identifier no registry answered for."""
    findings: list[AuthorFinding] = Field(default_factory=list)


def check_authors(path: pathlib.Path) -> AuthorReport:
    """Every entry in one bibliography, against the registry its own identifier names."""
    if not path.is_file():
        raise CitationsError(f"no such file: {path}")
    text = bibtex.read(path)
    # Reversed, so a key defined twice reports the line it was defined on first. Which copy is
    # the live one is `--bib`'s question, not this one's.
    lines = dict(reversed(bibtex.key_lines(text)))
    cache_path = path.parent / CACHE_NAME
    cache = load_cache(cache_path)
    report = AuthorReport(file=str(path), cache=str(cache_path))

    for _kind, key, body in bibtex.entries(text):
        report.entries += 1
        fields = {n.lower(): " ".join(v.split()) for n, v in audit.BIB_FIELD.findall(body)}
        id_kind, identifier = identifier_of(fields)
        if not identifier:
            report.skipped += 1
            continue
        answer = registry_authors(id_kind, identifier, cache, cache_path)
        if answer is None:
            report.unresolved += 1
            continue
        report.checked += 1
        registry, theirs = answer
        ours, marked = split_authors(fields.get("author", ""))
        for kind, detail in compare(ours, marked, theirs):
            report.findings.append(
                AuthorFinding(
                    file=str(path),
                    key=key,
                    line=lines.get(key, 0),
                    kind=kind,
                    identifier=f"{id_kind}:{identifier}",
                    registry=registry,
                    detail=detail,
                )
            )
    return report


def author_lists(files: list[pathlib.Path], as_json: bool) -> int:
    """Every author list that disagrees with its own identifier's registry. Exit 1 if any does.

    Exits 1 under `--json` as well, for the reason `bib_defects` gives.
    """
    reports = [check_authors(p) for p in files]
    findings = [f for r in reports for f in r.findings]

    if as_json:
        print(json.dumps([r.model_dump() for r in reports], indent=1))
        return 1 if findings else 0

    for r in reports:
        # What was examined, before what was found in it. A file whose entries mostly carry no
        # identifier reads exactly like a clean one once the findings are the only thing printed.
        print(f"  authors  {r.file}")
        print(f"  cache    {r.cache}")
        for f in r.findings:
            print(f"    {f.key[:36]:<38}{f.kind:<9}{f.identifier}  ({f.registry})")
            print(f"      {f.detail}")

    entries = sum(r.entries for r in reports)
    checked = sum(r.checked for r in reports)
    skipped = sum(r.skipped for r in reports)
    unresolved = sum(r.unresolved for r in reports)
    print(
        f"\n  {entries} entries, {checked} checked, {skipped} with no identifier, "
        f"{unresolved} that did not fetch, {len(findings)} finding(s)"
    )
    if unresolved:
        print("  an identifier that did not fetch was not measured; re-run with a network.")
    if not findings:
        print("  every checked entry lists the authors its own identifier resolves to.")
        return 0

    print("\n  A wrong author list under a correct identifier passes every other check here.")
    print("  The identifier resolves, the link is live, and the quotations pinned to it are")
    print("  genuine, because the identifier does point at the paper; it is the names beside")
    print("  it that belong to someone else, and a reader of the reference list cannot see the")
    print("  registry. Take the names from the registry, in its order and in full. `and others`")
    print("  writes a shortened list that looks like a complete one.")
    return 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="citations lint", description=__doc__.split("\n")[0])
    ap.add_argument("--json", action="store_true")
    ap.add_argument(
        "--bib",
        action="append",
        metavar="FILE",
        help="a bibliography to check for repeated keys and author lists written without "
        "given names, instead of the records; repeatable, and needs no papis, no library "
        "and no network",
    )
    ap.add_argument(
        "--authors",
        action="append",
        metavar="FILE",
        help="a bibliography whose author lists are read back against the registry each entry's "
        "own DOI or arXiv id names; repeatable, and offline once the lists are cached",
    )
    a = ap.parse_args(argv)

    if a.bib and a.authors and a.json:
        # Two documents printed back to back are not a JSON document. Refusing says so; running
        # one mode and dropping the other would report a check that never ran.
        print("  --json prints one document: ask for --bib or --authors, not both")
        return 2

    if a.bib or a.authors:
        code = 0
        if a.bib:
            code |= bib_defects([pathlib.Path(p).expanduser() for p in a.bib], a.json)
        if a.authors:
            code |= author_lists([pathlib.Path(p).expanduser() for p in a.authors], a.json)
        return code

    papis = find_papis()
    if papis is None:
        print("  papis is not on PATH\n  uv tool install papis   (or pip install papis)")
        return 1

    try:
        record_dir = paths.records()
    except CitationsError as e:
        print(str(e))
        return 2

    records = sorted(record_dir.glob("*.yaml"))
    if not records:
        print(f"  no records in {record_dir}")
        return 2

    with tempfile.TemporaryDirectory() as tmp:
        lib = pathlib.Path(tmp) / "lib"
        lib.mkdir()
        for p in records:
            rec = load_record(p)
            d = lib / rec.slug
            d.mkdir(exist_ok=True)
            (d / "info.yaml").write_text(
                yaml.safe_dump(project(rec), sort_keys=False, allow_unicode=True)
            )

        # papis reads its config from the platform location under HOME, not from an env var,
        # so the sandboxed HOME has to contain one. Getting this wrong makes papis fail to
        # find the library and print nothing, which this function would otherwise report as
        # a clean bill of health -- a check that passes by examining nothing.
        cfg = pathlib.Path(tmp) / "Library" / "Application Support" / "papis"
        cfg.mkdir(parents=True, exist_ok=True)
        (cfg / "config").write_text(f"[lint]\ndir = {lib}\n")
        proc = subprocess.run(
            [str(papis), "-l", "lint", "doctor", "--all", "--all-checks"],
            capture_output=True,
            text=True,
            env={"HOME": tmp, "PATH": "/usr/bin:/bin"},
        )
        out = proc.stdout
        if proc.returncode != 0 and not out.strip():
            print("  papis could not run; refusing to report a clean result")
            print(f"  {(proc.stderr or '').strip()[:400]}")
            return 2

    issues = []
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) >= 3:
            issues.append({"check": parts[0], "key": parts[1], "slug": pathlib.Path(parts[2]).name})

    if a.json:
        print(json.dumps(issues, indent=1))
        return 0

    counts = collections.Counter((i["check"], i["key"]) for i in issues)
    print(f"  {len(records)} records, {len(issues)} issues\n")
    for (check, key), n in counts.most_common():
        print(f"  {n:>4}  {check:<26}{key}")
        for i in [x for x in issues if (x["check"], x["key"]) == (check, key)][:4]:
            print(f"          {i['slug']}")
        if n > 4:
            print(f"          ... and {n - 4} more")
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
