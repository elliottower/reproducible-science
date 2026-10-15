"""What `repro bot check` finds on a pull request: one finding per assertion that fails or went
stale, as `repro ci claims` and `repro ci reruns` decide them.

Built from `claims.record.check_records`, the records `repro export` writes, so an outcome here
is the outcome there. An assertion is a finding where its record says `mismatch`, `not-found`
or `error`, the outcomes `repro export sarif` shows as results, or where the commands upstream
of what it reads are `stale`. An inferred assertion's record says `not-checked` and is never a
finding. Executes nothing and reaches no network.

The file this writes crosses from a workflow that ran with a read-only token to one that
writes, so it is read back through `Findings.model_validate_json` and nothing in it is trusted
to name the pull request: `repro bot post` checks the number against the run's head commit.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import posixpath
from typing import Annotated, Literal

from claims.export.sarif import _fingerprint
from claims.record import CheckType, ExportRecord, NormalizedOutcome, check_records
from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from repro.models import Freshness, Manifest

FORMAT = "repro-bot-findings/1"
#: Findings written to one file, and so comments posted for one run. A manifest can declare
#: thousands of assertions; a pull request is not the place for thousands of comments.
MAX_FINDINGS = 50
#: Characters of any one string a finding carries.
MAX_TEXT = 2000

_KEY = r"^[0-9a-f]{64}$"
_DIGEST = r"^[0-9a-f]{16}$"
_SHA = r"^[0-9a-f]{40}$"


def manifest_path(path: str) -> str:
    """A manifest's path from the top of the repository: relative, with no `..` and no
    backslash, ending `.yaml` or `.yml`. Raises ValueError for any other."""
    parts = path.split("/")
    if (
        not path.endswith((".yaml", ".yml"))
        or path.startswith("/")
        or "\\" in path
        or "\x00" in path
        or any(part in ("", ".", "..") for part in parts)
    ):
        raise ValueError(f"not a manifest's path from the top of a repository: {path!r}")
    return path


ManifestPath = Annotated[str, AfterValidator(manifest_path)]

#: The outcomes that are a finding, as `repro export sarif` makes each a result.
FAILING = (NormalizedOutcome.MISMATCH, NormalizedOutcome.NOT_FOUND, NormalizedOutcome.ERROR)


class Finding(BaseModel):
    """One assertion that fails or went stale, with what a comment on it says."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str = Field(pattern=_KEY)
    """The assertion's identity, the digest `repro export sarif` gives GitHub as its
    fingerprint: the claim's id, the assertion's kind, name and position, and what it reads.
    It does not move when a line does."""
    digest: str = Field(pattern=_DIGEST)
    """What was found: the outcome, the printed value, each stored value and the freshness.
    A comment whose digest differs is rewritten."""
    claim: str = Field(min_length=1, max_length=MAX_TEXT)
    assertion: str = Field(max_length=MAX_TEXT)
    """The assertion's kind and name, as `repro why` labels it."""
    label: str = Field(min_length=1, max_length=MAX_TEXT)
    """The claim's `where` where it has one, its id otherwise."""
    kind: Literal["mismatch", "not-found", "error", "stale"]
    printed: str | None = Field(default=None, max_length=MAX_TEXT)
    stored: str | None = Field(default=None, max_length=MAX_TEXT)
    """The value the file holds, where one file was read and a value was read from it."""
    file: str = Field(default="", max_length=MAX_TEXT)
    """The file read, from the top of the repository, and how many more where there are."""
    passage: bool = False
    """Whether the assertion is a quotation, so `printed` is a passage and not a value."""
    path: str | None = Field(default=None, max_length=MAX_TEXT)
    """The manuscript file holding the claim's sentence, from the top of the repository."""
    line: int | None = Field(default=None, ge=1)
    """The line the sentence starts on, where it is found there exactly once."""
    artifact: str = Field(default="", max_length=MAX_TEXT)
    """The text artifact a `set_aside` entry for this claim would name: the artifact of the
    claim's first quotation. Empty where the claim quotes no text."""
    text: str = Field(default="", max_length=MAX_TEXT)
    """The passage a `set_aside` entry for this claim would name."""


class Findings(BaseModel):
    """What one run of `repro bot check` found, and which pull request it ran on."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    format: Literal["repro-bot-findings/1"] = FORMAT
    pull_request: int = Field(ge=1)
    head_sha: str = Field(pattern=_SHA)
    manifest: ManifestPath = "repro.yaml"
    """The manifest checked, from the top of the repository: the file an answer of 3 or 4
    adds a `set_aside` entry to."""
    findings: tuple[Finding, ...] = Field(default=(), max_length=MAX_FINDINGS)
    more: int = Field(default=0, ge=0)
    """Findings beyond `MAX_FINDINGS`, left out of this file."""
    checked: tuple[str, ...] = ()
    """The key of every assertion checked. A comment whose key is here and not among the
    findings is on an assertion that now passes."""
    set_aside: tuple[str, ...] = ()
    """The key of every assertion whose claim's passage `repro.yaml` sets aside."""
    problem: str = Field(default="", max_length=MAX_TEXT)
    """Why nothing was checked, where nothing was. A run with a problem changes no comment."""


def _relative(path: str, base: pathlib.Path, root: pathlib.Path) -> str:
    """A path the manifest declares, named from the top of the repository where it is under
    it, and as declared otherwise."""
    resolved = (base / path).resolve()
    if resolved.is_relative_to(root):
        return resolved.relative_to(root).as_posix()
    return posixpath.normpath(path)


def _digest(record: ExportRecord) -> str:
    found = [
        record.outcome.value,
        record.native_reason,
        record.printed,
        [read.stored for read in record.reads],
        record.execution.state.value if record.execution else None,
    ]
    canonical = json.dumps(found, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def _cut(text: str | None) -> str | None:
    """A string no longer than a finding carries."""
    return text if text is None or len(text) <= MAX_TEXT else f"{text[: MAX_TEXT - 3]}..."


def _kind(record: ExportRecord) -> str | None:
    if record.outcome in FAILING:
        return record.outcome.value
    if record.execution is not None and record.execution.state is Freshness.STALE:
        return "stale"
    return None


def finding(record: ExportRecord, base: pathlib.Path, root: pathlib.Path) -> Finding | None:
    """The finding for one record, or None where the assertion neither fails nor went stale.

    `base` is the manifest's directory, which the paths it declares are relative to, and
    `root` the top of the repository, which a pull request's paths are relative to.
    """
    kind = _kind(record)
    if kind is None:
        return None
    files = [_relative(read.path, base, root) for read in record.reads if read.path]
    file = files[0] if files else ""
    if len(files) > 1:
        file += f" and {len(files) - 1} more"
    stored = record.reads[0].stored if len(record.reads) == 1 else None
    located = [passage for passage in record.claim.passages if passage.line is not None]
    own = [passage for passage in located if passage.assertion == record.assertion.index]
    where = next(iter((*own, *located)), None)
    # A passage too long to carry is not offered for `set_aside`: a cut one would not match.
    first = next((p for p in record.claim.passages if len(p.text) <= MAX_TEXT), None)
    return Finding(
        key=_fingerprint(record),
        digest=_digest(record),
        claim=_cut(record.claim.id),
        assertion=_cut(f"{record.assertion.kind} {record.assertion.name}".strip()),
        label=_cut(record.claim.where or record.claim.id),
        kind=kind,
        printed=_cut(record.printed),
        stored=_cut(stored),
        file=_cut(file),
        passage=record.check_type is CheckType.PASSAGE_PRESENCE,
        path=_relative(where.path, base, root) if where else None,
        line=where.line if where else None,
        artifact=first.artifact if first else "",
        text=first.text if first else "",
    )


def set_aside(manifest: Manifest, record: ExportRecord) -> bool:
    """Whether `repro.yaml` sets aside a passage the record's claim quotes."""
    passages = {(passage.artifact, passage.text) for passage in record.claim.passages}
    return any((entry.artifact, entry.text) in passages for entry in manifest.set_aside)


def check(manifest: Manifest, root: pathlib.Path, pull_request: int, head_sha: str) -> Findings:
    """Check every assertion in the manifest and say which fail or went stale."""
    base = manifest.path.parent.resolve() if manifest.path else root
    found, checked, aside = [], [], []
    for record in check_records(manifest):
        key = _fingerprint(record)
        checked.append(key)
        if set_aside(manifest, record):
            aside.append(key)
        elif (made := finding(record, base, root.resolve())) is not None:
            found.append(made)
    where = manifest.path.resolve() if manifest.path else root / "repro.yaml"
    return Findings(
        pull_request=pull_request,
        head_sha=head_sha,
        manifest=where.relative_to(root.resolve()).as_posix()
        if where.is_relative_to(root.resolve())
        else where.name,
        findings=tuple(found[:MAX_FINDINGS]),
        more=max(0, len(found) - MAX_FINDINGS),
        checked=tuple(checked),
        set_aside=tuple(aside),
    )


__all__ = [
    "FORMAT",
    "MAX_FINDINGS",
    "Finding",
    "Findings",
    "ManifestPath",
    "check",
    "finding",
    "manifest_path",
    "set_aside",
]
