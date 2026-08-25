"""Auditing repositories other than this one, reproducibly.

A corpus entry names a repository, the revision its figures were measured at, and the digest
of every artifact that was read. The digests are what make an entry checkable; the revision is
how someone goes and gets the same bytes.

Three states, and they are reported rather than collapsed:

    measured    the repository is present at the recorded revision
    drifted     it is present at a different revision
    absent      it is not on this machine

`absent` is not a pass. A corpus evaluation that silently skipped every entry would report
nothing and look like a clean run, which is the failure this package exists to prevent.

An entry with a remote is fetched when it is not already on the machine, so a reader who
clones this repository can reproduce the figures rather than take them on trust. Fetching is a
partial clone at the pinned commit, cached between runs, and skipped entirely under
`REPRO_OFFLINE`. An entry with no remote is usable only where it already exists.
"""

from __future__ import annotations

import enum
import os
import pathlib

from provenance_core.gitref import GitError, run
from pydantic import BaseModel, ConfigDict, Field

from repro.models import Digest
from repro.provenance import of_tree


class EntryState(enum.StrEnum):
    MEASURED = "measured"
    DRIFTED = "drifted"
    ABSENT = "absent"


class ArtifactPin(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    path: str
    """Relative to the repository root."""
    sha256: str


class CorpusEntry(BaseModel):
    """One repository, at one revision, with the artifacts that were read from it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    repository: str = ""
    """Remote URL, or empty where the repository has none and exists only locally."""

    commit: str = ""
    local_path: str = ""
    """Where to look on this machine. Relative paths resolve against the corpus file."""

    artifacts: tuple[ArtifactPin, ...] = ()

    manifest: str = ""
    """A manifest to verify against this entry, relative to the corpus file. Optional: an
    entry may pin artifacts without asserting anything about them."""

    expected: dict[str, int] = Field(default_factory=dict)
    """Outcome counts the manifest produced when the entry was written. An entry carrying a
    manifest and no expectation checks that verification runs and nothing else."""

    note: str = ""

    def resolve(self, corpus_dir: pathlib.Path) -> pathlib.Path:
        p = pathlib.Path(self.local_path).expanduser()
        return p if p.is_absolute() else (corpus_dir / p).resolve()


class EntryStatus(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    state: EntryState
    expected_commit: str = ""
    actual_commit: str = ""
    dirty: bool = False
    artifacts_matching: int = 0
    artifacts_differing: tuple[str, ...] = ()
    artifacts_missing: tuple[str, ...] = ()

    @property
    def usable(self) -> bool:
        """Whether this entry can stand behind a number.

        `_is_pinned_revision` documents that a dirty tree holds bytes that exist only on that
        machine, and this ignored it: an entry at the pinned commit with uncommitted edits to
        the analysis code reported as usable, so anything the entry does not pin could differ
        from the named revision while the corpus called it reproducible.
        """
        return (
            self.state is EntryState.MEASURED
            and not self.dirty
            and not self.artifacts_differing
            and not self.artifacts_missing
        )


DEFAULT_CACHE = pathlib.Path.home() / ".cache" / "repro" / "corpus"


class FetchError(Exception):
    """A repository could not be fetched at the pinned commit."""


def offline() -> bool:
    return bool(os.environ.get("REPRO_OFFLINE"))


def locate(
    entry: CorpusEntry, base: pathlib.Path, cache: pathlib.Path = DEFAULT_CACHE
) -> pathlib.Path | None:
    """Where the repository already is on this machine, without fetching anything.

    Separate from `ensure` because looking and fetching are different operations: a run with
    the network disabled must still find a cached checkout, and reporting a present repository
    as absent because fetching was off would misstate what is on disk.
    """
    if entry.local_path:
        local = entry.resolve(base)
        if local.is_dir():
            return local
    cached = cache / entry.name
    return cached if (cached / ".git").is_dir() else None


def ensure(
    entry: CorpusEntry, base: pathlib.Path, cache: pathlib.Path = DEFAULT_CACHE
) -> pathlib.Path | None:
    """The repository on disk at the pinned commit, fetching it if it is not already here.

    Returns None when the entry cannot be obtained: no remote and not present locally, or
    fetching disabled. A caller reports that as `absent` rather than treating it as a pass.

    The clone is `--filter=blob:none`, which fetches history without file contents and
    materialises only the commit checked out. A corpus of large result repositories stays
    cheap, and any commit remains reachable without a full copy.
    """
    found = locate(entry, base, cache)
    if found is not None and _is_pinned_revision(entry, found):
        return found
    # The local checkout is at another revision, or its tree is dirty. A working tree with
    # uncommitted changes is not the revision it sits on, and verifying against it produces
    # a result nobody else can reproduce, so prefer a clean copy where one can be fetched.
    if not entry.repository or offline():
        return found

    dest = cache / entry.name
    try:
        if not (dest / ".git").is_dir():
            dest.parent.mkdir(parents=True, exist_ok=True)
            _git(
                ["clone", "--filter=blob:none", "--no-checkout", entry.repository, str(dest)],
                cwd=dest.parent,
            )
        if entry.commit:
            # Fetch the exact commit rather than a branch: a branch moves, and the point of
            # the entry is that these figures were measured at one revision.
            _git(["fetch", "--quiet", "origin", entry.commit], cwd=dest)
            _git(["checkout", "--quiet", "--force", entry.commit], cwd=dest)
        else:
            _git(["checkout", "--quiet", "--force", "HEAD"], cwd=dest)
    except FetchError:
        return None
    return dest


def _is_pinned_revision(entry: CorpusEntry, root: pathlib.Path) -> bool:
    """Whether this checkout is the revision the entry pins, with nothing uncommitted.

    Dirtiness counts. A tree at the right commit with edited files holds bytes that exist
    only on that machine, and an entry verified against them is not reproducible.
    """
    if entry.commit and not _at_commit(root, entry.commit):
        return False
    return not _dirty(root)


def _dirty(root: pathlib.Path) -> bool:
    try:
        return bool(_git(["status", "--porcelain"], root))
    except FetchError:
        return False


def _at_commit(root: pathlib.Path, commit: str) -> bool:
    try:
        return _git(["rev-parse", "HEAD"], root) == commit
    except FetchError:
        return False


def _git(args: list[str], cwd: pathlib.Path) -> str:
    """A git command whose failure is an error. Clones need longer than the shared default."""
    try:
        return run(*args, cwd=cwd, timeout=600)
    except GitError as e:
        raise FetchError(e.detail) from e


class Corpus(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    entries: tuple[CorpusEntry, ...] = ()
    path: pathlib.Path | None = Field(default=None, exclude=True)

    def status(self, fetch: bool = True) -> tuple[EntryStatus, ...]:
        base = self.path.parent if self.path else pathlib.Path.cwd()
        return tuple(self._one(e, base, fetch) for e in self.entries)

    @staticmethod
    def _one(entry: CorpusEntry, base: pathlib.Path, fetch: bool = True) -> EntryStatus:
        root = ensure(entry, base) if fetch else locate(entry, base)
        if root is None or not root.is_dir():
            return EntryStatus(
                name=entry.name, state=EntryState.ABSENT, expected_commit=entry.commit
            )
        prov = of_tree(root)
        matching, differing, missing = 0, [], []
        for pin in entry.artifacts:
            f = root / pin.path
            if not f.is_file():
                missing.append(pin.path)
            elif Digest.of_file(f).value == pin.sha256:
                matching += 1
            else:
                differing.append(pin.path)
        state = EntryState.MEASURED if prov.commit == entry.commit else EntryState.DRIFTED
        return EntryStatus(
            name=entry.name,
            state=state,
            expected_commit=entry.commit,
            actual_commit=prov.commit,
            dirty=prov.dirty,
            artifacts_matching=matching,
            artifacts_differing=tuple(differing),
            artifacts_missing=tuple(missing),
        )


__all__ = [
    "DEFAULT_CACHE",
    "ArtifactPin",
    "Corpus",
    "CorpusEntry",
    "EntryState",
    "EntryStatus",
    "FetchError",
    "ensure",
    "locate",
    "offline",
]


# ------------------------------------------------------------------------------- regressions


class FindingState(enum.StrEnum):
    """Where a recorded finding stands."""

    OPEN = "open"
    """Reproduced at the `before` commit; no `after` commit recorded yet."""
    FIXED = "fixed"
    """Reproduced at `before` and absent at `after`."""
    UNREPRODUCED = "unreproduced"
    """The `before` commit no longer shows it. Either it was fixed without recording an
    `after`, or the entry is wrong; both need a person."""
    UNAVAILABLE = "unavailable"
    """A commit named by the entry could not be obtained."""


class Revision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    commit: str = ""
    manifest: str = ""
    """Path to the manifest to verify, relative to the repository root."""
    expected: dict[str, int] = Field(default_factory=dict)
    """Outcome counts recorded when the entry was written, keyed by flattened outcome."""


class Regression(BaseModel):
    """One finding, at the revision that showed it and the revision that closed it.

    A corpus of these is the difference between a tool that runs and a tool that found
    something. An entry with no `after` is an open finding and says so, rather than being
    quietly omitted until it is convenient.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    summary: str = ""
    repository: str = ""
    """Remote URL. Empty means the repository is reachable only where it already exists, which
    `needs_remote` reports so the gap stays visible."""

    local_path: str = ""
    before: Revision = Field(default_factory=Revision)
    after: Revision | None = None

    @property
    def needs_remote(self) -> bool:
        """Whether this entry cannot be reproduced by anyone who does not already have it."""
        return not self.repository

    @property
    def state(self) -> FindingState:
        return FindingState.OPEN if self.after is None else FindingState.FIXED


class RegressionCorpus(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    findings: tuple[Regression, ...] = ()
    path: pathlib.Path | None = Field(default=None, exclude=True)

    @property
    def without_remote(self) -> tuple[str, ...]:
        """Entries a third party could not reproduce. Reported, never silently tolerated."""
        return tuple(f.name for f in self.findings if f.needs_remote)


__all__ += ["FindingState", "Regression", "RegressionCorpus", "Revision"]
