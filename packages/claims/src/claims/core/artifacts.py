"""Content addresses, and the files a manifest declares."""

from __future__ import annotations

import hashlib
import pathlib
import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_serializer

SCHEMA_VERSION = "repro/1"

_SHA256_HEX = r"^[a-f0-9]{64}$"

_COMMIT_HEX = re.compile(r"[a-f0-9]{40}")


# --------------------------------------------------------------------------------- artifacts


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

    @model_serializer(mode="wrap")
    def _omit_no_origin(self, handler):
        """Leave the field out where there is none, so a manifest that declares no origin
        dumps, and so digests, as it did before the field existed."""
        dumped = handler(self)
        if self.origin is None:
            dumped.pop("origin", None)
        return dumped

    @property
    def is_pinned(self) -> bool:
        return self.digest is not None
