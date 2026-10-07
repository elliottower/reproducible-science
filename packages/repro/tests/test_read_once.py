"""A verification reads each artifact once, and never returns one run's read to the next.

A manifest of many claims over one table had the table parsed once per claim. Keeping a read
makes that one parse; the risk in keeping it is a later verification seeing an earlier file.
The tests are about both: how many times a file is parsed, and what a second run reports after
the file changed between runs.
"""

from __future__ import annotations

import yaml
from repro.adapters import prose, rows, table, tree
from repro.manifest import load
from repro.models import Outcome, Reason
from repro.verify import verify

NAMES = [f"r{at:03d}" for at in range(40)]


def side(artifact, locator):
    return {"name": artifact, "artifact": artifact, "locator": locator}


def project(tmp_path, stored="0.500217", duplicate=False):
    """Forty claims, each tying a number in a text to a cell of one CSV and to one JSON value."""
    lines = [f"Row {name} reports 0.500 units{name}." for name in NAMES]
    cells = [f"{name},{stored}" for name in NAMES] + ([f"{NAMES[0]},{stored}"] if duplicate else [])
    (tmp_path / "paper.txt").write_text("\n".join(lines) + "\n")
    (tmp_path / "output.csv").write_text("\n".join(["name,value", *cells]) + "\n")
    (tmp_path / "output.yaml").write_text(yaml.safe_dump(dict.fromkeys(NAMES, stored)))
    claims = []
    for name in NAMES:
        text = side(
            "paper", {"kind": "prose", "before": f"{name} reports", "after": f"units{name}"}
        )
        claims.append(
            {
                "id": name,
                "text": name,
                "evidence": [
                    {
                        "kind": "correspondence",
                        "name": f"{name}-csv",
                        "sides": [
                            text,
                            side(
                                "csv", {"kind": "table", "column": "value", "where": {"name": name}}
                            ),
                        ],
                    },
                    {
                        "kind": "correspondence",
                        "name": f"{name}-yaml",
                        "sides": [text, side("tree", {"kind": "tree", "pointer": f"/{name}"})],
                    },
                ],
            }
        )
    (tmp_path / "repro.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": "repro/1",
                "project": "t",
                "artifacts": [
                    {"id": "paper", "path": "paper.txt"},
                    {"id": "csv", "path": "output.csv"},
                    {"id": "tree", "path": "output.yaml"},
                ],
                "claims": claims,
            }
        )
    )
    return load(tmp_path / "repro.yaml")


def outcomes(report):
    return [decision.outcome for claim in report.claims for decision in claim.decisions]


def counted(monkeypatch, module, name):
    calls = []
    original = getattr(module, name)

    def counting(*args, **kwargs):
        calls.append(args)
        return original(*args, **kwargs)

    monkeypatch.setattr(module, name, counting)
    return calls


def test_one_verification_parses_each_artifact_once(tmp_path, monkeypatch):
    manifest = project(tmp_path)
    parsed_tables = counted(monkeypatch, table, "read_table")
    parsed_trees = counted(monkeypatch, tree, "_load_tree")
    indexed = counted(monkeypatch, table, "index_rows")
    extracted = counted(monkeypatch, prose, "once")

    report = verify(manifest)

    assert outcomes(report) == [Outcome.VERIFIED] * (2 * len(NAMES))
    assert len(parsed_tables) == 1
    assert len(parsed_trees) == 1
    assert len(indexed) == 1
    # The text is asked for by both assertions of every claim, and extracted for the first.
    assert len(extracted) == 2 * len(NAMES)


def test_a_second_verification_reads_the_file_as_it_now_is(tmp_path):
    manifest = project(tmp_path)
    assert set(outcomes(verify(manifest))) == {Outcome.VERIFIED}

    # Same length, so nothing about the file but its bytes says it changed.
    for name in ("output.csv", "output.yaml"):
        path = tmp_path / name
        path.write_text(path.read_text().replace("0.500217", "0.900217"))
    (tmp_path / "paper.txt").write_text(
        (tmp_path / "paper.txt")
        .read_text()
        .replace(f"{NAMES[0]} reports 0.500", f"{NAMES[0]} reports 0.900")
    )

    report = verify(manifest)
    by_claim = {claim.claim_id: [d.outcome for d in claim.decisions] for claim in report.claims}
    assert by_claim[NAMES[0]] == [Outcome.VERIFIED, Outcome.VERIFIED]
    assert all(
        found == [Outcome.MISMATCH, Outcome.MISMATCH]
        for name, found in by_claim.items()
        if name != NAMES[0]
    )


def test_an_indexed_table_reports_what_a_scan_reports(tmp_path):
    report = verify(project(tmp_path, duplicate=True))
    by_claim = {claim.claim_id: claim.decisions[0] for claim in report.claims}

    assert by_claim[NAMES[0]].reason is Reason.ROW_AMBIGUOUS
    assert "2 rows" in by_claim[NAMES[0]].detail
    assert all(by_claim[name].outcome is Outcome.VERIFIED for name in NAMES[1:])


def test_an_index_selects_the_rows_a_scan_selects():
    cells = [
        {"model": m, "seed": s, "value": f"{at}"}
        for at, (m, s) in enumerate([("a", "1"), ("a", "2"), ("b", "1"), ("a", "1"), ("c", "")])
    ]
    for where in ({"model": "a"}, {"seed": "1", "model": "a"}, {"model": "z"}, {"seed": ""}, {}):
        columns = tuple(sorted(where))
        scanned = rows.resolve_rows(["model", "seed", "value"], cells, "value", where, "t.csv")
        indexed = rows.resolve_rows(
            ["model", "seed", "value"],
            cells,
            "value",
            where,
            "t.csv",
            rows.index_rows(cells, columns),
        )
        assert indexed == scanned
