"""Workbooks, columnar files, and hierarchical arrays, under the invariant every adapter shares.

Each format's reader is an optional extra. The tests that need a reader build their fixture
with it and skip without it; the tests of what happens when a reader is missing need none,
and run everywhere.
"""

from __future__ import annotations

import pytest
from repro.adapters import array as array_adapter
from repro.adapters import columnar, sheet
from repro.models import (
    ArrayLocator,
    ArtifactRef,
    Claim,
    Digest,
    Manifest,
    Outcome,
    Reason,
    SheetLocator,
    TableLocator,
    TablePositionLocator,
    ValueEvidence,
    Warning_,
)
from repro.resolve import Resolution, resolve
from repro.verify import ValueBackend, verify

CLAIM = Claim(id="c", text="t")


def check(locator, path, reported="3.2"):
    ev = ValueEvidence(artifact="a", name="m", reported=reported, locator=locator)
    return ValueBackend().check(CLAIM, ev, {ev.artifact: path})


def engine(locator, path, reported="3.2"):
    """Through `verify`, which is where an exception from a reader becomes an outcome."""
    ev = ValueEvidence(artifact="a", name="m", reported=reported, locator=locator)
    manifest = Manifest(
        project="p",
        artifacts=(ArtifactRef(id="a", path=path, digest=Digest.of_file(path)),),
        claims=(Claim(id="c", text="t", evidence=(ev,)),),
    )
    return verify(manifest).claims[0].decisions[0]


def corrupt(tmp_path, name):
    path = tmp_path / name
    # The printed number is in the bytes, so a reader that fell back to searching would find it.
    path.write_bytes(b"\x00this is not what the suffix says; accuracy 3.2")
    return path


# -- a reader that is not installed ---------------------------------------------------------


@pytest.mark.parametrize(
    "module,attribute,name,locator,extra",
    [
        (sheet, "openpyxl", "r.xlsx", SheetLocator(column="acc", where={"m": "a"}), "sheets"),
        (sheet, "xlrd", "r.xls", SheetLocator(column="acc", where={"m": "a"}), "sheets"),
        (columnar, "pyarrow", "r.parquet", TableLocator(column="acc", where={"m": "a"}), "parquet"),
        (columnar, "pyarrow", "r.feather", TableLocator(column="acc", where={"m": "a"}), "parquet"),
        (
            columnar,
            "pyreadstat",
            "r.dta",
            TableLocator(column="acc", where={"m": "a"}),
            "stata-spss",
        ),
        (
            columnar,
            "pyreadstat",
            "r.sav",
            TableLocator(column="acc", where={"m": "a"}),
            "stata-spss",
        ),
        (columnar, "rdata", "r.rds", TableLocator(column="acc", where={"m": "a"}), "rds"),
        (array_adapter, "h5py", "r.h5", ArrayLocator(array="x", index=(0,)), "hdf5"),
        (array_adapter, "netCDF4", "r.nc", ArrayLocator(array="x", index=(0,)), "netcdf"),
    ],
)
def test_a_missing_reader_is_unchecked_and_names_its_extra(
    tmp_path, monkeypatch, module, attribute, name, locator, extra
):
    """Not a pass, not an error, and not a finding about the file: nothing read it."""
    monkeypatch.setattr(module, attribute, None)
    decision = engine(locator, corrupt(tmp_path, name))
    assert decision.outcome is Outcome.UNCHECKED
    assert decision.reason is Reason.EXTRACTOR_MISSING
    assert f"reproducible-science[{extra}]" in decision.detail


@pytest.mark.parametrize("name", ["r.pkl", "r.pickle", "r.joblib", "r.pt"])
def test_a_pickle_is_never_opened(tmp_path, name):
    decision = check(TableLocator(column="acc", where={"m": "a"}), corrupt(tmp_path, name))
    assert decision.outcome is Outcome.UNCHECKED
    assert decision.reason is Reason.FORMAT_UNSUPPORTED
    assert "runs" in decision.detail


# -- workbooks ------------------------------------------------------------------------------


@pytest.fixture
def workbook(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    book = openpyxl.Workbook()
    main = book.active
    main.title = "main"
    for row in [
        ("model", "seed", "accuracy", None),
        ("resnet", 1, 0.91, None),
        ("resnet", 2.0, 3.2, None),
        ("vit", 1, 0.75, None),
        ("vit", 1, 0.77, None),
        ("pending", 1, None, None),
    ]:
        main.append(row)
    # Same columns, different numbers: a reader that ignored `sheet` would answer from `main`.
    other = book.create_sheet("ablation")
    for row in [("model", "seed", "accuracy"), ("resnet", 2, 0.5)]:
        other.append(row)
    formulas = book.create_sheet("formulas")
    formulas.append(("model", "accuracy"))
    # openpyxl writes a formula and computes nothing, so the file holds no value for it.
    formulas.append(("mean", "=AVERAGE(main!C2:C3)"))
    path = tmp_path / "results.xlsx"
    book.save(path)
    return path


def test_a_cell_is_addressed_by_sheet_column_and_key(workbook):
    locator = SheetLocator(sheet="main", column="accuracy", where={"model": "resnet", "seed": 2})
    assert check(locator, workbook, "3.2").outcome is Outcome.VERIFIED
    assert check(locator, workbook, "3.3").outcome is Outcome.MISMATCH


def test_the_sheet_named_is_the_sheet_read(workbook):
    locator = SheetLocator(sheet="ablation", column="accuracy", where={"model": "resnet"})
    assert check(locator, workbook, "0.5").outcome is Outcome.VERIFIED
    assert check(locator, workbook, "3.2").outcome is Outcome.MISMATCH


def test_repeated_keys_in_a_sheet_are_ambiguous_rather_than_the_first(workbook):
    decision = check(
        SheetLocator(sheet="main", column="accuracy", where={"model": "vit"}), workbook, "0.75"
    )
    assert decision.reason is Reason.ROW_AMBIGUOUS
    assert "2 rows" in decision.detail


def test_a_numeric_key_matches_the_number_stored_as_a_float(workbook):
    # The workbook stores seed 2 as 2.0. `where: {seed: 2}` has to select it, and must not
    # select the row whose seed is 1.
    decision = check(
        SheetLocator(sheet="main", column="accuracy", where={"model": "resnet", "seed": 2}),
        workbook,
    )
    assert decision.outcome is Outcome.VERIFIED


def test_a_workbook_with_several_sheets_needs_one_named(workbook):
    decision = check(SheetLocator(column="accuracy", where={"model": "resnet"}), workbook)
    assert decision.reason is Reason.ROW_SELECTOR_INVALID
    assert "ablation" in decision.detail


def test_a_sheet_the_workbook_lacks_names_the_ones_it_has(workbook):
    decision = check(SheetLocator(sheet="nope", column="accuracy", where={"seed": 1}), workbook)
    assert decision.reason is Reason.ROW_SELECTOR_INVALID
    assert "main" in decision.detail and "ablation" in decision.detail


def test_an_empty_cell_and_an_uncomputed_formula_are_absent(workbook):
    empty = check(
        SheetLocator(sheet="main", column="accuracy", where={"model": "pending"}), workbook
    )
    assert empty.reason is Reason.ROW_ABSENT and "no value" in empty.detail
    formula = check(
        SheetLocator(sheet="formulas", column="accuracy", where={"model": "mean"}), workbook
    )
    assert formula.outcome is Outcome.NOT_FOUND
    assert "no value" in formula.detail


def test_a_one_sheet_workbook_needs_no_sheet_named(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    book = openpyxl.Workbook()
    book.active.append(("model", "accuracy"))
    book.active.append(("resnet", 3.2))
    path = tmp_path / "one.xlsx"
    book.save(path)
    decision = check(SheetLocator(column="accuracy", where={"model": "resnet"}), path)
    assert decision.outcome is Outcome.VERIFIED


def test_a_table_locator_on_a_workbook_is_sent_to_the_sheet_locator(workbook):
    decision = check(TableLocator(column="accuracy", where={"model": "resnet"}), workbook)
    assert decision.reason is Reason.FORMAT_UNSUPPORTED
    assert "kind: sheet" in decision.detail


def test_an_xls_workbook(tmp_path):
    pytest.importorskip("xlrd")
    xlwt = pytest.importorskip("xlwt")
    book = xlwt.Workbook()
    ws = book.add_sheet("main")
    for r, row in enumerate(
        [("model", "seed", "accuracy"), ("resnet", 1, 0.91), ("resnet", 2, 3.2)]
    ):
        for c, value in enumerate(row):
            ws.write(r, c, value)
    path = tmp_path / "results.xls"
    book.save(str(path))
    # The old format has no integer type: seed 2 is stored as 2.0 and still selected by 2.
    locator = SheetLocator(column="accuracy", where={"model": "resnet", "seed": 2})
    assert check(locator, path).outcome is Outcome.VERIFIED


@pytest.mark.parametrize("name,module", [("r.xlsx", "openpyxl"), ("r.xls", "xlrd")])
def test_a_file_that_is_not_a_workbook_is_unreadable(tmp_path, name, module):
    pytest.importorskip(module)
    decision = engine(SheetLocator(column="acc", where={"m": "a"}), corrupt(tmp_path, name))
    assert decision.outcome is Outcome.UNCHECKED
    assert decision.reason is Reason.ARTIFACT_UNREADABLE


# -- parquet, feather and arrow -------------------------------------------------------------


@pytest.fixture
def arrow_table():
    pyarrow = pytest.importorskip("pyarrow")
    return pyarrow.table(
        {
            "model": ["resnet", "resnet", "vit", "vit", "pending", "nested"],
            "seed": [1, 2, 1, 1, 1, 1],
            "accuracy": pyarrow.array([0.91, 3.2, 0.75, 0.77, None, 0.1], pyarrow.float64()),
            "single": pyarrow.array([0.1, 0.2, 0.3, 0.4, 0.5, 0.6], pyarrow.float32()),
            "folds": [[1.0], [2.0], [3.0], [4.0], [5.0], [0.91, 0.02]],
        }
    )


@pytest.fixture
def parquet(tmp_path, arrow_table):
    parquet = pytest.importorskip("pyarrow.parquet")
    path = tmp_path / "results.parquet"
    parquet.write_table(arrow_table, path)
    return path


def test_a_parquet_cell_is_addressed_like_a_csv_cell(parquet):
    locator = TableLocator(column="accuracy", where={"model": "resnet", "seed": 2})
    assert check(locator, parquet, "3.2").outcome is Outcome.VERIFIED
    assert check(locator, parquet, "3.3").outcome is Outcome.MISMATCH


def test_repeated_keys_in_parquet_are_ambiguous(parquet):
    decision = check(TableLocator(column="accuracy", where={"model": "vit"}), parquet, "0.75")
    assert decision.reason is Reason.ROW_AMBIGUOUS
    assert "2 rows" in decision.detail


def test_a_single_precision_value_is_its_own_shortest_decimal(parquet):
    # Widened to a double, the stored 0.1f is 0.10000000149011612, and a manuscript printing
    # nine decimals of the number the analyst wrote would be contradicted by digits of the
    # widening.
    locator = TableLocator(column="single", where={"model": "resnet", "seed": 1})
    _, extracted, _ = resolve(locator, parquet)
    assert extracted is not None and extracted.raw == "0.1"
    assert check(locator, parquet, "0.100000000").outcome is Outcome.VERIFIED


def test_a_parquet_null_is_absent(parquet):
    decision = check(TableLocator(column="accuracy", where={"model": "pending"}), parquet)
    assert decision.reason is Reason.ROW_ABSENT
    assert "no value" in decision.detail


def test_a_list_cell_is_not_a_value_even_when_the_number_is_in_it(parquet):
    decision = check(TableLocator(column="folds", where={"model": "nested"}), parquet, "0.91")
    assert decision.reason is Reason.SELECTOR_NOT_SCALAR
    assert decision.outcome is Outcome.NOT_FOUND


def test_a_column_parquet_lacks_names_the_ones_it_has(parquet):
    decision = check(TableLocator(column="f1", where={"model": "vit"}), parquet)
    assert decision.reason is Reason.COLUMN_ABSENT
    assert "accuracy" in decision.detail


def test_a_delimiter_on_a_parquet_file_is_a_broken_selector(parquet):
    decision = check(TableLocator(column="accuracy", where={"seed": 2}, delimiter=","), parquet)
    assert decision.reason is Reason.ROW_SELECTOR_INVALID


def test_a_positional_address_into_parquet_carries_its_warning(parquet):
    decision = check(TablePositionLocator(column="accuracy", row=1), parquet)
    assert decision.outcome is Outcome.VERIFIED
    assert Warning_.POSITIONAL_ADDRESS in decision.warnings


def test_a_feather_file_takes_the_same_path(tmp_path, arrow_table):
    feather = pytest.importorskip("pyarrow.feather")
    path = tmp_path / "results.feather"
    feather.write_feather(arrow_table, path)
    locator = TableLocator(column="accuracy", where={"model": "resnet", "seed": 2})
    assert check(locator, path).outcome is Outcome.VERIFIED


@pytest.mark.parametrize("name", ["r.parquet", "r.feather", "r.arrow"])
def test_a_file_that_is_not_columnar_is_unreadable(tmp_path, name):
    pytest.importorskip("pyarrow")
    decision = engine(TableLocator(column="acc", where={"m": "a"}), corrupt(tmp_path, name))
    assert decision.outcome is Outcome.UNCHECKED
    assert decision.reason is Reason.ARTIFACT_UNREADABLE


def test_a_truncated_parquet_file_is_unreadable(parquet):
    parquet.write_bytes(parquet.read_bytes()[:200])
    decision = engine(TableLocator(column="accuracy", where={"seed": 2}), parquet)
    assert decision.reason is Reason.ARTIFACT_UNREADABLE


# -- stata and spss -------------------------------------------------------------------------


@pytest.fixture
def frame():
    pandas = pytest.importorskip("pandas")
    return pandas.DataFrame(
        {
            "model": pandas.Series(["resnet", "resnet", "vit", "vit", "pending"], dtype=object),
            "seed": [1, 2, 1, 1, 1],
            "accuracy": [0.91, 3.2, 0.75, 0.77, None],
        }
    )


@pytest.mark.parametrize("suffix", [".dta", ".sav"])
def test_a_stata_or_spss_cell_is_addressed_like_a_table(tmp_path, frame, suffix):
    pyreadstat = pytest.importorskip("pyreadstat")
    path = tmp_path / f"results{suffix}"
    (pyreadstat.write_dta if suffix == ".dta" else pyreadstat.write_sav)(frame, str(path))
    # SPSS stores every number as a double, so seed 2 is 2.0 on disk.
    locator = TableLocator(column="accuracy", where={"model": "resnet", "seed": 2})
    assert check(locator, path, "3.2").outcome is Outcome.VERIFIED
    assert check(locator, path, "3.3").outcome is Outcome.MISMATCH
    ambiguous = check(TableLocator(column="accuracy", where={"model": "vit"}), path)
    assert ambiguous.reason is Reason.ROW_AMBIGUOUS
    missing = check(TableLocator(column="accuracy", where={"model": "pending"}), path)
    assert missing.reason is Reason.ROW_ABSENT


def test_a_stata_float_column_reads_as_the_single_it_stores(tmp_path, frame):
    pyreadstat = pytest.importorskip("pyreadstat")
    path = tmp_path / "results.dta"
    frame["single"] = frame["accuracy"].astype("float32")
    # pandas, because `pyreadstat.write_dta` widens a float32 column to a double on the way out.
    frame.to_stata(path, write_index=False)
    _, meta = pyreadstat.read_dta(str(path), metadataonly=True)
    assert meta.readstat_variable_types["single"] == "float", "the fixture must store a single"
    locator = TableLocator(column="single", where={"model": "resnet", "seed": 1})
    _, extracted, _ = resolve(locator, path)
    assert extracted is not None and extracted.raw == "0.91"
    assert check(locator, path, "0.910000000").outcome is Outcome.VERIFIED


@pytest.mark.parametrize("name", ["r.dta", "r.sav"])
def test_a_file_that_is_not_stata_or_spss_is_unreadable(tmp_path, name):
    pytest.importorskip("pyreadstat")
    decision = engine(TableLocator(column="acc", where={"m": "a"}), corrupt(tmp_path, name))
    assert decision.outcome is Outcome.UNCHECKED
    assert decision.reason is Reason.ARTIFACT_UNREADABLE


# -- r data frames --------------------------------------------------------------------------


def test_an_r_data_frame_is_addressed_like_a_table(tmp_path, frame):
    rdata = pytest.importorskip("rdata")
    path = tmp_path / "results.rds"
    rdata.write_rds(path, frame)
    locator = TableLocator(column="accuracy", where={"model": "resnet", "seed": 2})
    assert check(locator, path, "3.2").outcome is Outcome.VERIFIED
    assert check(locator, path, "3.3").outcome is Outcome.MISMATCH
    ambiguous = check(TableLocator(column="accuracy", where={"model": "vit"}), path)
    assert ambiguous.reason is Reason.ROW_AMBIGUOUS
    # R's NA: absent, and never the text "nan" a comparison would call non-numeric.
    missing = check(TableLocator(column="accuracy", where={"model": "pending"}), path)
    assert missing.reason is Reason.ROW_ABSENT


def test_an_rds_holding_something_other_than_a_data_frame_is_not_a_table(tmp_path):
    rdata = pytest.importorskip("rdata")
    numpy = pytest.importorskip("numpy")
    path = tmp_path / "vector.rds"
    rdata.write_rds(path, numpy.array([3.2, 0.91]))
    decision = engine(TableLocator(column="x", where={"k": "v"}), path)
    assert decision.reason is Reason.ARTIFACT_UNREADABLE
    assert "not a data frame" in decision.detail


def test_a_file_that_is_not_an_rds_is_unreadable(tmp_path):
    pytest.importorskip("rdata")
    decision = engine(TableLocator(column="acc", where={"m": "a"}), corrupt(tmp_path, "r.rds"))
    assert decision.outcome is Outcome.UNCHECKED
    assert decision.reason is Reason.ARTIFACT_UNREADABLE


# -- hdf5 -----------------------------------------------------------------------------------


@pytest.fixture
def hdf5(tmp_path):
    h5py = pytest.importorskip("h5py")
    numpy = pytest.importorskip("numpy")
    path = tmp_path / "results.h5"
    with h5py.File(path, "w") as f:
        f["runs/accuracy"] = numpy.array([[0.91, 3.2], [0.75, 0.77]])
        f["runs/single"] = numpy.array([0.1], dtype=numpy.float32)
        f["n"] = 3.2
        f["record"] = numpy.array([(0.91, 0.02)], dtype=[("mean", "f8"), ("sd", "f8")])
    return path


def test_an_hdf5_element_is_addressed_by_dataset_path_and_index(hdf5):
    assert check(ArrayLocator(array="runs/accuracy", index=(0, 1)), hdf5).outcome is (
        Outcome.VERIFIED
    )
    assert check(ArrayLocator(array="/runs/accuracy", index=(1, 0)), hdf5).outcome is (
        Outcome.MISMATCH
    )
    assert check(ArrayLocator(array="n", index=()), hdf5).outcome is Outcome.VERIFIED


def test_an_hdf5_single_reads_as_its_own_shortest_decimal(hdf5):
    decision = check(ArrayLocator(array="runs/single", index=(0,)), hdf5, "0.100000000")
    assert decision.outcome is Outcome.VERIFIED


def test_an_hdf5_group_is_not_a_dataset(hdf5):
    decision = check(ArrayLocator(array="runs", index=(0,)), hdf5)
    assert decision.reason is Reason.ROW_SELECTOR_INVALID
    assert "accuracy" in decision.detail


def test_an_hdf5_dataset_that_is_not_there(hdf5):
    decision = check(ArrayLocator(array="runs/f1", index=(0,)), hdf5)
    assert decision.reason is Reason.ROW_SELECTOR_INVALID


def test_an_hdf5_index_past_the_end_is_absent(hdf5):
    assert resolve(ArrayLocator(array="runs/accuracy", index=(2, 0)), hdf5)[0] is (
        Resolution.ABSENT
    )


def test_an_hdf5_record_is_not_a_value(hdf5):
    decision = check(ArrayLocator(array="record", index=(0,)), hdf5, "0.91")
    assert decision.reason is Reason.SELECTOR_NOT_SCALAR


def test_a_file_that_is_not_hdf5_is_unreadable(tmp_path):
    pytest.importorskip("h5py")
    decision = engine(ArrayLocator(array="x", index=(0,)), corrupt(tmp_path, "r.h5"))
    assert decision.outcome is Outcome.UNCHECKED
    assert decision.reason is Reason.ARTIFACT_UNREADABLE


# -- netcdf ---------------------------------------------------------------------------------


@pytest.fixture
def netcdf(tmp_path):
    netCDF4 = pytest.importorskip("netCDF4")
    numpy = pytest.importorskip("numpy")
    path = tmp_path / "results.nc"
    with netCDF4.Dataset(path, "w") as ds:
        ds.createDimension("station", 3)
        packed = ds.createVariable("temperature", "i2", ("station",), fill_value=-999)
        packed.scale_factor = 0.5
        packed.add_offset = 270.0
        packed[:] = numpy.ma.masked_array([273.5, 280.0, 0.0], mask=[False, False, True])
        group = ds.createGroup("runs")
        group.createDimension("seed", 2)
        group.createVariable("accuracy", "f8", ("seed",))[:] = [0.91, 3.2]
    return path


def test_a_netcdf_value_is_the_unpacked_one(netcdf):
    # Stored as the int16 7; read as HDF5 the comparison would be against 7.
    assert check(ArrayLocator(array="temperature", index=(0,)), netcdf, "273.5").outcome is (
        Outcome.VERIFIED
    )


def test_a_netcdf_fill_value_is_absent(netcdf):
    decision = check(ArrayLocator(array="temperature", index=(2,)), netcdf, "-999")
    assert decision.outcome is Outcome.NOT_FOUND
    assert "fill value" in decision.detail


def test_a_netcdf_variable_in_a_group(netcdf):
    assert check(ArrayLocator(array="/runs/accuracy", index=(1,)), netcdf).outcome is (
        Outcome.VERIFIED
    )
    assert check(ArrayLocator(array="runs", index=(0,)), netcdf).reason is (
        Reason.ROW_SELECTOR_INVALID
    )
    assert check(ArrayLocator(array="runs/f1", index=(0,)), netcdf).reason is (
        Reason.ROW_SELECTOR_INVALID
    )


def test_a_file_that_is_not_netcdf_is_unreadable(tmp_path):
    pytest.importorskip("netCDF4")
    decision = engine(ArrayLocator(array="x", index=(0,)), corrupt(tmp_path, "r.nc"))
    assert decision.outcome is Outcome.UNCHECKED
    assert decision.reason is Reason.ARTIFACT_UNREADABLE
