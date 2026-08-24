"""What can go wrong, named.

Library code raises; only the CLI catches and turns an exception into an exit code. Nothing
here calls `sys.exit` or raises `SystemExit`, so this package can be imported and driven from
inside another program -- an agent hook, a test, a notebook -- without taking the host process
down with it.

The split that matters runs through this file: an **operational** failure is an exception, and
a **scientific** outcome is a value in the report. A missing PDF extractor raises; a quotation
that is genuinely absent from its source does not. Collapsing those two is how a tool ends up
reporting that nothing failed because nothing ran.
"""

from __future__ import annotations

import pathlib


class ReproError(Exception):
    """Base for every error this package raises."""


class ManifestError(ReproError):
    """A manifest could not be read as the shape this package expects."""

    def __init__(self, path: pathlib.Path, detail: str) -> None:
        self.path = path
        self.detail = detail
        super().__init__(f"{path}: {detail}")


class ArtifactMissingError(ReproError):
    """A manifest names an artifact that is not on disk."""

    def __init__(self, artifact_id: str, path: pathlib.Path) -> None:
        self.artifact_id = artifact_id
        self.path = path
        super().__init__(f"artifact {artifact_id!r}: {path} does not exist")


class DigestMismatchError(ReproError):
    """The file on disk is not the file that was pinned."""

    def __init__(self, artifact_id: str, expected: str, actual: str) -> None:
        self.artifact_id = artifact_id
        self.expected = expected
        self.actual = actual
        super().__init__(
            f"artifact {artifact_id!r}: pinned {expected[:16]}... but found {actual[:16]}..."
        )


class BackendUnavailableError(ReproError):
    """A verifier could not run at all.

    Distinct from a verifier that ran and found nothing. Raised where the cause is the
    toolchain rather than the evidence -- a missing binary, an uninstalled package, a registry
    that answers 404 for identifiers it does not carry -- so that an infrastructure failure is
    never recorded as a claim that failed to check out.
    """

    def __init__(self, backend: str, detail: str) -> None:
        self.backend = backend
        self.detail = detail
        super().__init__(f"{backend}: {detail}")


class ArtifactUnreadableError(ReproError):
    """An artifact exists and could not be parsed into the shape a backend needs.

    Distinct from `BackendUnavailableError`, which means the toolchain is absent, and from a
    value that is simply not there, which is a finding rather than an error.
    """

    def __init__(self, path: pathlib.Path, detail: str) -> None:
        self.path = path
        self.detail = detail
        super().__init__(f"{path}: {detail}")


class UnknownEvidenceKindError(ReproError):
    """No registered verifier handles this kind of evidence."""

    def __init__(self, kind: str, known: tuple[str, ...]) -> None:
        self.kind = kind
        self.known = known
        super().__init__(f"no verifier for evidence kind {kind!r}; known: {', '.join(known)}")
