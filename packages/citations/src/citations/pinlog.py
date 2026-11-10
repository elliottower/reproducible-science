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
    rewritten    lines git history shows were taken out of the log. Taken out while the claims
                 files still hold the quotation, it fails `verify`: only an edit does that. Taken
                 out by a `git revert` of the commit that added it, or with its quotation gone
                 from the claims files too, it is a note with the way back

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
from dataclasses import dataclass

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


@dataclass(frozen=True)
class Removed:
    """A line taken out of the log, and what took it out."""

    line: str
    #: The commit that removed it, or "" where the removal is not committed yet.
    commit: str = ""
    #: The commit that added it, where the removal is a `git revert` of that commit.
    reverts: str = ""


_REVERTS = re.compile(r"This reverts commit ([0-9a-f]{7,64})")


def _diff(sha: str, claims_dir: pathlib.Path) -> tuple[list[str], list[str]]:
    said = try_run("show", "--format=", sha, "--", LOG, cwd=claims_dir) or ""
    added = [x[1:] for x in said.splitlines() if x.startswith("+") and not x.startswith("+++")]
    gone = [x[1:] for x in said.splitlines() if x.startswith("-") and not x.startswith("---")]
    return added, gone


def _changes(older: str, newer: str, claims_dir: pathlib.Path) -> list[str] | None:
    """What `git diff older newer` changes, file by file: each file's header and the lines it
    adds and removes, or None where git cannot say, as for the parent of a first commit. Kept
    by file, so lines a decoy file supplies never stand for the log's."""
    said = try_run("diff", older, newer, cwd=claims_dir)
    if said is None:
        return None
    return [
        x
        for x in said.splitlines()
        if x.startswith("diff --git ") or (x[:1] in "+-" and not x.startswith(("+++", "---")))
    ]


def _inverse(sha: str, reverted: str, claims_dir: pathlib.Path) -> bool:
    """Whether commit `sha` undid exactly what `reverted` did, in the log and in every other
    file: what `git revert` writes. A commit taking out only the log line, while the claims
    file keeps the quotation the pin added, is not a revert of the pin."""
    mine = _changes(f"{sha}^", sha, claims_dir)
    undone = _changes(reverted, f"{reverted}^", claims_dir)
    return mine is not None and undone is not None and bool(mine) and mine == undone


def _held_at(rev: str | None, claims_dir: pathlib.Path) -> set[str]:
    """The log's lines as commit `rev` holds them; empty where it holds no log."""
    said = try_run("show", f"{rev}:./{LOG}", cwd=claims_dir) if rev else None
    return set((said or "").splitlines())


def _merged_out(sha: str, parents: list[str], claims_dir: pathlib.Path) -> list[str]:
    """The lines merge `sha` took out of the log (see `rewritten`). `git show` gives a merge
    only its combined diff, which leaves out a line the merge took out, so the versions are
    read whole."""
    sides = [_held_at(p, claims_dir) for p in parents]
    base = _held_at(try_run("merge-base", "--octopus", *parents, cwd=claims_dir), claims_dir)
    lost = set().union(*sides) - _held_at(sha, claims_dir)
    taken_on_a_side = {line for side in sides for line in base - side}
    return sorted(line for line in lost - taken_on_a_side if line.strip())


def rewritten(claims_dir: pathlib.Path) -> list[Removed]:
    """Lines taken out of the log: in any commit that changed it, or since the last one, each
    with the commit that removed it and, where that commit is a `git revert` of the commit that
    added the line, that commit.

    A merge is read against its parents: a line a parent held that the merge does not was
    taken out by the merge, unless another parent lacks a line the merge base held, in which
    case that parent's own commit took it out and is read there. A log two branches added to
    therefore reads as two sets of additions. `--full-history`, so a merge that keeps one
    side's log does not hide the other side's commits. Empty outside a repository, where git
    is absent, and for a log git has never held.
    """
    log = path(claims_dir)
    held = set(log.read_text(errors="replace").splitlines()) if log.is_file() else set()
    removed: list[Removed] = []
    for entry in (
        try_run("log", "--full-history", "--format=%H %P", "--", LOG, cwd=claims_dir) or ""
    ).splitlines():
        sha, *parents = entry.split()
        if len(parents) > 1:
            removed += [Removed(line, sha) for line in _merged_out(sha, parents, claims_dir)]
            continue
        _, gone = _diff(sha, claims_dir)
        if not gone:
            continue
        message = try_run("log", "-1", "--format=%B", sha, cwd=claims_dir) or ""
        named = _REVERTS.search(message)
        reverted = try_run("rev-parse", named.group(1), cwd=claims_dir) if named else None
        # The message names a commit; only the change says whether it reverses it. A line in a
        # message is anyone's to write, and alone it turned a removal into a note.
        if reverted and not _inverse(sha, reverted, claims_dir):
            reverted = None
        put = set(_diff(reverted, claims_dir)[0]) if reverted else set()
        removed += [
            Removed(line, sha, reverted if reverted and line in put else "")
            for line in gone
            if line.strip()
        ]
    said = try_run("diff", "HEAD", "--", LOG, cwd=claims_dir) or ""
    removed += [
        Removed(x[1:])
        for x in said.splitlines()
        if x.startswith("-") and not x.startswith("---") and x[1:].strip()
    ]
    return [r for r in removed if r.line not in held]


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
