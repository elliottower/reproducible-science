"""Content addresses, and the files a manifest declares."""

from __future__ import annotations

import hashlib
import pathlib
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = "repro/1"

_SHA256_HEX = r"^[a-f0-9]{64}$"


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

    @property
    def is_pinned(self) -> bool:
        return self.digest is not None
