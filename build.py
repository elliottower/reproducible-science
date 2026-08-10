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

import yaml

ROOT = pathlib.Path(__file__).resolve().parent
RECORDS = ROOT / "records"
GITHUB = ROOT.parent

# Each paper: where its bibliography lives and which tex cites into it.
PAPERS = {
    "mechanistic-validity": {
        "bib": GITHUB / "mechanistic-validity-NEW2" / "paper" / "references.bib",
        "sources": GITHUB / "mechanistic-validity-NEW2" / "sources",
        "claims": GITHUB / "mechanistic-validity-NEW2" / "claims",
    },
    "mechanistic-reference": {
        "bib": GITHUB / "mechanistic-reference" / "paper" / "references.bib",
    },
    "mechanistic-views": {
        "bibitem": GITHUB / "mechanistic-views-NEW" / "paper" / "mechviews_bib.tex",
    },
}

FIELD = re.compile(r"(\w+)\s*=\s*[{\"](.*?)[}\"]\s*,?\s*$", re.S)


def clean(s: str) -> str:
    s = re.sub(r"\\emph\{([^}]*)\}", r"\1", s or "")
    s = re.sub(r"[{}]", "", s).replace("\\&", "&").replace("--", "-").replace("\\", "")
    return " ".join(s.split())


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
        au = [a.strip() for a in re.split(r"\s+and\s+", f.get("author", "")) if a.strip()]
        out[key] = {
            "title": f.get("title", ""), "authors": au, "year": f.get("year", ""),
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
        au = [a.strip() for a in re.split(r",| and ", authors_raw) if a.strip()]
        url = re.search(r"\\url\{([^}]*)\}", ch)
        out[key] = {
            "title": title.rstrip("."), "authors": au, "year": ym.group(0) if ym else "",
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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--scan", action="store_true")
    a = ap.parse_args()

    got = contributions()
    for name, entries in got.items():
        print(f"  {name:<24}{len(entries):>4} entries")
    enrich_from_validity(got.get("mechanistic-validity", {}))

    merged: dict[str, dict] = {}
    for paper, entries in got.items():
        for key, e in entries.items():
            s = slug_for(e)
            rec = merged.setdefault(s, {
                "slug": s, "title": e["title"], "authors": e["authors"], "year": e["year"],
                "venue": e["venue"], "doi": e.get("doi", ""), "arxiv": e.get("arxiv", ""),
                "url": e.get("url", ""), "sha256": e.get("sha256", ""), "cited_by": {},
            })
            for k in ("doi", "arxiv", "url", "sha256", "venue"):
                if e.get(k) and not rec.get(k):
                    rec[k] = e[k]
            if len(e["authors"]) > len(rec["authors"]):
                rec["authors"] = e["authors"]
            rec["cited_by"][paper] = {"key": key}

    shared = {s: r for s, r in merged.items() if len(r["cited_by"]) > 1}
    divergent = {s: r for s, r in shared.items()
                 if len({c["key"] for c in r["cited_by"].values()}) > 1}
    print(f"\n  distinct works            {len(merged):>4}")
    print(f"  cited by 2+ papers        {len(shared):>4}")
    print(f"  ...under divergent keys   {len(divergent):>4}")
    unidentified = sum(1 for r in merged.values() if r["slug"].startswith("t-"))
    print(f"  with no DOI or arXiv id   {unidentified:>4}   (joined on title, less reliable)")

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
