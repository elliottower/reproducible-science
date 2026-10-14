"""`claims from-clawbio` on a ClawBio skill's output folder.

Every fixture here is invented. ClawBio's LICENSE is MIT for the repository and carves out any
skill that declares its own license and any model or data a skill uses, so no real skill's
output is copied in. The folder below has the layout ClawBio's shared helpers write
(`clawbio/common/reproducibility.py` at 9405cfd): `report.md`, `tables/`, and
`reproducibility/` with `commands.sh`, `environment.yml` and `checksums.sha256`, whose labels
are paths from the folder.
"""

from __future__ import annotations

import hashlib
import json
import pathlib

import pytest
import yaml
from claims.cli import main
from claims.manifest import load
from claims.models import Basis, Outcome, Validity
from claims.open_items import ClaimState, OpenItemsError, tally
from claims.open_items import read as read_items
from claims.sources.clawbio import ClawbioError, from_clawbio
from claims.verify import verify

REPORT = """# Invented Score Report

**Date**: 2026-10-14
**Input checksum**: `3f9a0c11b2e4`

## Summary

- **Samples**: 48
- **Mean coverage**: 31.25 reads per site
- **Pass rate**: 87.5%

| Group | Count | Score |
|-------|-------|-------|
| A | 20 | 0.812 |

```bash
python invented.py --threshold 0.05
```
"""

SUMMARY = "group,count,score\nA,20,0.8124\nB,28,0.7\n"
STATS = '{"samples": 48, "mean_coverage": 31.25, "pass_rate": 0.875}\n'


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _folder(root: pathlib.Path, stats: str = STATS) -> pathlib.Path:
    """A skill's output folder whose checksums record `STATS`, holding `stats` on disk."""
    folder = root / "run"
    (folder / "tables").mkdir(parents=True)
    (folder / "reproducibility").mkdir()
    (folder / "report.md").write_text(REPORT)
    (folder / "tables" / "summary.csv").write_text(SUMMARY)
    (folder / "tables" / "stats.json").write_text(stats)
    (folder / "tables" / "left_over.csv").write_text("x\n1\n")
    (folder / "reproducibility" / "commands.sh").write_text("#!/usr/bin/env bash\ntrue\n")
    (folder / "reproducibility" / "environment.yml").write_text("name: invented\n")
    (folder / "reproducibility" / "checksums.sha256").write_text(
        f"{_sha(SUMMARY)}  tables/summary.csv\n"
        f"{_sha(STATS)}  tables/stats.json\n"
        f"{'0' * 64}  absent.txt\n"
        f"{'1' * 64}  ../outside.csv\n"
        "not a checksum line\n"
    )
    return folder


def verify_draft(out: pathlib.Path):
    return verify(load(out / "repro.draft.yaml"))


def _draft(out: pathlib.Path) -> dict:
    return yaml.safe_load((out / "repro.draft.yaml").read_text())


def test_each_listed_file_is_pinned_to_the_digest_clawbio_recorded(tmp_path):
    out = tmp_path / "out"
    written = from_clawbio(_folder(tmp_path), out)
    artifacts = {a["id"]: a for a in _draft(out)["artifacts"]}
    assert artifacts["tables/summary.csv"]["digest"]["value"] == _sha(SUMMARY)
    assert artifacts["tables/stats.json"]["digest"]["value"] == _sha(STATS)
    assert artifacts["report.md"]["digest"]["value"] == _sha(REPORT)
    assert set(artifacts) == {"tables/summary.csv", "tables/stats.json", "report.md"}
    passed = {p.file: p.reason for p in written.passed_over}
    assert "outside the folder" in passed["../outside.csv"]
    assert "bare file name" in passed["absent.txt"]
    assert "not in checksums.sha256" in passed["tables/left_over.csv"]
    assert "line 5 is not a sha256 line" in passed["reproducibility/checksums.sha256"]

    source = read_items(out / "open-items.json").source
    assert (
        source.digest
        == hashlib.sha256(
            (tmp_path / "run/reproducibility/checksums.sha256").read_bytes()
        ).hexdigest()
    )
    assert source.pins == {
        "report.md": _sha(REPORT),
        "reproducibility/commands.sh": _sha("#!/usr/bin/env bash\ntrue\n"),
        "reproducibility/environment.yml": _sha("name: invented\n"),
    }


def test_a_table_whose_bytes_moved_since_the_run_verifies_as_a_broken_pin(tmp_path):
    out = tmp_path / "out"
    written = from_clawbio(_folder(tmp_path, stats=STATS.replace("48", "49")), out)
    assert [p.file for p in written.not_checked] == ["tables/stats.json"]
    report = verify_draft(out)
    assert report.artifacts_with(Validity.BROKEN_PIN) == ("tables/stats.json",)
    # No candidate is read from bytes the run did not write.
    for item in read_items(out / "open-items.json").items:
        assert all(c["artifact"] != "tables/stats.json" for c in item.candidates)


def test_every_number_the_report_prints_is_an_item_or_passed_over_with_its_line(tmp_path):
    out = tmp_path / "out"
    written = from_clawbio(_folder(tmp_path), out)
    items = read_items(out / "open-items.json").items
    assert [(i.context["line"], i.context["printed"]) for i in items] == [
        (8, "48"),
        (9, "31.25"),
        (10, "87.5%"),
        (14, "20"),
        (14, "0.812"),
    ]
    reasons = [p.reason for p in written.passed_over if p.file == "report.md"]
    # The date is set aside by the number rule, the checksum in inline code by the reader,
    # and the threshold in the fenced command by the reader.
    assert any(r.startswith("line 3:") and "date" in r for r in reasons)
    assert any(r.startswith("line 4:") and "inline code" in r for r in reasons)
    assert any(r.startswith("line 17:") and "fenced code block" in r for r in reasons)
    assert not any(r.startswith(("line 8:", "line 9:", "line 10:", "line 14:")) for r in reasons)
    assert written.claims == written.items == 5


def test_each_claim_quotes_its_line_and_holds_no_value_the_reader_found(tmp_path):
    out = tmp_path / "out"
    from_clawbio(_folder(tmp_path), out)
    claims = _draft(out)["claims"]
    assert {c["id"]: c["text"] for c in claims}["line-9-1"] == (
        "- **Mean coverage**: 31.25 reads per site"
    )
    for claim in claims:
        assert claim["evidence"] == [
            {"kind": "quote", "artifact": "report.md", "text": claim["text"]}
        ]
    report = verify_draft(out)
    assert report.counts == {Outcome.VERIFIED.value: 5}


def test_candidates_are_the_matching_addresses_and_are_never_in_the_draft(tmp_path):
    out = tmp_path / "out"
    from_clawbio(_folder(tmp_path), out)
    items = {i.claim: i for i in read_items(out / "open-items.json").items}
    assert [(c["artifact"], c["locator"]["pointer"]) for c in items["line-9-1"].candidates] == [
        ("tables/stats.json", "/mean_coverage")
    ]
    pass_rate = items["line-10-1"].candidates
    assert [(c["locator"]["pointer"], c.get("conversion")) for c in pass_rate] == [
        ("/pass_rate", "percent")
    ]
    score = items["line-14-2"].candidates
    assert [
        (c["artifact"], c["locator"]["kind"], c["locator"]["column"], c["locator"]["row"])
        for c in score
    ] == [("tables/summary.csv", "table_position", "score", 0)]
    assert all(c["basis"] == "inferred" for i in items.values() for c in i.candidates)
    draft = (out / "repro.draft.yaml").read_text()
    assert "pointer" not in draft and "table_position" not in draft


def test_open_items_counts_an_inferred_fill_that_matches_as_bound_and_never_verified(tmp_path):
    out = tmp_path / "out"
    from_clawbio(_folder(tmp_path), out)
    before = tally(out / "open-items.json")
    assert before.claims[ClaimState.OPEN] == 5 and before.items["open"] == 5

    items = {i.claim: i for i in read_items(out / "open-items.json").items}
    draft = _draft(out)
    for claim in draft["claims"]:
        if claim["id"] == "line-9-1":
            claim["evidence"].append(items["line-9-1"].candidates[0])
    (out / "repro.draft.yaml").write_text(yaml.safe_dump(draft, sort_keys=False))

    after = tally(out / "open-items.json")
    assert after.claims[ClaimState.BOUND] == 1 and after.claims[ClaimState.OPEN] == 4
    assert after.items["filled_by_inferred"] == 1 and after.items["filled_as_sole_candidate"] == 1
    assert after.assertions[Basis.INFERRED] == {Outcome.VERIFIED: 1}
    assert after.inferred_counted_as_verified == 0
    assert verify_draft(out).counts[Outcome.VERIFIED.value] == 5


def test_a_reading_never_overwrites_and_a_folder_without_checksums_is_refused(tmp_path):
    folder, out = _folder(tmp_path), tmp_path / "out"
    from_clawbio(folder, out)
    with pytest.raises(OpenItemsError, match="never overwrites"):
        from_clawbio(folder, out)
    (folder / "reproducibility" / "checksums.sha256").unlink()
    with pytest.raises(ClawbioError, match=r"checksums\.sha256"):
        from_clawbio(folder, tmp_path / "elsewhere")


def test_the_command_prints_what_it_wrote(tmp_path, capsys):
    folder, out = _folder(tmp_path), tmp_path / "out"
    assert main(["from-clawbio", str(folder), "-o", str(out), "--format", "json"]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert (printed["claims"], printed["items"], printed["pinned"]) == (5, 5, 3)
