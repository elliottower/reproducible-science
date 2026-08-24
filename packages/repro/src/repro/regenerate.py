"""Does the pinned code, over the pinned inputs, still produce the pinned artifact?

The ordering check asks whether a confirmatory run followed its plan. That question has no
meaning for a measurement no plan could have registered -- an exhaustive count over a
declared corpus selects no outcome, so there is nothing for a registration to fix in advance.
What can be asked of such a number is whether it is still the output of the code that claims
to produce it, and that is what this checks.

**It runs in a sandbox, not in the repository.** The declared inputs are copied into an empty
directory and the command runs there, so nothing in the working tree is written to. That also
makes the check say something extra: a command needing a file the manifest never declared
fails, which is a real defect in the declaration rather than a passing run.

**Comparison is canonical, not literal.** An output carrying a timestamp or an absolute path
never reproduces byte for byte, so a record names those fields as `volatile` and they are
removed before hashing. Naming them keeps the comparison exact everywhere else, where
loosening the whole comparison would not.
"""

from __future__ import annotations

import json
import pathlib
import shutil
import subprocess
import tempfile

from repro.models import (
    ArtifactState,
    Digest,
    Manifest,
    Regeneration,
    RegenerationReason,
    RegenerationRecord,
    RegenerationState,
    Validity,
)
from repro.resolve import resolve_pointer

_MISSING = object()


def _unchecked(
    record: RegenerationRecord, reason: RegenerationReason, detail: str
) -> RegenerationState:
    return RegenerationState(
        regeneration_id=record.id,
        artifact_id=record.output.artifact,
        state=Regeneration.UNCHECKED,
        reason=reason,
        detail=detail,
        expected=record.output.digest.value if record.output.digest else None,
    )


def _drop(document: object, pointer: str) -> object:
    """Remove one JSON Pointer's target, if it resolves. Returns the document."""
    if pointer in ("", "/"):
        return document
    parent_pointer, _, last = pointer.rpartition("/")
    parent = resolve_pointer(document, parent_pointer)
    key = last.replace("~1", "/").replace("~0", "~")
    if isinstance(parent, dict):
        parent.pop(key, None)
    elif isinstance(parent, list) and key.isdigit() and int(key) < len(parent):
        parent.pop(int(key))
    return document


def canonical_digest(path: pathlib.Path, volatile: tuple[str, ...]) -> Digest:
    """The artifact's digest, after removing any volatile fields.

    Falls back to the file's own digest where the artifact is not JSON or names no volatile
    fields, so the strict comparison stays the default.
    """
    if not volatile:
        return Digest.of_file(path)
    try:
        document = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        # Volatile fields are addressed as JSON Pointers, so a non-JSON artifact cannot have
        # them removed. Comparing the raw bytes is the honest fallback.
        return Digest.of_file(path)
    for pointer in volatile:
        document = _drop(document, pointer)
    return Digest.of_text(
        json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    )


def check(
    record: RegenerationRecord, manifest: Manifest, states: dict[str, ArtifactState]
) -> RegenerationState:
    """Run one regeneration record in a sandbox and compare what it produced."""
    if record.output.digest is None:
        return _unchecked(
            record,
            RegenerationReason.INPUT_UNPINNED,
            "the record names no expected digest for its output",
        )

    files: dict[str, pathlib.Path] = {}
    for wanted in (*record.inputs, record.output):
        artifact = manifest.artifact(wanted.artifact)
        if artifact is None:
            return _unchecked(
                record,
                RegenerationReason.INPUT_MISSING,
                f"manifest declares no artifact {wanted.artifact!r}",
            )
        files[wanted.artifact] = manifest.resolve(artifact)

    for wanted in record.inputs:
        state = states.get(wanted.artifact)
        if state is None or not state.exists:
            return _unchecked(
                record, RegenerationReason.INPUT_MISSING, f"input {wanted.artifact} is not present"
            )
        if state.validity is Validity.BROKEN_PIN:
            return _unchecked(
                record,
                RegenerationReason.INPUT_CHANGED,
                f"input {wanted.artifact} is not the file that was pinned",
            )
        if wanted.digest is None:
            return _unchecked(
                record,
                RegenerationReason.INPUT_UNPINNED,
                f"input {wanted.artifact} carries no digest in the record",
            )
        if state.actual != wanted.digest.value:
            return _unchecked(
                record,
                RegenerationReason.INPUT_CHANGED,
                f"input {wanted.artifact} holds {(state.actual or '')[:12]}, "
                f"the record names {wanted.digest.value[:12]}",
            )

    root = manifest.path.parent if manifest.path else pathlib.Path.cwd()
    with tempfile.TemporaryDirectory(prefix="repro-regen-") as scratch:
        sandbox = pathlib.Path(scratch)
        for wanted in record.inputs:
            source = files[wanted.artifact]
            try:
                target = sandbox / source.relative_to(root)
            except ValueError:
                target = sandbox / source.name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)

        try:
            completed = subprocess.run(
                record.command,
                cwd=sandbox,
                capture_output=True,
                text=True,
                timeout=record.timeout_seconds,
                check=False,
            )
        except FileNotFoundError as e:
            return _unchecked(
                record,
                RegenerationReason.RUNNER_UNAVAILABLE,
                f"{record.command[0]} is not on PATH: {e}",
            )
        except subprocess.TimeoutExpired:
            return _unchecked(
                record,
                RegenerationReason.COMMAND_TIMED_OUT,
                f"exceeded {record.timeout_seconds:g}s",
            )

        if completed.returncode != 0:
            tail = (completed.stderr or completed.stdout or "").strip().splitlines()
            return RegenerationState(
                regeneration_id=record.id,
                artifact_id=record.output.artifact,
                state=Regeneration.DIVERGED,
                reason=RegenerationReason.COMMAND_FAILED,
                expected=record.output.digest.value,
                detail=f"exit {completed.returncode}: {tail[-1] if tail else 'no output'}",
            )

        source = files[record.output.artifact]
        try:
            produced = sandbox / source.relative_to(root)
        except ValueError:
            produced = sandbox / source.name
        if not produced.is_file():
            return RegenerationState(
                regeneration_id=record.id,
                artifact_id=record.output.artifact,
                state=Regeneration.DIVERGED,
                reason=RegenerationReason.OUTPUT_NOT_PRODUCED,
                expected=record.output.digest.value,
                detail=f"the command wrote nothing to {produced.name}",
            )

        actual = canonical_digest(produced, record.volatile)

    # Where a record names volatile fields, the digest it pins is the canonical one, since
    # the raw bytes could never match. Either way the comparison is exact.
    expected = record.output.digest.value
    matched = actual.value == expected
    return RegenerationState(
        regeneration_id=record.id,
        artifact_id=record.output.artifact,
        state=Regeneration.REPRODUCED if matched else Regeneration.DIVERGED,
        reason=(
            RegenerationReason.OUTPUT_MATCHES if matched else RegenerationReason.OUTPUT_DIFFERS
        ),
        expected=expected,
        actual=actual.value,
        detail=(
            "" if matched else f"produced {actual.value[:12]}, the manifest pins {expected[:12]}"
        ),
    )


def check_all(
    manifest: Manifest, states: dict[str, ArtifactState], enabled: bool
) -> tuple[RegenerationState, ...]:
    """Every declared regeneration, or an `unchecked` state per record when not enabled."""
    if not enabled:
        return tuple(
            _unchecked(
                record,
                RegenerationReason.NOT_REQUESTED,
                "regeneration runs only when explicitly enabled",
            )
            for record in manifest.regenerations
        )
    return tuple(check(record, manifest, states) for record in manifest.regenerations)
