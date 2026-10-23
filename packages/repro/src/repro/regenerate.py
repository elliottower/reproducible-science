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

**The sandbox is a directory, not a wall.** The command can still name a file in the project by
its absolute path, and `cp <project>/results/out.json results/out.json` then reproduces any
output byte for byte. Two things stand against that by default. A command whose arguments name
a path inside the project by its absolute path, or name the output's own path, is refused
before it runs: what it would read is the working tree, not the copies of its declared inputs.
And while the command runs, the pinned output is set aside under a hidden name beside it and
put back afterwards, so a command that reaches for it however it spells the path finds nothing
there, as it would in a fresh clone. Neither stops a command that copies another file holding
the same bytes. `isolate` does: the command runs under the operating system's sandbox
(`sandbox-exec` on macOS, `bwrap` on Linux) with the project's directory unreadable to it,
apart from a virtual environment inside it that the program itself lives in.

**The byte comparison is canonical, not literal.** An output carrying a timestamp or an
absolute path never reproduces byte for byte, so a record names those fields as `volatile` and
they are removed before hashing. Naming them keeps the comparison exact everywhere else, where
loosening the whole comparison would not.

Nothing here reads a claim. `repro.reproduce` supplies `read_claims`, so this module stays
below the verification engine it would otherwise have to import.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import pathlib
import platform
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable, Iterator

from claims.models import (
    ArtifactState,
    ClaimReading,
    InputReading,
    Manifest,
    Reading,
    Regeneration,
    RegenerationReason,
    RegenerationRecord,
    RegenerationState,
    Validity,
)
from claims.reruns import canonical_digest as canonical_digest
from claims.reruns import upstream as upstream

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
    """Remove the directories a message may name, for the same reason.

    The longest spelling goes first. On macOS a temporary directory is `/var/...` as named and
    `/private/var/...` resolved, and replacing the short spelling first leaves `/private.` in
    the message, which names the machine's layout and matches neither spelling again.
    """
    spellings = {spelling for place in places for spelling in (str(place.resolve()), str(place))}
    for spelling in sorted(spellings, key=len, reverse=True):
        text = text.replace(spelling, ".")
    return text.replace(str(pathlib.Path.home()), "~")


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()


def _spellings(place: pathlib.Path) -> set[str]:
    """The ways an argument can name a directory: as given, resolved, and from `~`."""
    found = {str(place), str(place.resolve())}
    home = pathlib.Path.home()
    for spelled in tuple(found):
        if pathlib.Path(spelled).is_relative_to(home):
            found.add("~/" + pathlib.Path(spelled).relative_to(home).as_posix())
    return found


def names_the_project(
    command: tuple[str, ...], root: pathlib.Path, output: pathlib.Path
) -> str | None:
    """Why an argument of `command` reaches past its sandbox, or None where none does.

    An argument naming a path inside the project by its absolute path reads the working tree,
    so what the command is handed is not the copy of a declared input, and a command that
    copies the pinned output that way reproduces it whatever the code does. An argument naming
    the output's own absolute path is the same thing said directly. The program itself, the
    first argument, may live in the project: a virtual environment inside it is the ordinary
    place for an interpreter.
    """
    inside = _spellings(root)
    outputs = _spellings(output)
    for position, argument in enumerate(command):
        if any(spelled in argument for spelled in outputs):
            return f"argument {position + 1} names the output's own path"
        if position == 0:
            continue
        for spelled in inside:
            if argument == spelled or f"{spelled}{os.sep}" in argument:
                return (
                    f"argument {position + 1} names a path inside the project by its absolute "
                    "path, so the command would read the working tree and not the declared "
                    "inputs; name the file relative to the project"
                )
    return None


#: Where a pinned output waits while its command runs: beside it, so the move is a rename.
SET_ASIDE = ".{name}.repro-set-aside"


def waiting_place(output: pathlib.Path) -> pathlib.Path:
    return output.with_name(SET_ASIDE.format(name=output.name))


@contextlib.contextmanager
def set_aside(output: pathlib.Path) -> Iterator[pathlib.Path | None]:
    """Move the pinned output out of its place for the length of the block, and put it back.

    A fresh clone of a project whose outputs are not committed has none, and a command that
    regenerates its output does not need it. A command that copies it does, and finds nothing.
    Yields where it waits, or None where there was no file to move. The file is put back
    however the block ends, over anything written at its path meanwhile, so the working tree
    is left as it was found.
    """
    if not output.is_file():
        yield None
        return
    waiting = waiting_place(output)
    if waiting.exists():
        raise FileExistsError(17, "File exists", str(waiting))
    os.replace(output, waiting)
    try:
        yield waiting
    finally:
        os.replace(waiting, output)


def _environment_of(program: str, root: pathlib.Path) -> tuple[pathlib.Path, ...]:
    """The virtual environment inside the project that `program` lives in, as written and
    resolved, or nothing."""
    found = shutil.which(program)
    if found is None:
        return ()
    for parent in pathlib.Path(found).absolute().parents:
        if (parent / "pyvenv.cfg").is_file() and parent.resolve().is_relative_to(root):
            return tuple(dict.fromkeys((parent.absolute(), parent.resolve())))
    return ()


#: What `isolate` needs, by the operating system it runs on.
ISOLATORS = {"Darwin": "sandbox-exec", "Linux": "bwrap"}


def isolated(
    command: tuple[str, ...], root: pathlib.Path, sandbox: pathlib.Path
) -> tuple[str, ...] | None:
    """`command` under the operating system's sandbox with the project's directory unreadable
    to it, or None where this system has no sandbox this knows how to use."""
    real = root.resolve()
    keep = _environment_of(command[0], real)
    tool = ISOLATORS.get(platform.system())
    if tool is None or shutil.which(tool) is None:
        return None
    if tool == "sandbox-exec":
        # The last rule that matches wins, so the environment is let back in after the
        # project is shut. A path is written as a JSON string, which is how the profile
        # language quotes one.
        profile = (
            "(version 1)(allow default)"
            f"(deny file-read* file-write* (subpath {json.dumps(str(real))}))"
            + "".join(f"(allow file-read* (subpath {json.dumps(str(k))}))" for k in keep)
        )
        return ("sandbox-exec", "-p", profile, *command)
    binds = [part for k in keep for part in ("--ro-bind", str(k), str(k))]
    return (
        "bwrap",
        "--dev-bind",
        "/",
        "/",
        "--tmpfs",
        str(real),
        *binds,
        "--chdir",
        str(sandbox),
        "--",
        *command,
    )


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
    isolate: bool = False,
) -> RegenerationState:
    """Run one regeneration record in a sandbox and compare what it produced.

    With `isolate`, under the operating system's sandbox with the project unreadable; a system
    with none is `failed`, `runner_unavailable`, and nothing runs."""
    root = manifest.path.parent if manifest.path else pathlib.Path.cwd()
    # Every state this returns starts from the same facts about the record, so they are set
    # once and each return says only what it adds.
    base = RegenerationState(
        regeneration_id=record.id,
        artifact_id=record.output.artifact,
        state=Regeneration.NOT_RERUN,
        reason=RegenerationReason.SKIPPED,
        expected=record.output.digest.value if record.output.digest else None,
        command=record.command,
        inputs=tuple(
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
    )

    def not_rerun(reason: RegenerationReason, detail: str) -> RegenerationState:
        return base.model_copy(update={"reason": reason, "detail": detail})

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

    # Failed, not "not re-run": a command that copies the answer out of the working tree is
    # the one thing this check exists to tell apart from a reproduction, and a policy that
    # ignores a record it chose not to run would pass it.
    if reaches := names_the_project(record.command, root, files[record.output.artifact]):
        return base.model_copy(
            update={
                "state": Regeneration.FAILED,
                "reason": RegenerationReason.COMMAND_NAMES_THE_PROJECT,
                "detail": reaches,
            }
        )

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
        # The output's folder is part of where the declaration says the file goes. A command
        # that writes `results/table.csv` and reads nothing from `results/` would otherwise
        # fail on a folder the repository has and the sandbox was never given.
        produced.parent.mkdir(parents=True, exist_ok=True)

        started = time.monotonic()

        def failed(
            source: RegenerationState, reason: RegenerationReason, detail: str
        ) -> RegenerationState:
            return source.model_copy(
                update={
                    "state": Regeneration.FAILED,
                    "reason": reason,
                    "detail": _scrub(detail, sandbox, root),
                    "duration_seconds": round(time.monotonic() - started, 3),
                }
            )

        command = record.command
        if isolate:
            wrapped = isolated(record.command, root, sandbox)
            if wrapped is None:
                wanted = ISOLATORS.get(platform.system())
                return failed(
                    base,
                    RegenerationReason.RUNNER_UNAVAILABLE,
                    f"--isolate needs {wanted}, which is not on PATH"
                    if wanted
                    else f"--isolate has no sandbox to use on {platform.system()}",
                )
            command = wrapped
            base = base.model_copy(update={"isolated": True})
        # The variable a shell reads the working directory from is the sandbox's, so `$PWD`
        # does not name the project the command was started from.
        variables = {k: v for k, v in os.environ.items() if k != "OLDPWD"} | {"PWD": str(sandbox)}
        pinned_output = files[record.output.artifact]
        waiting = waiting_place(pinned_output)
        if not isolate and waiting.exists():
            # Never moved over: that file may be the only copy of the pinned output.
            return not_rerun(
                RegenerationReason.OUTPUT_ALREADY_SET_ASIDE,
                f"{_shown(waiting, root)} is there already, left by a `repro reproduce` that "
                f"was interrupted or is still running; if none is running, move it back to "
                f"{_shown(pinned_output, root)}",
            )
        # Under `isolate` the project is out of reach already, and nothing in it is moved.
        hiding = contextlib.nullcontext(None) if isolate else set_aside(pinned_output)
        moved = not isolate and pinned_output.is_file()
        try:
            with hiding:
                completed = subprocess.run(
                    command,
                    cwd=sandbox,
                    env=variables,
                    capture_output=True,
                    text=True,
                    timeout=record.timeout_seconds,
                    check=False,
                )
        except FileNotFoundError:
            return failed(
                base, RegenerationReason.RUNNER_UNAVAILABLE, f"{command[0]} is not on PATH"
            )
        except subprocess.TimeoutExpired:
            return failed(
                base.model_copy(update={"executed": True}),
                RegenerationReason.COMMAND_TIMED_OUT,
                f"exceeded {record.timeout_seconds:g}s",
            )

        written = sorted(
            path.relative_to(sandbox).as_posix()
            for path in sandbox.rglob("*")
            if path.is_file() and path.resolve() not in placed and path.resolve() != produced
        )
        more = len(written) - MAX_UNDECLARED
        ran = base.model_copy(
            update={
                "executed": True,
                "exit_code": completed.returncode,
                "stdout_digest": _digest(completed.stdout or ""),
                "stderr_digest": _digest(completed.stderr or ""),
                "undeclared_outputs": (
                    *written[:MAX_UNDECLARED],
                    *((f"... and {more} more",) if more > 0 else ()),
                ),
            }
        )

        if completed.returncode != 0:
            said = (completed.stderr or completed.stdout or "").strip()
            tail = said.splitlines()
            # Said only where the command's own words name the file, so an ordinary failure
            # is not explained by something it had nothing to do with.
            note = (
                f"; {pinned_output.name} was set aside while it ran, as a fresh clone lacks it"
                if moved and pinned_output.name in said
                else ""
            )
            return failed(
                ran,
                RegenerationReason.COMMAND_FAILED,
                f"exit {completed.returncode}: {tail[-1] if tail else 'no output'}{note}",
            )
        if not produced.is_file():
            # Exit 0 and nothing written is not a pass, and is not a difference either: there is
            # no output to differ.
            return failed(
                ran,
                RegenerationReason.OUTPUT_NOT_PRODUCED,
                f"the command wrote nothing to {produced.name}",
            )

        # Where a record names volatile fields, the digest it pins is the canonical one, since
        # the raw bytes could never match. Either way the byte comparison is exact.
        actual = canonical_digest(produced, record.volatile).value
        expected = record.output.digest.value
        ran = ran.model_copy(
            update={"actual": actual, "duration_seconds": round(time.monotonic() - started, 3)}
        )
        if actual == expected:
            return ran.model_copy(
                update={
                    "state": Regeneration.REPRODUCED,
                    "reason": RegenerationReason.OUTPUT_MATCHES,
                    "bytes_identical": True,
                }
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
    return ran.model_copy(
        update={
            "state": state,
            "reason": reason,
            "detail": detail,
            "bytes_identical": False,
            "claims": tuple(
                r.model_copy(update={"detail": _scrub(r.detail, sandbox, root)}) for r in readings
            ),
        }
    )
