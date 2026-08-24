"""A metric manifest for the RNA manuscript's Table 5.

The reported values are the ones printed in the manuscript, carried as strings so the
comparison happens at the precision the table prints. The pointers address the value the
pipeline stored. Nothing here decides whether a disagreement is the table's fault or the
pipeline's; it reports that they differ.
"""
import json
import pathlib

from repro import Digest

R = pathlib.Path.home() / "Documents/GitHub/rna-sa-public"
D = R / "data/gpu_results/phase6_compensatory"

# Exactly as printed in Table 5, as strings.
REPORTED = {
    "rinalmo": "0.2150", "ernierna": "0.1204", "ernierna_untrained": "9.5e-8",
    "caduceus": "0.0034", "evo": "0.0011", "hyenadna": "0.0003",
    "splicebert": "0.0002", "rnafm": "0.0001", "utrlm": "0.00001",
    "nt": "0.001", "dnabert2": "-0.016",
}

by_model = {}
for f in sorted(D.glob("*.json")):
    d = json.loads(f.read_text())
    if (m := d.get("model")) and "mean_best_ps" in (d.get("results") or {}):
        by_model[m] = f

artifacts, claims, missing = [], [], []
for model, reported in REPORTED.items():
    f = by_model.get(model)
    if f is None:
        missing.append(model)
        continue
    aid = f"phase6-{model}"
    artifacts.append({
        "id": aid, "path": str(f.relative_to(R)), "media_type": "application/json",
        "digest": {"algorithm": "sha256", "value": Digest.of_file(f).value}})
    claims.append({
        "id": f"table5-{model}", "confirmatory": True,
        "text": f"Table 5 reports mean perturbation specificity {reported} for {model}.",
        "where": "Table 5",
        "evidence": [{"kind": "metric", "artifact": aid, "name": f"{model} mean PS",
                      "reported": reported, "pointer": "/results/mean_best_ps"}]})

import yaml

(R / "repro.yaml").write_text(yaml.safe_dump(
    {"schema_version": "repro/1", "project": "rna-structure-awareness",
     "artifacts": artifacts, "claims": claims}, sort_keys=False, width=110))
print(f"  wrote {R/'repro.yaml'}: {len(claims)} metric assertions over {len(artifacts)} artifacts")
if missing:
    print(f"  no stored result file for: {', '.join(missing)}")
