"""Conditions an audit found the engine reporting wrongly.

Each test here corresponds to a case where the tool said something false: a check that passed
when the evidence did not support it, or a defect in the tooling emitted as a finding about a
manuscript. Those are worse than ordinary bugs, because the whole claim of the package is that
its report can be trusted where a reader cannot check by hand.
"""

from __future__ import annotations

import decimal
import json

import pytest
from pydantic import ValidationError
from repro.models import (
    ArrayLocator,
    ArtifactRef,
    Claim,
    Digest,
    Manifest,
    MetricEvidence,
    Outcome,
    Reason,
    TableLocator,
    TreeLocator,
    Validity,
    ValueEvidence,
    Warning_,
)
from repro.policy import PUBLICATION, STRICT
from repro.verify import compare_decimal, verify


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


def quote_manifest(source, page: int):
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
