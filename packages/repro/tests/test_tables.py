"""Addressing a cell in a delimited table.

Most published result artifacts are tables rather than JSON, so this is the variant a
manuscript's own tables need.
"""
from __future__ import annotations

import pytest
from repro import Claim, TableCellEvidence, read_table
from repro.exceptions import ArtifactUnreadableError
from repro.resolve import sniff_delimiter
from repro.verify import TableBackend

TABLE = """model,accuracy,n,note
LASSO-Cox,0.6478999999999999,120,baseline
CoxMLP,0.641,120,
VAECox,0.648,118,frozen encoder
CoxMLP,0.700,64,second run
"""


@pytest.fixture
def table(tmp_path):
    p = tmp_path / "results.csv"
    p.write_text(TABLE)
    return p


def check(table, **kw):
    ev = TableCellEvidence(artifact="t", name="metric", **kw)
    return TableBackend().check(Claim(id="c", text="t"), ev, table)


def test_a_cell_selected_by_key_column(table):
    d = check(table, reported="0.648", column="accuracy", where={"model": "VAECox"})
    assert d.outcome.value == "verified"


def test_printed_precision_absorbs_a_float_artifact(table):
    # The stored value is 0.6478999999999999; a manuscript printing three decimals is not
    # contradicted by the sixteen a float round-trip produced.
    d = check(table, reported="0.648", column="accuracy", where={"model": "LASSO-Cox"})
    assert d.outcome.value == "verified"


def test_more_precision_than_printed_still_has_to_agree(table):
    d = check(table, reported="0.64790", column="accuracy", where={"model": "LASSO-Cox"})
    assert d.outcome.value == "verified"
    d = check(table, reported="0.64780", column="accuracy", where={"model": "LASSO-Cox"})
    assert d.outcome.value == "mismatch"


def test_a_value_that_disagrees(table):
    d = check(table, reported="0.900", column="accuracy", where={"model": "VAECox"})
    assert d.outcome.value == "mismatch"


def test_a_column_that_is_not_there_names_the_ones_that_are(table):
    d = check(table, reported="1", column="f1", where={"model": "VAECox"})
    assert d.outcome.value == "not_found"
    assert d.reason.value == "column_absent"
    assert "accuracy" in d.detail


def test_a_row_that_is_not_there(table):
    d = check(table, reported="1", column="accuracy", where={"model": "Nope"})
    assert d.outcome.value == "not_found"
    assert d.reason.value == "row_absent"


def test_a_selector_matching_two_rows_is_reported_not_resolved(table):
    # Taking the first would make the answer depend on row order, which is what a selector
    # exists to avoid.
    d = check(table, reported="0.641", column="accuracy", where={"model": "CoxMLP"})
    assert d.outcome.value == "not_found"
    assert d.reason.value == "row_ambiguous"
    assert "2 rows" in d.detail


def test_a_second_key_disambiguates(table):
    d = check(table, reported="0.641", column="accuracy", where={"model": "CoxMLP", "n": "120"})
    assert d.outcome.value == "verified"


def test_a_row_index_addresses_a_data_row_not_the_header(table):
    d = check(table, reported="0.648", column="accuracy", row=2)
    assert d.outcome.value == "verified", d.detail


def test_an_out_of_range_row_index(table):
    d = check(table, reported="0.648", column="accuracy", row=99)
    assert d.reason.value == "row_absent"


def test_exactly_one_row_selector_is_required(table):
    both = check(table, reported="0.648", column="accuracy", row=2, where={"model": "VAECox"})
    assert both.reason.value == "row_selector_invalid"
    neither = check(table, reported="0.648", column="accuracy")
    assert neither.reason.value == "row_selector_invalid"


def test_a_cell_that_is_not_a_number(table):
    d = check(table, reported="1", column="note", where={"model": "VAECox"})
    assert d.reason.value == "value_not_numeric"


def test_an_empty_cell_is_not_a_number(table):
    d = check(table, reported="1", column="note", where={"model": "CoxMLP", "n": "120"})
    assert d.reason.value == "value_not_numeric"


def test_a_file_with_no_header_is_unreadable(tmp_path):
    p = tmp_path / "empty.csv"
    p.write_text("")
    with pytest.raises(ArtifactUnreadableError):
        read_table(p)


def test_a_tsv_is_read_as_tabs_even_when_a_field_contains_commas(tmp_path):
    # Sniffing the header would count the commas and split every row in the wrong place.
    p = tmp_path / "results.tsv"
    p.write_text("model\tnote\tvalue\nA\tone, two, three\t0.5\n")
    header, rows = read_table(p)
    assert header == ["model", "note", "value"]
    assert rows[0]["note"] == "one, two, three"
    assert sniff_delimiter(p, p.read_text()) == "\t"
