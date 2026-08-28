"""Three more text layers, offered to the comparison `compare_readers.py` already runs.

The question is not whether another reader exists. It is whether one fails in a *different*
direction from the readers already installed: a reader that resolves what poppler misses and
misses what poppler resolves earns a place in triangulation, and one that is uniformly a little
worse earns nothing. So the candidates are registered into `compare_readers.READERS` and
measured by the harness that produced `results.json`, on the same corpus, with the same
per-passage unit.

    pdf-extract   a Rust crate with its own text-positioning layer over lopdf's object model
    lopdf         the same object model with no layout layer at all: `Document::extract_text`
    pdfium        Chrome's PDF engine, reached through the `pypdfium2` wheel

Both Rust readers are reached through one small binary built from `pdfrs/`, so the harness
calls them the way it calls `pdftotext` -- a program given a path that prints text. Building it
needs a Rust toolchain, which is why the path is a parameter and an absent binary is reported
rather than raised.

`pdfium-render` is not a fourth candidate. It is a Rust binding to the same libpdfium that
`pypdfium2` binds from Python, calling the same `FPDFText_*` entry points, so the two cannot
disagree about what text a page holds. Measuring both would report one engine's agreement with
itself. Which language binds it is a packaging question, and the packaging answer is that the
wheel installs with no toolchain.
"""

from __future__ import annotations

import pathlib
import subprocess
import time

import compare_readers as C

#: How long a candidate gets on one document before it is recorded as a failure rather than
#: waited on. The same cap the harness gives poppler, so a slow reader and a fast one are
#: bounded alike.
TIMEOUT = 300

#: Built by `cargo build --release` in `pdfrs/`. Overridden by `--pdfrs` on the runner.
PDFRS = pathlib.Path(__file__).parent / "pdfrs" / "target" / "release" / "pdfrs"


def _rust(pdf: pathlib.Path, mode: str, name: str, binary: pathlib.Path) -> C.Reading:
    started = time.monotonic()
    try:
        proc = subprocess.run(
            [str(binary), mode, str(pdf)], capture_output=True, text=True, timeout=TIMEOUT
        )
    except FileNotFoundError:
        return C.Reading(name, None, f"{binary} is not built", time.monotonic() - started)
    except subprocess.TimeoutExpired:
        return C.Reading(name, None, f"timed out after {TIMEOUT}s", time.monotonic() - started)
    except OSError as e:
        return C.Reading(name, None, f"could not be run: {e}", time.monotonic() - started)
    if proc.returncode != 0:
        said = (proc.stderr or "").strip().splitlines()
        return C.Reading(
            name,
            None,
            f"exited {proc.returncode}" + (f": {said[-1]}"[:200] if said else ""),
            time.monotonic() - started,
        )
    return C.Reading(name, proc.stdout, None, time.monotonic() - started)


def read_pdf_extract(pdf: pathlib.Path, binary: pathlib.Path = PDFRS) -> C.Reading:
    return _rust(pdf, "extract", "pdf-extract", binary)


def read_lopdf(pdf: pathlib.Path, binary: pathlib.Path = PDFRS) -> C.Reading:
    return _rust(pdf, "lopdf", "lopdf", binary)


def read_pdfium(pdf: pathlib.Path) -> C.Reading:
    """PDFium in process, page by page.

    In process and not through a subprocess, because that is what a reader added to
    `citations.readers` would cost. A C++ engine that segfaults takes the harness with it; the
    harness appends one line per document to its shard and resumes, so a crash costs one
    document and is visible as the document the shard stops at.
    """
    import pypdfium2

    started = time.monotonic()
    doc = None
    try:
        doc = pypdfium2.PdfDocument(pdf)
        parts = [page.get_textpage().get_text_range() for page in doc]
    except Exception as e:
        return C.Reading(
            "pdfium", None, f"{type(e).__name__}: {e}"[:200], time.monotonic() - started
        )
    finally:
        if doc is not None:
            doc.close()
    return C.Reading("pdfium", "\n".join(parts), None, time.monotonic() - started)


#: Name -> (reader, pipeline). The pipeline label is what stops two bindings of one engine
#: being counted as two readers agreeing; `pdf-extract` and `lopdf` share lopdf's object model
#: and are labelled as one for the same reason poppler's two modes are.
CANDIDATES = {
    "pdf-extract": (read_pdf_extract, "lopdf"),
    "lopdf": (read_lopdf, "lopdf"),
    "pdfium": (read_pdfium, "pdfium"),
}


def register(binary: pathlib.Path = PDFRS, only: list[str] | None = None) -> list[str]:
    """Add the candidates to the harness's own reader table and say which were added.

    Mutates `compare_readers.READERS`, which `measure_document` and `summarize` both read, so
    the candidates are measured by the code that produced `results.json` rather than by a
    second implementation of it that could differ.
    """
    added = []
    for name, (read, pipeline) in CANDIDATES.items():
        if only is not None and name not in only:
            continue
        if name in ("pdf-extract", "lopdf"):
            C.READERS[name] = lambda pdf, _read=read: _read(pdf, binary)
        else:
            C.READERS[name] = read
        C.PIPELINES[name] = pipeline
        added.append(name)
    return added


def versions(binary: pathlib.Path = PDFRS) -> dict[str, str]:
    """What each candidate is, at the versions this run used."""
    out: dict[str, str] = {}
    lock = binary.parent.parent.parent / "Cargo.lock"
    if lock.exists():
        pinned: dict[str, list[str]] = {}
        name = ""
        for line in lock.read_text().splitlines():
            if line.startswith('name = "'):
                name = line.split('"')[1]
            elif line.startswith('version = "') and name:
                pinned.setdefault(name, []).append(line.split('"')[1])
                name = ""
        for crate in ("pdf-extract", "lopdf"):
            out[f"crate {crate}"] = ", ".join(pinned.get(crate, ["absent"]))
    else:
        out["crate pdf-extract"] = out["crate lopdf"] = f"no Cargo.lock beside {binary}"
    out["pdfrs binary"] = str(binary) if binary.exists() else f"{binary} (not built)"
    try:
        rustc = subprocess.run(["rustc", "--version"], capture_output=True, text=True, timeout=30)
        out["rustc"] = rustc.stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        out["rustc"] = "absent"
    try:
        import pypdfium2.version as v

        out["pypdfium2"] = str(v.PYPDFIUM_INFO)
        out["libpdfium"] = str(v.PDFIUM_INFO)
    except ImportError:
        out["pypdfium2"] = "not installed"
    return out
