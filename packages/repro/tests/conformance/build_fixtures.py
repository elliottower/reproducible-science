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
TABLE = "model,accuracy,n\nLASSO-Cox,0.6478999999999999,120\nCoxMLP,0.641,120\nCoxMLP,0.700,64\n"
RESULTS = {"delta": 3.2, "label": "primary", "nested": {"a/b": 7}}

#: A document making three claims about the code beside it, and the file that settles them.
#: The first is the shape of the defect the `correspondence` kind exists for: the sentence and
#: the count disagree, and neither number is written in the manifest.
DOC = (
    "The conformance suite holds eighteen fixtures, each with canonical expected JSON.\n"
    "Improvement reached 3.2 percentage points on the held-out split.\n"
    "Appendix A lists 7 rows and Appendix B lists 9 rows.\n"
)
COUNTS = {"fixtures": 19, "improvement": 3.2004}


def write(
    name: str,
    *,
    artifacts: list[dict],
    claims: list[dict],
    expected: list[str],
    reasons: list[str | None] | None = None,
    validity: dict[str, str] | None = None,
    files: dict[str, str] | None = None,
) -> None:
    """Write one fixture and the outcomes it is required to produce.

    `expected`, `reasons` and `validity` are declared here and never read back off a run. A
    fixture that records whatever the engine said cannot fail, and the corpus exists to fail.
    """
    d = CASES / name
    prior = d / "expected.json"
    declared = {
        "outcomes",
        *(("reasons",) if reasons is not None else ()),
        *(("artifacts",) if validity is not None else ()),
    }
    if prior.exists() and (lost := set(json.loads(prior.read_text())) - declared):
        # The committed corpus asserts more than the earliest version of this script wrote.
        # Rewriting a fixture with fewer keys deletes assertions from the contract, and does
        # it silently: every remaining assertion still passes.
        raise SystemExit(
            f"{name}: expected.json declares {', '.join(sorted(lost))}, which this call does "
            f"not supply. Pass them rather than dropping them."
        )
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    for filename, content in (files or {}).items():
        (d / filename).write_text(content)
    for a in artifacts:
        if a.pop("_pin", True) and (d / a["path"]).exists():
            a["digest"] = {"algorithm": "sha256", "value": Digest.of_file(d / a["path"]).value}
    (d / "repro.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": "repro/1",
                "project": name,
                "artifacts": artifacts,
                "claims": claims,
            },
            sort_keys=False,
            width=100,
        )
    )
    record: dict[str, object] = {"outcomes": expected}
    if reasons is not None:
        record["reasons"] = reasons
    if validity is not None:
        record["artifacts"] = validity
    (d / "expected.json").write_text(json.dumps(record, indent=2) + "\n")


BOTH = {"source.txt": SOURCE, "results.json": json.dumps(RESULTS, indent=2), "table.csv": TABLE}

#: Only the prose and correspondence cases need these, and putting them in `BOTH` would add
#: two unread files to every fixture that has nothing to do with them.
PROSE = {"doc.md": DOC, "counts.json": json.dumps(COUNTS, indent=2)}
SRC = [{"id": "src", "path": "source.txt"}]
RES = [{"id": "res", "path": "results.json"}]


def quote(text, artifact="src", **kw):
    return {"kind": "quote", "artifact": artifact, "text": text, **kw}


TAB = [{"id": "tab", "path": "table.csv"}]


def cell(reported, column, artifact="tab", **kw):
    return {
        "kind": "table",
        "artifact": artifact,
        "name": "m",
        "reported": reported,
        "column": column,
        **kw,
    }


def metric(reported, pointer, artifact="res", **kw):
    return {
        "kind": "metric",
        "artifact": artifact,
        "name": "m",
        "reported": reported,
        "pointer": pointer,
        **kw,
    }


write(
    "passage_present",
    artifacts=SRC,
    files=BOTH,
    expected=["verified"],
    reasons=["passage_present"],
    validity={"src": "authoritative"},
    claims=[{"id": "c", "text": "t", "evidence": [quote("matches the Haar expectation")]}],
)

write(
    "passage_absent",
    artifacts=SRC,
    files=BOTH,
    expected=["mismatch"],
    reasons=["passage_absent"],
    validity={"src": "authoritative"},
    claims=[
        {
            "id": "c",
            "text": "t",
            "evidence": [quote("matches the Poisson expectation for this ensemble")],
        }
    ],
)

write(
    "value_match",
    artifacts=RES,
    files=BOTH,
    expected=["verified"],
    reasons=["value_match"],
    validity={"res": "authoritative"},
    claims=[{"id": "c", "text": "t", "evidence": [metric("3.2", "/delta")]}],
)

write(
    "value_match_printed_precision",
    artifacts=RES,
    files=BOTH,
    expected=["verified"],
    reasons=["value_match"],
    validity={"res": "authoritative"},
    claims=[{"id": "c", "text": "t", "evidence": [metric("3", "/delta")]}],
)

write(
    "value_mismatch",
    artifacts=RES,
    files=BOTH,
    expected=["mismatch"],
    reasons=["value_mismatch"],
    validity={"res": "authoritative"},
    claims=[{"id": "c", "text": "t", "evidence": [metric("9.9", "/delta")]}],
)

write(
    "pointer_absent",
    artifacts=RES,
    files=BOTH,
    expected=["not_found"],
    reasons=["pointer_absent"],
    validity={"res": "authoritative"},
    claims=[{"id": "c", "text": "t", "evidence": [metric("1000", "/no/such/key")]}],
)

write(
    "value_not_numeric",
    artifacts=RES,
    files=BOTH,
    expected=["not_found"],
    reasons=["selector_not_scalar"],
    validity={"res": "authoritative"},
    claims=[{"id": "c", "text": "t", "evidence": [metric("1", "/nested")]}],
)

write(
    "pointer_escaped_key",
    artifacts=RES,
    files=BOTH,
    expected=["verified"],
    reasons=["value_match"],
    validity={"res": "authoritative"},
    claims=[{"id": "c", "text": "t", "evidence": [metric("7", "/nested/a~1b")]}],
)

write(
    "artifact_missing",
    files=BOTH,
    expected=["unchecked"],
    reasons=["artifact_missing"],
    validity={"src": "artifact_absent"},
    artifacts=[{"id": "src", "path": "gone.txt", "_pin": False}],
    claims=[{"id": "c", "text": "t", "evidence": [quote("anything at all here")]}],
)

write(
    "artifact_unreadable",
    files={**BOTH, "broken.json": "{not json"},
    expected=["unchecked"],
    reasons=["artifact_unreadable"],
    validity={"res": "authoritative"},
    artifacts=[{"id": "res", "path": "broken.json"}],
    claims=[{"id": "c", "text": "t", "evidence": [metric("1", "/delta")]}],
)

write(
    "artifact_undeclared",
    artifacts=SRC,
    files=BOTH,
    expected=["unchecked"],
    reasons=["artifact_undeclared"],
    validity={"src": "authoritative"},
    claims=[{"id": "c", "text": "t", "evidence": [quote("matches", artifact="nope")]}],
)

write(
    "no_evidence_offered",
    artifacts=SRC,
    files=BOTH,
    expected=["not_offered"],
    reasons=[None],
    validity={"src": "authoritative"},
    claims=[{"id": "c", "text": "t", "evidence": []}],
)

write(
    "unpinned_artifact",
    files=BOTH,
    expected=["verified"],
    reasons=["passage_present"],
    validity={"src": "unpinned_artifact"},
    artifacts=[{"id": "src", "path": "source.txt", "_pin": False}],
    claims=[{"id": "c", "text": "t", "evidence": [quote("matches the Haar expectation")]}],
)

write(
    "table_cell_match",
    artifacts=TAB,
    files=BOTH,
    expected=["verified"],
    reasons=["value_match"],
    validity={"tab": "authoritative"},
    claims=[
        {
            "id": "c",
            "text": "t",
            "evidence": [cell("0.648", "accuracy", where={"model": "LASSO-Cox"})],
        }
    ],
)

write(
    "table_cell_mismatch",
    artifacts=TAB,
    files=BOTH,
    expected=["mismatch"],
    reasons=["value_mismatch"],
    validity={"tab": "authoritative"},
    claims=[
        {
            "id": "c",
            "text": "t",
            "evidence": [cell("0.900", "accuracy", where={"model": "LASSO-Cox"})],
        }
    ],
)

write(
    "table_column_absent",
    artifacts=TAB,
    files=BOTH,
    expected=["not_found"],
    reasons=["column_absent"],
    validity={"tab": "authoritative"},
    claims=[
        {"id": "c", "text": "t", "evidence": [cell("0.648", "f1", where={"model": "LASSO-Cox"})]}
    ],
)

write(
    "table_row_absent",
    artifacts=TAB,
    files=BOTH,
    expected=["not_found"],
    reasons=["row_absent"],
    validity={"tab": "authoritative"},
    claims=[
        {"id": "c", "text": "t", "evidence": [cell("0.648", "accuracy", where={"model": "Nope"})]}
    ],
)

write(
    "table_row_ambiguous",
    artifacts=TAB,
    files=BOTH,
    expected=["not_found"],
    reasons=["row_ambiguous"],
    validity={"tab": "authoritative"},
    claims=[
        {"id": "c", "text": "t", "evidence": [cell("0.641", "accuracy", where={"model": "CoxMLP"})]}
    ],
)

# -- prose locators, and assertions whose two sides are both artifacts ----------------------

DOCS = [{"id": "doc", "path": "doc.md"}, {"id": "counts", "path": "counts.json"}]
INTACT = {"doc": "authoritative", "counts": "authoritative"}


def prose(before, after, form="decimal"):
    return {"kind": "prose", "before": before, "after": after, "form": form}


def against(document, measured, **kw):
    return {
        "kind": "correspondence",
        "name": "fixture-count",
        "sides": [
            {"name": "stated", "artifact": "doc", "locator": document},
            {"name": "measured", "artifact": "counts", "locator": {"kind": "tree", **measured}},
        ],
        **kw,
    }


def one(evidence):
    return [{"id": "c", "text": "t", "evidence": [evidence]}]


write(
    "prose_value_match",
    artifacts=DOCS,
    files=PROSE,
    expected=["verified"],
    reasons=["value_match"],
    validity=INTACT,
    claims=one(
        {
            "kind": "value",
            "artifact": "doc",
            "name": "m",
            "reported": "18",
            "locator": prose("suite holds", "fixtures", "cardinal_word"),
        }
    ),
)

write(
    "prose_number_as_word",
    artifacts=DOCS,
    files=PROSE,
    expected=["not_found"],
    reasons=["number_as_word"],
    validity=INTACT,
    claims=one(
        {
            "kind": "value",
            "artifact": "doc",
            "name": "m",
            "reported": "18",
            # No `form`, so the default applies: a spelled-out number is refused rather than
            # read. Converting it is a semantic decision, and this is the row that records
            # that the engine declines to make one unasked.
            "locator": prose("suite holds", "fixtures"),
        }
    ),
)

write(
    "prose_anchors_ambiguous",
    artifacts=DOCS,
    files=PROSE,
    expected=["not_found"],
    reasons=["passage_ambiguous"],
    validity=INTACT,
    claims=one(
        {
            "kind": "value",
            "artifact": "doc",
            "name": "m",
            "reported": "7",
            # The document says 7 in one appendix and 9 in the other. Resolving to the first
            # would report a document that contradicts itself as verified.
            "locator": prose("lists", "rows"),
        }
    ),
)

write(
    "correspondence_match",
    artifacts=DOCS,
    files=PROSE,
    expected=["verified"],
    reasons=["value_match"],
    validity=INTACT,
    claims=one(
        # 3.2 against 3.2004: compared at the coarser of the two precisions, which is the
        # document's. A sentence printing one decimal is not contradicted by a fourth.
        against(prose("Improvement reached", "percentage points"), {"pointer": "/improvement"})
    ),
)

write(
    "correspondence_mismatch",
    artifacts=DOCS,
    files=PROSE,
    expected=["mismatch"],
    reasons=["value_mismatch"],
    validity=INTACT,
    claims=one(
        # Neither 18 nor 19 appears in the manifest. Rewriting the manifest cannot make this
        # pass; only editing the document or the count can, which is the whole point of the
        # kind.
        against(
            prose("suite holds", "fixtures", "cardinal_word"),
            {"pointer": "/fixtures"},
        )
    ),
)

write(
    "correspondence_side_absent",
    artifacts=DOCS,
    files=PROSE,
    expected=["not_found"],
    reasons=["pointer_absent"],
    validity=INTACT,
    claims=one(
        # One side reads 18 and the other reads nothing. A file silent on a value does not
        # contradict a document stating it, so this is `not_found` and never `mismatch`.
        against(
            prose("suite holds", "fixtures", "cardinal_word"),
            {"pointer": "/no/such/key"},
        )
    ),
)

print(f"  built {len(list(CASES.iterdir()))} fixtures in {CASES}")
