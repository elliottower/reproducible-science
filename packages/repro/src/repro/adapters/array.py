"""NumPy `.npy` and `.npz`, addressed by array name and index."""

from __future__ import annotations

import pathlib

from repro.adapters.base import Found, Resolution, _no, _ok
from repro.exceptions import ArtifactUnreadableError, BackendUnavailableError
from repro.models import (
    ArrayLocator,
)

# ----------------------------------------------------------------------------------- arrays

_ARRAY_SUFFIXES = {".npy", ".npz"}


def _resolve_array(locator: ArrayLocator, path: pathlib.Path) -> Found:
    if path.suffix.lower() not in _ARRAY_SUFFIXES:
        return _no(
            Resolution.FORMAT_UNSUPPORTED,
            f"an array locator addresses .npy or .npz; {path.name} is {path.suffix}",
        )
    try:
        import numpy
    except ImportError as e:
        raise BackendUnavailableError("array", f"numpy is not installed: {e}") from e

    try:
        loaded = numpy.load(path, allow_pickle=False)
    except (OSError, ValueError) as e:
        raise ArtifactUnreadableError(path, str(e)) from e

    if path.suffix.lower() == ".npz":
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

    if len(locator.index) != array.ndim:
        return _no(
            Resolution.SELECTOR_INVALID,
            f"array has {array.ndim} dimensions; index gives {len(locator.index)}",
        )
    if any(i < 0 for i in locator.index):
        # A negative index resolves from the end in Python, so `-1` silently addressed the
        # last element and `-99` raised out of the adapter as a backend defect. Neither is an
        # address; the same condition on the upper side is a clean `absent`.
        return _no(
            Resolution.SELECTOR_INVALID,
            f"index {locator.index} is negative; an address is not relative to the end",
        )
    if any(i >= n for i, n in zip(locator.index, array.shape, strict=True)):
        return _no(
            Resolution.ABSENT, f"index {locator.index} is outside shape {tuple(array.shape)}"
        )
    value = array[locator.index]
    if value.ndim:
        return _no(Resolution.NOT_SCALAR, f"index resolves to a {value.ndim}-d slice")
    if value.dtype.kind == "V":
        # `ndim` does not settle this. The rank guard above forces a full index, so every
        # element is 0-d -- including one of a structured or subarray dtype, which indexes to
        # a `numpy.void` holding several fields. That stringified as `(0.91, 0.02)` and was
        # returned as one resolved value, against the invariant this adapter exists to hold.
        held = ", ".join(value.dtype.names) if value.dtype.names else f"{value.itemsize} bytes"
        return _no(Resolution.NOT_SCALAR, f"index resolves to a record holding {held}")
    return _ok(str(value), str(array.dtype), f"{locator.array or path.stem}{list(locator.index)}")
