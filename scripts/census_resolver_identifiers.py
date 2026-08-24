"""Exact denominators for every number the paper states about the resolver study."""

import pathlib
import re
import sys

import yaml

sys.path.insert(0, str(pathlib.Path.home() / "Documents/GitHub/citations/src"))
from citations.audit import from_crossref
from citations.text import surname_variants

lib = pathlib.Path.home() / "Documents/GitHub/citations-library"
cache, records = lib / ".audit-cache", lib / "records"
enrich = yaml.safe_load((lib / "enrichment.yaml").read_text()) or {}

slug = lambda doi: "doi-" + re.sub(r"[^a-z0-9]+", "-", doi.lower()).strip("-")
written = [
    (k, v["doi"])
    for k, v in enrich.items()
    if k.startswith("t-") and isinstance(v, dict) and v.get("doi")
]

no_record = no_authors = unresolved = agreed = 0
mismatched = []
for key, doi in written:
    f = records / f"{slug(doi)}.yaml"
    if not f.exists():
        no_record += 1
        continue
    rec = yaml.safe_load(f.read_text()) or {}
    authors = rec.get("authors") or []
    if not authors:
        no_authors += 1
        continue
    reg = from_crossref(doi, cache)
    if reg is None:
        unresolved += 1
        continue
    want = surname_variants(authors[0])
    fams = {" ".join(f) for f, _ in reg.authors}
    if want and not any(w == fam or w in fam.split() for fam in fams for w in want):
        mismatched.append(doi)
    else:
        agreed += 1

checkable = agreed + len(mismatched)
print(f"  resolver-written identifiers with a DOI : {len(written)}")
print(f"    no record file on disk                : {no_record}")
print(f"    record carries no author list         : {no_authors}")
print(f"    DOI did not resolve in Crossref       : {unresolved}")
print(f"    CHECKABLE (record + authors + resolve): {checkable}")
print(f"      first author present                : {agreed}")
print(f"      FIRST AUTHOR ABSENT                 : {len(mismatched)}")
print(
    f"\n  rate over checkable : {len(mismatched)}/{checkable} = {100 * len(mismatched) / checkable:.1f}%"
)
print(
    f"  rate over all written: {len(mismatched)}/{len(written)} = {100 * len(mismatched) / len(written):.1f}%"
)
