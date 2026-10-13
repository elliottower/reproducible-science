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
    stages: list[list[str]] | None = None,
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
        *(("stages",) if stages is not None else ()),
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
    if stages is not None:
        # Execution, extraction and comparison, one triple per decision. The outcome is
        # derived from these, so declaring them says which row of §4 the case is.
        record["stages"] = stages
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

# -- a statistic over several stored values --------------------------------------------------

#: Four runs of one model, and a fifth file that reports a loss and no accuracy.
RUNS = {
    **{f"run{n}.json": json.dumps({"accuracy": value}) for n, value in enumerate((1, 1, 2, 4))},
    "other.json": json.dumps({"loss": 0.2}),
}
RUN = [{"id": f"run{n}", "path": f"run{n}.json"} for n in range(4)]
OTHER = [{"id": "other", "path": "other.json"}]


def held(artifacts):
    """The files these artifacts name, and no other: a fixture carries only what it reads."""
    return {a["path"]: RUNS[a["path"]] for a in artifacts}


def over(reported, statistic, artifacts):
    return {
        "kind": "aggregate",
        "name": "m",
        "reported": reported,
        "statistic": statistic,
        "count": len(artifacts),
        "members": [
            {"artifact": a["id"], "locator": {"kind": "tree", "pointer": "/accuracy"}}
            for a in artifacts
        ],
    }


write(
    "aggregate_match",
    artifacts=RUN[:3],
    files=held(RUN[:3]),
    expected=["verified"],
    reasons=["value_match"],
    validity={a["id"]: "authoritative" for a in RUN[:3]},
    stages=[["completed", "extracted", "match"]],
    # 1, 1 and 2 have a mean of four thirds, which no decimal holds. It is rounded once, to
    # the two places the manifest prints.
    claims=one(over("1.33", "mean", RUN[:3])),
)

write(
    "aggregate_mismatch",
    artifacts=RUN,
    files=held(RUN),
    expected=["mismatch"],
    reasons=["value_mismatch"],
    validity={a["id"]: "authoritative" for a in RUN},
    stages=[["completed", "extracted", "mismatch"]],
    # The best of the four runs, printed as their mean, which is 2.
    claims=one(over("4", "mean", RUN)),
)

write(
    "aggregate_member_absent",
    artifacts=RUN[:3] + OTHER,
    files=held(RUN[:3] + OTHER),
    expected=["not_found"],
    reasons=["pointer_absent"],
    validity={a["id"]: "authoritative" for a in RUN[:3] + OTHER},
    stages=[["completed", "absent", "not_applicable"]],
    # Three members hold 1, 1 and 2 and the fourth holds no accuracy. The mean of the three
    # that resolve is 1.33, which is what the manifest prints, and it is not taken: a
    # statistic over fewer members than were declared is `not_found` and never a match.
    claims=one(over("1.33", "mean", RUN[:3] + OTHER)),
)

# -- a printed table, read as text -----------------------------------------------------------

#: What a script prints and a report keeps: a pipe table, each cell padded on the left and
#: glued to the divider on its right, every line carrying the `## ` an R chunk's output has.
PRINTED = (
    "## $north\n"
    "##\n"
    "##\n"
    "## |   N (sites)| Slope|    se|   pval|\n"
    "## |-----------:|-----:|-----:|------:|\n"
    "## |           7| 0.318| 0.107| 0.0271|\n"
    "##\n"
    "## $south\n"
    "##\n"
    "##\n"
    "## |   N (sites)| Slope|    se|   pval|\n"
    "## |-----------:|-----:|-----:|------:|\n"
    "## |           5| 0.212| 0.090| 0.0412|\n"
    "##\n"
)
OUT = [{"id": "out", "path": "output.txt"}]


def printed(reported, before, after):
    return one(
        {
            "kind": "value",
            "artifact": "out",
            "name": "delta",
            "reported": reported,
            "locator": prose(before, after),
        }
    )


write(
    "prose_table_cell_match",
    artifacts=OUT,
    files={"output.txt": PRINTED},
    expected=["verified"],
    reasons=["value_match"],
    validity={"out": "authoritative"},
    stages=[["completed", "extracted", "match"]],
    # The anchors are written with single spaces and the file pads the cell with ten. The
    # divider is the trailing anchor, so the value is the cell and not the cell with a bar on it.
    claims=printed("0.318", "| 7|", "|"),
)

write(
    "prose_table_cell_not_numeric",
    artifacts=OUT,
    files={"output.txt": PRINTED},
    expected=["not_found"],
    reasons=["value_not_numeric"],
    validity={"out": "authoritative"},
    stages=[["completed", "invalid", "not_applicable"]],
    # No trailing anchor, so the value runs to the next whitespace and is `0.318|`. The engine
    # strips nothing the locator did not name, and reports what it read.
    claims=printed("0.318", "| 7|", ""),
)

write(
    "prose_anchor_absent",
    artifacts=OUT,
    files={"output.txt": PRINTED},
    expected=["not_found"],
    reasons=["passage_absent"],
    validity={"out": "authoritative"},
    stages=[["completed", "absent", "not_applicable"]],
    # No row of either table opens with a 4. A row that is not there is absent, and is not
    # read off the nearest row that is.
    claims=printed("0.318", "| 4|", "|"),
)

write(
    "prose_anchor_splits_number",
    artifacts=OUT,
    files={"output.txt": PRINTED},
    expected=["not_found"],
    reasons=["passage_absent"],
    validity={"out": "authoritative"},
    stages=[["completed", "absent", "not_applicable"]],
    # `8|` begins inside `0.318`, and cutting there would read `0.31`, which is what the
    # manifest reports. An anchor never splits a number, so nothing is read.
    claims=printed("0.31", "| 7|", "8|"),
)

#: A file storing fractions that a manuscript prints as percentages.
RATES = {"rates.json": json.dumps({"low": 0.0424, "high": 0.0426}, indent=2)}
RATE = [{"id": "rates", "path": "rates.json"}]

write(
    "value_match_converted",
    artifacts=RATE,
    files=RATES,
    expected=["verified", "mismatch"],
    reasons=["value_match", "value_mismatch"],
    validity={"rates": "authoritative"},
    stages=[["completed", "extracted", "match"], ["completed", "extracted", "mismatch"]],
    # 0.0424 is 4.24 as a percentage, which is 4.2 at the one decimal the manuscript prints.
    # The same address with no conversion declared compares 0.0424 with 4.2: nothing is
    # converted that the assertion did not name.
    claims=[
        {
            "id": "c",
            "text": "t",
            "evidence": [
                metric("4.2", "/low", artifact="rates", conversion="percent"),
                metric("4.2", "/low", artifact="rates"),
            ],
        }
    ],
)

write(
    "value_mismatch_converted",
    artifacts=RATE,
    files=RATES,
    expected=["mismatch"],
    reasons=["value_mismatch"],
    validity={"rates": "authoritative"},
    stages=[["completed", "extracted", "mismatch"]],
    # 0.0426 is 4.26 as a percentage, and 4.3 at one decimal. Rounding the stored fraction
    # before converting it would lose the digit that decides this.
    claims=[
        {
            "id": "c",
            "text": "t",
            "evidence": [metric("4.2", "/high", artifact="rates", conversion="percent")],
        }
    ],
)

#: A value exactly halfway between two values at one decimal place, and one that is not.
HALVES = {"halves.json": json.dumps({"tie": 4.25, "effect": 4.2011}, indent=2)}
HALF = [{"id": "halves", "path": "halves.json"}]

write(
    "value_tie_either_neighbor",
    artifacts=HALF,
    files=HALVES,
    expected=["verified", "verified", "mismatch"],
    reasons=["value_match", "value_match", "value_mismatch"],
    validity={"halves": "authoritative"},
    stages=[
        ["completed", "extracted", "match"],
        ["completed", "extracted", "match"],
        ["completed", "extracted", "mismatch"],
    ],
    # 4.25 rounds to 4.2 half to even and to 4.3 half up, and a manuscript printing either
    # has rounded correctly. 4.4 is neither.
    claims=[
        {
            "id": "c",
            "text": "t",
            "evidence": [
                metric("4.2", "/tie", artifact="halves"),
                metric("4.3", "/tie", artifact="halves"),
                metric("4.4", "/tie", artifact="halves"),
            ],
        }
    ],
)

write(
    "value_places_mismatch",
    artifacts=HALF,
    files=HALVES,
    expected=["mismatch", "verified"],
    reasons=["places_mismatch", "value_match"],
    validity={"halves": "authoritative"},
    stages=[["completed", "extracted", "mismatch"], ["completed", "extracted", "match"]],
    # The file holds 4.2011, which is 4.20 at two places, so the printed value is right. It
    # is declared to one place and printed to two, and that is what does not hold.
    claims=[
        {
            "id": "c",
            "text": "t",
            "evidence": [
                metric("4.20", "/effect", artifact="halves", places=1),
                metric("4.2", "/effect", artifact="halves", places=1),
            ],
        }
    ],
)

print(f"  built {len(list(CASES.iterdir()))} fixtures in {CASES}")
