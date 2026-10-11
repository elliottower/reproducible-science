"""Arrays, addressed by array name and index: NumPy `.npy` and `.npz`, HDF5, and NetCDF.

An HDF5 or NetCDF file holds many arrays under paths, as an `.npz` holds them under names, so
the locator is the same: `array` is the dataset's path and `index` the element. Each reader is
an optional extra (`reproducible-science[arrays]`, `[hdf5]`, `[netcdf]`), and a missing one is
`unchecked` with the extra named.

NetCDF is read through `netCDF4` rather than as the HDF5 file a NetCDF-4 file also is. A
NetCDF variable is often stored packed -- integers with a `scale_factor` and an `add_offset`
-- and its fill value marks an element that holds nothing. Read as plain HDF5, the packed
integer would be compared with the manuscript and the fill value would be a number. The value
of a NetCDF variable is the one a NetCDF reader reports, unpacked, and a filled element is
absent.
"""

from __future__ import annotations

import pathlib

from repro.adapters.base import Found, Resolution, _no, _ok
from repro.exceptions import ArtifactUnreadableError, BackendUnavailableError
from repro.models import (
    ArrayLocator,
)

try:  # optional: `pip install "reproducible-science[arrays]"`
    import numpy
except ImportError:  # pragma: no cover - exercised by the extras matrix, not the suite
    numpy = None

try:  # optional: `pip install "reproducible-science[hdf5]"`
    import h5py
except ImportError:  # pragma: no cover
    h5py = None

try:  # optional: `pip install "reproducible-science[netcdf]"`
    import netCDF4
except ImportError:  # pragma: no cover
    netCDF4 = None

# ----------------------------------------------------------------------------------- arrays

_NUMPY_SUFFIXES = {".npy", ".npz"}
_HDF5_SUFFIXES = {".h5", ".hdf5"}
_NETCDF_SUFFIXES = {".nc"}
_ARRAY_SUFFIXES = _NUMPY_SUFFIXES | _HDF5_SUFFIXES | _NETCDF_SUFFIXES


def _resolve_array(locator: ArrayLocator, path: pathlib.Path) -> Found:
    suffix = path.suffix.lower()
    if suffix not in _ARRAY_SUFFIXES:
        return _no(
            Resolution.FORMAT_UNSUPPORTED,
            f"an array locator addresses .npy, .npz, HDF5 or NetCDF; {path.name} is {path.suffix}",
        )
    if suffix in _HDF5_SUFFIXES:
        return _resolve_hdf5(locator, path)
    if suffix in _NETCDF_SUFFIXES:
        return _resolve_netcdf(locator, path)
    if numpy is None:
        raise BackendUnavailableError(
            "array", 'numpy is not installed -- pip install "reproducible-science[arrays]"'
        )

    try:
        loaded = numpy.load(path, allow_pickle=False)
    except (OSError, ValueError) as e:
        raise ArtifactUnreadableError(path, str(e)) from e

    if suffix == ".npz":
        if locator.array is None:
            return _no(Resolution.SELECTOR_INVALID, f"{path.name} holds several arrays; name one")
        if locator.array not in loaded.files:
            return _no(
                Resolution.SELECTOR_INVALID,
                f"{path.name} has no array {locator.array!r}; arrays are "
                f"{', '.join(loaded.files[:8])}",
            )
        array = loaded[locator.array]
    else:
        array = loaded

    if failure := _index_faults(locator.index, tuple(array.shape)):
        return failure
    return _element(array[locator.index], locator.array or path.stem, locator.index)


def _index_faults(index: tuple[int, ...], shape: tuple[int, ...]) -> Found | None:
    """What is wrong with an index for an array of this shape, or None."""
    if len(index) != len(shape):
        return _no(
            Resolution.SELECTOR_INVALID,
            f"array has {len(shape)} dimensions; index gives {len(index)}",
        )
    if any(i < 0 for i in index):
        # A negative index resolves from the end in Python, so `-1` silently addressed the
        # last element and `-99` raised out of the adapter as a backend defect. Neither is an
        # address; the same condition on the upper side is a clean `absent`.
        return _no(
            Resolution.SELECTOR_INVALID,
            f"index {index} is negative; an address is not relative to the end",
        )
    if any(i >= n for i, n in zip(index, shape, strict=True)):
        return _no(Resolution.ABSENT, f"index {index} is outside shape {shape}")
    return None


def _element(value, name: str, index: tuple[int, ...]) -> Found:
    """One indexed element as a resolution, refusing anything that is not one scalar."""
    if value.ndim:
        return _no(Resolution.NOT_SCALAR, f"index resolves to a {value.ndim}-d slice")
    if value.dtype.kind == "V":
        # `ndim` does not settle this. The rank guard forces a full index, so every element is
        # 0-d -- including one of a structured or subarray dtype, which indexes to a
        # `numpy.void` holding several fields. That stringified as `(0.91, 0.02)` and was
        # returned as one resolved value, against the invariant this adapter exists to hold.
        held = ", ".join(value.dtype.names) if value.dtype.names else f"{value.itemsize} bytes"
        return _no(Resolution.NOT_SCALAR, f"index resolves to a record holding {held}")
    if value.dtype.kind in "SO":
        # `str(numpy.bytes_(b"0.91"))` is `b'0.91'`, which is not the text the file holds. HDF5
        # stores strings as bytes, fixed-length or variable, and these reach here as either.
        item = value.item()
        text = item.decode("utf-8", errors="replace") if isinstance(item, bytes) else str(item)
        return _ok(text, type(item).__name__, f"{name}{list(index)}")
    return _ok(str(value), str(value.dtype), f"{name}{list(index)}")


# ------------------------------------------------------------------------------------- hdf5


def _members(group) -> str:
    return ", ".join(list(group.keys())[:8]) or "nothing"


def _resolve_hdf5(locator: ArrayLocator, path: pathlib.Path) -> Found:
    if h5py is None or numpy is None:
        raise BackendUnavailableError(
            "array", 'h5py is not installed -- pip install "reproducible-science[hdf5]"'
        )
    if locator.array is None:
        return _no(Resolution.SELECTOR_INVALID, f"{path.name} holds datasets by path; name one")
    try:
        handle = h5py.File(path, "r")
    except OSError as e:
        raise ArtifactUnreadableError(path, f"not a readable HDF5 file: {e}") from e
    with handle:
        # `get` rather than indexing: a dangling soft or external link is a name that leads
        # nowhere, which for a locator is the same fact as a name that is not there.
        node = handle.get(locator.array)
        if node is None:
            return _no(
                Resolution.SELECTOR_INVALID,
                f"{path.name} has no dataset {locator.array!r}; the root holds {_members(handle)}",
            )
        if not isinstance(node, h5py.Dataset):
            return _no(
                Resolution.SELECTOR_INVALID,
                f"{locator.array!r} in {path.name} is a group, holding {_members(node)}",
            )
        if node.shape is None:
            return _no(Resolution.ABSENT, f"{locator.array!r} in {path.name} holds no data")
        if failure := _index_faults(locator.index, tuple(node.shape)):
            return failure
        try:
            # Reads the one element, not the dataset: a results file can be gigabytes.
            value = node[locator.index]
        except OSError as e:
            # A compression filter this build of HDF5 lacks fails here, not on open.
            raise ArtifactUnreadableError(path, f"{locator.array!r} cannot be read: {e}") from e
    return _element(numpy.asarray(value), locator.array, locator.index)


# ----------------------------------------------------------------------------------- netcdf


def _resolve_netcdf(locator: ArrayLocator, path: pathlib.Path) -> Found:
    if netCDF4 is None or numpy is None:
        raise BackendUnavailableError(
            "array", 'netCDF4 is not installed -- pip install "reproducible-science[netcdf]"'
        )
    if locator.array is None:
        return _no(Resolution.SELECTOR_INVALID, f"{path.name} holds variables by path; name one")
    try:
        dataset = netCDF4.Dataset(path, "r")
    except OSError as e:
        raise ArtifactUnreadableError(path, f"not a readable NetCDF file: {e}") from e
    try:
        try:
            node = dataset[locator.array]
        except IndexError:
            return _no(
                Resolution.SELECTOR_INVALID,
                f"{path.name} has no variable {locator.array!r}; the root holds "
                f"{', '.join([*dataset.variables, *dataset.groups][:8]) or 'nothing'}",
            )
        if not isinstance(node, netCDF4.Variable):
            return _no(
                Resolution.SELECTOR_INVALID,
                f"{locator.array!r} in {path.name} is a group, not a variable",
            )
        if failure := _index_faults(locator.index, tuple(node.shape)):
            return failure
        value = node[locator.index]
    finally:
        dataset.close()
    if numpy.ma.is_masked(value):
        return _no(
            Resolution.ABSENT,
            f"{locator.array}{list(locator.index)} in {path.name} holds the fill value",
        )
    return _element(numpy.asarray(numpy.ma.getdata(value)), locator.array, locator.index)
