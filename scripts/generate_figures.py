"""Produce every figure the paper states, as one JSON artifact.

The paper's claims point into this file by JSON Pointer, so `repro verify` checks the
manuscript against the numbers actually measured. A figure that is not produced here does not
appear in the paper.

    uv run python scripts/generate_figures.py
    repro verify paper/repro.yaml
"""
from __future__ import annotations

import collections
import json
import pathlib
import re
import subprocess
import sys

import yaml

from citations import verify as CV
from citations.audit import from_crossref
from citations.exceptions import ClaimFileError
from citations.models import load_claim_file
from citations.text import surname_variants

ROOT = pathlib.Path(__file__).resolve().parent.parent
GH = pathlib.Path.home() / "Documents/GitHub"
LIB = GH / "citations-library"


def quotation_corpus() -> dict:
    projects, quotes, unparsed = set(), 0, 0
    pins: collections.Counter = collections.Counter()
    warnings: collections.Counter = collections.Counter()
    files = sorted(GH.glob("*/claims/*.yaml"))
    for f in files:
        try:
            cf = load_claim_file(f)
        except ClaimFileError:
            unparsed += 1
            continue
        projects.add(f.parent.parent.name)
        quotes += sum(len(c.quotes) for c in cf.claims.values())
        pins[CV.check_pin(cf.artifact(), cf.source.sha256).state] += 1
    return {"assertions": quotes, "manuscripts": len(projects),
            "declaration_files": len(files), "unparseable_files": unparsed,
            "pins": dict(pins), "warnings": dict(warnings)}


def resolver_identifiers() -> dict:
    enrich = yaml.safe_load((LIB / "enrichment.yaml").read_text()) or {}
    slug = lambda doi: "doi-" + re.sub(r"[^a-z0-9]+", "-", doi.lower()).strip("-")
    written = [(k, v["doi"]) for k, v in enrich.items()
               if k.startswith("t-") and isinstance(v, dict) and v.get("doi")]
    counts = collections.Counter()
    for _key, doi in written:
        f = LIB / "records" / f"{slug(doi)}.yaml"
        if not f.exists():
            counts["no_record"] += 1
            continue
        rec = yaml.safe_load(f.read_text()) or {}
        authors = rec.get("authors") or []
        if not authors:
            counts["no_authors"] += 1
            continue
        reg = from_crossref(doi, LIB / ".audit-cache")
        if reg is None:
            counts["unresolved"] += 1
            continue
        want = surname_variants(authors[0])
        fams = {" ".join(fam) for fam, _ in reg.authors}
        hit = any(w == fam or w in fam.split() for fam in fams for w in want)
        counts["first_author_present" if hit or not want else "first_author_absent"] += 1
    checkable = counts["first_author_present"] + counts["first_author_absent"]
    return {"written": len(written), **dict(counts), "checkable": checkable,
            "absent_rate": round(100 * counts["first_author_absent"] / checkable, 1)
            if checkable else None}


def conformance() -> dict:
    cases = sorted((ROOT / "tests/conformance/cases").iterdir())
    proc = subprocess.run([sys.executable, "-m", "pytest", "tests/", "-q", "--no-header"],
                          cwd=ROOT, capture_output=True, text=True)
    m = re.search(r"(\d+) passed", proc.stdout)
    return {"fixtures": len(cases), "tests_passing": int(m.group(1)) if m else None}


figures = {"quotation_corpus": quotation_corpus(),
           "resolver_identifiers": resolver_identifiers(),
           "conformance": conformance()}

out = ROOT / "paper" / "figures.json"
out.write_text(json.dumps(figures, indent=2, sort_keys=True) + "\n")
print(f"  wrote {out}")
print(json.dumps(figures, indent=2, sort_keys=True))
