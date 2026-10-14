"""Whether an artifact copied from another repository is still the bytes it was copied from.

A manifest may say, for an artifact, which repository, commit and path its bytes were copied
from (`artifacts[].origin`). `claims verify` never reads that: it stays offline and compares
each file with its pin. This compares the pin with the bytes at the origin.

The bytes at `<commit>:<path>` are obtained in one of two ways and no other. A local clone,
named with `--repo URL=PATH` or by an origin whose repository is itself a local path, is read
with `git cat-file`, so what is compared is the committed blob and never the working tree.
Where no clone is given and the caller asked for the network, a public GitHub repository is
read from `raw.githubusercontent.com` at the commit. Anything else is `not_checked`, with the
reason, and is never reported as the same bytes.
"""

from __future__ import annotations

import enum
import hashlib
import pathlib
import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping

from provenance_core.gitref import clean_env
from pydantic import BaseModel, ConfigDict

from claims.exceptions import ReproError
from claims.models import ArtifactRef, Digest, Manifest, Origin

#: Seconds to wait for one file from GitHub.
FETCH_TIMEOUT = 30.0

#: `https://github.com/<owner>/<repo>`, `git@github.com:<owner>/<repo>` and
#: `ssh://git@github.com/<owner>/<repo>`, each with or without `.git`.
_GITHUB = re.compile(
    r"(?:https://github\.com/|git@github\.com:|ssh://git@github\.com/)"
    r"(?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+?)(?:\.git)?/?"
)

#: A URL with a scheme, or the scp-like `user@host:path` git accepts for ssh.
_REMOTE = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://.*|[^/\s]+@[^/\s:]+:.*")


class OriginState(enum.StrEnum):
    """What was found at an artifact's declared origin."""

    SAME = "same"
    """The bytes at the origin have the artifact's pinned digest."""
    DIFFERS = "differs"
    """The bytes at the origin have another digest."""
    ABSENT = "absent"
    """The commit is there and the path is not in it."""
    UNKNOWN_COMMIT = "unknown_commit"
    """The clone read holds no such commit."""
    NOT_CHECKED = "not_checked"
    """No bytes were obtained from the origin, or there was no pin to compare them with."""


class OriginCheck(BaseModel):
    """One artifact's origin, and what was found there."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    artifact_id: str
    path: str
    """The artifact's path as the manifest declares it."""
    origin: Origin
    state: OriginState
    reason: str
    """Why the state is what it is, in words."""
    read_from: str = ""
    """The clone or the URL the bytes were read from. Empty where nothing was read."""
    pinned: str | None = None
    at_origin: str | None = None
    """The sha256 of the bytes at the origin, where they were obtained."""
    on_disk: str | None = None
    """The sha256 of the file at the declared path. None where nothing is there."""

    @property
    def disk_disagrees(self) -> bool:
        """The file on disk is not the pinned bytes, which `claims verify` reports as a broken
        pin or an absent artifact. Said here so a `same` is not read as a statement about it."""
        return self.pinned is not None and self.on_disk != self.pinned


class OriginsReport(BaseModel):
    """Every artifact that declares an origin, each with what was found there."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    manifest_digest: str
    origins: tuple[OriginCheck, ...] = ()
    without_origin: tuple[str, ...] = ()
    """Artifacts that declare no origin, by id. Not checked, because nothing is claimed."""

    @property
    def counts(self) -> dict[str, int]:
        tally: dict[str, int] = {}
        for check in self.origins:
            tally[check.state.value] = tally.get(check.state.value, 0) + 1
        return tally


class OriginUnreadableError(ReproError):
    """The bytes at an origin could not be obtained. Raised by a fetcher, and reported as
    `not_checked` with this detail."""

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)


#: Takes a URL, returns the bytes there, or raises `OriginUnreadableError`.
Fetcher = Callable[[str], bytes]


def fetch_url(url: str) -> bytes:
    """The bytes at a URL, read with the standard library: no credentials, no headers of our
    own, and a timeout."""
    try:
        with urllib.request.urlopen(url, timeout=FETCH_TIMEOUT) as response:
            return response.read()
    except urllib.error.HTTPError as e:
        raise OriginUnreadableError(f"{url} answered {e.code} {e.reason}") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise OriginUnreadableError(f"{url} could not be read: {e}") from e


def _same_repository(name: str) -> str:
    """A repository string with the spellings that name one repository made one."""
    return name.rstrip("/").removesuffix(".git")


def raw_github_url(origin: Origin) -> str | None:
    """Where GitHub serves the file at the commit, or None for a repository not on GitHub."""
    found = _GITHUB.fullmatch(origin.repository)
    if found is None:
        return None
    return (
        f"https://raw.githubusercontent.com/{found['owner']}/{found['repo']}/"
        f"{origin.commit}/{urllib.parse.quote(origin.path)}"
    )


def _git(clone: pathlib.Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", "-C", str(clone), *args], capture_output=True, env=clean_env(), check=False
    )


def _from_clone(origin: Origin, clone: pathlib.Path) -> bytes | tuple[OriginState, str]:
    """The committed bytes at the origin in a local clone, or the state that says why not."""
    try:
        if _git(clone, "rev-parse", "--git-dir").returncode != 0:
            return OriginState.NOT_CHECKED, f"{clone} is not a git repository"
    except FileNotFoundError:
        return OriginState.NOT_CHECKED, "git is not installed"
    commit = f"{origin.commit}^{{commit}}"
    if _git(clone, "rev-parse", "--verify", "--quiet", commit).returncode != 0:
        return (
            OriginState.UNKNOWN_COMMIT,
            f"the clone at {clone} holds no commit {origin.commit}; fetch it, or name a "
            "clone that has it",
        )
    blob = f"{origin.commit}:{origin.path}"
    kind = _git(clone, "cat-file", "-t", blob)
    if kind.returncode != 0:
        return OriginState.ABSENT, f"commit {origin.commit[:12]} has no {origin.path}"
    if kind.stdout.strip() != b"blob":
        return (
            OriginState.ABSENT,
            f"{origin.path} at commit {origin.commit[:12]} is a "
            f"{kind.stdout.decode().strip()}, not a file",
        )
    read = _git(clone, "cat-file", "blob", blob)
    if read.returncode != 0:
        detail = read.stderr.decode(errors="replace").strip()
        return OriginState.NOT_CHECKED, f"git could not read {blob}: {detail}"
    return read.stdout


def _local_clone(
    origin: Origin, clones: Mapping[str, pathlib.Path], base: pathlib.Path
) -> pathlib.Path | None:
    named = {_same_repository(url): path for url, path in clones.items()}
    if (clone := named.get(_same_repository(origin.repository))) is not None:
        return clone
    if _REMOTE.fullmatch(origin.repository):
        return None
    local = pathlib.Path(origin.repository).expanduser()
    return local if local.is_absolute() else base / local


def _check(
    artifact: ArtifactRef,
    origin: Origin,
    on_disk: str | None,
    clones: Mapping[str, pathlib.Path],
    base: pathlib.Path,
    fetcher: Fetcher | None,
) -> OriginCheck:
    pinned = artifact.digest.value if artifact.digest else None

    def found(
        state: OriginState, reason: str, read_from: str = "", got: str | None = None
    ) -> OriginCheck:
        return OriginCheck(
            artifact_id=artifact.id,
            path=artifact.path.as_posix(),
            origin=origin,
            state=state,
            reason=reason,
            read_from=read_from,
            pinned=pinned,
            at_origin=got,
            on_disk=on_disk,
        )

    clone = _local_clone(origin, clones, base)
    if clone is not None:
        read_from = str(clone)
        content = _from_clone(origin, clone)
        if isinstance(content, tuple):
            return found(*content, read_from)
    else:
        url = raw_github_url(origin)
        if fetcher is None:
            return found(
                OriginState.NOT_CHECKED,
                "no clone of this repository was given"
                + (", and the network was not asked for (--fetch)" if url else ""),
            )
        if url is None:
            return found(
                OriginState.NOT_CHECKED,
                "no clone of this repository was given, and only a GitHub repository is fetched",
            )
        read_from = url
        try:
            content = fetcher(url)
        except OriginUnreadableError as e:
            return found(
                OriginState.NOT_CHECKED,
                f"{e.detail}; a missing path, a commit GitHub does not have and a private "
                "repository all answer so, and a clone tells them apart",
                read_from,
            )

    got = hashlib.sha256(content).hexdigest()
    if pinned is None:
        return found(
            OriginState.NOT_CHECKED,
            "the artifact has no pinned digest to compare the origin's bytes with",
            read_from,
            got,
        )
    if got == pinned:
        return found(OriginState.SAME, "the origin's bytes have the pinned digest", read_from, got)
    return found(
        OriginState.DIFFERS, "the origin's bytes do not have the pinned digest", read_from, got
    )


def origins(
    manifest: Manifest,
    clones: Mapping[str, pathlib.Path] | None = None,
    fetcher: Fetcher | None = None,
) -> OriginsReport:
    """Compare each artifact that declares an origin with the bytes there.

    `clones` maps a repository, as an origin names it, to a local clone. `fetcher` is called
    with a URL for a GitHub repository no clone is given for; None, the default, touches no
    network. Returns facts and carries no verdict.
    """
    base = manifest.path.parent if manifest.path is not None else pathlib.Path.cwd()
    checked = []
    for artifact in manifest.artifacts:
        if artifact.origin is None:
            continue
        path = manifest.resolve(artifact)
        on_disk = Digest.of_file(path).value if path.is_file() else None
        checked.append(_check(artifact, artifact.origin, on_disk, clones or {}, base, fetcher))
    return OriginsReport(
        manifest_digest=Digest.of_text(manifest.model_dump_json()).value,
        origins=tuple(checked),
        without_origin=tuple(a.id for a in manifest.artifacts if a.origin is None),
    )


__all__ = [
    "FETCH_TIMEOUT",
    "Fetcher",
    "OriginCheck",
    "OriginState",
    "OriginUnreadableError",
    "OriginsReport",
    "fetch_url",
    "origins",
    "raw_github_url",
]
