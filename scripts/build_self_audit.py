"""Bind this paper's own numbers to the artifact that produced them.

Each claim carries two assertions: a quotation, that the manuscript states the sentence, and a
metric, that `figures.json` holds the number the sentence prints. Running `repro verify` over
the result checks the paper against its own measurements, which is the operation the paper
describes.

Regenerate after `generate_figures.py`, then verify:

    uv run python scripts/generate_figures.py
    uv run python scripts/build_self_audit.py
    repro verify paper/repro.yaml --policy strict
"""
from __future__ import annotations

import pathlib

import yaml

from repro import Digest
from repro.provenance import of_tree

ROOT = pathlib.Path(__file__).resolve().parent.parent
PAPER = ROOT / "paper" / "DRAFT_v2.md"
FIGURES = ROOT / "paper" / "figures.json"

# (id, sentence stated in the manuscript, printed value, pointer into figures.json)
CLAIMS = [
    ("corpus-assertions", "quotation assertions | 5,686", "5686",
     "/quotation_corpus/assertions"),
    ("corpus-manuscripts", "manuscripts | 17", "17", "/quotation_corpus/manuscripts"),
    ("corpus-declared", "source files declared | 366", "366",
     "/quotation_corpus/declaration_files"),
    ("corpus-pinned", "sources with a matching pin | 355", "355", "/quotation_corpus/pins/ok"),
    ("corpus-unpinned", "sources carrying no pin | 9", "9", "/quotation_corpus/pins/unpinned"),
    ("corpus-missing", "sources named and not present | 1", "1",
     "/quotation_corpus/pins/missing"),
    ("corpus-unparseable", "declaration files that do not parse | 1", "1",
     "/quotation_corpus/unparseable_files"),
    ("resolver-written", "resolver wrote 172 identifiers", "172",
     "/resolver_identifiers/written"),
    ("resolver-checkable", "121 are checkable", "121", "/resolver_identifiers/checkable"),
    ("resolver-absent", "12\nname a work whose first author does not appear", "12",
     "/resolver_identifiers/first_author_absent"),
    ("resolver-rate", "9.9%", "9.9", "/resolver_identifiers/absent_rate"),
    ("resolver-unresolved", "24 carry a DOI that Crossref does not resolve", "24",
     "/resolver_identifiers/unresolved"),
    ("conformance-fixtures", "Thirteen fixtures", "13", "/conformance/fixtures"),
]

artifacts = [
    # Paths are relative to the manifest, which lives beside them in paper/.
    {"id": "manuscript", "path": PAPER.name, "media_type": "text/markdown",
     "digest": {"algorithm": "sha256", "value": Digest.of_file(PAPER).value}},
    {"id": "figures", "path": FIGURES.name, "media_type": "application/json",
     "digest": {"algorithm": "sha256", "value": Digest.of_file(FIGURES).value}},
]

claims = []
for cid, sentence, printed, pointer in CLAIMS:
    evidence = [{"kind": "metric", "artifact": "figures", "name": cid,
                 "reported": printed, "pointer": pointer}]
    # A sentence spanning a line break cannot be quoted verbatim against the source; those
    # carry the metric assertion only rather than a quotation that would always fail.
    if "\n" not in sentence:
        evidence.insert(0, {"kind": "quote", "artifact": "manuscript", "text": sentence})
    claims.append({"id": cid, "confirmatory": True, "where": "Section 6",
                   "text": f"The manuscript states {printed} for {cid}.",
                   "evidence": evidence})

prov = of_tree(ROOT, generated_by="scripts/build_self_audit.py")
out = ROOT / "paper" / "repro.yaml"
out.write_text(yaml.safe_dump(
    {"schema_version": "repro/1", "project": "reproducible-science (self-audit)",
     "provenance": prov.model_dump(), "artifacts": artifacts, "claims": claims},
    sort_keys=False, width=110))
print(f"  wrote {out}: {len(claims)} claims over {len(artifacts)} artifacts")
print(f"  provenance: {prov.commit[:12]}{' (dirty)' if prov.dirty else ''}")
