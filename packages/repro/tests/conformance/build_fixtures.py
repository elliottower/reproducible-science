"""Build one fixture per row of the outcome table in SPEC.md §4.

Each fixture is a directory with its artifacts, a manifest whose digests are computed rather
than typed, and the expected flattened outcome. Conformance becomes executable: an
implementation either reproduces these or does not.
"""
from __future__ import annotations

import json
import pathlib
import shutil

import yaml
from repro import Digest

HERE = pathlib.Path(__file__).parent
CASES = HERE / "cases"

SOURCE = "The measured angle matches the Haar expectation for this ensemble.\n"
TABLE = ("model,accuracy,n\n"
         "LASSO-Cox,0.6478999999999999,120\n"
         "CoxMLP,0.641,120\n"
         "CoxMLP,0.700,64\n")
RESULTS = {"delta": 3.2, "label": "primary", "nested": {"a/b": 7}}


def write(name: str, *, artifacts: list[dict], claims: list[dict],
          expected: list[str], files: dict[str, str] | None = None) -> None:
    d = CASES / name
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    for filename, content in (files or {}).items():
        (d / filename).write_text(content)
    for a in artifacts:
        if a.pop("_pin", True) and (d / a["path"]).exists():
            a["digest"] = {"algorithm": "sha256", "value": Digest.of_file(d / a["path"]).value}
    (d / "repro.yaml").write_text(yaml.safe_dump(
        {"schema_version": "repro/1", "project": name,
         "artifacts": artifacts, "claims": claims}, sort_keys=False, width=100))
    (d / "expected.json").write_text(json.dumps({"outcomes": expected}, indent=2) + "\n")


BOTH = {"source.txt": SOURCE, "results.json": json.dumps(RESULTS, indent=2),
        "table.csv": TABLE}
SRC = [{"id": "src", "path": "source.txt"}]
RES = [{"id": "res", "path": "results.json"}]


def quote(text, artifact="src", **kw):
    return {"kind": "quote", "artifact": artifact, "text": text, **kw}


TAB = [{"id": "tab", "path": "table.csv"}]


def cell(reported, column, artifact="tab", **kw):
    return {"kind": "table", "artifact": artifact, "name": "m",
            "reported": reported, "column": column, **kw}


def metric(reported, pointer, artifact="res", **kw):
    return {"kind": "metric", "artifact": artifact, "name": "m",
            "reported": reported, "pointer": pointer, **kw}


write("passage_present", artifacts=SRC, files=BOTH, expected=["verified"],
      claims=[{"id": "c", "text": "t", "evidence": [quote("matches the Haar expectation")]}])

write("passage_absent", artifacts=SRC, files=BOTH, expected=["mismatch"],
      claims=[{"id": "c", "text": "t",
               "evidence": [quote("matches the Poisson expectation for this ensemble")]}])

write("value_match", artifacts=RES, files=BOTH, expected=["verified"],
      claims=[{"id": "c", "text": "t", "evidence": [metric("3.2", "/delta")]}])

write("value_match_printed_precision", artifacts=RES, files=BOTH, expected=["verified"],
      claims=[{"id": "c", "text": "t", "evidence": [metric("3", "/delta")]}])

write("value_mismatch", artifacts=RES, files=BOTH, expected=["mismatch"],
      claims=[{"id": "c", "text": "t", "evidence": [metric("9.9", "/delta")]}])

write("pointer_absent", artifacts=RES, files=BOTH, expected=["not_found"],
      claims=[{"id": "c", "text": "t", "evidence": [metric("1000", "/no/such/key")]}])

write("value_not_numeric", artifacts=RES, files=BOTH, expected=["not_found"],
      claims=[{"id": "c", "text": "t", "evidence": [metric("1", "/nested")]}])

write("pointer_escaped_key", artifacts=RES, files=BOTH, expected=["verified"],
      claims=[{"id": "c", "text": "t", "evidence": [metric("7", "/nested/a~1b")]}])

write("artifact_missing", files=BOTH, expected=["unchecked"],
      artifacts=[{"id": "src", "path": "gone.txt", "_pin": False}],
      claims=[{"id": "c", "text": "t", "evidence": [quote("anything at all here")]}])

write("artifact_unreadable", files={**BOTH, "broken.json": "{not json"}, expected=["unchecked"],
      artifacts=[{"id": "res", "path": "broken.json"}],
      claims=[{"id": "c", "text": "t", "evidence": [metric("1", "/delta")]}])

write("artifact_undeclared", artifacts=SRC, files=BOTH, expected=["unchecked"],
      claims=[{"id": "c", "text": "t", "evidence": [quote("matches", artifact="nope")]}])

write("no_evidence_offered", artifacts=SRC, files=BOTH, expected=["not_offered"],
      claims=[{"id": "c", "text": "t", "evidence": []}])

write("unpinned_artifact", files=BOTH, expected=["verified"],
      artifacts=[{"id": "src", "path": "source.txt", "_pin": False}],
      claims=[{"id": "c", "text": "t", "evidence": [quote("matches the Haar expectation")]}])

write("table_cell_match", artifacts=TAB, files=BOTH, expected=["verified"],
      claims=[{"id": "c", "text": "t",
               "evidence": [cell("0.648", "accuracy", where={"model": "LASSO-Cox"})]}])

write("table_cell_mismatch", artifacts=TAB, files=BOTH, expected=["mismatch"],
      claims=[{"id": "c", "text": "t",
               "evidence": [cell("0.900", "accuracy", where={"model": "LASSO-Cox"})]}])

write("table_column_absent", artifacts=TAB, files=BOTH, expected=["not_found"],
      claims=[{"id": "c", "text": "t",
               "evidence": [cell("0.648", "f1", where={"model": "LASSO-Cox"})]}])

write("table_row_absent", artifacts=TAB, files=BOTH, expected=["not_found"],
      claims=[{"id": "c", "text": "t",
               "evidence": [cell("0.648", "accuracy", where={"model": "Nope"})]}])

write("table_row_ambiguous", artifacts=TAB, files=BOTH, expected=["not_found"],
      claims=[{"id": "c", "text": "t",
               "evidence": [cell("0.641", "accuracy", where={"model": "CoxMLP"})]}])

print(f"  built {len(list(CASES.iterdir()))} fixtures in {CASES}")
