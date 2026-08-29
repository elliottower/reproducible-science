"""Which papers cite into this library, and where their bibliographies live.

This was a dict of absolute paths inside `build.py`, which made the package work on exactly one
machine. It is configuration, so it lives in the library as data:

    <library>/papers.yaml

    papers:
      structure-audit:
        bib: ~/papers/structure-audit/paper/references.bib
        claims: ~/papers/structure-audit/claims
        sources: ~/papers/structure-audit/sources

Paths may be absolute, may use `~`, or may be relative to the library. A configured path that
does not exist is reported rather than skipped: a bibliography that quietly contributes nothing
looks exactly like a paper that cites nothing.
"""

from __future__ import annotations

import pathlib

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from citations import paths
from citations.exceptions import ClaimFileError

CONFIG_NAME = "papers.yaml"


class PaperConfig(BaseModel):
    """One paper that cites into the library."""

    model_config = ConfigDict(extra="allow")

    bib: pathlib.Path | None = None
    """Its BibTeX file. The bibliography is authoritative for every field it carries."""

    bibitem: pathlib.Path | None = None
    """A hand-written `thebibliography` block, where a paper has no .bib. Fields are
    positional there, so parsing is best-effort and the .bib is always preferred."""

    claims: pathlib.Path | None = None
    """Its `claims/` directory, read for pinned artifacts and their hashes."""

    sources: pathlib.Path | None = None
    """A directory of per-source YAML with identifiers already resolved."""

    def resolved(self, field: str, library: pathlib.Path) -> pathlib.Path | None:
        """One configured path, expanded and made absolute against the library."""
        value = getattr(self, field)
        if value is None:
            return None
        p = pathlib.Path(value).expanduser()
        return p if p.is_absolute() else (library / p).resolve()


class LibraryConfig(BaseModel):
    """Everything `papers.yaml` declares."""

    model_config = ConfigDict(extra="allow")

    papers: dict[str, PaperConfig] = Field(default_factory=dict)
    """Papers by name. The name becomes the key under a record's `cited_by`."""


def config_path(library: pathlib.Path | None = None) -> pathlib.Path:
    return (library or paths.home()) / CONFIG_NAME


def load(library: pathlib.Path | None = None) -> LibraryConfig:
    """Read `papers.yaml`, or return an empty config when the library has none."""
    library = library or paths.home()
    p = config_path(library)
    if not p.exists():
        return LibraryConfig()
    try:
        raw = yaml.safe_load(p.read_text()) or {}
    except yaml.YAMLError as e:
        raise ClaimFileError(p, f"not valid YAML: {e}") from e
    try:
        return LibraryConfig.model_validate(raw)
    except ValidationError as e:
        first = e.errors()[0]
        where = ".".join(str(x) for x in first["loc"]) or "(top level)"
        raise ClaimFileError(p, f"{where}: {first['msg']}") from e


def save(cfg: LibraryConfig, library: pathlib.Path | None = None) -> pathlib.Path:
    """Write `papers.yaml`, with a header saying what it is."""
    library = library or paths.home()
    p = config_path(library)
    body = {
        "papers": {
            name: {k: str(v) for k, v in paper.model_dump(exclude_none=True).items()}
            for name, paper in cfg.papers.items()
        }
    }
    p.write_text(
        "# Papers that cite into this library, and where their bibliographies live.\n"
        "# Paths may be absolute, use ~, or be relative to this directory.\n"
        "# `citations build` reads this; nothing writes to it automatically.\n"
        + yaml.safe_dump(body, sort_keys=True, allow_unicode=True, width=100)
    )
    return p
