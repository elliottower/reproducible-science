"""Places where the verifier reported a pass it had not established.

Each of these produced a favourable verdict out of an absence: two empty strings comparing equal,
a one-character reference matching any commit, a volatile field switching a guard off, and a crash
standing in for the finding a policy would have made.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import sys

from repro.corpus import Corpus, CorpusEntry, EntryState
from repro.crosscheck import Freeze
from repro.manifest import load
from repro.reproduce import reproduce
from repro.verify import verify

FROZEN = "a1b2c3d4e5f6"


def canonical(doc: dict) -> str:
    return hashlib.sha256(
        json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


# --- a cited freeze reference must supply a whole prefix ---------------------------------------


def test_a_one_character_reference_does_not_match_a_freeze():
    assert not Freeze(pathlib.Path("PREREG.md"), FROZEN).matches("a")


def test_a_reference_shorter_than_the_prefix_does_not_match():
    assert not Freeze(pathlib.Path("PREREG.md"), FROZEN).matches("a1b2c3")


def test_an_empty_reference_does_not_match():
    assert not Freeze(pathlib.Path("PREREG.md"), FROZEN).matches("")


def test_a_full_prefix_still_matches():
    assert Freeze(pathlib.Path("PREREG.md"), FROZEN).matches("a1b2c3d")


def test_the_whole_reference_still_matches():
    assert Freeze(pathlib.Path("PREREG.md"), FROZEN).matches(FROZEN)


def test_a_differing_reference_of_full_length_does_not_match():
    assert not Freeze(pathlib.Path("PREREG.md"), FROZEN).matches("a1b2c3e")


def test_matching_ignores_case():
    assert Freeze(pathlib.Path("PREREG.md"), FROZEN).matches(FROZEN.upper())


# --- a corpus entry with no revision is not "at the recorded revision" -------------------------


def test_an_entry_with_no_commit_over_a_plain_directory_is_unpinned(tmp_path):
    (tmp_path / "someproject").mkdir()
    corpus = Corpus(entries=(CorpusEntry(name="someproject", local_path="someproject"),))
    corpus = corpus.model_copy(update={"path": tmp_path / "corpus.yaml"})

    status = corpus.status(fetch=False)[0]

    assert status.state is EntryState.UNPINNED


def test_an_unpinned_entry_cannot_stand_behind_a_number(tmp_path):
    (tmp_path / "someproject").mkdir()
    corpus = Corpus(entries=(CorpusEntry(name="someproject", local_path="someproject"),))
    corpus = corpus.model_copy(update={"path": tmp_path / "corpus.yaml"})

    assert not corpus.status(fetch=False)[0].usable


def test_an_entry_naming_a_commit_over_a_plain_directory_is_unpinned(tmp_path):
    (tmp_path / "someproject").mkdir()
    corpus = Corpus(
        entries=(CorpusEntry(name="someproject", local_path="someproject", commit="f" * 40),)
    )
    corpus = corpus.model_copy(update={"path": tmp_path / "corpus.yaml"})

    assert corpus.status(fetch=False)[0].state is EntryState.UNPINNED


# --- a confirmatory claim with no evidence is a finding, not a traceback -----------------------

NO_EVIDENCE = """\
project: demo
artifacts:
  - id: results
    path: results.json
claims:
  - id: c1
    text: "the effect is 0.5"
    confirmatory: true
"""


def test_a_confirmatory_claim_with_no_evidence_does_not_crash(tmp_path):
    (tmp_path / "results.json").write_text('{"x": 1}\n')
    (tmp_path / "repro.yaml").write_text(NO_EVIDENCE)

    report = verify(load(tmp_path / "repro.yaml"))

    assert [c.claim_id for c in report.claims] == ["c1"]


def test_a_confirmatory_claim_with_no_evidence_is_reported_unchecked(tmp_path):
    (tmp_path / "results.json").write_text('{"x": 1}\n')
    (tmp_path / "repro.yaml").write_text(NO_EVIDENCE)

    claim = verify(load(tmp_path / "repro.yaml")).claims[0]

    # Not `no_run_record`, which sends a reader looking for a run that should exist. The claim
    # offered nothing to order against.
    assert claim.ordering_reason.value == "no_evidence_offered"


# --- naming a volatile field does not switch the output guard off ------------------------------

PINNED_DOC = {"delta": 0.99}
PRODUCED_DOC = {"delta": 0.11}

REGEN = """\
project: demo
artifacts:
  - id: results
    path: results.json
    digest: {{algorithm: sha256, value: "{pinned}"}}
claims:
  - id: c1
    text: "delta is 0.99"
    evidence:
      - kind: metric
        artifact: results
        name: delta
        reported: "0.99"
        pointer: /delta
regenerations:
  - id: regen
    command: ["{python}", "-c", "open('results.json','w').write('{{\\"delta\\": 0.11}}')"]
    output:
      artifact: results
      digest: {{algorithm: sha256, value: "{expected}"}}
    volatile: ["/nonexistent"]
"""


def _regen_state(tmp_path):
    text = json.dumps(PINNED_DOC)
    (tmp_path / "results.json").write_text(text)
    (tmp_path / "repro.yaml").write_text(
        REGEN.format(
            pinned=hashlib.sha256(text.encode()).hexdigest(),
            python=sys.executable,
            expected=canonical(PRODUCED_DOC),
        )
    )
    return reproduce(load(tmp_path / "repro.yaml")).regenerations[0]


def test_a_record_naming_a_volatile_field_cannot_pin_its_own_answer(tmp_path):
    assert _regen_state(tmp_path).state.value != "reproduced"


def test_the_record_is_reported_as_not_the_artifact(tmp_path):
    assert _regen_state(tmp_path).reason.value == "output_not_the_artifact"


# --- every state the quotation backend can return is mapped ------------------------------------


def test_every_citations_quote_state_is_mapped():
    # `citations.verify` answers with five states and two were mapped, so a passage occurring
    # twice raised `KeyError: 'ambiguous'` inside the backend and was reported as a defect in the
    # tool rather than as an undecided quotation. A gate here rather than a comment, so a sixth
    # state added upstream fails a build instead of a run.
    from typing import get_args

    from citations.verify import State
    from repro.verify import _QUOTE_STATE

    assert set(_QUOTE_STATE) == set(get_args(State))


# --- a quotation occurring twice is undecided, and says why -------------------------------------

PASSAGE = "The effect held in every cohort we examined"

QUOTED_TWICE = """\
project: demo
artifacts:
  - id: manuscript
    path: manuscript.txt
claims:
  - id: unresolved-quotations
    text: "the effect held throughout"
    evidence:
      - kind: quote
        artifact: manuscript
        text: "The effect held in every cohort we examined"
"""


def _quoted(tmp_path, occurrences: int):
    body = "".join(f"Paragraph {i}. {PASSAGE}.\n" for i in range(occurrences))
    (tmp_path / "manuscript.txt").write_text(body)
    (tmp_path / "repro.yaml").write_text(QUOTED_TWICE)
    return verify(load(tmp_path / "repro.yaml")).claims[0].decisions[0]


def test_a_passage_occurring_twice_is_reported_as_an_ambiguous_quotation(tmp_path):
    # Observed 1 Oct 2026 under the released 0.4.2: `repro verify --policy strict` reported
    # `evidence.error ... KeyError: 'ambiguous'` for this manifest. The state is mapped now, and
    # under its own reason: `passage_ambiguous` says a document states two different numbers,
    # which accuses the manuscript of contradicting itself. A quotation found twice accuses
    # nothing; the record has not said which occurrence it means.
    from repro.models import ComparisonStatus, ExecutionStatus, ExtractionStatus, Outcome, Reason

    decision = _quoted(tmp_path, 2)

    assert decision.execution is ExecutionStatus.COMPLETED
    assert decision.extraction is ExtractionStatus.INVALID
    assert decision.comparison is ComparisonStatus.NOT_APPLICABLE
    assert decision.reason is Reason.QUOTATION_AMBIGUOUS
    assert decision.outcome is Outcome.NOT_FOUND
    assert "occurs 2 times" in decision.detail


def test_the_same_passage_occurring_once_is_verified(tmp_path):
    # The control: the passage and the manifest are the ones above, so what made the first
    # decision undecided is the second occurrence and nothing else.
    from repro.models import Outcome, Reason

    decision = _quoted(tmp_path, 1)

    assert decision.reason is Reason.PASSAGE_PRESENT
    assert decision.outcome is Outcome.VERIFIED


def test_strict_verify_grades_an_ambiguous_quotation_as_a_finding_not_a_defect(tmp_path, capsys):
    from repro.cli import main

    _quoted(tmp_path, 2)

    main(["verify", str(tmp_path / "repro.yaml"), "--policy", "strict"])

    out = capsys.readouterr().out
    assert "KeyError" not in out
    assert "evidence.error" not in out
    assert "evidence.not_found" in out


# --- a claim the policy grades an error does not render as a note -------------------------------


def test_a_claim_with_no_evidence_renders_at_the_level_the_policy_gives_it(tmp_path):
    from repro.policy import PUBLICATION
    from repro.renderers.sarif import to_sarif

    (tmp_path / "results.json").write_text('{"x": 1}\n')
    (tmp_path / "repro.yaml").write_text(NO_EVIDENCE)
    report = verify(load(tmp_path / "repro.yaml"))

    sarif = to_sarif(report, PUBLICATION.assess(report))

    levels = {r["ruleId"]: r["level"] for r in sarif["runs"][0]["results"]}
    assert levels["repro/not_offered"] == "error"


def test_without_a_policy_the_same_claim_stays_a_note(tmp_path):
    from repro.renderers.sarif import to_sarif

    (tmp_path / "results.json").write_text('{"x": 1}\n')
    (tmp_path / "repro.yaml").write_text(NO_EVIDENCE)
    report = verify(load(tmp_path / "repro.yaml"))

    sarif = to_sarif(report)

    levels = {r["ruleId"]: r["level"] for r in sarif["runs"][0]["results"]}
    assert levels["repro/not_offered"] == "note"
