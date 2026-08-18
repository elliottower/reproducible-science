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
import sys
import unicodedata

import yaml

from citations.paths import home as _home

ROOT = _home()
RECORDS = ROOT / "records"
ENRICHMENT = ROOT / "enrichment.yaml"   # facts resolved after a .bib was written
GITHUB = pathlib.Path.home() / "Documents" / "GitHub"

# Each paper: where its bibliography lives.
#
# The three mechanistic-* papers read from their -NEW repositories, which exist because those
# were rebuilt clean for submission. The others read from their working repositories directly:
# they are research repos where the experiments, data and pre-registrations are the substance,
# and a stripped-down copy of one would be a different artifact, not a tidier version of it.
PAPERS = {
    "mechanistic-validity": {
        "bib": GITHUB / "mechanistic-validity-NEW2" / "paper" / "references.bib",
        "sources": GITHUB / "mechanistic-validity-NEW2" / "sources",
        "claims": GITHUB / "mechanistic-validity-NEW2" / "claims",
    },
    "mechanistic-reference": {
        "bib": GITHUB / "mechanistic-reference-NEW" / "paper" / "references.bib",
    },
    "epistatic-circuits": {
        "bib": GITHUB / "epistatic-circuits" / "paper" / "references.bib",
    },
    "neural-geometry-reliability": {
        "bib": GITHUB / "neural-geometry-reliability" / "paper" / "references.bib",
    },
    "knockout-epistasis-dynamics": {
        "bib": GITHUB / "knockout-epistasis-dynamics" / "paper" / "refs.bib",
    },
    "msms-subspace-collapse": {
        "bib": GITHUB / "msms-subspace-collapse" / "paper" / "references.bib",
    },
    "mechanistic-views": {
        # v30 replaced the hand-written thebibliography block with a real .bib, so this
        # reads structured fields instead of guessing at positional ones
        "bib": GITHUB / "mechanistic-views-NEW" / "paper" / "references.bib",
    },
    "mechanistic-nosology": {
        "bib": GITHUB / "mechanistic-nosology" / "paper" / "references.bib",
        "claims": GITHUB / "mechanistic-nosology" / "claims",
    },
}

FIELD = re.compile(r"(\w+)\s*=\s*[{\"](.*?)[}\"]\s*,?\s*$", re.S)


# LaTeX accents resolved to the character rather than deleted. Stripping backslashes turns
# Kram\'{a}r into Kram'ar and J\'anos into J'anos, which is how a bibliography ends up
# misspelling people's names.
ACCENT = {"'": "\u0301", "`": "\u0300", '"': "\u0308", "^": "\u0302", "~": "\u0303",
          "=": "\u0304", ".": "\u0307", "u": "\u0306", "v": "\u030c", "H": "\u030b",
          "c": "\u0327", "k": "\u0328", "r": "\u030a"}
LIGATURE = [(r"\\ss\b", "\u00df"), (r"\\o\b", "\u00f8"), (r"\\O\b", "\u00d8"),
            (r"\\ae\b", "\u00e6"), (r"\\AE\b", "\u00c6"), (r"\\aa\b", "\u00e5"),
            (r"\\AA\b", "\u00c5"), (r"\\l\b", "\u0142"), (r"\\L\b", "\u0141"),
            (r"\\i\b", "i"), (r"\\j\b", "j")]


def clean(s: str) -> str:
    s = re.sub(r"\\emph\{([^}]*)\}", r"\1", s or "")
    for pat, ch in LIGATURE:
        s = re.sub(pat, ch, s)
    # \'{a}, \'a and {\'a} all mean the same character
    for mark, comb in ACCENT.items():
        m = re.escape(mark)
        s = re.sub(rf"\\{m}\s*\{{(\w)\}}", lambda g: g.group(1) + comb, s)
        s = re.sub(rf"\\{m}\s*(\w)", lambda g: g.group(1) + comb, s)
    s = unicodedata.normalize("NFC", s)
    s = re.sub(r"[{}]", "", s).replace("\\&", "&").replace("--", "-")
    s = re.sub(r"\\[a-zA-Z]+", "", s).replace("\\", "")
    # No trailing-punctuation strip here: it would take the period off an initial and turn
    # "Fisher, Ronald A." into "Fisher, Ronald A". Trailing junk from a \bibitem author line is
    # that parser's problem, handled where the sentence structure is still visible.
    return " ".join(s.split())


CORPORATE = re.compile(r"\b(Administration|Task Force|Committee|Council|Organization|Organisation|Association|Institute|Society|Collaboration|Consortium|Agency|Commission|Academy|Department|Bureau|Office of)\b", re.I)


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
    base = re.sub(r"[^a-z0-9]+", "", (rec.get("title", "") + (rec.get("authors") or [""])[0]).lower())
    return "t-" + hashlib.sha256(base.encode()).hexdigest()[:16]


def arxiv_of(*texts: str) -> str:
    for t in texts:
        m = re.search(r"arxiv[:\s]*(\d{4}\.\d{4,5})", (t or "").lower())
        if m:
            return m.group(1)
    return ""


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
            "title": f.get("title", ""), "authors": au, "et_al": truncated,
            "year": f.get("year", ""),
            "venue": f.get("booktitle") or f.get("journal") or f.get("howpublished", ""),
            "doi": f.get("doi", ""), "url": f.get("url", ""),
            "arxiv": arxiv_of(f.get("note", ""), f.get("url", ""), f.get("journal", "")),
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
        rest = ch[km.end():]
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
            "title": title.rstrip("."), "authors": au, "et_al": truncated,
            "year": ym.group(0) if ym else "",
            "venue": venue, "doi": "", "url": url.group(1) if url else "",
            "arxiv": arxiv_of(venue, ch),
        }
    return out


def contributions() -> dict[str, dict[str, dict]]:
    got = {}
    for name, cfg in PAPERS.items():
        if cfg.get("bib") and cfg["bib"].exists():
            got[name] = parse_bib(cfg["bib"])
        elif cfg.get("bibitem") and cfg["bibitem"].exists():
            got[name] = parse_bibitem(cfg["bibitem"])
        else:
            got[name] = {}
    return got


def enrich_from_claims(entries: dict[str, dict]) -> None:
    """Pull the pinned artifact out of each audited claim record.

    The sixteen audited papers record their source PDF and its sha256 in claims/, which is
    where the quote gate reads it from. Those are the artifacts actually read, so they are the
    ones worth linking.
    """
    d = PAPERS["mechanistic-validity"].get("claims")
    if not d or not d.exists():
        return
    for p in d.glob("*.yaml"):
        r = yaml.safe_load(p.read_text()) or {}
        s = r.get("source") or {}
        e = entries.get(s.get("citation"))
        if not e:
            continue
        for k in ("local", "sha256", "url"):
            if s.get(k) and not e.get(k):
                e[k] = s[k]


def enrich_from_validity(entries: dict[str, dict]) -> None:
    """Fold in the url/doi/sha256 already resolved in mechanistic-validity's sources/."""
    d = PAPERS["mechanistic-validity"].get("sources")
    if not d or not d.exists():
        return
    for p in d.glob("*.yaml"):
        r = yaml.safe_load(p.read_text()) or {}
        e = entries.get(r.get("citation"))
        if not e:
            continue
        for k in ("url", "doi", "arxiv", "sha256", "local"):
            if r.get(k) and not e.get(k):
                e[k] = r[k]


def carry_forward(merged: dict) -> int:
    """Apply facts resolved after the bibliographies were written.

    Records are generated, so anything learned later -- a year looked up from Crossref, a DOI
    resolved by hand -- has to live somewhere that regenerating does not touch. An earlier
    version read it back out of the records themselves, which works until someone clears the
    directory before rebuilding, at which point sixteen verified years vanish silently. It
    lives in enrichment.yaml instead, keyed by slug.

    The bibliography still wins where it has a value; this only fills gaps.
    """
    if not ENRICHMENT.exists():
        return 0
    overlay = yaml.safe_load(ENRICHMENT.read_text()) or {}
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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--scan", action="store_true")
    a = ap.parse_args()

    got = contributions()
    for name, entries in got.items():
        print(f"  {name:<24}{len(entries):>4} entries")
    enrich_from_validity(got.get("mechanistic-validity", {}))
    enrich_from_claims(got.get("mechanistic-validity", {}))

    merged: dict[str, dict] = {}
    for paper, entries in got.items():
        for key, e in entries.items():
            s = slug_for(e)
            rec = merged.setdefault(s, {
                "slug": s, "title": e["title"], "authors": e["authors"], "year": e["year"],
                "venue": e["venue"], "doi": e.get("doi", ""), "arxiv": e.get("arxiv", ""),
                "et_al": e.get("et_al", False),
                "url": e.get("url", ""), "sha256": e.get("sha256", ""),
                "local": e.get("local", ""), "cited_by": {},
            })
            for k in ("doi", "arxiv", "url", "sha256", "venue", "local"):
                if e.get(k) and not rec.get(k):
                    rec[k] = e[k]
            if len(e["authors"]) > len(rec["authors"]):
                rec["authors"] = e["authors"]
            rec["cited_by"][paper] = {"key": key}

    kept = carry_forward(merged)
    shared = {s: r for s, r in merged.items() if len(r["cited_by"]) > 1}
    divergent = {s: r for s, r in shared.items()
                 if len({c["key"] for c in r["cited_by"].values()}) > 1}
    print(f"\n  distinct works            {len(merged):>4}")
    print(f"  cited by 2+ papers        {len(shared):>4}")
    print(f"  ...under divergent keys   {len(divergent):>4}")
    unidentified = sum(1 for r in merged.values() if r["slug"].startswith("t-"))
    print(f"  with no DOI or arXiv id   {unidentified:>4}   (joined on title, less reliable)")
    print(f"  fields carried forward    {kept:>4}   (resolved after the .bib was written)")

    if divergent:
        print("\n  same work, different key:")
        for r in list(divergent.values())[:12]:
            keys = ", ".join(f"{p}={c['key']}" for p, c in r["cited_by"].items())
            print(f"    {r['title'][:52]:<54}{keys}")

    if not a.scan:
        RECORDS.mkdir(parents=True, exist_ok=True)
        for s, r in merged.items():
            (RECORDS / f"{s}.yaml").write_text(
                yaml.safe_dump(r, sort_keys=False, allow_unicode=True, width=100))
        print(f"\n  wrote {len(merged)} records")
    return 0


if __name__ == "__main__":
    sys.exit(main())
