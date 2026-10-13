"""Conditions an audit found the engine reporting wrongly.

Each test here corresponds to a case where the tool said something false: a check that passed
when the evidence did not support it, or a defect in the tooling emitted as a finding about a
manuscript. Those are worse than ordinary bugs, because the whole claim of the package is that
its report can be trusted where a reader cannot check by hand.
"""

from __future__ import annotations

import decimal
import json
import pathlib
import shutil

import citations.cli
import pytest
from pydantic import ValidationError
from repro import cli
from repro.models import (
    ArrayLocator,
    ArtifactRef,
    Claim,
    Digest,
    Freshness,
    Manifest,
    MetricEvidence,
    NotEstablishedKind,
    NumberRule,
    Outcome,
    Reason,
    RegistrationAuthority,
    StaleCause,
    Standing,
    TableLocator,
    TreeLocator,
    Validity,
    ValueEvidence,
    Warning_,
)
from repro.policy import EXPLORATORY, PUBLICATION, STRICT
from repro.verify import _QUOTE_WARNINGS, compare_decimal, verify


def metric(reported="1", pointer="/x", artifact="a") -> MetricEvidence:
    return MetricEvidence(artifact=artifact, name="m", reported=reported, pointer=pointer)


def one(path, locator, reported="0.91"):
    """The single decision from a one-claim manifest over one artifact."""
    manifest = Manifest(
        project="p",
        artifacts=(ArtifactRef(id="a", path=path, digest=Digest.of_file(path)),),
        claims=(
            Claim(
                id="c",
                text="t",
                evidence=(
                    ValueEvidence(artifact="a", name="m", reported=reported, locator=locator),
                ),
            ),
        ),
    )
    return verify(manifest).claims[0].decisions[0]


# -- one id names one thing -----------------------------------------------------------------


def test_two_artifacts_may_not_share_an_id(tmp_path):
    """The engine keys state by id, so a duplicate kept the last declaration and dropped the
    rest -- including a broken pin, which then vanished from the report and left strict
    passing with no violations at all."""
    real, decoy = tmp_path / "real.json", tmp_path / "decoy.json"
    real.write_text('{"x": 1}')
    decoy.write_text('{"x": 1}')
    with pytest.raises(ValidationError, match="duplicate artifact id"):
        Manifest(
            project="p",
            artifacts=(
                ArtifactRef(
                    id="results", path=real, digest=Digest(algorithm="sha256", value="0" * 64)
                ),
                ArtifactRef(id="results", path=decoy, digest=Digest.of_file(decoy)),
            ),
        )


def test_two_claims_may_not_share_an_id():
    with pytest.raises(ValidationError, match="duplicate claim id"):
        Manifest(project="p", claims=(Claim(id="c", text="one"), Claim(id="c", text="two")))


# -- arithmetic is not a scientific finding -------------------------------------------------


def test_identical_values_agree_however_many_digits_they_carry():
    """`quantize` raises when the result exceeds the context precision, which two identical
    thirty-digit integers do. That was reported as a manuscript contradicted by its own data."""
    huge = "123456789012345678901234567890"
    assert compare_decimal(decimal.Decimal(huge), metric(reported=huge)) is True


def test_an_end_to_end_comparison_of_identical_long_values_verifies(tmp_path):
    path = tmp_path / "r.json"
    path.write_text(json.dumps({"n": 123456789012345678901234567890}))
    assert (
        one(path, TreeLocator(pointer="/n"), "123456789012345678901234567890").outcome
        is Outcome.VERIFIED
    )


def test_values_that_truly_differ_by_orders_of_magnitude_still_disagree():
    assert compare_decimal(decimal.Decimal("1E+30"), metric(reported="3.20")) is False


# -- one unreadable path must not suppress the report ---------------------------------------


def test_a_directory_where_a_file_was_declared_is_reported_not_raised(tmp_path):
    """`Digest.of_file` raised, and `verify()` had no guard, so a single bad path threw away
    the result for every other claim in the manifest."""
    directory = tmp_path / "adir"
    directory.mkdir()
    good = tmp_path / "ok.json"
    good.write_text('{"x": 1}')
    manifest = Manifest(
        project="p",
        artifacts=(
            ArtifactRef(
                id="bad", path=directory, digest=Digest(algorithm="sha256", value="0" * 64)
            ),
            ArtifactRef(id="good", path=good, digest=Digest.of_file(good)),
        ),
        claims=(
            Claim(id="c1", text="t", evidence=(metric(artifact="bad"),)),
            Claim(id="c2", text="t", evidence=(metric(artifact="good"),)),
        ),
    )
    report = verify(manifest)
    states = {a.artifact_id: a for a in report.artifacts}
    assert states["bad"].validity is Validity.ARTIFACT_ABSENT
    assert "cannot be read" in states["bad"].detail
    assert report.claims[1].decisions[0].outcome is Outcome.VERIFIED
    assert STRICT.assess(report).passed is False


# -- an assertion that fails must not report as verified ------------------------------------


PAGES = {1: "an unrelated opening paragraph\n", 2: "the effect was large\n"}


@pytest.fixture
def paginated(monkeypatch, tmp_path):
    """A source whose pages are addressable, without depending on `pdftotext` being installed.

    The earlier version of this test used a `.txt` source, for which `citations` treats the
    page number as meaningless and never examines it -- so the wrong-page branch it was
    written to guard was never reached, and the test accepted either outcome.
    """
    V = pytest.importorskip("citations.verify")
    source = tmp_path / "s.pdf"
    source.write_bytes(b"%PDF-1.4 stand-in; the extractor is stubbed")

    def extract(artifact, page=None):
        return "".join(PAGES.values()) if page is None else PAGES.get(page, "")

    monkeypatch.setattr(V, "extract", extract)
    return source


def quote_manifest(source, page: int | None):
    return Manifest(
        project="p",
        artifacts=(ArtifactRef(id="s", path=source, digest=Digest.of_file(source)),),
        claims=(
            Claim(
                id="c",
                text="t",
                evidence=(
                    {
                        "kind": "quote",
                        "artifact": "s",
                        "text": "the effect was large",
                        "page": page,
                    },
                ),
            ),
        ),
    )


def test_a_passage_on_the_wrong_page_is_a_mismatch(paginated):
    """`page` is documented as verified when present. Reporting `match` with a warning left
    the assertion unenforceable, since no policy reads decision warnings."""
    decision = verify(quote_manifest(paginated, page=7)).claims[0].decisions[0]
    assert decision.reason is Reason.WRONG_PAGE
    assert decision.outcome is Outcome.MISMATCH
    assert Warning_.WRONG_PAGE in decision.warnings
    assert "not on page 7" in decision.detail


def test_the_page_the_passage_is_actually_on_verifies(paginated):
    # The control: the quote and the document are identical in both tests, so the page number
    # is the only thing that moves the outcome.
    decision = verify(quote_manifest(paginated, page=2)).claims[0].decisions[0]
    assert decision.outcome is Outcome.VERIFIED
    assert Warning_.WRONG_PAGE not in decision.warnings


def _page_on_a_text_source(tmp_path, page: int | None):
    source = tmp_path / "s.txt"
    source.write_text("an unrelated opening paragraph\nthe effect was large\n")
    manifest = quote_manifest(source, page=page)
    return verify(manifest)


def test_a_page_declared_on_a_source_with_no_pages_is_verified_and_says_it_was_not_checked(
    tmp_path,
):
    decision = _page_on_a_text_source(tmp_path, page=9999).claims[0].decisions[0]
    assert decision.outcome is Outcome.VERIFIED
    assert decision.reason is Reason.PASSAGE_PRESENT
    assert Warning_.PAGE_UNCHECKED in decision.warnings
    assert "page 9999 was not checked" in decision.detail


@pytest.mark.skipif(shutil.which("detex") is None, reason="detex is not installed")
@pytest.mark.parametrize("page", [1, 9999])
def test_a_page_declared_on_a_latex_source_is_not_checked_and_never_a_wrong_page(tmp_path, page):
    source = tmp_path / "s.tex"
    source.write_text(
        "\\documentclass{article}\\begin{document}\nthe effect was large\n\\end{document}\n"
    )
    decision = verify(quote_manifest(source, page=page)).claims[0].decisions[0]
    assert decision.outcome is Outcome.VERIFIED
    assert decision.reason is Reason.PASSAGE_PRESENT
    assert Warning_.PAGE_UNCHECKED in decision.warnings
    assert Warning_.WRONG_PAGE not in decision.warnings


def test_a_passage_that_is_absent_carries_no_warning_about_its_page(tmp_path):
    source = tmp_path / "s.txt"
    source.write_text("an unrelated opening paragraph\n")
    report = verify(quote_manifest(source, page=3))
    decision = report.claims[0].decisions[0]
    assert decision.outcome is Outcome.MISMATCH
    assert Warning_.PAGE_UNCHECKED not in decision.warnings
    assert not [v for v in STRICT.assess(report).violations if v.rule == "evidence.page_unchecked"]


def test_a_quote_declaring_no_page_carries_no_page_warning(tmp_path):
    decision = _page_on_a_text_source(tmp_path, page=None).claims[0].decisions[0]
    assert decision.outcome is Outcome.VERIFIED
    assert Warning_.PAGE_UNCHECKED not in decision.warnings
    assert decision.detail == ""


def test_a_page_that_was_checked_carries_no_page_unchecked_warning(paginated):
    for page in (2, 7):
        decision = verify(quote_manifest(paginated, page=page)).claims[0].decisions[0]
        assert Warning_.PAGE_UNCHECKED not in decision.warnings


def test_a_passage_matched_only_with_spacing_ignored_says_its_page_was_not_checked(
    monkeypatch, tmp_path
):
    V = pytest.importorskip("citations.verify")
    source = tmp_path / "s.pdf"
    source.write_bytes(b"%PDF-1.4 stand-in; the extractor is stubbed")
    monkeypatch.setattr(V, "extract", lambda artifact, page=None: "the effectwas large\n")

    decision = verify(quote_manifest(source, page=7)).claims[0].decisions[0]

    assert decision.outcome is Outcome.VERIFIED
    assert Warning_.NORMALIZED in decision.warnings
    assert Warning_.PAGE_UNCHECKED in decision.warnings
    assert "spacing ignored" in decision.detail


@pytest.mark.parametrize(
    ("policy", "severity", "passed"),
    [(EXPLORATORY, "warning", True), (PUBLICATION, "warning", True), (STRICT, "error", False)],
    ids=lambda v: getattr(v, "name", None),
)
def test_an_unchecked_page_is_graded_as_the_policy_grades_an_unchecked_assertion(
    tmp_path, policy, severity, passed
):
    assessment = policy.assess(_page_on_a_text_source(tmp_path, page=3))
    found = [v for v in assessment.violations if v.rule == "evidence.page_unchecked"]
    assert [v.severity.value for v in found] == [severity]
    assert found[0].subject == "c/quote"
    assert assessment.passed is passed


def test_a_quote_with_no_page_raises_no_page_violation_under_strict(tmp_path):
    assessment = STRICT.assess(_page_on_a_text_source(tmp_path, page=None))
    assert assessment.violations == ()
    assert assessment.passed


def test_verify_prints_the_unchecked_page_beside_the_verified_passage(tmp_path, capsys):
    source = tmp_path / "s.txt"
    source.write_text("the effect was large\n")
    (tmp_path / "repro.yaml").write_text(
        "project: p\nartifacts:\n  - id: s\n    path: s.txt\nclaims:\n  - id: c\n    text: t\n"
        "    evidence:\n      - kind: quote\n        artifact: s\n"
        "        text: the effect was large\n        page: 3\n"
    )

    code = cli.main(["verify", str(tmp_path / "repro.yaml"), "--policy", "strict"])

    out = capsys.readouterr().out
    assert "page 3 was not checked" in out
    assert "[short,page_unchecked]" in out
    assert "evidence.page_unchecked" in out
    assert code == 1


def test_every_warning_citations_can_put_on_a_result_is_mapped():
    assert set(_QUOTE_WARNINGS) == set(citations.cli.WARNINGS)


SPEC = (pathlib.Path(__file__).resolve().parents[3] / "docs" / "SPEC.md").read_text()


@pytest.mark.parametrize("value", [*Reason, *Warning_], ids=lambda v: f"{type(v).__name__}.{v}")
def test_the_specification_names_every_reason_and_every_warning(value):
    assert f"| `{value.value}` |" in SPEC


@pytest.mark.parametrize(
    "value",
    [
        *Freshness,
        *StaleCause,
        *NotEstablishedKind,
        *Standing,
        *NumberRule,
        *RegistrationAuthority,
    ],
    ids=lambda v: f"{type(v).__name__}.{v}",
)
def test_the_specification_names_every_state_cause_kind_standing_rule_and_authority(value):
    assert f"| `{value.value}` |" in SPEC


def test_a_wrong_page_fails_publication_rather_than_passing_with_a_warning(paginated):
    assessment = PUBLICATION.assess(verify(quote_manifest(paginated, page=7)))
    assert assessment.passed is False
    assert any(v.rule == "evidence.mismatch" for v in assessment.errors)


# -- exactly one scalar, for columns and keys as well as rows -------------------------------


def test_a_repeated_column_name_is_a_broken_selector(tmp_path):
    """`csv.DictReader` keeps the last field of a repeated header, so the other column is
    unreachable and the value silently resolved to whichever came last."""
    path = tmp_path / "t.csv"
    path.write_text("model,auc,auc\nLASSO-Cox,0.62,0.91\n")
    decision = one(path, TableLocator(column="auc", where={"model": "LASSO-Cox"}))
    assert decision.reason is Reason.ROW_SELECTOR_INVALID
    assert "repeats the column name" in decision.detail


def test_a_repeated_predicate_column_does_not_blame_the_table(tmp_path):
    """It reported `no row where model='A'` for a row that is plainly there."""
    path = tmp_path / "t.csv"
    path.write_text("model,model,auc\nA,B,0.5\n")
    decision = one(path, TableLocator(column="auc", where={"model": "A"}), "0.5")
    assert decision.reason is Reason.ROW_SELECTOR_INVALID
    assert decision.reason is not Reason.ROW_ABSENT


def test_duplicate_json_keys_are_refused_as_yaml_already_was(tmp_path):
    """One artifact holding two values for one quantity is the finding this repository's own
    regression corpus records against someone else's paper."""
    path = tmp_path / "r.json"
    path.write_text('{"accuracy": 0.91, "accuracy": 0.62}')
    decision = one(path, TreeLocator(pointer="/accuracy"))
    assert decision.outcome is Outcome.UNCHECKED
    assert decision.reason is Reason.ARTIFACT_UNREADABLE
    assert "duplicate key" in decision.detail


@pytest.mark.parametrize("index", [(-1,), (-99,)])
def test_a_negative_array_index_is_not_an_address(tmp_path, index):
    """`-1` silently resolved to the last element and `-99` escaped as a backend defect."""
    numpy = pytest.importorskip("numpy")
    path = tmp_path / "a.npy"
    numpy.save(path, numpy.array([1.0, 2.0, 3.0, 4.0, 5.0]))
    decision = one(path, ArrayLocator(index=index), "5.0")
    assert decision.reason is Reason.ROW_SELECTOR_INVALID
    assert decision.outcome is not Outcome.VERIFIED
