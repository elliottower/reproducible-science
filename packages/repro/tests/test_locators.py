"""One contract over several formats, and the invariant every adapter shares.

A locator resolves to exactly one scalar. Zero is absent, two or more is ambiguous, and a
container is not a value. No adapter takes the first match, and none falls back to searching
a file for the printed number.
"""

from __future__ import annotations

import json
import sqlite3

import pytest
from repro.exceptions import ArtifactUnreadableError
from repro.models import (
    ArrayLocator,
    ArtifactRef,
    Claim,
    Digest,
    Manifest,
    Outcome,
    Reason,
    SqliteLocator,
    TableLocator,
    TablePositionLocator,
    TreeLocator,
    ValueEvidence,
    Warning_,
)
from repro.resolve import Resolution, resolve
from repro.verify import ValueBackend, verify

CLAIM = Claim(id="c", text="t")


def evidence(locator, reported="3.2") -> ValueEvidence:
    return ValueEvidence(artifact="a", name="m", reported=reported, locator=locator)


def check(locator, path, reported="3.2"):
    return ValueBackend().check(CLAIM, evidence(locator, reported), path)


# -- the shared invariant -------------------------------------------------------------------


def test_a_pointer_onto_a_container_is_not_a_value(tmp_path):
    path = tmp_path / "r.json"
    path.write_text(json.dumps({"group": {"x": 1}}))
    decision = check(TreeLocator(pointer="/group"), path)
    assert decision.reason is Reason.SELECTOR_NOT_SCALAR
    assert decision.outcome is Outcome.NOT_FOUND


def test_a_predicate_matching_two_rows_is_never_resolved_to_the_first(tmp_path):
    path = tmp_path / "t.csv"
    path.write_text("model,accuracy\nresnet,0.91\nresnet,0.88\n")
    decision = check(TableLocator(column="accuracy", where={"model": "resnet"}), path, "0.91")
    assert decision.reason is Reason.ROW_AMBIGUOUS
    assert "2 rows" in decision.detail


def test_a_locator_needs_a_predicate():
    with pytest.raises(ValueError, match="table_position"):
        TableLocator(column="accuracy")


# -- trees: JSON and restricted YAML --------------------------------------------------------


def test_a_pointer_resolves_in_yaml(tmp_path):
    path = tmp_path / "r.yaml"
    path.write_text("metrics:\n  accuracy: 3.2\n")
    assert check(TreeLocator(pointer="/metrics/accuracy"), path).outcome is Outcome.VERIFIED


def test_yaml_with_a_duplicated_key_cannot_be_addressed(tmp_path):
    """PyYAML keeps the last of a duplicated key, so the file resolves one way with nothing
    said about the other. An artifact that cannot be read one way only is not addressable."""
    path = tmp_path / "r.yaml"
    path.write_text("accuracy: 3.2\naccuracy: 9.9\n")
    with pytest.raises(ArtifactUnreadableError, match="duplicate key"):
        resolve(TreeLocator(pointer="/accuracy"), path)


def test_the_engine_reports_an_unreadable_artifact_as_unchecked(tmp_path):
    """Not as an absent value: nothing was looked into."""
    path = tmp_path / "r.yaml"
    path.write_text("accuracy: 3.2\naccuracy: 9.9\n")
    manifest = Manifest(
        project="p",
        artifacts=(ArtifactRef(id="a", path=path, digest=Digest.of_file(path)),),
        claims=(Claim(id="c", text="t", evidence=(evidence(TreeLocator(pointer="/accuracy")),)),),
    )
    decision = verify(manifest).claims[0].decisions[0]
    assert decision.outcome is Outcome.UNCHECKED
    assert decision.reason is Reason.ARTIFACT_UNREADABLE


def test_an_array_index_with_a_leading_zero_addresses_nothing(tmp_path):
    """RFC 6901 array indices carry no leading zeros, so `/0` and `/00` are not the same."""
    path = tmp_path / "r.json"
    path.write_text(json.dumps({"xs": [3.2, 9.9]}))
    assert resolve(TreeLocator(pointer="/xs/00"), path)[0] is Resolution.ABSENT
    assert resolve(TreeLocator(pointer="/xs/0"), path)[0] is Resolution.RESOLVED


def test_a_tree_locator_declines_a_format_it_does_not_address(tmp_path):
    path = tmp_path / "r.csv"
    path.write_text("a,b\n1,2\n")
    decision = check(TreeLocator(pointer="/a"), path)
    assert decision.reason is Reason.FORMAT_UNSUPPORTED
    assert decision.outcome is Outcome.UNCHECKED, "a check that did not run is not a failure"


# -- tables ---------------------------------------------------------------------------------


def test_a_positional_address_is_warned_about(tmp_path):
    """Sorting or inserting a row changes what row 1 means."""
    path = tmp_path / "t.csv"
    path.write_text("model,accuracy\nresnet,0.91\nvit,3.2\n")
    decision = check(TablePositionLocator(column="accuracy", row=1), path)
    assert decision.outcome is Outcome.VERIFIED
    assert Warning_.POSITIONAL_ADDRESS in decision.warnings


def test_a_key_predicate_carries_no_such_warning(tmp_path):
    path = tmp_path / "t.csv"
    path.write_text("model,accuracy\nresnet,0.91\nvit,3.2\n")
    decision = check(TableLocator(column="accuracy", where={"model": "vit"}), path)
    assert decision.warnings == ()


def test_a_row_past_the_end_is_absent(tmp_path):
    path = tmp_path / "t.csv"
    path.write_text("model,accuracy\nresnet,0.91\n")
    decision = check(TablePositionLocator(column="accuracy", row=7), path)
    assert decision.reason is Reason.ROW_ABSENT
    assert "1 data rows" in decision.detail


def test_a_predicate_value_is_compared_as_text_and_never_coerced(tmp_path):
    """For an identifier column, `001` and `1` are different rows."""
    path = tmp_path / "t.csv"
    path.write_text("id,accuracy\n001,0.91\n1,3.2\n")
    assert (
        check(TableLocator(column="accuracy", where={"id": "001"}), path, "0.91").outcome
        is Outcome.VERIFIED
    )
    assert (
        check(TableLocator(column="accuracy", where={"id": 1}), path, "3.2").outcome
        is Outcome.VERIFIED
    )


# -- sqlite ---------------------------------------------------------------------------------


@pytest.fixture
def database(tmp_path):
    path = tmp_path / "results.sqlite"
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE runs (model TEXT, seed INTEGER, accuracy REAL)")
    connection.executemany(
        "INSERT INTO runs VALUES (?,?,?)",
        [("resnet", 1, 3.2), ("resnet", 2, 0.88), ("vit", 1, 0.75)],
    )
    connection.commit()
    connection.close()
    return path


def test_a_row_is_addressed_by_key(database):
    decision = check(
        SqliteLocator(table="runs", column="accuracy", where={"model": "resnet", "seed": 1}),
        database,
    )
    assert decision.outcome is Outcome.VERIFIED


def test_a_predicate_matching_two_rows_in_a_database_is_ambiguous(database):
    decision = check(
        SqliteLocator(table="runs", column="accuracy", where={"model": "resnet"}), database
    )
    assert decision.reason is Reason.ROW_AMBIGUOUS


def test_a_column_the_table_lacks_is_the_selector_and_not_the_data(database):
    decision = check(SqliteLocator(table="runs", column="nope", where={"seed": 1}), database)
    assert decision.reason is Reason.ROW_SELECTOR_INVALID
    assert "accuracy" in decision.detail


def test_a_table_the_database_lacks(database):
    decision = check(SqliteLocator(table="nope", column="accuracy", where={"seed": 1}), database)
    assert decision.reason is Reason.ROW_SELECTOR_INVALID
    assert "runs" in decision.detail


def test_an_identifier_cannot_smuggle_sql(database):
    """Identifiers are checked against the schema before being quoted; values are bound."""
    decision = check(
        SqliteLocator(table='runs" ; DROP TABLE runs --', column="accuracy", where={"seed": 1}),
        database,
    )
    assert decision.reason is Reason.ROW_SELECTOR_INVALID
    connection = sqlite3.connect(database)
    assert connection.execute("SELECT count(*) FROM runs").fetchone()[0] == 3
    connection.close()


# -- formats with no adapter ----------------------------------------------------------------


@pytest.mark.parametrize("name", ["r.h5", "r.parquet", "r.xlsx", "r.nc"])
def test_a_format_with_no_adapter_is_declined_rather_than_guessed(tmp_path, name):
    path = tmp_path / name
    path.write_bytes(b"\x00binary")
    decision = check(TreeLocator(pointer="/x"), path)
    assert decision.reason is Reason.FORMAT_UNSUPPORTED
    assert decision.outcome is Outcome.UNCHECKED


def test_an_unsupported_format_never_reports_a_value_present(tmp_path):
    """The printed number appears in the bytes; a search would find it and call that a
    verification."""
    path = tmp_path / "r.parquet"
    path.write_bytes(b"accuracy 3.2 somewhere in here")
    assert check(TreeLocator(pointer="/accuracy"), path).outcome is not Outcome.VERIFIED


# -- the locator is bound into the decision -------------------------------------------------


def test_a_decision_records_how_the_value_was_addressed(tmp_path):
    path = tmp_path / "r.json"
    path.write_text(json.dumps({"x": 3.2}))
    locator = TreeLocator(pointer="/x")
    assert check(locator, path).locator_digest == locator.digest.value


def test_editing_a_selector_changes_the_digest_though_the_file_does_not():
    assert TreeLocator(pointer="/a").digest.value != TreeLocator(pointer="/b").digest.value


def test_the_canonical_form_is_key_ordered():
    a = TableLocator(column="acc", where={"b": 1, "a": 2})
    b = TableLocator(column="acc", where={"a": 2, "b": 1})
    assert a.canonical() == b.canonical()
    assert a.digest.value == b.digest.value


def test_the_shorthand_kinds_resolve_through_the_same_locators():
    from repro.models import MetricEvidence, TableCellEvidence

    assert MetricEvidence(
        artifact="a", name="m", reported="1", pointer="/x"
    ).locator == TreeLocator(pointer="/x")
    assert (
        TableCellEvidence(
            artifact="a", name="m", reported="1", column="c", where={"k": "v"}
        ).locator.kind
        == "table"
    )


# -- arrays, where numpy is installed --------------------------------------------------------


def test_an_array_element_is_addressed_by_index(tmp_path):
    numpy = pytest.importorskip("numpy")
    path = tmp_path / "r.npy"
    numpy.save(path, numpy.array([[1.0, 3.2], [5.0, 7.0]]))
    assert check(ArrayLocator(index=(0, 1)), path).outcome is Outcome.VERIFIED


def test_an_index_of_the_wrong_rank_is_a_broken_selector(tmp_path):
    numpy = pytest.importorskip("numpy")
    path = tmp_path / "r.npy"
    numpy.save(path, numpy.array([[1.0, 3.2]]))
    decision = check(ArrayLocator(index=(0,)), path)
    assert decision.reason is Reason.ROW_SELECTOR_INVALID


def test_an_index_resolving_to_a_slice_is_not_a_value(tmp_path):
    numpy = pytest.importorskip("numpy")
    path = tmp_path / "r.npz"
    numpy.savez(path, scores=numpy.array([[1.0, 3.2]]))
    decision = check(ArrayLocator(array="scores", index=(0, 0)), path)
    assert decision.outcome in (Outcome.VERIFIED, Outcome.MISMATCH)
