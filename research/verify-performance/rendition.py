"""A content-addressed rendition cache, and the page map that removes per-page extraction.

Prototype. Nothing here is imported by `citations`; it exists to be measured against the
current implementation and to make the design concrete enough to argue about.

Two things are cached, because two things are expensive and they are invalidated by different
events.

    rendition     what backend B, under profile P, made of the bytes of artifact A.
                  Invalidated by a changed artifact, a changed backend, a changed argument
                  vector, or a changed rendition schema. Not by a changed quotation.
    check         what the matcher concluded about one quotation against one rendition.
                  Invalidated by a changed quotation, selector, page constraint, or any
                  version of the matching or decision policy. Not by anything about the PDF.

A quotation edited between two runs must not re-extract a 30 MB PDF, and a re-extracted PDF
must not be trusted to have produced the same text. Two keys, because one key would conflate
them.

Page maps
---------

`pdftotext` writes U+000C between pages, so a whole-document extraction already carries every
page boundary. Measured on this corpus, `full.split("\\f")[p-1]` is byte-identical to
`pdftotext -f p -l p` output with its trailing form feed removed, on every page of every
artifact -- `bench_pagemap.py` is that check and it is a canary, not a formality. The current
implementation instead spawns one `pdftotext` per page, up to `PAGE_SCAN_LIMIT`, and pays a
process spawn, an xref parse and a font setup for each.

Identity
--------

The key is the whole of what could change the text, not the path. A path names a mutable
location; a digest names bytes. `backend_version` is in the key because poppler's output
changes between releases and a rendition taken under one is not a rendition taken under
another.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import threading
import time

import platformdirs

#: Bumped when the stored shape changes. An old entry then misses rather than being
#: misread, which is the only safe way to change a cache format.
RENDITION_SCHEMA = 1
CHECK_SCHEMA = 1

#: Bumped by whoever changes `fold`, `skeleton`, `_count`, or the verdict rules. A cached
#: verdict taken under different matching rules is not a verdict about this run's question.
MATCHING_POLICY_VERSION = "citations-0.3.1+quote-selector"

DEFAULT_CACHE = pathlib.Path(platformdirs.user_cache_dir("citations")) / "renditions"


class CacheError(RuntimeError):
    """A cache entry could not be read, written, or published."""


@dataclasses.dataclass(frozen=True)
class ExtractorIdentity:
    """Everything about the reader that can change the text it produces."""

    backend: str
    version: str
    arguments: tuple[str, ...]

    def as_dict(self) -> dict:
        return {
            "backend": self.backend,
            "version": self.version,
            "arguments": list(self.arguments),
        }


def poppler_identity(layout: bool = True) -> ExtractorIdentity:
    exe = shutil.which("pdftotext")
    if not exe:
        raise CacheError("pdftotext is not on PATH")
    r = subprocess.run([exe, "-v"], capture_output=True, text=True, timeout=30)
    version = ((r.stderr or r.stdout or "").strip().splitlines() or [""])[0]
    return ExtractorIdentity("poppler-pdftotext", version, ("-layout",) if layout else ())


@dataclasses.dataclass(frozen=True)
class Rendition:
    """One reading of one artifact, and the page boundaries inside it."""

    text: str
    text_sha256: str
    pages: tuple[str, ...]
    extractor: ExtractorIdentity
    artifact_sha256: str
    produced_utc: str
    origin: str  # "executed" or "reused"

    @property
    def n_pages(self) -> int:
        return len(self.pages)

    def page(self, n: int) -> str:
        """One page's text, 1-based. Empty past the end, which is how a page scan stops."""
        return self.pages[n - 1] if 1 <= n <= len(self.pages) else ""


def _canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()


def rendition_key(artifact_sha256: str, extractor: ExtractorIdentity) -> str:
    """The address of a rendition. Content, reader, and stored shape -- never the path."""
    return hashlib.sha256(
        _canonical(
            {
                "artifact_sha256": artifact_sha256,
                "extractor": extractor.as_dict(),
                "page_selection": "whole-document",
                "schema": RENDITION_SCHEMA,
            }
        )
    ).hexdigest()


def check_key(
    rendition_sha256: str,
    quote: str,
    prefix: str,
    suffix: str,
    page: int | None,
) -> str:
    """The address of a verdict.

    Keyed on the *rendition* digest rather than on the artifact plus extractor: the matcher
    consumes text, and two paths that produced the same text ask the same question. The policy
    version is in the key because a changed `fold` changes the answer without changing any
    input the record names.
    """
    return hashlib.sha256(
        _canonical(
            {
                "rendition_sha256": rendition_sha256,
                "quote": quote,
                "prefix": prefix,
                "suffix": suffix,
                "page": page,
                "matching_policy": MATCHING_POLICY_VERSION,
                "schema": CHECK_SCHEMA,
            }
        )
    ).hexdigest()


def sha256_of_file(p: pathlib.Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class RenditionCache:
    """Content-addressed store with atomic publication and in-process single flight.

    `lru_cache` serializes access to its dictionary and does not stop two threads observing
    the same miss and both extracting. A per-key lock does, so N threads asking for one
    artifact spawn one `pdftotext` rather than N.

    Publication is write-to-temp, fsync, rename. A reader never sees a partial entry, and two
    processes racing to produce the same rendition both succeed: the loser's rename replaces
    identical bytes.
    """

    def __init__(self, root: pathlib.Path | None = None) -> None:
        self.root = pathlib.Path(root or DEFAULT_CACHE)
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()
        self.hits = 0
        self.misses = 0
        self.extractions = 0
        self.extract_seconds = 0.0
        self.hash_seconds = 0.0
        self.io_seconds = 0.0

    def _path(self, key: str) -> pathlib.Path:
        return self.root / key[:2] / f"{key}.json"

    def _lock_for(self, key: str) -> threading.Lock:
        with self._guard:
            return self._locks.setdefault(key, threading.Lock())

    def get(
        self, artifact: pathlib.Path, extractor: ExtractorIdentity, artifact_sha: str | None = None
    ) -> Rendition:
        sha = artifact_sha
        if sha is None:
            t0 = time.perf_counter()
            sha = sha256_of_file(artifact)
            self.hash_seconds += time.perf_counter() - t0
        key = rendition_key(sha, extractor)
        with self._lock_for(key):
            stored = self._read(key)
            if stored is not None:
                self.hits += 1
                return stored
            self.misses += 1
            rend = self._extract(artifact, extractor, sha)
            self._publish(key, rend)
            return rend

    def _read(self, key: str) -> Rendition | None:
        p = self._path(key)
        if not p.is_file():
            return None
        t0 = time.perf_counter()
        try:
            raw = json.loads(p.read_text())
        except (OSError, json.JSONDecodeError):
            return None  # a damaged entry is a miss, never an error
        finally:
            self.io_seconds += time.perf_counter() - t0
        text = raw["text"]
        # The stored digest is checked against the stored text. A cache that returns whatever
        # is in the file cannot fail, and a check that cannot fail is not a check.
        if hashlib.sha256(text.encode()).hexdigest() != raw["text_sha256"]:
            return None
        return Rendition(
            text=text,
            text_sha256=raw["text_sha256"],
            pages=tuple(text.split("\f")),
            extractor=ExtractorIdentity(
                raw["extractor"]["backend"],
                raw["extractor"]["version"],
                tuple(raw["extractor"]["arguments"]),
            ),
            artifact_sha256=raw["artifact_sha256"],
            produced_utc=raw["produced_utc"],
            origin="reused",
        )

    def _extract(self, artifact: pathlib.Path, extractor: ExtractorIdentity, sha: str) -> Rendition:
        argv = ["pdftotext", *extractor.arguments, str(artifact), "-"]
        t0 = time.perf_counter()
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=300)
        self.extract_seconds += time.perf_counter() - t0
        self.extractions += 1
        if proc.returncode != 0:
            raise CacheError(f"{argv[0]} exited {proc.returncode}: {(proc.stderr or '')[-200:]}")
        text = proc.stdout
        return Rendition(
            text=text,
            text_sha256=hashlib.sha256(text.encode()).hexdigest(),
            pages=tuple(text.split("\f")),
            extractor=extractor,
            artifact_sha256=sha,
            produced_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            origin="executed",
        )

    def _publish(self, key: str, rend: Rendition) -> None:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        body = {
            "schema": RENDITION_SCHEMA,
            "artifact_sha256": rend.artifact_sha256,
            "extractor": rend.extractor.as_dict(),
            "page_selection": "whole-document",
            "text_sha256": rend.text_sha256,
            "n_pages": rend.n_pages,
            "produced_utc": rend.produced_utc,
            "text": rend.text,
        }
        t0 = time.perf_counter()
        tmp = p.with_name(f".{key}.{os.getpid()}.{threading.get_ident()}.tmp")
        with tmp.open("w") as fh:
            fh.write(json.dumps(body))
            fh.flush()
            os.fsync(fh.fileno())
        tmp.replace(p)  # atomic within the filesystem; a racing writer wrote the same bytes
        self.io_seconds += time.perf_counter() - t0

    def size_bytes(self) -> int:
        return sum(p.stat().st_size for p in self.root.rglob("*.json"))

    def entries(self) -> int:
        return sum(1 for _ in self.root.rglob("*.json"))


class CheckCache:
    """Verdicts, keyed on the rendition they were taken against.

    One file per rendition rather than per verdict: a document contributes hundreds of
    quotations, and hundreds of 400-byte files cost more in inodes and `stat` calls than they
    save. The rendition digest is in the filename, so an entry for a rendition nobody produces
    any more is identifiable and prunable.
    """

    def __init__(self, root: pathlib.Path | None = None) -> None:
        self.root = pathlib.Path(root or DEFAULT_CACHE.parent / "checks")
        self.hits = 0
        self.misses = 0
        self._loaded: dict[str, dict] = {}
        self._dirty: set[str] = set()
        # Reentrant: `put` holds the guard and then calls `_bucket`, which takes it again. A
        # plain `Lock` deadlocks there on the first write, in the main thread, with no threads
        # running -- which is what happened, and why the guard is named rather than implicit.
        self._guard = threading.RLock()

    def _path(self, rendition_sha: str) -> pathlib.Path:
        return self.root / rendition_sha[:2] / f"{rendition_sha}.json"

    def _bucket(self, rendition_sha: str) -> dict:
        with self._guard:
            if rendition_sha in self._loaded:
                return self._loaded[rendition_sha]
            p = self._path(rendition_sha)
            try:
                raw = json.loads(p.read_text()) if p.is_file() else {}
            except (OSError, json.JSONDecodeError):
                raw = {}
            self._loaded[rendition_sha] = raw
            return raw

    def get(self, rendition_sha: str, key: str) -> dict | None:
        got = self._bucket(rendition_sha).get(key)
        with self._guard:
            if got is None:
                self.misses += 1
            else:
                self.hits += 1
        return got

    def put(self, rendition_sha: str, key: str, value: dict) -> None:
        with self._guard:
            self._bucket(rendition_sha)[key] = value
            self._dirty.add(rendition_sha)

    def flush(self) -> None:
        with self._guard:
            dirty, self._dirty = self._dirty, set()
            snapshot = {k: dict(self._loaded[k]) for k in dirty}
        for rendition_sha, body in snapshot.items():
            p = self._path(rendition_sha)
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_name(f".{rendition_sha}.{os.getpid()}.tmp")
            with tmp.open("w") as fh:
                fh.write(json.dumps(body))
                fh.flush()
                os.fsync(fh.fileno())
            tmp.replace(p)

    def size_bytes(self) -> int:
        return sum(p.stat().st_size for p in self.root.rglob("*.json"))
