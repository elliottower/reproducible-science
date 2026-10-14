"""SciTeX Clew's exported claims, read into check records.

Clew (https://github.com/ywatanabe1989/scitex-clew) registers a claim against a manuscript
line and a source file, records the file's sha256 and the session that wrote it, and verifies
the claim by re-hashing the file and walking the sessions upstream of it. It writes what it
holds to `.scitex/clew/runtime/claims.json`, a regenerable export of its host store. This
module reads that file and nothing else: no Clew code is imported or copied, and Clew is
never run. The store is not read.

Clew's check is on the file, not on the value: `claim_value` is never compared with anything,
so no record written here is a `value-comparison`, and `claim_value` travels as written in a
field of its own and is never parsed. A claim becomes one record of each check Clew's stored
status says ran:

    registered, superseded   artifact-identity, not-checked
    missing                  artifact-identity, not-checked; the file was absent
    mismatch                 artifact-identity, mismatch; the chain was not walked
    suspect                  artifact-identity, match; and lineage-check, mismatch
    verified                 artifact-identity, match; and lineage-check, match where Clew's
                             resolved status is `verified` too, and not-checked where its chain
                             flags resolve it to `exception`, `frozen` or `unsourced`

Clew writes `verified_at` and `registered_at` as naive local time. A record's time carries an
offset, and the offset of the host that ran Clew is not in the file, so a naive time is refused
unless the caller states the offset. UTC is never assumed. Paths are written relative to the
project root; a path outside it is written as its file name, with a warning on the record, and
an absolute path is never written.
"""

from __future__ import annotations

import collections
import datetime
import hashlib
import json
import pathlib
import re
from typing import Any

from pydantic import AwareDatetime, BaseModel, ConfigDict, ValidationError

from claims.exceptions import ReproError
from claims.models import Digest, Validity
from claims.record import (
    AssertionRef,
    Checker,
    CheckType,
    ClaimRef,
    ExportRecord,
    FileRead,
    ManifestRef,
    NormalizedOutcome,
)

READER = "claims from-clew"
CHECKER = "scitex-clew"

#: The export versions this reader was written against. Clew's `_export.py` at 44b9426 writes
#: "1.4"; an earlier or later version may give a field another meaning and is refused.
SCHEMA_VERSIONS = frozenset({"1.4"})

#: Where Clew writes the export under a project root.
RUNTIME = (".scitex", "clew", "runtime")

#: Clew's stored statuses, each with the outcome of the file-hash check it records.
IDENTITY: dict[str, NormalizedOutcome] = {
    "verified": NormalizedOutcome.MATCH,
    "suspect": NormalizedOutcome.MATCH,
    "mismatch": NormalizedOutcome.MISMATCH,
    "missing": NormalizedOutcome.NOT_CHECKED,
    "registered": NormalizedOutcome.NOT_CHECKED,
    "superseded": NormalizedOutcome.NOT_CHECKED,
}

#: The stored statuses under which Clew walked the session chain.
WALKED = frozenset({"verified", "suspect"})

_IDENTITY_REASONS = {
    "verified": "the source file's sha256 was the one recorded at registration",
    "suspect": "the source file's sha256 was the one recorded at registration",
    "mismatch": "the source file's sha256 was not the one recorded at registration",
    "missing": "the source file was absent when Clew verified the claim",
    "registered": "Clew has not verified the claim",
    "superseded": "a later claim superseded this one",
}

_OFFSET = re.compile(r"(?P<sign>[+-])(?P<hours>\d{2}):(?P<minutes>\d{2})")


class ClewError(ReproError):
    """A Clew export could not be read into check records."""


class ClewClaim(BaseModel):
    """One claim of the export, in Clew's field names. Fields this reader does not name are
    kept, and not read."""

    model_config = ConfigDict(frozen=True, extra="allow")

    claim_id: str
    file_path: str
    line_number: int | None = None
    claim_type: str
    claim_value: Any = None
    source_session: str | None = None
    source_file: str | None = None
    source_hash: str | None = None
    registered_at: str | None = None
    verified_at: str | None = None
    status: str
    resolved_status: str | None = None
    grounded: bool | None = None
    chain_has_exception: bool = False
    chain_has_frozen: bool = False
    exception_reasons: tuple[str, ...] = ()


class Attestation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    tool: str = CHECKER
    version: str
    url: str = ""


class ClaimsExport(BaseModel):
    """`claims.json`, as far as this reader reads it."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    schema_version: str
    generated_at: AwareDatetime
    attestation: Attestation
    claims: tuple[ClewClaim, ...]


def offset(text: str) -> datetime.timezone:
    """A UTC offset written `+HH:MM` or `-HH:MM`."""
    found = _OFFSET.fullmatch(text)
    if found is None or int(found["hours"]) > 23 or int(found["minutes"]) > 59:
        raise ClewError(f"{text!r} is not an offset; write it +HH:MM or -HH:MM")
    delta = datetime.timedelta(hours=int(found["hours"]), minutes=int(found["minutes"]))
    return datetime.timezone(-delta if found["sign"] == "-" else delta)


def _parsed(text: str, field: str, claim_id: str) -> datetime.datetime:
    try:
        return datetime.datetime.fromisoformat(text)
    except ValueError as e:
        raise ClewError(f"claim {claim_id}: {field} {text!r} is not an ISO 8601 time") from e


def _aware(
    text: str | None, field: str, claim_id: str, given: datetime.timezone | None
) -> datetime.datetime | None:
    if text is None:
        return None
    when = _parsed(text, field, claim_id)
    if when.tzinfo is None:
        if given is None:
            raise ClewError(f"claim {claim_id}: {field} is naive")
        when = when.replace(tzinfo=given)
    return when


def _naive(claims: tuple[ClewClaim, ...]) -> list[str]:
    return [
        claim.claim_id
        for claim in claims
        for text, field in (
            (claim.verified_at, "verified_at"),
            (claim.registered_at, "registered_at"),
        )
        if text is not None and _parsed(text, field, claim.claim_id).tzinfo is None
    ]


def project_root(path: pathlib.Path) -> pathlib.Path:
    """The project an export at Clew's default place belongs to: the folder holding `.scitex`."""
    folder = path.absolute().parent
    if folder.parts[-len(RUNTIME) :] != RUNTIME:
        raise ClewError(
            f"{path} is not at {'/'.join(RUNTIME)}/claims.json under a project, so its project "
            "root is not known: give --root"
        )
    return folder.parents[len(RUNTIME) - 1]


def _relative(path: str, roots: tuple[pathlib.PurePosixPath, ...]) -> tuple[str, bool]:
    """A path from the project root, and whether it lay outside it and was cut to its name."""
    written = pathlib.PurePosixPath(path)
    if not written.is_absolute():
        return (written.name, True) if ".." in written.parts else (written.as_posix(), False)
    for root in roots:
        if written.is_relative_to(root):
            return written.relative_to(root).as_posix(), False
    return written.name, True


def _manifest(path: pathlib.Path, raw: bytes) -> ManifestRef:
    here, resolved = pathlib.Path.cwd().resolve(), path.resolve()
    named = resolved.relative_to(here).as_posix() if resolved.is_relative_to(here) else path.name
    return ManifestRef(path=named, digest=hashlib.sha256(raw).hexdigest())


def _read(claim: ClewClaim, source: str) -> FileRead:
    if claim.status == "missing":
        validity = Validity.ARTIFACT_ABSENT
    elif not claim.source_hash:
        validity = Validity.UNPINNED_ARTIFACT
    else:
        # The export carries the hash Clew recorded and not the one it computed, so neither
        # authoritative nor broken pin can be stated: each needs both digests.
        validity = None
    return FileRead(
        artifact=source, path=source, validity=validity, pinned=claim.source_hash or None
    )


def _lineage(claim: ClewClaim) -> tuple[NormalizedOutcome, str, str]:
    """The outcome, the native word and the reason of a walk of the session chain."""
    resolved = claim.resolved_status or claim.status
    if claim.status == "suspect":
        return (
            NormalizedOutcome.MISMATCH,
            resolved,
            "the sessions upstream of the source file did not verify",
        )
    if resolved == "verified":
        return (
            NormalizedOutcome.MATCH,
            resolved,
            "the sessions upstream of the source file verified",
        )
    return (
        NormalizedOutcome.NOT_CHECKED,
        resolved,
        f"the sessions upstream of the source file verified, and Clew resolves the claim to "
        f"{resolved}: its chain holds a node it does not verify itself",
    )


def records(
    path: pathlib.Path,
    root: pathlib.Path | None = None,
    given: datetime.timezone | None = None,
) -> tuple[ExportRecord, ...]:
    """One record per check each claim of a Clew export records, in the export's order.

    `root` is the project the paths are made relative to: the folder holding `.scitex` where
    none is given. `given` is the UTC offset of the host that wrote the export's naive times,
    which are refused without it.
    """
    try:
        raw = path.read_bytes()
    except OSError as e:
        raise ClewError(f"{path} could not be read: {e}") from e
    try:
        document = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ClewError(f"{path} is not JSON: {e}") from e
    version = document.get("schema_version") if isinstance(document, dict) else None
    if version not in SCHEMA_VERSIONS:
        raise ClewError(
            f"{path} is a Clew export of schema {version!r}; this reader reads "
            f"{', '.join(sorted(SCHEMA_VERSIONS))}"
        )
    try:
        export = ClaimsExport.model_validate(document)
    except ValidationError as e:
        raise ClewError(f"{path} is not a Clew claims export: {e}") from e

    if given is None and (naive := _naive(export.claims)):
        raise ClewError(
            f"{len(naive)} claims in {path} carry a time with no UTC offset, which Clew writes "
            f"in the local time of the host that ran it (first: {naive[0]}); give that host's "
            "offset with --offset +HH:MM"
        )

    base = root if root is not None else project_root(path)
    roots = tuple(
        dict.fromkeys(pathlib.PurePosixPath(p) for p in (base.absolute(), base.resolve()))
    )
    checker = Checker(name=CHECKER, version=export.attestation.version, url=export.attestation.url)
    manifest = _manifest(path, raw)

    found = []
    for claim in export.claims:
        where, outside = _relative(claim.file_path, roots)
        if claim.line_number:
            where = f"{where}:L{claim.line_number}"
        reads, warnings = (), []
        if outside:
            warnings.append("the manuscript lies outside the project root; named by its file")
        if claim.source_file:
            source, cut = _relative(claim.source_file, roots)
            reads = (_read(claim, source),)
            if cut:
                warnings.append("the source file lies outside the project root; named by its file")
        verified_at = _aware(claim.verified_at, "verified_at", claim.claim_id, given)
        registered_at = _aware(claim.registered_at, "registered_at", claim.claim_id, given)
        common = {
            "checker": checker,
            "checked_at": verified_at or export.generated_at,
            "manifest": manifest,
            "claim": ClaimRef(
                id=claim.claim_id,
                where=where,
                digest=Digest.of_text(f"{claim.claim_id}\x00\x00{where}").value,
            ),
            "reads": reads,
            "warnings": tuple(warnings),
            "claim_value": claim.claim_value,
            "source_session": claim.source_session,
            "clew": {
                "status": claim.status,
                "resolved_status": claim.resolved_status,
                "registered_at": registered_at.isoformat() if registered_at else None,
                "grounded": claim.grounded,
                "chain_has_exception": claim.chain_has_exception,
                "chain_has_frozen": claim.chain_has_frozen,
                "exception_reasons": list(claim.exception_reasons),
            },
        }
        if not claim.source_file:
            identity = NormalizedOutcome.NOT_CHECKED
            reason = "the claim names no source file, so Clew checked none"
        else:
            identity = IDENTITY.get(claim.status, NormalizedOutcome.NOT_CHECKED)
            reason = _IDENTITY_REASONS.get(claim.status, "a status this reader does not know")
        found.append(
            ExportRecord(
                **common,
                assertion=AssertionRef(kind=claim.claim_type, name="source", index=0),
                check_type=CheckType.ARTIFACT_IDENTITY,
                outcome=identity,
                native_outcome=claim.status,
                native_reason=reason,
            )
        )
        if claim.source_file and claim.status in WALKED:
            outcome, word, why = _lineage(claim)
            found.append(
                ExportRecord(
                    **common,
                    assertion=AssertionRef(kind=claim.claim_type, name="lineage", index=1),
                    check_type=CheckType.LINEAGE_CHECK,
                    outcome=outcome,
                    native_outcome=word,
                    native_reason=why,
                )
            )
    return tuple(found)


def summary(found: tuple[ExportRecord, ...]) -> dict[str, dict[str, int]]:
    """Records by check type and outcome."""
    tally: dict[str, collections.Counter[str]] = collections.defaultdict(collections.Counter)
    for record in found:
        tally[record.check_type.value][record.outcome.value] += 1
    return {kind: dict(counts) for kind, counts in sorted(tally.items())}
