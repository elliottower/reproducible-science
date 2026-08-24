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
from citations.audit import from_crossref, from_datacite, is_datacite
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
        cache = LIB / ".audit-cache"
        # Ask the registry the DOI is registered with, so an arXiv or Zenodo identifier is
        # not counted as unresolved because Crossref does not carry it.
        reg = (from_datacite(doi, cache) if is_datacite(doi)
               else from_crossref(doi, cache) or from_datacite(doi, cache))
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


def metric_corpus() -> dict:
    """Run each corpus manifest against the repository it audits.

    The figures the paper states about the metric corpus come from the same engine and the
    same manifests the corpus tests use, so a number in the paper and a number in a test
    cannot disagree.
    """
    from repro.corpus import Corpus, ensure
    from repro.regression import _manifest_against

    here = ROOT / "tests" / "corpus"
    cp = here / "corpus.yaml"
    rp = here / "regressions.yaml"
    out: dict[str, dict] = {}

    if cp.is_file():
        corpus = Corpus.model_validate({**(yaml.safe_load(cp.read_text()) or {}), "path": cp})
        for entry in corpus.entries:
            if not entry.manifest:
                continue
            root = ensure(entry, here)
            if root is None:
                out[entry.name] = {"available": False}
                continue
            report = _manifest_against(here / entry.manifest, root)
            out[entry.name] = {"available": True, "commit": entry.commit[:12],
                               **report.counts,
                               "assertions": len(report.decisions)}

    for finding in (yaml.safe_load(rp.read_text()) or {}).get("findings", []) if rp.is_file() else []:
        from repro.corpus import CorpusEntry
        before = finding.get("before") or {}
        entry = CorpusEntry(name=finding["name"], repository=finding.get("repository", ""),
                            commit=before.get("commit", ""),
                            local_path=finding.get("local_path", ""))
        root = ensure(entry, here)
        manifest = here / before.get("manifest", "")
        if root is None or not manifest.is_file():
            out[finding["name"]] = {"available": False}
            continue
        report = _manifest_against(manifest, root)
        out[finding["name"]] = {"available": True, "commit": entry.commit[:12],
                                **report.counts, "assertions": len(report.decisions)}
    return out


def self_audit() -> dict:
    """How many assertions the paper makes about itself.

    The verdict is deliberately not recorded here. Writing this file changes it, which breaks
    the pin the self-audit checks, so a figure stating that the self-audit passes is false at
    the moment it is written and true only after the manifest is rebuilt. The count is stable
    under that cycle; the verdict is not, and belongs to `repro verify` rather than to an
    artifact it inspects.

        uv run python scripts/generate_figures.py
        uv run python scripts/build_self_audit.py
        repro verify paper/repro.yaml --policy strict
    """
    from repro import load, verify

    m = ROOT / "paper" / "repro.yaml"
    if not m.is_file():
        return {"available": False}
    report = verify(load(m))
    return {"available": True, "assertions": len(report.decisions)}


figures = {"quotation_corpus": quotation_corpus(),
           "metric_corpus": metric_corpus(),
           "self_audit": self_audit(),
           "resolver_identifiers": resolver_identifiers(),
           "conformance": conformance()}

out = ROOT / "paper" / "figures.json"
out.write_text(json.dumps(figures, indent=2, sort_keys=True) + "\n")
print(f"  wrote {out}")
print(json.dumps(figures, indent=2, sort_keys=True))
