"""A web page as a pinned source, obtained and held by `retrieved`.

A claims file pins a file by sha256, and a web page is not a file until somebody saves it.
Saving one by hand, hashing it and writing its path into a claims file is three steps in which
the page pinned can stop being the page read. `retrieved` does the first two for every page it
captures: it fetches the URL itself, stores the bytes under their digest, and records when.

    citations pin claims/guide.yaml --url https://docs.example.org/guide --id scope \
        --quote "the passage, exactly as the page has it"

`obtain` answers with the most recent retrieval of the URL the library already holds, or
captures the page now where it holds none. A capture goes through `retrieved`'s own denylist,
pacing and fetch, in the order its `capture` command applies them, so a URL it refuses is
refused here with its reason and a request it would not make is not made.

The bytes stay in the library. A page is somebody else's text, and nothing here copies it into
the project: the claims file records the URL, the digest, the moment of retrieval and the
path of the bytes inside the library, and each machine finds the library for itself. See
`paths.retrieved_library` for which one.

`retrieved` is optional, installed by the `web` extra, and imported in `_retrieved` alone.
`verify` and `fetch` read a pinned page as a path and need none of it.
"""

from __future__ import annotations

import dataclasses
import pathlib

import yaml
from provenance_core import sha256_of_file

from citations import paths
from citations.exceptions import CitationsError
from citations.models import ClaimFile

EXTRA = "citations[web]"

#: What an HTML page declares as its reading: the built-in extractor that drops its tags,
#: decodes its entities and leaves out its scripts and stylesheets. Written into the claims
#: file, so `verify` reads the page the same way later with no record of the retrieval to ask.
HTML = "html-text"

#: What a page that is neither HTML nor a PDF declares: the bytes as they are. A file in the
#: store has no suffix to say it is text, and without a declaration it would be handed to the
#: PDF readers. `verify.reads_as_is` reads this in process and runs no program.
AS_SERVED = "cat {}"

PDF_MAGIC = b"%PDF-"

#: How a page whose record names no content type is told to be HTML: one of these, in any
#: case, within its first `SNIFFED` bytes.
HTML_MARKS = (b"<!doctype html", b"<html")
SNIFFED = 1024


class WebSourceError(CitationsError):
    """A page could not be obtained: `retrieved` is absent, refused the URL, or the fetch failed."""


@dataclasses.dataclass(frozen=True)
class Page:
    """One retrieval of a URL, as a claims file pins it."""

    url: str
    sha256: str
    fetched_at: str
    """When `retrieved` fetched these bytes, as its record has it."""

    path: pathlib.Path
    """The bytes, in the library's store."""

    captured: bool
    """Whether this call fetched the page. False where the library already held it."""

    content_type: str = ""
    """The `Content-Type` the server sent, as the retrieval's record has it. Empty where the
    record has none, and the bytes are then looked at instead."""

    def source(self) -> dict:
        """The `source` block that pins this retrieval, in the order a reader wants it.

        It names the reading: `html-text` for an HTML page, the bytes as served for other text,
        and nothing for a PDF, which the PDF readers take as they take any other.
        """
        block = {
            "url": self.url,
            "sha256": self.sha256,
            "retrieved": f"store/{self.sha256}",
            "retrieved_at": self.fetched_at,
        }
        with self.path.open("rb") as handle:
            head = handle.read(SNIFFED)
        if "html" in self.content_type.lower() or (
            not self.content_type and any(mark in head.lower() for mark in HTML_MARKS)
        ):
            block["extractor"] = HTML
        elif not head.startswith(PDF_MAGIC):
            block["extract_cmd"] = AS_SERVED
        return block


def _retrieved():
    """`retrieved`'s modules, imported when a page is asked for and not before."""
    try:
        from retrieved import capture, politeness, refuse, store
    except ImportError as e:
        raise WebSourceError(f'retrieved is not installed -- pip install "{EXTRA}"') from e
    return capture, politeness, refuse, store


def _held(library, url: str) -> tuple[str, str, str] | None:
    """The most recent retrieval of `url` whose bytes the store still has: when, its digest,
    and the content type its record gives.

    A library keeps a record after its bytes are removed, so a row in the index is not a file.
    """
    if not library.root.is_dir():
        return None
    # `history` reads a table only `create` makes, and a directory can exist without one.
    library.create()
    for fetched_at, digest, _ in reversed(library.history(url)):
        if not (library.store / digest).is_file():
            continue
        record = yaml.safe_load((library.retrievals / f"{digest}.yaml").read_text())
        status = record["http_status"]
        if not 200 <= status < 300:
            raise WebSourceError(
                f"the most recent retrieval of {url}, at {fetched_at}, is the server's answer "
                f"HTTP {status} and not the page. --recapture fetches it again."
            )
        return fetched_at, digest, record.get("content_type") or ""
    return None


def _capture(library, url: str, capture, politeness, refuse) -> tuple[str, str, str]:
    """Fetch `url` through `retrieved` and store what came back: when, its digest, and the
    content type the server sent.

    The denylist, then the pacing, then the fetch, which checks the denylist again on the URL a
    redirect reached. A refusal is written to the library's `skipped.jsonl`, as `retrieved`
    writes its own, unless there is no library yet: one is not created to hold a refusal.
    """
    try:
        refuse.check(url)
        library.create()
        with library.connect() as db:
            politeness.check(db, url, capture.USER_AGENT)
            politeness.record(db, url)
        try:
            got = capture.fetch(url)
        except refuse.Refused:
            raise
        except Exception as e:  # the client raises its own hierarchy; none of it is ours
            raise WebSourceError(f"{url} could not be fetched: {e}") from e
    except (refuse.Refused, politeness.Declined) as e:
        if library.root.is_dir():
            library.skip(url, e.reason)
        raise WebSourceError(f"retrieved will not capture {url}: {e.reason}") from e
    if not 200 <= got.http_status < 300:
        library.skip(url, f"HTTP {got.http_status}")
        raise WebSourceError(f"{url} answered HTTP {got.http_status}, and nothing was stored.")
    library.write(got)
    return got.fetched_at, got.bytes_sha256, got.content_type


def obtain(url: str, project: pathlib.Path, recapture: bool = False) -> Page:
    """The page at `url` as the `retrieved` library governing `project` holds it.

    The most recent retrieval already there, or a capture made now where there is none or
    `recapture` asks for one. Raises `WebSourceError` where there is no page to pin.
    """
    capture, politeness, refuse, store = _retrieved()
    library = store.Library(paths.retrieved_library(project))
    found = None if recapture else _held(library, url)
    captured = found is None
    if found is None:
        found = _capture(library, url, capture, politeness, refuse)
    fetched_at, digest, content_type = found
    blob = library.store / digest
    if sha256_of_file(blob) != digest:
        raise WebSourceError(
            f"{blob} does not hash to its name, so it is not the retrieval its record "
            f"describes. `retrieved verify` lists every such file."
        )
    return Page(url, digest, fetched_at, blob, captured, content_type)


def missing(cf: ClaimFile) -> str:
    """Why a quotation is `unchecked` where the page its claims file pins is not in the store."""
    assert cf.path is not None
    store = paths.retrieved_library(cf.path.resolve().parent.parent) / "store"
    return (
        f"not in the retrieved store at {store}: the source is a web page pinned by its URL, "
        f"and its bytes are kept in the library that captured it"
    )


__all__ = ["AS_SERVED", "EXTRA", "HTML", "Page", "WebSourceError", "missing", "obtain"]
