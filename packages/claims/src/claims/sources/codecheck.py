"""A CODECHECK configuration file, read into a draft manifest and its open items.

A `codecheck.yml` (specification 2.0, https://codecheck.org.uk/spec/config/2.0/) lists the
output files a codechecker recreated, each with an optional comment saying what it is, and the
paper they belong to. It states no value and no sentence: it says that `table2.csv` is
"Table 2 in the paper", and not which number of the paper is which cell of the file. So the
reader states what the file states and opens an item for each of the two things a claim needs
and the file does not give:

- every output becomes an artifact, pinned by sha256 where the bundle holding it is on disk;
- every output in a format the claims backends read as a value, and whose comment does not
  say it is outside the paper, becomes a claim whose text is the comment as written, with one
  item asking for the passage of the paper it supports and one for a value the paper prints
  from it;
- a figure, a file in another format, an output the comment places outside the paper, and a
  check that declares no output files are passed over, each with the reason.

The draft is never called a certificate and carries none of a certificate's fields. The
certificate's identifier, `YYYY-NNN`, names the source a reading came from and nothing of the
draft's own: no claim, artifact or project is named by it.

A certificate is found by its identifier in a copy of the register's `register.json`, which
is pinned by its sha256 in the open items. Its configuration file is read from a local copy
of the bundle, or, asked for and for a GitHub repository only, fetched at the commit the
default branch points to, which is recorded.
"""

from __future__ import annotations

import enum
import hashlib
import json
import mimetypes
import os
import pathlib
import re
import urllib.parse
from collections.abc import Callable

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from claims import __version__
from claims.exceptions import ReproError
from claims.models import SCHEMA_VERSION, Digest
from claims.open_items import DRAFT_NAME, Need, OpenItem, Source, write_draft
from claims.sources import (
    PassedOver,
    RefusedYamlError,
    Written,
    inside,
    is_lfs_pointer,
    load_yaml,
    named,
)

READER = "claims from-codecheck"
NAME = "codecheck.yml"

#: `YYYY-NNN`, the form the specification gives a certificate's identifier.
CERTIFICATE = re.compile(r"\d{4}-\d{3}")

#: Suffixes a claims backend reads a value from: the eligibility rule of the CODECHECK claim
#: audit (`reproducible-science-codecheck`, `scripts/eligibility.py`).
VALUE = frozenset(
    {
        ".csv", ".tsv", ".psv", ".json", ".yaml", ".yml", ".xlsx", ".xlsm", ".xls", ".parquet",
        ".feather", ".arrow", ".dta", ".sav", ".zsav", ".rds", ".npy", ".npz", ".h5", ".hdf5",
        ".nc", ".db", ".sqlite", ".sqlite3",
    }
)  # fmt: skip
FIGURE = frozenset({".png", ".pdf", ".jpg", ".jpeg", ".svg", ".tif", ".tiff", ".gif", ".eps"})
TABLE_NUMBER = re.compile(r"\btab(?:le|\.)?\s*(S?\d+|[IVX]+\b)", re.IGNORECASE)
NOT_IN_PAPER = re.compile(r"not\s+in\s+(?:the\s+)?(?:manuscript|paper|article)", re.IGNORECASE)

#: `github::owner/repo`, optionally `|path/inside`.
_GITHUB = re.compile(
    r"github::(?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+)(?:\|(?P<under>.*))?"
)

Fetcher = Callable[[str], bytes]


class CodecheckError(ReproError):
    """A CODECHECK file, or the register entry naming it, could not be read as one."""


class Kind(enum.StrEnum):
    VALUE = "value"
    FIGURE = "figure"
    OTHER = "other"


class Output(BaseModel):
    """One entry of a configuration file's `manifest`, as the eligibility rule classifies it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    file: str
    comment: str
    kind: Kind
    tables: tuple[str, ...]
    """Table numbers the comment names, `2` for "Table 2"."""
    outside_paper: bool
    """The comment says the output is not in the paper."""


class RegisterEntry(BaseModel):
    """One certificate in `register.json`, in the register's own field names."""

    model_config = ConfigDict(frozen=True, extra="ignore", populate_by_name=True)

    certificate: str = Field(alias="Certificate ID")
    repository: str = Field(alias="Repository")
    repository_link: str = Field(default="", alias="Repository Link")


def _text(value: object) -> str:
    """A field the specification gives as a string, as one: a list's items joined, and a
    folded block's trailing line break dropped."""
    if isinstance(value, list):
        return "; ".join(_text(item) for item in value if item is not None)
    return "" if value is None else str(value).strip()


def classify(entry: dict) -> Output:
    file = pathlib.PurePosixPath(_text(entry.get("file"))).as_posix() if entry.get("file") else ""
    comment = _text(entry.get("comment"))
    suffix = pathlib.PurePosixPath(file).suffix.lower()
    kind = Kind.VALUE if suffix in VALUE else Kind.FIGURE if suffix in FIGURE else Kind.OTHER
    return Output(
        file=file,
        comment=comment,
        kind=kind,
        tables=tuple(sorted({match.group(1) for match in TABLE_NUMBER.finditer(comment)})),
        outside_paper=bool(NOT_IN_PAPER.search(comment)),
    )


def register_entry(register: pathlib.Path, certificate: str, digest: str | None) -> RegisterEntry:
    """The register's entry for a certificate, from a copy whose sha256 is `digest` if given."""
    try:
        raw = register.read_bytes()
    except OSError as e:
        raise CodecheckError(f"{register} could not be read: {e}") from e
    found = hashlib.sha256(raw).hexdigest()
    if digest is not None and found != digest:
        raise CodecheckError(f"{register} has sha256 {found}, not the {digest} it is pinned to")
    try:
        entries = [RegisterEntry.model_validate(row) for row in json.loads(raw)]
    except (json.JSONDecodeError, TypeError, ValidationError) as e:
        raise CodecheckError(f"{register} is not a CODECHECK register.json: {e}") from e
    matching = [entry for entry in entries if entry.certificate == certificate]
    if len(matching) != 1:
        raise CodecheckError(
            f"{register} lists certificate {certificate} {len(matching)} times, not once"
        )
    return matching[0]


def _under(entry: RegisterEntry) -> str:
    """The folder of the repository the configuration file is in, from the register."""
    _, _, under = entry.repository.partition("|")
    return under.strip("/")


def fetch_configuration(entry: RegisterEntry, fetch: Fetcher) -> tuple[bytes, str, str]:
    """A certificate's configuration file from GitHub, at the commit its default branch points
    to: the bytes, the address they were read from, and the commit."""
    found = _GITHUB.fullmatch(entry.repository)
    if found is None:
        raise CodecheckError(
            f"certificate {entry.certificate} is held at {entry.repository}; only a GitHub "
            "repository is fetched, so give a local copy of the bundle with --bundle"
        )
    owner, repo = found["owner"], found["repo"]
    try:
        head = json.loads(fetch(f"https://api.github.com/repos/{owner}/{repo}/commits/HEAD"))
        commit = str(head["sha"])
    except (ReproError, json.JSONDecodeError, KeyError, TypeError) as e:
        raise CodecheckError(f"the commit of {owner}/{repo} could not be read: {e}") from e
    under = f"{found['under'].strip('/')}/" if found["under"] else ""
    url = (
        f"https://raw.githubusercontent.com/{owner}/{repo}/{commit}/"
        f"{urllib.parse.quote(under + NAME)}"
    )
    try:
        return fetch(url), url, commit
    except ReproError as e:
        raise CodecheckError(f"{url} could not be read: {e}") from e


def _parsed(raw: bytes, where: str) -> dict:
    try:
        document = load_yaml(raw)
    except RefusedYamlError as e:
        raise CodecheckError(f"{where}: {e}") from e
    except yaml.YAMLError as e:
        raise CodecheckError(f"{where} is not valid YAML: {e}") from e
    if not isinstance(document, dict) or not isinstance(document.get("manifest"), list):
        raise CodecheckError(f"{where} has no `manifest` list, which the specification requires")
    return document


def _slug(text: str, taken: set[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "output"
    name, n = base, 2
    while name in taken:
        name, n = f"{base}-{n}", n + 1
    taken.add(name)
    return name


def _inside(file: str) -> bool:
    parts = pathlib.PurePosixPath(file).parts
    return bool(file) and not file.startswith("/") and "\\" not in file and ".." not in parts


def _artifact(output: Output, located: pathlib.Path | None, directory: pathlib.Path) -> dict:
    """The artifact for one output: its path from the draft's directory, and its sha256 where
    the file is on disk."""
    media_type = mimetypes.guess_type(output.file)[0] or "application/octet-stream"
    if located is None:
        return {"id": output.file, "path": output.file, "media_type": media_type}
    path = pathlib.Path(os.path.relpath(located.absolute(), directory.absolute())).as_posix()
    if not located.is_file():
        return {"id": output.file, "path": path, "media_type": media_type}
    return {
        "id": output.file,
        "path": path,
        "digest": {"algorithm": "sha256", "value": Digest.of_file(located).value},
        "media_type": media_type,
    }


def _items(claim_id: str, output: Output, paper: dict) -> list[OpenItem]:
    context = {
        "file": output.file,
        "comment": output.comment,
        "tables": list(output.tables),
        "paper_title": _text(paper.get("title")),
        "paper_reference": _text(paper.get("reference")),
    }
    return [
        OpenItem(
            id=f"{claim_id}/passage",
            claim=claim_id,
            need=Need.PASSAGE,
            asks=(
                "the passage of the paper this output supports, quoted from the paper, which "
                "is added as an artifact and pinned"
            ),
            context=context,
        ),
        OpenItem(
            id=f"{claim_id}/value",
            claim=claim_id,
            need=Need.VALUE,
            asks=f"a number the paper prints from {output.file}, at its address in the file",
            context=context,
        ),
    ]


def _not_read(located: pathlib.Path, root: pathlib.Path) -> str:
    """Why a file in the bundle is not to be read, or nothing where it may be."""
    if not inside(root, located):
        return "a link to a file outside the bundle, which is not followed"
    if located.is_file() and is_lfs_pointer(located):
        return "a Git LFS pointer: the file's content is not here, so it is not checked"
    return ""


def read(
    raw: bytes,
    source: Source,
    files: pathlib.Path | None,
    directory: pathlib.Path,
    repository: str = "",
    commit: str = "",
    root: pathlib.Path | None = None,
) -> Written:
    """Write the draft and the open items one configuration file gives into `directory`.

    `files` is the directory the configuration file's paths are relative to, where a copy of
    the bundle is on disk, and `root` the bundle's top, which no file read may resolve outside
    (`files` where none is given). An output found there is pinned; any other is declared
    unpinned. Nothing is written into the bundle.
    """
    root = root or files
    document = _parsed(raw, source.path)
    paper = document.get("paper") if isinstance(document.get("paper"), dict) else {}
    entries = [entry for entry in document["manifest"] if isinstance(entry, dict)]

    artifacts: list[dict] = []
    claims: list[dict] = []
    items: list[OpenItem] = []
    passed: list[PassedOver] = [
        PassedOver(
            file=str(entry),
            reason="a bare entry, not a mapping with `file`, which the specification requires",
        )
        for entry in document["manifest"]
        if not isinstance(entry, dict)
    ]
    unread: list[PassedOver] = []
    missing: list[PassedOver] = []
    taken: set[str] = set()
    if len(entries) == 1 and "file" not in entries[0]:
        # The specification's form for a check whose results were printed, not written.
        passed.append(PassedOver(file="", reason="the check declares no output files"))
        entries = []

    for output in (classify(entry) for entry in entries):
        if not _inside(output.file):
            passed.append(
                PassedOver(file=output.file, reason="not a relative path inside the bundle")
            )
            continue
        if output.file in {artifact["id"] for artifact in artifacts}:
            passed.append(PassedOver(file=output.file, reason="listed twice"))
            continue
        located = files / output.file if files is not None else None
        why = _not_read(located, root) if located is not None and root is not None else ""
        if why:
            unread.append(PassedOver(file=output.file, reason=why))
            # Declared, so the draft names it, and never pinned: its bytes are not the output.
            artifacts.append(_artifact(output, None, directory))
            continue
        artifacts.append(_artifact(output, located, directory))
        if located is None:
            reason = "no copy of the bundle is on disk, so it is declared without a pin"
            missing.append(PassedOver(file=output.file, reason=reason))
        elif not located.is_file():
            reason = f"not in the bundle at {output.file}, so it is declared without a pin"
            missing.append(PassedOver(file=output.file, reason=reason))
        if output.kind is not Kind.VALUE:
            reason = (
                "a figure, from which no backend reads a value"
                if output.kind is Kind.FIGURE
                else "a file in a format no backend reads a value from"
            )
            passed.append(PassedOver(file=output.file, reason=reason))
            continue
        if output.outside_paper:
            reason = "its comment says it is not in the paper"
            passed.append(PassedOver(file=output.file, reason=reason))
            continue
        claim_id = _slug(output.file, taken)
        claims.append({"id": claim_id, "text": output.comment or output.file})
        items += _items(claim_id, output, paper)

    provenance = {"generated_by": READER}
    if repository:
        provenance["repository"] = repository
    if commit:
        provenance["commit"] = commit
    draft = {
        "schema_version": SCHEMA_VERSION,
        "project": _text(paper.get("title")),
        "provenance": provenance,
        "artifacts": artifacts,
        "claims": claims,
    }
    written = write_draft(directory, draft, source, tuple(items))
    return Written(
        open_items=written.as_posix(),
        draft=(written.parent / DRAFT_NAME).as_posix(),
        artifacts=len(artifacts),
        pinned=sum("digest" in artifact for artifact in artifacts),
        claims=len(claims),
        items=len(items),
        passed_over=tuple(passed),
        not_checked=tuple(unread),
        unpinned=tuple(missing),
    )


def from_codecheck(
    given: str,
    directory: pathlib.Path,
    register: pathlib.Path | None = None,
    register_sha256: str | None = None,
    bundle: pathlib.Path | None = None,
    fetch: Fetcher | None = None,
) -> Written:
    """Read a configuration file, named by its path or by its certificate's identifier.

    An identifier is looked up in `register`. Its configuration file is then read from
    `bundle`, a local copy of the repository the register names, or fetched with `fetch` where
    no bundle is given. A path is read as it is, with the outputs looked for beside it unless
    `bundle` says where they are.
    """
    if CERTIFICATE.fullmatch(given) is None:
        path = pathlib.Path(given)
        try:
            raw = path.read_bytes()
        except OSError as e:
            raise CodecheckError(f"{path} could not be read: {e}") from e
        if is_lfs_pointer(path):
            raise CodecheckError(f"{path} is a Git LFS pointer, not the configuration file")
        source = _source(raw, named(path))
        return read(raw, source, bundle or path.parent, directory)

    if register is None:
        raise CodecheckError(
            f"{given} is a certificate's identifier, which is looked up in a copy of the "
            "register: give --register register.json"
        )
    entry = register_entry(register, given, register_sha256)
    pins = {"register.json": Digest.of_file(register).value}
    under = _under(entry)
    if bundle is not None:
        files = bundle / under if under else bundle
        if not _inside(f"{under}/{NAME}" if under else NAME) or not inside(bundle, files / NAME):
            raise CodecheckError(f"the register's folder {under!r} is outside {bundle}")
        try:
            raw = (files / NAME).read_bytes()
        except OSError as e:
            raise CodecheckError(f"{files / NAME} could not be read: {e}") from e
        source = _source(raw, given, pins=pins)
        return read(raw, source, files, directory, repository=entry.repository_link, root=bundle)
    if fetch is None:
        raise CodecheckError(
            f"certificate {given}'s configuration file is not on disk: give --bundle, a local "
            "copy of its repository, or --fetch"
        )
    raw, url, commit = fetch_configuration(entry, fetch)
    source = _source(raw, given, pins=pins, url=url)
    return read(raw, source, None, directory, repository=entry.repository_link, commit=commit)


def _source(raw: bytes, given: str, pins: dict[str, str] | None = None, url: str = "") -> Source:
    try:
        document = load_yaml(raw)
    except (yaml.YAMLError, RefusedYamlError):
        document = None
    version = document.get("version") if isinstance(document, dict) else None
    return Source(
        reader=READER,
        reader_version=__version__,
        format=f"CODECHECK configuration file {version or '(no version given)'}",
        path=given,
        digest=hashlib.sha256(raw).hexdigest(),
        pins=pins or {},
        url=url,
    )
