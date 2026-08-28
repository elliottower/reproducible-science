"""One line telling a user that the other tools they already use can run together.

A tool that advertises itself is worse for it, and one that prints advertising into a CI log
is worse still. So this is bounded to the case where the note is a fact rather than a pitch,
and every bound is a condition on saying anything at all:

  * **the project already uses another tool.** If it does not, `repro check` would run one
    thing and the note would be false. Detection is on state directories, never on a data
    directory that happens to share the name.
  * **stderr, never stdout.** A note on stdout corrupts `citations verify --json | jq`.
  * **a terminal, never a pipe or CI.** Nothing is printed where nobody is reading.
  * **once per project.** Recorded under the user's cache, so it does not accumulate in the
    repository and does not need writing into another tool's state directory.
  * **`REPRO_NO_HINT` turns it off** for anyone who wants it gone regardless.

The point is that a user running two of these separately is doing more work than they need to,
and has no way to find that out. Once told, they never need telling again.
"""

from __future__ import annotations

import os
import pathlib

#: State directories, one per tool. A project "uses" a tool when its state directory is there.
#: `results/` is a committed data directory in this project's convention and `.results/` is the
#: tool's own, so matching the former would announce a tool the project never ran.
MARKERS: dict[str, str] = {
    "prereg": ".prereg",
    "citations": ".citations",
    "results": ".results",
    "repro": "repro.yaml",
}

OFF = "REPRO_NO_HINT"


def cache_root() -> pathlib.Path:
    """Where the record of having spoken lives. Computed, because this package has no deps."""
    base = os.environ.get("XDG_CACHE_HOME")
    return (
        pathlib.Path(base) if base else pathlib.Path.home() / ".cache"
    ) / "reproducible-science"


def others_in_use(root: pathlib.Path, me: str) -> list[str]:
    """Tools other than `me` whose state directory is present under `root`."""
    return sorted(n for n, m in MARKERS.items() if n != me and (root / m).exists())


def _seen(root: pathlib.Path, me: str) -> pathlib.Path:
    # Keyed on the project path so a second project still gets told once. A digest rather than
    # the path itself, because a path contains separators and may contain anything else.
    from .digests import sha256_of_text

    return cache_root() / f"{me}-{sha256_of_text(str(root.resolve()))[:16]}"


def note(me: str, root: pathlib.Path | None = None, stream=None) -> str | None:
    """Print the note if every condition holds, and return what was printed.

    Returns `None` when nothing was said, which is the ordinary case. Never raises: a cache
    that cannot be written is a reason to say nothing twice, not a reason to fail a command
    that had already done its work.
    """
    if os.environ.get(OFF):
        return None
    root = (root or pathlib.Path.cwd()).resolve()
    others = others_in_use(root, me)
    if not others:
        return None

    import sys as _sys

    stream = stream if stream is not None else _sys.stderr
    if not getattr(stream, "isatty", lambda: False)():
        return None

    marker = _seen(root, me)
    try:
        if marker.exists():
            return None
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.touch()
    except OSError:
        return None

    names = ", ".join(others)
    line = (
        f"note: this project also uses {names}. `repro check` runs them together in one pass, "
        f"and reports what no single tool can see. `{OFF}=1` silences this."
    )
    print(line, file=stream)
    return line
