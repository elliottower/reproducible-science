"""What `citations pin` has recorded, so that pinning again against other bytes shows.

A claims file holds a source's sha256 and the quotations taken from it, and both can be edited
together. Change a sentence in the source, write the new sha256 into the claims file, pin a
passage that only the edited source holds, and `verify` reports every quotation found: the file
on disk matches the pin, and the pin is the one the file now names.

So `citations pin` also appends one line to `pins.jsonl` beside the claims files: the source,
the sha256 it had, a digest of the quotation, and the claims file and claim for information.
A line is keyed by the source and by the pair of sha256 and quotation, never by the claims
file's name, which a rename changes: renaming the file hid a repin. Nothing rewrites a line.
`verify` then reports

    repinned     a source naming a sha256 other than the first one the log recorded for it, or a
                 quotation the log holds only under other bytes: the source was pinned again
                 against other bytes. A new version of a paper is an honest reason, and the
                 report says which bytes each pin named
    unlogged     quotations no `citations pin` recorded against the sha256 the source names:
                 written into the file by hand
    rewritten    lines git history shows were taken out of the log, which only an edit does,
                 and which fails `verify`

The log is lines and not a chain, so two branches that each pin something merge into a log
holding both. Git is what holds the earlier versions, so a log that was never committed shows
nothing taken out of it.

The quotation is stored as a digest, not as text: the text is in the claims file already, and
a log of somebody else's sentences is a second copy of them.

The same place reads the facts about a source that is absent, which is the ordinary state of a
clone: the sha256 must be 64 hexadecimal digits and a DOI must have the shape of one. Nothing
here resolves a DOI: that needs the network, and `verify` reads no network.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import pathlib
import re

from provenance_core import exclusive_lock, try_run

#: The log's name, in the claims directory.
LOG = "pins.jsonl"

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_DOI = re.compile(r"^10\.\d{4,9}/\S+$")


def quote_digest(text: str) -> str:
    """The digest a log line holds for a quotation, of the text as a claims file reads it."""
    return hashlib.sha256(text.strip().encode()).hexdigest()


def path(claims_dir: pathlib.Path) -> pathlib.Path:
    return claims_dir / LOG


def source_key(citation: str | None, local: str | None, fallback: str) -> str:
    """What names a source in the log: its citation key, else its local path, else `fallback`."""
    return (citation or "").strip() or (local or "").strip() or fallback


def record(
    claims_file: pathlib.Path, claim: str, quote: str, sha256: str | None, source: str = ""
) -> None:
    """Append one pin to the log beside `claims_file`."""
    log = path(claims_file.parent)
    line = {
        "source": source or claims_file.name,
        "file": claims_file.name,
        "claim": claim,
        "sha256": (sha256 or "").strip().lower(),
        "quote": quote_digest(quote),
        "at": datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
    }
    with exclusive_lock(log), log.open("a") as handle:
        handle.write(json.dumps(line, sort_keys=True) + "\n")


def read(claims_dir: pathlib.Path) -> list[dict]:
    """Every line of the log that parses, in order. Empty where there is no log."""
    log = path(claims_dir)
    if not log.is_file():
        return []
    out = []
    for raw in log.read_text(errors="replace").splitlines():
        try:
            line = json.loads(raw)
        except ValueError:
            continue
        if isinstance(line, dict):
            out.append(line)
    return out


def _key(line: dict) -> str | None:
    """The source a line names. A line an earlier version wrote names only the claims file."""
    key = line.get("source") or line.get("file")
    return key if isinstance(key, str) else None


def first_pins(lines: list[dict]) -> dict[str, str]:
    """The first sha256 the log recorded for each source."""
    first: dict[str, str] = {}
    for line in lines:
        key, sha = _key(line), line.get("sha256")
        if key and isinstance(sha, str) and sha:
            first.setdefault(key, sha)
    return first


def logged(lines: list[dict]) -> dict[str, set[str]]:
    """The sha256 values each quotation digest was pinned against."""
    out: dict[str, set[str]] = {}
    for line in lines:
        quote, sha = line.get("quote"), line.get("sha256")
        if isinstance(quote, str) and isinstance(sha, str):
            out.setdefault(quote, set()).add(sha)
    return out


def rewritten(claims_dir: pathlib.Path) -> list[str]:
    """Lines taken out of the log: in any commit that changed it, or since the last one.

    One `git log -p` over the one file. A merge is not diffed by it, so a log that two branches
    added to reads as two sets of additions. Empty outside a repository, where git is absent,
    and for a log git has never held.
    """
    log = path(claims_dir)
    removed: list[str] = []
    for said in (
        try_run("log", "-p", "--format=", "--", LOG, cwd=claims_dir),
        try_run("diff", "HEAD", "--", LOG, cwd=claims_dir),
    ):
        for line in (said or "").splitlines():
            if line.startswith("-") and not line.startswith("---"):
                removed.append(line[1:])
    held = set(log.read_text(errors="replace").splitlines()) if log.is_file() else set()
    return [line for line in removed if line.strip() and line not in held]


def sha256_shape(value: str | None) -> str:
    """Why a recorded sha256 is not one, or empty where it is or where none is recorded."""
    if not (value and value.strip()):
        return ""
    if _SHA256.match(value.strip().lower()):
        return ""
    return f"sha256 `{value.strip()[:70]}` is not 64 hexadecimal digits"


def doi_shape(value: str | None) -> str:
    """Why a recorded DOI is not one, or empty where it is or where none is recorded.

    A `doi:` prefix and a resolver address are accepted and read past.
    """
    if not (value and str(value).strip()):
        return ""
    doi = str(value).strip()
    doi = re.sub(r"^(?:doi:\s*|https?://(?:dx\.)?doi\.org/)", "", doi, flags=re.I)
    if _DOI.match(doi):
        return ""
    return f"DOI `{str(value).strip()[:70]}` does not have the shape 10.NNNN/suffix"
