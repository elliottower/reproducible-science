"""A claim can name any commit as its freeze. These pin what that costs and who can see it.

`results` verifies the reference resolves to a commit and cannot verify a plan was frozen at
it, because it never reads a preregistration. `prereg` records the freeze and never reads the
ledger. Each is right on its own and the pair is what leaves the gap.

Distinct from `test_ordering.py`, which covers `repro.verify._ordering`: whether the runs
producing a claim's evidence started after its plan was registered, decided inside this
package's own manifest. Neither check subsumes the other.
"""

from __future__ import annotations

import json
import pathlib

import pytest
from repro.crosscheck import Freeze, confirmatory_without_a_plan, frozen_plans, unmatched


def _plan(tmp_path, name, ref):
    p = tmp_path / f"{name}.md"
    p.write_text(f"# {name}\n\n**Status:** FROZEN at `{ref}`\n**Frozen:** 2026-08-28\n")
    return p


def _ledger(tmp_path, events):
    d = tmp_path / ".results"
    d.mkdir(exist_ok=True)
    (d / "ledger.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events))


def test_a_frozen_plan_is_found_by_the_header_freeze_wrote(tmp_path):
    _plan(tmp_path, "trial", "5394ef0950b6")
    assert [f.ref for f in frozen_plans(tmp_path)] == ["5394ef0950b6"]


def test_a_draft_plan_is_not_a_freeze(tmp_path):
    (tmp_path / "draft.md").write_text("# draft\n\n**Status:** DRAFT — not frozen.\n")
    assert frozen_plans(tmp_path) == []


def test_a_claim_citing_a_freeze_no_plan_records_is_reported(tmp_path):
    _plan(tmp_path, "trial", "5394ef0950b6")
    _ledger(tmp_path, [{"event": "claim", "claim_id": "c1", "frozen_at": "deadbeefcafe"}])
    assert [c.claim_id for c in unmatched(tmp_path)] == ["c1"]


def test_a_claim_citing_the_real_freeze_is_not_reported(tmp_path):
    _plan(tmp_path, "trial", "5394ef0950b6")
    _ledger(tmp_path, [{"event": "claim", "claim_id": "c1", "frozen_at": "5394ef0950b6"}])
    assert unmatched(tmp_path) == []


def test_an_abbreviated_reference_still_matches(tmp_path):
    """`prereg` writes twelve characters; a claim may cite git's default seven."""
    _plan(tmp_path, "trial", "5394ef0950b6")
    _ledger(tmp_path, [{"event": "claim", "claim_id": "c1", "frozen_at": "5394ef0"}])
    assert unmatched(tmp_path) == []


def test_a_reference_differing_inside_the_prefix_is_not_a_match(tmp_path):
    _plan(tmp_path, "trial", "5394ef0950b6")
    _ledger(tmp_path, [{"event": "claim", "claim_id": "c1", "frozen_at": "5394eff"}])
    assert [c.claim_id for c in unmatched(tmp_path)] == ["c1"]


def test_a_confirmatory_claim_with_no_plan_anywhere_is_reported(tmp_path):
    _ledger(tmp_path, [{"event": "claim", "claim_id": "c1", "confirmatory": True}])
    assert confirmatory_without_a_plan(tmp_path) == ["c1"]


def test_it_says_nothing_where_a_plan_exists(tmp_path):
    _plan(tmp_path, "trial", "5394ef0950b6")
    _ledger(tmp_path, [{"event": "claim", "claim_id": "c1", "confirmatory": True}])
    assert confirmatory_without_a_plan(tmp_path) == []


def test_an_exploratory_claim_needs_no_plan(tmp_path):
    _ledger(tmp_path, [{"event": "claim", "claim_id": "c1", "confirmatory": False}])
    assert confirmatory_without_a_plan(tmp_path) == []


def test_a_project_with_no_ledger_reports_nothing_rather_than_failing(tmp_path):
    _plan(tmp_path, "trial", "5394ef0950b6")
    assert unmatched(tmp_path) == []
    assert confirmatory_without_a_plan(tmp_path) == []


def test_a_malformed_ledger_line_does_not_stop_the_check(tmp_path):
    d = tmp_path / ".results"
    d.mkdir()
    (d / "ledger.jsonl").write_text(
        "not json\n"
        + json.dumps({"event": "claim", "claim_id": "c1", "frozen_at": "beef123"})
        + "\n"
    )
    assert [c.claim_id for c in unmatched(tmp_path)] == ["c1"]


def test_the_git_directory_is_not_searched_for_plans(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "stray.md").write_text("**Status:** FROZEN at `abc1234`\n")
    assert frozen_plans(tmp_path) == []


@pytest.mark.parametrize("other", ["", "5394eff"])
def test_matching_refuses_an_empty_or_divergent_reference(tmp_path, other):
    assert not Freeze(pathlib.Path(tmp_path), "5394ef0950b6").matches(other)
