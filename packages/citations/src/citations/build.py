"""Build the shared citation database from every paper that cites into it.

One record per work, organized by the source rather than by the paper. Each record carries the
bibliographic facts once -- who wrote it, where it appeared, the DOI or arXiv id needed to
fetch it, the sha256 of the copy that was read -- and then, under `cited_by`, what each of my
papers does with it: the citation key that paper uses, and any passages it quotes.

Reading it source-first is the point. "Craver 2007: mechanistic-validity cites it as
craver2007explaining and quotes three passages under nomological validity; mechanistic-views
cites the same book as craver2007 and quotes a different passage." That is invisible when each
paper keeps its own bibliography, and it is where the duplicated reading, the divergent keys
and the contradictory year fields all show up.

Works are joined on DOI or arXiv id, never on citation key. Ten works are already cited under
two different keys across two of these repos, so the key cannot identify anything.

    python build.py --scan       # report what each paper contributes, write nothing
    python build.py              # write records/
"""

from __future__ import annotations

import argparse
import hashlib
import pathlib
import re
import unicodedata

import yaml

from citations import config, paths
from citations.exceptions import ClaimFileError
from citations.models import load_claim_file

FIELD = re.compile(r"(\w+)\s*=\s*[{\"](.*?)[}\"]\s*,?\s*$", re.S)


# LaTeX accents resolved to the character rather than deleted. Stripping backslashes turns
# Kram\'{a}r into Kram'ar and J\'anos into J'anos, which is how a bibliography ends up
# misspelling people's names.
ACCENT = {
    "'": "\u0301",
    "`": "\u0300",
    '"': "\u0308",
    "^": "\u0302",
    "~": "\u0303",
    "=": "\u0304",
    ".": "\u0307",
    "u": "\u0306",
    "v": "\u030c",
    "H": "\u030b",
    "c": "\u0327",
    "k": "\u0328",
    "r": "\u030a",
}
LIGATURE = [
    (r"\\ss\b", "\u00df"),
    (r"\\o\b", "\u00f8"),
    (r"\\O\b", "\u00d8"),
    (r"\\ae\b", "\u00e6"),
    (r"\\AE\b", "\u00c6"),
    (r"\\aa\b", "\u00e5"),
    (r"\\AA\b", "\u00c5"),
    (r"\\l\b", "\u0142"),
    (r"\\L\b", "\u0141"),
    (r"\\i\b", "i"),
    (r"\\j\b", "j"),
]


def clean(s: str) -> str:
    s = re.sub(r"\\emph\{([^}]*)\}", r"\1", s or "")
    for pat, ch in LIGATURE:
        s = re.sub(pat, ch, s)
    # \'{a}, \'a and {\'a} all mean the same character
    for mark, comb in ACCENT.items():
        m = re.escape(mark)
        s = re.sub(rf"\\{m}\s*\{{(\w)\}}", lambda g, comb=comb: g.group(1) + comb, s)
        s = re.sub(rf"\\{m}\s*(\w)", lambda g, comb=comb: g.group(1) + comb, s)
    s = unicodedata.normalize("NFC", s)
    s = re.sub(r"[{}]", "", s).replace("\\&", "&").replace("--", "-")
    s = re.sub(r"\\[a-zA-Z]+", "", s).replace("\\", "")
    # No trailing-punctuation strip here: it would take the period off an initial and turn
    # "Fisher, Ronald A." into "Fisher, Ronald A". Trailing junk from a \bibitem author line is
    # that parser's problem, handled where the sentence structure is still visible.
    return " ".join(s.split())


CORPORATE = re.compile(
    r"\b(Administration|Task Force|Committee|Council|Organization|Organisation|Association|Institute|Society|Collaboration|Consortium|Agency|Commission|Academy|Department|Bureau|Office of)\b",
    re.I,
)


def split_authors(raw: str) -> tuple[list[str], bool]:
    """Author list, plus whether BibTeX's `and others` truncated it.

    "and others" is BibTeX for et al. Read literally it produces a person named "others",
    which 23 records had. It is a property of the list, not a member of it.
    """
    raw = (raw or "").strip()
    # A corporate author is a single name that may contain "and" -- splitting
    # "U.S. Food and Drug Administration" on it invents two organizations.
    if CORPORATE.search(raw) and "," not in raw.split(" and ")[0]:
        return [raw], False
    parts = [a.strip() for a in re.split(r"\s+and\s+", raw) if a.strip()]
    truncated = any(a.lower().rstrip(".") == "others" for a in parts)
    parts = [a for a in parts if a.lower().rstrip(".") != "others"]
    return [normalize_initials(a) for a in parts], truncated


def normalize_initials(name: str) -> str:
    """Give a bare trailing initial its period: "Glennan, Stuart S" -> "Glennan, Stuart S."

    The missing period is in the source bibliographies, not introduced here. A single capital
    at the end of a name is an initial in every style that matters.
    """
    # every bare initial, not just the final one: "Ioannidis, John P A" has two
    return re.sub(r"(?<![A-Za-z.])([A-Z])(?=\s|$)", r"\1.", name.strip())


def slug_for(rec: dict) -> str:
    """Stable identity: DOI, else arXiv id, else a hash of normalized title+first author."""
    if rec.get("doi"):
        return "doi-" + re.sub(r"[^a-z0-9]+", "-", rec["doi"].lower()).strip("-")
    if rec.get("arxiv"):
        return "arxiv-" + rec["arxiv"].replace(".", "-")
    base = re.sub(
        r"[^a-z0-9]+", "", (rec.get("title", "") + (rec.get("authors") or [""])[0]).lower()
    )
    return "t-" + hashlib.sha256(base.encode()).hexdigest()[:16]


# 0704.0001 is the modern form; cs/0501001 and math.GT/0309136 are the pre-2007 one.
ARXIV_ID = r"(\d{4}\.\d{4,5}|[a-z-]+(?:\.[a-z]{2})?/\d{7})"
ARXIV_PATTERNS = (
    rf"arxiv\.org/(?:abs|pdf)/{ARXIV_ID}",  # https://arxiv.org/abs/2211.00593
    rf"arxiv[:\s]+{ARXIV_ID}",  # arXiv:2211.00593, "arXiv preprint arXiv:..."
)


def arxiv_of(*texts: str) -> str:
    """The id out of any field that might carry it, as a url or as an arXiv: prefix."""
    for t in texts:
        low = (t or "").lower()
        for pat in ARXIV_PATTERNS:
            m = re.search(pat, low)
            if m:
                return m.group(1)
    return ""


def arxiv_from_fields(f: dict) -> str:
    """`eprint` is BibTeX's own field for this and holds a bare id, with no "arXiv:" to match on.

    Reading only note/url/journal missed every entry written the standard way, which split one
    work across two records whenever some bibliographies used eprint and others used a url.
    """
    ep = (f.get("eprint") or "").strip()
    if re.fullmatch(ARXIV_ID, ep, re.I):
        return ep.lower()
    return arxiv_of(
        ep, f.get("note", ""), f.get("url", ""), f.get("journal", ""), f.get("howpublished", "")
    )


def parse_bib(path: pathlib.Path) -> dict[str, dict]:
    out = {}
    for m in re.finditer(r"@(\w+)\s*\{([^,]+),(.*?)\n\}", path.read_text(errors="ignore"), re.S):
        key, body = m.group(2).strip(), m.group(3)
        f = {}
        for line in re.split(r",\s*\n", body):
            fm = FIELD.search(line.strip())
            if fm:
                f[fm.group(1).lower()] = clean(fm.group(2))
        au, truncated = split_authors(f.get("author", ""))
        out[key] = {
            "title": f.get("title", ""),
            "authors": au,
            "et_al": truncated,
            "year": f.get("year", ""),
            "venue": f.get("booktitle") or f.get("journal") or f.get("howpublished", ""),
            "doi": f.get("doi", ""),
            "url": f.get("url", ""),
            "arxiv": arxiv_from_fields(f),
        }
    return out


def parse_bibitem(path: pathlib.Path) -> dict[str, dict]:
    """A hand-written thebibliography block. Fields are positional, so this is best-effort."""
    txt = path.read_text(errors="ignore")
    out = {}
    chunks = re.split(r"\\bibitem", txt)[1:]
    for ch in chunks:
        km = re.search(r"\{([^}]+)\}", ch)
        if not km:
            continue
        key = km.group(1).strip()
        rest = ch[km.end() :]
        blocks = [clean(b) for b in re.split(r"\\newblock", rest)]
        authors_raw = blocks[0] if blocks else ""
        title = blocks[1] if len(blocks) > 1 else ""
        venue = blocks[2] if len(blocks) > 2 else ""
        ym = re.search(r"\b(19|20)\d{2}\b", venue) or re.search(r"\((\d{4})\)", ch)
        # a \bibitem author line ends the sentence, so the last name carries a period
        # that is punctuation rather than an initial
        # a \bibitem author line ends the sentence, so a final period there is
        # punctuation rather than an initial
        raw = [a.strip() for a in re.split(r",| and ", authors_raw) if a.strip()]
        au = []
        for i, a in enumerate(raw):
            if i and a.endswith(".") and not re.search(r"\b[A-Z]\.$", a):
                a = a.rstrip(".")
            au.append(normalize_initials(a))
        truncated = any(x.lower().rstrip(".") == "others" for x in au)
        au = [x for x in au if x.lower().rstrip(".") != "others"]
        url = re.search(r"\\url\{([^}]*)\}", ch)
        out[key] = {
            "title": title.rstrip("."),
            "authors": au,
            "et_al": truncated,
            "year": ym.group(0) if ym else "",
            "venue": venue,
            "doi": "",
            "url": url.group(1) if url else "",
            "arxiv": arxiv_of(venue, ch),
        }
    return out


def contributions(
    cfg: config.LibraryConfig, library: pathlib.Path
) -> tuple[dict[str, dict[str, dict]], list[str]]:
    """What each paper contributes, and which configured paths were not there.

    A missing bibliography is returned rather than skipped. A paper contributing zero entries
    because its path is wrong looks exactly like a paper that cites nothing, and the second is
    a fact while the first is a broken config.
    """
    got: dict[str, dict[str, dict]] = {}
    missing: list[str] = []
    for name, paper in cfg.papers.items():
        bib = paper.resolved("bib", library)
        bibitem = paper.resolved("bibitem", library)
        if bib and bib.exists():
            got[name] = parse_bib(bib)
        elif bibitem and bibitem.exists():
            got[name] = parse_bibitem(bibitem)
        else:
            got[name] = {}
            named = bib or bibitem
            missing.append(f"{name}: {named}" if named else f"{name}: no bib or bibitem configured")
    return got, missing


def enrich_from_claims(entries: dict[str, dict], claims_dir: pathlib.Path) -> int:
    """Pull the pinned artifact out of each claim record in one paper's claims/.

    A claims file records the source PDF and its sha256, which is where the quote gate reads
    them from. Those are the artifacts actually read, so they are the ones worth linking.

    Applies to every paper that configures a `claims` directory. It read one hardcoded paper
    before, so pinned artifacts recorded by the others were never folded in.
    """
    filled = 0
    for p in sorted(claims_dir.glob("*.yaml")):
        try:
            cf = load_claim_file(p)
        except ClaimFileError:
            continue  # reported by `verify`; not this command's business
        e = entries.get(cf.source.citation) if cf.source.citation else None
        if not e:
            continue
        for field in ("local", "sha256", "url"):
            value = getattr(cf.source, field, None)
            if value and not e.get(field):
                e[field] = value
                filled += 1
    return filled


def enrich_from_sources(entries: dict[str, dict], sources_dir: pathlib.Path) -> int:
    """Fold in url/doi/arxiv/sha256 already resolved in a paper's own sources/."""
    filled = 0
    for p in sorted(sources_dir.glob("*.yaml")):
        try:
            r = yaml.safe_load(p.read_text()) or {}
        except yaml.YAMLError:
            continue
        citation = r.get("citation")
        e = entries.get(citation) if isinstance(citation, str) else None
        if not e:
            continue
        for k in ("url", "doi", "arxiv", "sha256", "local"):
            if r.get(k) and not e.get(k):
                e[k] = r[k]
                filled += 1
    return filled


def carry_forward(merged: dict) -> int:
    """Apply facts resolved after the bibliographies were written.

    Records are generated, so anything learned later -- a year looked up from Crossref, a DOI
    resolved by hand -- has to live somewhere that regenerating does not touch. An earlier
    version read it back out of the records themselves, which works until someone clears the
    directory before rebuilding, at which point sixteen verified years vanish silently. It
    lives in enrichment.yaml instead, keyed by slug.

    The bibliography still wins where it has a value; this only fills gaps.

    Identifiers are handled earlier, in main(), because a DOI that arrives here cannot change
    the slug the record was already filed under -- it would fill the field and leave the work
    split across two records. Everything else lands here.
    """
    enrichment = paths.enrichment()
    if not enrichment.exists():
        return 0
    overlay = yaml.safe_load(enrichment.read_text()) or {}
    kept = 0
    for slug, extra in overlay.items():
        rec = merged.get(slug)
        if not rec:
            continue
        for k, v in (extra or {}).items():
            if v and not rec.get(k):
                rec[k] = v
                kept += 1
    return kept


def audit_existing(merged: dict) -> tuple[list[tuple[str, str, str]], list[str]]:
    """What a write would destroy, and what it would leave behind.

    A record is derived from the bibliographies, so anything written into one by hand is gone at
    the next build. Saying so is the difference between a fact resolved once and a fact resolved
    every time someone rebuilds.
    """
    losing: list[tuple[str, str, str]] = []
    stale: list[str] = []
    records = paths.records()
    if not records.exists():
        return losing, stale
    for p in sorted(records.glob("*.yaml")):
        slug = p.stem
        rec = merged.get(slug)
        if rec is None:
            stale.append(slug)
            continue
        try:
            old = yaml.safe_load(p.read_text()) or {}
        except (yaml.YAMLError, OSError):
            continue
        for field in ("doi", "arxiv"):
            if old.get(field) and not rec.get(field):
                losing.append((slug, field, str(old[field])))
    return losing, stale


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="citations build", description=__doc__.split("\n")[0])
    ap.add_argument("--scan", action="store_true", help="report, write nothing")
    a = ap.parse_args(argv)

    library = paths.home()
    cfg = config.load(library)
    if not cfg.papers:
        print(f"no papers configured in {config.config_path(library)}\n")
        print("list the bibliographies that cite into this library:\n")
        print("    papers:\n      my-paper:\n        bib: ~/path/to/references.bib")
        return 2

    got, missing = contributions(cfg, library)
    for name, entries in sorted(got.items()):
        print(f"  {name:<28}{len(entries):>4} entries")
    if missing:
        # A paper contributing nothing because its path is wrong reads exactly like a paper
        # that cites nothing, so the difference is stated rather than left to be inferred.
        print("\n  configured but not on disk:")
        for m in missing:
            print(f"    {m}")

    filled = 0
    for name, paper in cfg.papers.items():
        entries = got.get(name) or {}
        sources = paper.resolved("sources", library)
        if sources and sources.is_dir():
            filled += enrich_from_sources(entries, sources)
        claims = paper.resolved("claims", library)
        if claims and claims.is_dir():
            filled += enrich_from_claims(entries, claims)

    enrichment = paths.enrichment()
    overlay = (yaml.safe_load(enrichment.read_text()) or {}) if enrichment.exists() else {}

    merged: dict[str, dict] = {}
    for paper, entries in got.items():
        for key, e in entries.items():
            s = slug_for(e)
            # An identifier resolved after the .bib was written has to be able to identify the
            # work, not just decorate it. Applying the overlay only after the slug is fixed
            # leaves the record under its title hash and still split from its twin, so look it
            # up under the provisional slug and re-slug when it supplies a DOI or an arXiv id.
            extra = overlay.get(s) or {}
            if extra.get("doi") or extra.get("arxiv"):
                for k in ("doi", "arxiv"):
                    if extra.get(k) and not e.get(k):
                        e[k] = extra[k]
                s = slug_for(e)
            rec = merged.setdefault(
                s,
                {
                    "slug": s,
                    "title": e["title"],
                    "authors": e["authors"],
                    "year": e["year"],
                    "venue": e["venue"],
                    "doi": e.get("doi", ""),
                    "arxiv": e.get("arxiv", ""),
                    "et_al": e.get("et_al", False),
                    "url": e.get("url", ""),
                    "sha256": e.get("sha256", ""),
                    "local": e.get("local", ""),
                    "cited_by": {},
                },
            )
            for k in ("doi", "arxiv", "url", "sha256", "venue", "local"):
                if e.get(k) and not rec.get(k):
                    rec[k] = e[k]
            if len(e["authors"]) > len(rec["authors"]):
                rec["authors"] = e["authors"]
            rec["cited_by"][paper] = {"key": key}

    kept = carry_forward(merged)
    shared = {s: r for s, r in merged.items() if len(r["cited_by"]) > 1}
    divergent = {
        s: r for s, r in shared.items() if len({c["key"] for c in r["cited_by"].values()}) > 1
    }
    print(f"\n  distinct works            {len(merged):>4}")
    print(f"  cited by 2+ papers        {len(shared):>4}")
    print(f"  ...under divergent keys   {len(divergent):>4}")
    unidentified = sum(1 for r in merged.values() if r["slug"].startswith("t-"))
    print(f"  with no DOI or arXiv id   {unidentified:>4}   (joined on title, less reliable)")
    print(f"  fields carried forward    {kept:>4}   (resolved after the .bib was written)")
    print(f"  filled from claims/sources{filled:>4}   (pinned artifacts and identifiers)")

    if divergent:
        print("\n  same work, different key:")
        for r in list(divergent.values())[:12]:
            keys = ", ".join(f"{p}={c['key']}" for p, c in r["cited_by"].items())
            print(f"    {r['title'][:52]:<54}{keys}")

    losing, stale = audit_existing(merged)
    if losing:
        print("\n  identifiers on disk that this rebuild does not have:")
        for slug, field, val in losing[:12]:
            print(f"    {slug:<44}{field}={val}")
        print(f"  {len(losing)} in total. Records are generated, so these are dropped on write.")
        print(f"  Put them in the citing .bib, or in {enrichment.name} keyed by slug to fill the")
        print(
            "  field -- note that enrichment cannot re-slug a record, only a .bib identifier can."
        )
    if stale:
        print(
            f"\n  {len(stale)} record file(s) no longer produced by any bibliography (superseded);"
        )
        print("  they remain on disk and are not deleted.")

    if not a.scan:
        records = paths.records()
        records.mkdir(parents=True, exist_ok=True)
        for s, r in merged.items():
            (records / f"{s}.yaml").write_text(
                yaml.safe_dump(r, sort_keys=False, allow_unicode=True, width=100)
            )
        print(f"\n  wrote {len(merged)} records")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
