"""Content addresses, and the files a manifest declares."""

from __future__ import annotations

import datetime
import enum
import hashlib
import pathlib
import re
from typing import Annotated, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_serializer,
    model_validator,
)

SCHEMA_VERSION = "repro/1"

_SHA256_HEX = r"^[a-f0-9]{64}$"

_COMMIT_HEX = re.compile(r"[a-f0-9]{40}")


# --------------------------------------------------------------------------------- artifacts


class Basis(enum.StrEnum):
    """Who states an assertion: the manifest's author, or a proposal nobody has accepted.

    A check of an inferred assertion runs as any other and reports what it found. What it
    cannot establish is that the address is the one the sentence means, which is the part an
    author vouches for and a proposal does not, so an inferred assertion is never counted as
    verified: a policy grades it as a draft, a report counts it apart, and a check record
    passes on none of its matches. A search that finds a value at one address proposes it like
    anything else; it never binds it.
    """

    DECLARED = "declared"
    """Written by the author, or read from another tool's file where that file states it. The
    default, and left out of a manifest where it holds."""
    INFERRED = "inferred"
    """Proposed by a program or a model and not yet accepted by an author. Accepting one is
    deleting the field, or recording who reviewed it under `reviewed`."""


class Review(BaseModel):
    """Who accepted an inferred assertion, and when. An assertion carrying one is counted as
    declared."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    who: str = Field(min_length=1)
    when: AwareDatetime | datetime.date


class Digest(BaseModel):
    """A content address."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    algorithm: Literal["sha256"] = "sha256"
    value: Annotated[str, Field(pattern=_SHA256_HEX)]
    """Lowercase hex. The pattern is enforced because a truncated or uppercase digest compares
    unequal to a correct one and reads, in a report, as a tampered file."""

    def __str__(self) -> str:
        return f"{self.algorithm}:{self.value}"

    @classmethod
    def of_file(cls, path: pathlib.Path) -> Digest:
        h = hashlib.sha256()
        with path.open("rb") as fh:
            for block in iter(lambda: fh.read(1 << 20), b""):
                h.update(block)
        return cls(value=h.hexdigest())

    @classmethod
    def of_text(cls, text: str) -> Digest:
        return cls(value=hashlib.sha256(text.encode("utf-8")).hexdigest())


class Origin(BaseModel):
    """The place an artifact's bytes were copied from: one file, at one commit, of one
    repository.

    An origin names immutable bytes or it names nothing. A branch moves and a short id can
    come to name two commits, so `commit` is the full 40-character id and nothing else. The
    origin is a statement about where the bytes came from; `claims origins` is what checks it,
    and `claims verify` never reads it.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    repository: str = Field(min_length=1)
    """A URL (https or ssh) or a local path. A relative path is read from the manifest's
    directory."""

    commit: str
    """The full commit id, 40 lowercase hex characters."""

    path: str
    """POSIX, relative to the root of that repository."""

    @field_validator("commit")
    @classmethod
    def _names_a_commit(cls, value: str) -> str:
        if not _COMMIT_HEX.fullmatch(value):
            raise ValueError(
                f"{value!r} is not a full commit id: an origin names one commit by its 40 "
                "lowercase hex characters, and a branch, a tag or a short id can come to name "
                "other bytes"
            )
        return value

    @field_validator("path")
    @classmethod
    def _inside_the_repository(cls, value: str) -> str:
        parts = pathlib.PurePosixPath(value).parts
        if not value or "\\" in value or value.startswith("/") or ".." in parts:
            raise ValueError(
                f"{value!r} is not a path inside a repository: it is written with `/`, "
                "relative to the repository's root, and has no `..`"
            )
        return value


class ArtifactRef(BaseModel):
    """A file a manifest names, whether or not it has been pinned.

    Separate from `PinnedArtifact` because "identified by content" and "may carry no digest"
    cannot both be true of one type. An unpinned reference is a legitimate thing to write down
    and an illegitimate thing to verify against, and the type says which it is.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    path: pathlib.Path
    digest: Digest | None = None
    media_type: str = "application/octet-stream"
    origin: Origin | None = None
    """Where the bytes were copied from, where the manifest says."""
    basis: Basis = Basis.DECLARED
    """`inferred` for a file an agent added and no author has accepted. Every assertion that
    reads it is counted as inferred, whatever its own basis, until someone records `reviewed`
    here or deletes the field."""
    reviewed: Review | None = None

    @model_serializer(mode="wrap")
    def _omit_no_origin(self, handler):
        """Leave each field out where it holds its default, so a manifest that declares none
        dumps, and so digests, as it did before the field existed."""
        dumped = handler(self)
        if self.origin is None:
            dumped.pop("origin", None)
        if self.basis is Basis.DECLARED:
            dumped.pop("basis", None)
        if self.reviewed is None:
            dumped.pop("reviewed", None)
        return dumped

    @model_validator(mode="after")
    def _a_review_is_of_an_inferred_artifact(self):
        if self.reviewed is not None and self.basis is not Basis.INFERRED:
            raise ValueError(
                f"artifact {self.id!r}: `reviewed` records who accepted an artifact an agent "
                "added; a declared one is its author's already"
            )
        return self

    @property
    def counted(self) -> Basis:
        """Declared once someone has reviewed it."""
        return Basis.DECLARED if self.reviewed is not None else self.basis

    @property
    def is_pinned(self) -> bool:
        return self.digest is not None
