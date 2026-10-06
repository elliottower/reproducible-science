"""Does the pinned code, over the pinned inputs, still produce the numbers the manuscript prints?

The ordering check asks whether a confirmatory run followed its plan. That question has no
meaning for a measurement no plan could have registered -- an exhaustive count over a
declared corpus selects no outcome, so there is nothing for a registration to fix in advance.
What can be asked of such a number is whether it is still the output of the code that claims
to produce it, and that is what this checks.

**The verdict is about the manuscript's numbers, not the output's bytes.** A re-run that lists
a directory in another order writes a different file holding every value the manuscript prints.
Where the bytes match, the record reproduced. Where they differ, the caller's `read_claims` is
handed the new file and evaluates each assertion that reads it; the record reproduced if they
all hold, and has changed if one does not. Whether the bytes matched is recorded either way.

**It runs in a sandbox, not in the repository.** The declared inputs are copied into an empty
directory and the command runs there, so nothing in the working tree is written to. That also
makes the check say something extra: a command needing a file the manifest never declared
fails, which is a real defect in the declaration rather than a passing run.

**The byte comparison is canonical, not literal.** An output carrying a timestamp or an
absolute path never reproduces byte for byte, so a record names those fields as `volatile` and
they are removed before hashing. Naming them keeps the comparison exact everywhere else, where
loosening the whole comparison would not.

Nothing here reads a claim. `repro.reproduce` supplies `read_claims`, so this module stays
below the verification engine it would otherwise have to import.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable

from repro.models import (
    ArtifactState,
    ClaimReading,
    Digest,
    InputReading,
    Manifest,
    Reading,
    Regeneration,
    RegenerationReason,
    RegenerationRecord,
    RegenerationState,
    Validity,
)
from repro.resolve import resolve_pointer

_MISSING = object()


def _inside(sandbox: pathlib.Path, source: pathlib.Path, root: pathlib.Path) -> pathlib.Path | None:
    """Where `source` belongs inside the sandbox, or None if it would land outside.

    `Path.relative_to` is lexical, so an absolute artifact path containing `..` yields a
    relative path that climbs back out, and `sandbox / that` is not inside the sandbox at all.
    Resolving both sides and re-checking containment is what actually confines it.
    """
    try:
        relative = source.resolve().relative_to(root.resolve())
    except ValueError:
        relative = pathlib.Path(source.name)
    candidate = (sandbox / relative).resolve()
    if candidate == sandbox.resolve() or sandbox.resolve() not in candidate.parents:
        return None
    return candidate


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


#: Undeclared files named in a record. A command that unpacks an archive writes thousands, and
#: the count is recorded beside the names that fit.
MAX_UNDECLARED = 50

ReadClaims = Callable[[pathlib.Path], tuple[ClaimReading, ...]]


def _shown(source: pathlib.Path, root: pathlib.Path) -> str:
    """A declared path as a record may carry it: relative to the project, or its name alone.

    A record is committed, and an absolute path names a machine and usually a person.
    """
    try:
        return source.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return source.name


def _scrub(text: str, *places: pathlib.Path) -> str:
    """Remove the directories a message may name, for the same reason."""
    for place in places:
        for spelling in {str(place.resolve()), str(place)}:
            text = text.replace(spelling, ".")
    return text.replace(str(pathlib.Path.home()), "~")


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()


def skipped(record: RegenerationRecord) -> RegenerationState:
    """The state of a record the caller chose not to run."""
    return RegenerationState(
        regeneration_id=record.id,
        artifact_id=record.output.artifact,
        state=Regeneration.NOT_RERUN,
        reason=RegenerationReason.SKIPPED,
        detail="skipped",
        expected=record.output.digest.value if record.output.digest else None,
        command=record.command,
    )


def check(
    record: RegenerationRecord,
    manifest: Manifest,
    states: dict[str, ArtifactState],
    read_claims: ReadClaims,
) -> RegenerationState:
    """Run one regeneration record in a sandbox and compare what it produced."""
    root = manifest.path.parent if manifest.path else pathlib.Path.cwd()
    known = {
        "regeneration_id": record.id,
        "artifact_id": record.output.artifact,
        "expected": record.output.digest.value if record.output.digest else None,
        "command": record.command,
        "inputs": tuple(
            InputReading(
                artifact_id=wanted.artifact,
                path=_shown(manifest.resolve(artifact), root) if artifact is not None else "",
                pinned=wanted.digest.value if wanted.digest else None,
                observed=state.actual if state is not None else None,
            )
            for wanted in record.inputs
            for artifact, state in (
                (manifest.artifact(wanted.artifact), states.get(wanted.artifact)),
            )
        ),
    }

    def not_rerun(reason: RegenerationReason, detail: str) -> RegenerationState:
        return RegenerationState(
            **known, state=Regeneration.NOT_RERUN, reason=reason, detail=detail
        )

    if record.output.digest is None:
        return not_rerun(
            RegenerationReason.OUTPUT_UNPINNED,
            "the record names no expected digest for its output",
        )

    # Copying the output in as one of its own inputs means `true` reproduces it: the file is
    # already sitting at the expected path when the comparison runs.
    if record.output.artifact in {i.artifact for i in record.inputs}:
        return not_rerun(
            RegenerationReason.OUTPUT_IS_ALSO_AN_INPUT,
            f"{record.output.artifact} is declared as both an input and the output",
        )

    files: dict[str, pathlib.Path] = {}
    for wanted in (*record.inputs, record.output):
        artifact = manifest.artifact(wanted.artifact)
        if artifact is None:
            return not_rerun(
                RegenerationReason.INPUT_MISSING,
                f"manifest declares no artifact {wanted.artifact!r}",
            )
        files[wanted.artifact] = manifest.resolve(artifact)

    for wanted in record.inputs:
        state = states.get(wanted.artifact)
        if state is None or not state.exists:
            return not_rerun(
                RegenerationReason.INPUT_MISSING, f"input {wanted.artifact} is not present"
            )
        if state.validity is Validity.BROKEN_PIN:
            return not_rerun(
                RegenerationReason.INPUT_CHANGED,
                f"input {wanted.artifact} is not the file that was pinned",
            )
        if wanted.digest is None:
            return not_rerun(
                RegenerationReason.INPUT_UNPINNED,
                f"input {wanted.artifact} carries no digest in the record",
            )
        if state.actual != wanted.digest.value:
            return not_rerun(
                RegenerationReason.INPUT_CHANGED,
                f"input {wanted.artifact} holds {(state.actual or '')[:12]}, "
                f"the record names {wanted.digest.value[:12]}",
            )

    # The record declares what it expects to produce. Nothing checked that against the
    # artifact the claims were actually read from, so a record could declare its own answer:
    # the command writes 0.11, the record expects 0.11, the paper's pinned file says 0.99, and
    # the report states the pinned code still produces the pinned artifact.
    # Naming any volatile field turned this guard off entirely, so `volatile: ["/nonexistent"]`
    # restored exactly the hole the paragraph above describes. Where a record masks volatile
    # fields the digest it pins is canonical, so the artifact has to be canonicalized the same
    # way before the two can be compared -- not exempted from comparison.
    output_state = states.get(record.output.artifact)
    if output_state is not None:
        declared = output_state.expected or output_state.actual
        if record.volatile:
            pinned = manifest.artifact(record.output.artifact)
            path = manifest.resolve(pinned) if pinned is not None else None
            # Canonicalizing needs the pinned bytes, and the file on disk is them only while it
            # still matches what the manifest pins. Where it does not, the raw digest on hand
            # cannot be compared with a canonical one, and the question is left to the run below.
            on_disk_is_pinned = output_state.expected in (None, "", output_state.actual)
            declared = (
                canonical_digest(path, record.volatile).value
                if path is not None and path.is_file() and on_disk_is_pinned
                else ""
            )
        if declared and declared != record.output.digest.value:
            return not_rerun(
                RegenerationReason.OUTPUT_NOT_THE_ARTIFACT,
                f"the record expects {record.output.digest.value[:12]} but "
                f"{record.output.artifact} is {declared[:12]}",
            )

    with tempfile.TemporaryDirectory(prefix="repro-regen-") as scratch:
        sandbox = pathlib.Path(scratch)
        placed: dict[pathlib.Path, str] = {}
        for wanted in record.inputs:
            source = files[wanted.artifact]
            target = _inside(sandbox, source, root)
            if target is None:
                return not_rerun(
                    RegenerationReason.INPUT_MISSING,
                    f"input {wanted.artifact} resolves outside the sandbox",
                )
            if target in placed:
                # Two inputs from outside the root can share a basename; the second silently
                # overwrote the first, and the command then read a file that was never
                # digest-matched to the input it stood for.
                return not_rerun(
                    RegenerationReason.INPUT_MISSING,
                    f"inputs {placed[target]} and {wanted.artifact} collide at "
                    f"{target.name} in the sandbox",
                )
            placed[target] = wanted.artifact
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)

        # Settled before the command runs: where the output would land is a fact about the
        # declaration, and a record refused for it should not have executed anything.
        produced = _inside(sandbox, files[record.output.artifact], root)
        if produced is None:
            return not_rerun(
                RegenerationReason.OUTPUT_OUTSIDE_SANDBOX,
                f"output {record.output.artifact} resolves outside the sandbox",
            )

        started = time.monotonic()

        def failed(reason: RegenerationReason, detail: str, **ran) -> RegenerationState:
            return RegenerationState(
                **known,
                state=Regeneration.FAILED,
                reason=reason,
                detail=_scrub(detail, sandbox, root),
                duration_seconds=round(time.monotonic() - started, 3),
                **ran,
            )

        try:
            completed = subprocess.run(
                record.command,
                cwd=sandbox,
                capture_output=True,
                text=True,
                timeout=record.timeout_seconds,
                check=False,
            )
        except FileNotFoundError:
            return failed(
                RegenerationReason.RUNNER_UNAVAILABLE, f"{record.command[0]} is not on PATH"
            )
        except subprocess.TimeoutExpired:
            return failed(
                RegenerationReason.COMMAND_TIMED_OUT,
                f"exceeded {record.timeout_seconds:g}s",
                executed=True,
            )

        written = sorted(
            path.relative_to(sandbox).as_posix()
            for path in sandbox.rglob("*")
            if path.is_file() and path.resolve() not in placed and path.resolve() != produced
        )
        ran = {
            "executed": True,
            "exit_code": completed.returncode,
            "stdout_digest": _digest(completed.stdout or ""),
            "stderr_digest": _digest(completed.stderr or ""),
            "undeclared_outputs": tuple(written[:MAX_UNDECLARED])
            + (
                (f"... and {len(written) - MAX_UNDECLARED} more",)
                if len(written) > MAX_UNDECLARED
                else ()
            ),
        }

        if completed.returncode != 0:
            tail = (completed.stderr or completed.stdout or "").strip().splitlines()
            return failed(
                RegenerationReason.COMMAND_FAILED,
                f"exit {completed.returncode}: {tail[-1] if tail else 'no output'}",
                **ran,
            )
        if not produced.is_file():
            # Exit 0 and nothing written is not a pass, and is not a difference either: there is
            # no output to differ.
            return failed(
                RegenerationReason.OUTPUT_NOT_PRODUCED,
                f"the command wrote nothing to {produced.name}",
                **ran,
            )

        # Where a record names volatile fields, the digest it pins is the canonical one, since
        # the raw bytes could never match. Either way the byte comparison is exact.
        actual = canonical_digest(produced, record.volatile).value
        expected = record.output.digest.value
        ran |= {"actual": actual, "duration_seconds": round(time.monotonic() - started, 3)}
        if actual == expected:
            return RegenerationState(
                **known,
                **ran,
                state=Regeneration.REPRODUCED,
                reason=RegenerationReason.OUTPUT_MATCHES,
                bytes_identical=True,
            )

        # The bytes differ. What that means depends on what the manuscript reads from them, and
        # the file exists only inside this block.
        readings = read_claims(produced)

    differs = f"produced {actual[:12]}, the manifest pins {expected[:12]}"
    changed = [r for r in readings if r.reading is Reading.CHANGED]
    unreadable = [r for r in readings if r.reading is Reading.UNREADABLE]
    if not readings:
        state, reason = Regeneration.CHANGED, RegenerationReason.NO_CLAIM_READS_OUTPUT
        detail = f"{differs}; no claim reads this file, so its bytes are all there is to compare"
    elif changed:
        state, reason = Regeneration.CHANGED, RegenerationReason.CLAIM_CHANGED
        detail = f"{len(changed)} of {len(readings)} numbers changed"
    elif unreadable:
        state, reason = Regeneration.UNCHECKED, RegenerationReason.CLAIM_UNREADABLE
        detail = f"{len(unreadable)} of {len(readings)} numbers could not be read"
    else:
        state, reason = Regeneration.REPRODUCED, RegenerationReason.CLAIMS_HOLD
        detail = f"bytes differ, {len(readings)} of {len(readings)} numbers hold"
    return RegenerationState(
        **known,
        **ran,
        state=state,
        reason=reason,
        detail=detail,
        bytes_identical=False,
        claims=tuple(
            r.model_copy(update={"detail": _scrub(r.detail, sandbox, root)}) for r in readings
        ),
    )
