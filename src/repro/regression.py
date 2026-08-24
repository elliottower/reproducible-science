"""Running a recorded finding against the revisions it was recorded at.

A regression entry names a repository, a revision where a finding reproduced, and optionally a
revision where it stopped. Running one checks out each revision in turn and verifies a
manifest against it.

The manifest lives in this corpus rather than in the repository under test, because a finding
is often recorded about a project that has not adopted this tool. Artifact paths in such a
manifest are relative to the repository root, and are resolved to absolute paths against the
checkout before verification, so nothing is written into the project being audited.
"""
from __future__ import annotations

import pathlib
import tempfile

import yaml
from pydantic import BaseModel, ConfigDict

from repro.corpus import DEFAULT_CACHE, CorpusEntry, FindingState, Regression, ensure
from repro.manifest import load
from repro.models import VerificationReport
from repro.verify import verify


class RevisionResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    commit: str
    available: bool
    counts: dict[str, int] = {}
    expected: dict[str, int] = {}

    @property
    def matches_expected(self) -> bool:
        return bool(self.expected) and self.counts == self.expected


class FindingResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    state: FindingState
    before: RevisionResult | None = None
    after: RevisionResult | None = None
    detail: str = ""


def _manifest_against(manifest_path: pathlib.Path, root: pathlib.Path) -> VerificationReport:
    """Verify a manifest whose artifact paths are relative to `root`.

    The rewritten copy is written to a temporary directory; the repository under test is only
    read.
    """
    raw = yaml.safe_load(manifest_path.read_text()) or {}
    for artifact in raw.get("artifacts", []):
        p = pathlib.Path(artifact["path"])
        if not p.is_absolute():
            artifact["path"] = str((root / p).resolve())
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td) / "repro.yaml"
        tmp.write_text(yaml.safe_dump(raw, sort_keys=False))
        return verify(load(tmp))


def _at(entry: Regression, revision, corpus_dir: pathlib.Path,
        cache: pathlib.Path) -> RevisionResult:
    if revision is None or not revision.commit:
        return RevisionResult(commit="", available=False)
    root = ensure(CorpusEntry(name=entry.name, repository=entry.repository,
                              commit=revision.commit, local_path=entry.local_path),
                  corpus_dir, cache)
    if root is None:
        return RevisionResult(commit=revision.commit, available=False,
                              expected=revision.expected)
    manifest = corpus_dir / revision.manifest
    if not manifest.is_file():
        return RevisionResult(commit=revision.commit, available=False,
                              expected=revision.expected)
    report = _manifest_against(manifest, root)
    return RevisionResult(commit=revision.commit, available=True,
                          counts=report.counts, expected=revision.expected)


def run(entry: Regression, corpus_dir: pathlib.Path,
        cache: pathlib.Path = DEFAULT_CACHE) -> FindingResult:
    """Check a recorded finding at the revisions it names."""
    before = _at(entry, entry.before, corpus_dir, cache)
    after = _at(entry, entry.after, corpus_dir, cache) if entry.after else None

    if not before.available:
        return FindingResult(name=entry.name, state=FindingState.UNAVAILABLE, before=before,
                             after=after, detail="the revision that showed it is unavailable")
    if not before.matches_expected:
        # The finding no longer reproduces where it was recorded. That is not a pass: either
        # it was fixed without an `after` being recorded, or the entry is wrong.
        return FindingResult(
            name=entry.name, state=FindingState.UNREPRODUCED, before=before, after=after,
            detail=f"expected {before.expected} at {before.commit[:12]}, got {before.counts}")
    if after is None:
        return FindingResult(name=entry.name, state=FindingState.OPEN, before=before,
                             detail="reproduced; no revision recorded as fixing it")
    if not after.available:
        return FindingResult(name=entry.name, state=FindingState.UNAVAILABLE, before=before,
                             after=after, detail="the revision that fixed it is unavailable")
    if after.matches_expected:
        return FindingResult(name=entry.name, state=FindingState.FIXED, before=before,
                             after=after, detail="reproduced at before, absent at after")
    return FindingResult(
        name=entry.name, state=FindingState.UNREPRODUCED, before=before, after=after,
        detail=f"expected {after.expected} at {after.commit[:12]}, got {after.counts}")


__all__ = ["RevisionResult", "FindingResult", "run"]
