"""The readers are pointed at repositories nobody here wrote, in formats that execute code
when opened the ordinary way. These tests guard the properties that make that safe."""

import gzip
import os
import pathlib
import pickle
import struct
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]
                       / "experiments" / "addressability-sample"))

from artifact_readers import read_pickle, read_rdata, unwrap  # noqa: E402


class _Payload:
    """Its `__reduce__` runs a shell command on unpickling. It is never unpickled."""

    def __init__(self, marker: pathlib.Path) -> None:
        self.marker = marker

    def __reduce__(self):
        return (os.system, (f"touch {self.marker}",))


def test_read_pickle_does_not_execute_reduce(tmp_path):
    marker = tmp_path / "executed"
    hostile = tmp_path / "hostile.pkl"
    hostile.write_bytes(pickle.dumps(_Payload(marker)) + pickle.dumps([1.5, 0.9489]))

    read_pickle(hostile)

    assert not marker.exists()


def test_read_pickle_recovers_literals_past_a_hostile_reduce(tmp_path):
    hostile = tmp_path / "mixed.pkl"
    hostile.write_bytes(pickle.dumps(_Payload(tmp_path / "unused"))
                        + pickle.dumps([0.9489, 1234.5]))

    values, complete = read_pickle(hostile)

    assert complete
    assert "0.9489" in values
    assert "1234.5" in values


def test_read_pickle_reports_a_truncated_stream_as_incomplete(tmp_path):
    whole = pickle.dumps([3.25] * 200)
    truncated = tmp_path / "cut.pkl"
    truncated.write_bytes(whole[: len(whole) // 2])

    _, complete = read_pickle(truncated)

    assert not complete


def test_read_rdata_rejects_a_file_that_is_not_r_serialization(tmp_path):
    impostor = tmp_path / "notreally.rds"
    impostor.write_bytes(b"\x89PNG\r\n\x1a\n" + os.urandom(256))

    values, complete = read_rdata(impostor)

    assert values == []
    assert not complete


def test_read_rdata_reports_incomplete_rather_than_inventing_values(tmp_path):
    # A well-formed header followed by a type this parser does not model. It must stop and
    # say so: a wrong field width would desynchronise the stream and yield plausible noise.
    body = b"X\n" + struct.pack(">iii", 2, 0x030601, 0x030500) + struct.pack(">i", 0x0006)
    unmodelled = tmp_path / "closure.rds"
    unmodelled.write_bytes(body)

    values, complete = read_rdata(unmodelled)

    assert not complete
    assert values == []


def test_read_rdata_recovers_a_real_vector(tmp_path):
    # REALSXP, length 3, three big-endian doubles.
    stream = (b"X\n" + struct.pack(">iii", 2, 0x030601, 0x030500)
              + struct.pack(">i", 14) + struct.pack(">i", 3)
              + struct.pack(">3d", 0.9489, 94.872, -1.5))
    path = tmp_path / "vector.rds"
    path.write_bytes(stream)

    values, complete = read_rdata(path)

    assert complete
    assert [float(v) for v in values] == pytest.approx([0.9489, 94.872, -1.5])


def test_read_rdata_reads_through_each_supported_compressor(tmp_path):
    stream = (b"X\n" + struct.pack(">iii", 2, 0x030601, 0x030500)
              + struct.pack(">i", 14) + struct.pack(">i", 1) + struct.pack(">d", 42.125))
    path = tmp_path / "compressed.rds"
    path.write_bytes(gzip.compress(stream))

    values, complete = read_rdata(path)

    assert complete
    assert [float(v) for v in values] == pytest.approx([42.125])


def test_unwrap_dispatches_on_a_stem_that_names_a_format(tmp_path):
    inner = (b"X\n" + struct.pack(">iii", 2, 0x030601, 0x030500)
             + struct.pack(">i", 14) + struct.pack(">i", 1) + struct.pack(">d", 7.5))
    wrapper = tmp_path / "RData.gz"
    wrapper.write_bytes(gzip.compress(inner))

    member = unwrap(wrapper, tmp_path)

    assert member is not None
    assert [float(v) for v in read_rdata(member)[0]] == pytest.approx([7.5])


def test_unwrap_refuses_a_wrapper_naming_no_format(tmp_path):
    wrapper = tmp_path / "coords.gz"
    wrapper.write_bytes(gzip.compress(b"1 2 3"))

    assert unwrap(wrapper, tmp_path) is None
