"""Add one entry to a `.bib`, and refuse a key the file already has.

Appending an entry by hand is how a duplicate key gets into a bibliography, and BibTeX's answer
to a duplicate is non-fatal:

    Repeated entry---line 923 of file references.bib
     : @misc{mbusa2026drivepilot
    I'm skipping whatever remains of this entry

It then writes a `.bbl` with that entry missing. The next `latexmk` run reports a hundred-odd
`Citation undefined` warnings and produces a PDF with no reference list, and nothing in the
toolchain names the repeated key as the cause. That happened twice in one session on one paper;
the second time the stale `.bbl` outlived the fix and produced a third misleading build.

    citations add refs.bib --key smith2026thing --entry-file entry.bib
    citations add refs.bib --key smith2026thing < entry.bib
    citations add refs.bib --doi 10.1145/3287560.3287596
    citations add refs.bib --arxiv 2608.14611
    citations add refs.bib --doi 10.1145/3287560.3287596 --check

A key the file already defines exits non-zero, prints both entries side by side and writes
nothing. Merging them is not on offer: two entries under one key are two readings of a work, and
which fields survive is a decision for whoever wrote them.

Nothing here writes a library record. `citations build` regenerates `records/` from the
bibliographies, so a work enters the library by entering a `.bib`.
"""

from __future__ import annotations

import argparse
import collections
import itertools
import pathlib
import re
import urllib.parse
import xml.etree.ElementTree as ET
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator, model_validator

from citations import bibtex, resolve
from citations.exceptions import BibFileError, CitationsError, MetadataError
from citations.text import fold, strip_markup, surname

CROSSREF = "https://api.crossref.org/works/{}"
DATACITE = "https://api.datacite.org/dois/{}"
ARXIV = "https://export.arxiv.org/api/query?id_list={}"

ATOM = "{http://www.w3.org/2005/Atom}"
ARXIV_SCHEMA = "{http://arxiv.org/schemas/atom}"

#: Crossref's `type` for a work, and the BibTeX entry type that carries the fields it returns.
#: Anything not listed is `misc`, which demands no field a registry may not have supplied --
#: an `@article` with no journal is a warning in every style, and the warning would be ours.
BIB_KIND = {
    "journal-article": "article",
    "proceedings-article": "inproceedings",
    "book": "book",
    "monograph": "book",
    "edited-book": "book",
    "book-chapter": "incollection",
    "report": "techreport",
    "dissertation": "phdthesis",
    "posted-content": "misc",
    "dataset": "misc",
}
KNOWN_KINDS = frozenset(BIB_KIND.values())

#: Skipped when a citation key takes the first substantive word of the title.
STOPWORDS = frozenset({"a", "an", "and", "are", "for", "in", "is", "of", "on", "the", "to", "with"})

#: Characters that are markup in a `.bib` value and ordinary text in a registry payload.
LATEX_SPECIAL = {"&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#", "_": r"\_"}

#: Width of each column in the side-by-side a repeated key prints.
COLUMN = 46


# ------------------------------------------------------------------------------------ shapes


class Entry(BaseModel):
    """One `@kind{key, ...}` block: the text to write, and the two facts a duplicate check reads.

    Defined here rather than in `models.py` because that module is the boundary for the YAML this
    package reads and this is the boundary for a `.bib`. Whitespace is deliberately not stripped:
    `models._Base` sets `str_strip_whitespace`, and an entry's own trailing newline is what keeps
    it from welding to the next one.
    """

    model_config = ConfigDict(frozen=True)

    kind: str
    key: str
    text: str


class Work(BaseModel):
    """What a registry holds for one identifier, in the shape an entry is rendered from.

    Local for the reason `services.Candidate` is: it validates one kind of payload at one call
    site. It is also lossy in the opposite direction -- `Candidate` keeps folded surnames because
    it exists to match on them, this keeps every name as the registry wrote it because it is
    going into a file somebody will read.
    """

    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    source: str
    """Which registry answered: `crossref`, `datacite` or `arxiv`."""

    kind: str = "misc"
    title: str = ""
    authors: tuple[str, ...] = ()
    year: str = ""
    venue: str = ""
    publisher: str = ""
    volume: str = ""
    number: str = ""
    pages: str = ""
    doi: str = ""
    arxiv: str = ""
    primary_class: str = ""
    url: str = ""

    @field_validator("authors")
    @classmethod
    def _complete(cls, authors: tuple[str, ...]) -> tuple[str, ...]:
        """Refuse a list carrying a truncation marker.

        `and others` is BibTeX for et al., and read back literally it is a person named
        "others" -- 23 records in this library had one. A shortened list is also invisible
        downstream: `citations audit` found four author lists in one bibliography that stopped
        early with no marker at all, and a truncated list looks exactly like a complete one.
        Nothing written from here is allowed to start that.
        """
        for name in authors:
            if fold(name) in ("others", "et al"):
                raise ValueError(f"the author list ends in {name!r}, so it is not complete")
        return authors

    @model_validator(mode="after")
    def _identifies_something(self) -> Work:
        """A payload with neither a title nor an author identifies no work.

        A registry that answers with an empty envelope would otherwise render to `@misc{key,}`,
        which parses, appends and cites nothing.
        """
        if not (self.title or self.authors):
            raise ValueError("neither a title nor an author was returned")
        return self


# ------------------------------------------------------------------------------------- fetch


def _work(identifier: str, **fields: Any) -> Work:
    """A `Work`, or `MetadataError` naming the identifier and the field that failed.

    `fields` are whatever a decoded JSON payload holds, which is why they are typed as they are:
    the shape is checked by the model at runtime, and that check is the point of this function.

    A `ValidationError` reaching the CLI is a traceback out of a network response. Only
    `cli.py` turns an error into an exit code, and it catches `CitationsError`.
    """
    try:
        return Work(**fields)
    except ValidationError as e:
        first = e.errors()[0]
        where = ".".join(str(p) for p in first["loc"]) or "(top level)"
        raise MetadataError(identifier, f"{where}: {first['msg']}") from e


def _payload(url: str, identifier: str, as_json: bool) -> object:
    """One registry response, or None where the registry answered and had nothing.

    `resolve.get` is the transport: it retries the codes that mean "ask again later" and raises
    `Throttled` for a refusal, so a rate limit is never read as an identifier that does not
    exist. Collapsing those two is how a batch of sixty lookups reported sixty works as
    unfindable when Crossref had simply started refusing.
    """
    try:
        return resolve.get(url, as_json=as_json)
    except resolve.Throttled as e:
        raise MetadataError(identifier, "the registry refused to answer; try again later") from e


def _name(value: object) -> str:
    """A field a registry writes sometimes as a string and sometimes as `{"name": ...}`."""
    if isinstance(value, dict):
        return str(value.get("name") or value.get("title") or "")
    return "" if value is None else str(value)


def _crossref_author(author: dict) -> str:
    """One author as BibTeX reads a name: `Family, Given`, or a corporate name as deposited."""
    family = str(author.get("family") or "").strip()
    given = str(author.get("given") or "").strip()
    if family and given:
        return f"{family}, {given}"
    return family or str(author.get("name") or "").strip()


def from_crossref(doi: str) -> Work | None:
    """The Crossref record for a DOI, with every author it lists."""
    payload = _payload(CROSSREF.format(urllib.parse.quote(doi, safe="")), doi, as_json=True)
    message = payload.get("message") if isinstance(payload, dict) else None
    return crossref_work(message, doi) if isinstance(message, dict) else None


def crossref_work(message: dict, doi: str) -> Work:
    """One Crossref `message` as a `Work`.

    Separate from the request so the reading of a payload can be checked against a payload,
    with no network in the way and nothing monkeypatched to stand in for one.
    """
    year = ""
    # A journal publishing online ahead of print carries two legitimate years. The printed one
    # is the one a reference list prints, so it is asked for first.
    for field in ("published-print", "published-online", "issued", "created"):
        parts = ((message.get(field) or {}).get("date-parts") or [[None]])[0]
        if parts and parts[0]:
            year = str(parts[0])
            break
    return _work(
        doi,
        source="crossref",
        kind=BIB_KIND.get(str(message.get("type") or ""), "misc"),
        title=(message.get("title") or [""])[0],
        authors=tuple(n for n in (_crossref_author(a) for a in message.get("author") or []) if n),
        year=year,
        venue=(message.get("container-title") or [""])[0],
        publisher=_name(message.get("publisher")),
        volume=_name(message.get("volume")),
        number=_name(message.get("issue")),
        pages=_name(message.get("page") or message.get("article-number")),
        doi=_name(message.get("DOI")) or doi,
        url=f"https://doi.org/{doi}",
    )


def from_datacite(doi: str) -> Work | None:
    """The DataCite record for a DOI, for the DOIs Crossref does not have.

    arXiv preprints (10.48550), Zenodo deposits (10.5281), Dryad, figshare and OSF register with
    DataCite, and Crossref answers 404 for every one of them. Asking only Crossref would report a
    correct identifier as one that resolves to nothing.
    """
    payload = _payload(DATACITE.format(urllib.parse.quote(doi, safe="")), doi, as_json=True)
    data = payload.get("data") if isinstance(payload, dict) else None
    attrs = data.get("attributes") if isinstance(data, dict) else None
    return datacite_work(attrs, doi) if isinstance(attrs, dict) else None


def datacite_work(attrs: dict, doi: str) -> Work:
    """One DataCite `attributes` block as a `Work`."""
    titles = attrs.get("titles") or [{}]
    container = attrs.get("container") or {}
    kind = str((attrs.get("types") or {}).get("bibtex") or "")
    return _work(
        doi,
        source="datacite",
        kind=kind if kind in KNOWN_KINDS else "misc",
        title=_name(titles[0].get("title")),
        authors=tuple(n for n in (_datacite_creator(c) for c in attrs.get("creators") or []) if n),
        year=_name(attrs.get("publicationYear")),
        venue=_name(container.get("title")),
        publisher=_name(attrs.get("publisher")),
        volume=_name(container.get("volume")),
        doi=_name(attrs.get("doi")) or doi,
        url=f"https://doi.org/{doi}",
    )


def _datacite_creator(creator: dict) -> str:
    """One creator as a BibTeX name. DataCite often carries only `name`, in either order."""
    family = str(creator.get("familyName") or "").strip()
    given = str(creator.get("givenName") or "").strip()
    if family:
        return f"{family}, {given}" if given else family
    return str(creator.get("name") or "").strip()


def from_arxiv(identifier: str) -> Work | None:
    """The arXiv record for an identifier, with every author named.

    Names arrive as one string -- `Ashish Vaswani`, not `Vaswani, Ashish` -- and are written that
    way. BibTeX reads both forms, and guessing where a multi-word surname begins (`van
    Beethoven`, `de la Cruz`) is how a name gets filed under the wrong letter.
    """
    body = _payload(ARXIV.format(urllib.parse.quote(identifier)), identifier, as_json=False)
    if not isinstance(body, str) or not body:
        return None
    return arxiv_work(body, identifier)


def arxiv_work(body: str, identifier: str) -> Work | None:
    """One arXiv Atom feed as a `Work`, or None where it describes no paper."""
    try:
        feed = ET.fromstring(body)
    except ET.ParseError:
        return None
    entry = feed.find(f"{ATOM}entry")
    if entry is None:
        return None
    # An identifier arXiv cannot parse answers 400 with a feed holding one entry titled `Error`,
    # written by `arXiv api core`, whose `id` is an `errors#` URL rather than an abstract page.
    # Reading it would write an entry citing the error message. An identifier that is well formed
    # and unknown answers with no entry at all, which the check above catches.
    at = entry.findtext(f"{ATOM}id") or ""
    if "/abs/" not in at:
        return None
    arxiv_id = re.sub(r"v\d+$", "", at.split("/abs/")[-1])
    category = entry.find(f"{ARXIV_SCHEMA}primary_category")
    names = [
        " ".join((a.findtext(f"{ATOM}name") or "").split()) for a in entry.findall(f"{ATOM}author")
    ]
    return _work(
        identifier,
        source="arxiv",
        kind="misc",
        title=" ".join((entry.findtext(f"{ATOM}title") or "").split()),
        authors=tuple(n for n in names if n),
        year=(entry.findtext(f"{ATOM}published") or "")[:4],
        venue=" ".join((entry.findtext(f"{ARXIV_SCHEMA}journal_ref") or "").split()),
        arxiv=arxiv_id,
        primary_class=(category.get("term") or "") if category is not None else "",
        doi=(entry.findtext(f"{ARXIV_SCHEMA}doi") or "").strip(),
        url=f"https://arxiv.org/abs/{arxiv_id}",
    )


def fetch(doi: str | None, arxiv: str | None) -> Work:
    """The metadata for one identifier, or `MetadataError` saying which registries had nothing."""
    if arxiv:
        work = from_arxiv(arxiv.strip())
        if work is None:
            raise MetadataError(arxiv, "arXiv holds no paper with this identifier")
        return work
    # A DOI is quoted from a browser as often as it is typed, and the prefix is not part of it.
    bare = (doi or "").strip().removeprefix("https://doi.org/").removeprefix("doi:")
    work = from_crossref(bare) or from_datacite(bare)
    if work is None:
        raise MetadataError(bare, "neither Crossref nor DataCite holds a record for this DOI")
    return work


# ------------------------------------------------------------------------------------ render


def latex(value: str) -> str:
    """A registry's plain text as a BibTeX field value.

    Crossref deposits titles with markup in them -- `<i>` tags, and entities escaped twice, so a
    stored title can literally contain `&amp;lt;i&amp;gt;` -- and none of that is part of the
    title.
    """
    text = " ".join(strip_markup(value).split())
    return "".join(LATEX_SPECIAL.get(c, c) for c in text)


def render(work: Work, key: str) -> str:
    """`work` as a BibTeX entry under `key`."""
    venue_field = "booktitle" if work.kind in ("inproceedings", "incollection") else "journal"
    fields = [
        ("author", " and ".join(latex(a) for a in work.authors)),
        # The title is braced inside its own field: `plain.bst` lowercases a title it is given
        # bare, which turns a name in one into a common noun.
        ("title", "{" + latex(work.title) + "}"),
        (venue_field, latex(work.venue)),
        ("publisher", latex(work.publisher)),
        ("year", work.year),
        ("volume", work.volume),
        ("number", work.number),
        ("pages", work.pages),
        ("eprint", work.arxiv),
        ("archivePrefix", "arXiv" if work.arxiv else ""),
        ("primaryClass", work.primary_class),
        ("doi", work.doi),
        ("url", work.url),
    ]
    present = [(name, value) for name, value in fields if value]
    width = max((len(name) for name, _ in present), default=0)
    body = "".join(f"  {name:<{width}} = {{{value}}},\n" for name, value in present)
    return f"@{work.kind}{{{key},\n{body}}}\n"


def suggest_key(work: Work) -> str:
    """A citation key from the work itself: surname, year, first substantive title word.

    The convention the corpus already uses, `vaswani2017attention`. A key that collides with one
    the file has is not resolved here; it is reported like any other repeat, and `--key` names a
    different one.
    """
    if not work.authors:
        raise MetadataError(
            work.doi or work.arxiv,
            "no author to build a citation key from; name the key with --key",
        )
    words = [w for w in fold(work.title).split() if w not in STOPWORDS and len(w) > 2]
    return f"{surname(work.authors[0])}{work.year}{words[0] if words else ''}"


# --------------------------------------------------------------------------------------- add


def one_entry(text: str, source: pathlib.Path) -> Entry:
    """The single entry in `text`, or `BibFileError` naming `source` and what is wrong with it.

    Read with the same brace counter that reads the target file, so text rejected here is text
    that would not have read back there either.
    """
    found = bibtex.entries(text)
    if not found:
        raise BibFileError(
            source,
            "no BibTeX entry here. An entry reads `@type{key, field = {value}, ...}`, and one "
            "whose braces never close is not read as an entry at all",
        )
    if len(found) > 1:
        keys = ", ".join(key for _kind, key, _body in found)
        raise BibFileError(source, f"{len(found)} entries here, and add writes one: {keys}")
    kind, key, _body = found[0]
    return Entry(kind=kind, key=key, text=text.strip() + "\n")


def existing_entry(text: str, key: str) -> tuple[str, int] | None:
    """The entry in `text` that already defines `key`, and the line it starts on.

    Case-folded, because BibTeX folds it: see `bibtex.duplicate_keys`.
    """
    wanted = key.lower()
    line = next((ln for k, ln in bibtex.key_lines(text) if k.lower() == wanted), None)
    if line is None:
        return None
    for kind, other, body in bibtex.entries(text):
        if other.lower() == wanted:
            # Rebuilt from the parse rather than sliced out of the file: the body is the file's
            # own text and only the `@type{key,` header is re-spaced.
            return f"@{kind}{{{other},{body}}}", line
    # The key is in the file inside an entry whose braces never close, so there is no body to
    # show. It collides all the same.
    return "", line


def unclosed(text: str) -> tuple[str, int] | None:
    """An entry the file starts and never closes, as `(key, line)`, or None.

    Every `@type{key,` is an entry BibTeX will read; only the ones whose braces balance are an
    entry this package can read, so a difference between the two counts is a syntax error already
    in the file. Appending to it is how a defect that predates the addition gets attributed to
    the addition.
    """
    started = collections.Counter(key for key, _line in bibtex.key_lines(text))
    started.subtract(key for _kind, key, _body in bibtex.entries(text))
    for key, line in bibtex.key_lines(text):
        if started[key] > 0:
            return key, line
    return None


def append(bib: pathlib.Path, entry: Entry) -> tuple[int, int]:
    """Write `entry` at the end of `bib`, then read the file back. Returns entries before, after.

    A write that is not read back is not verified. This is the last check between the duplicate
    report and the file: `main` reads the bibliography, decides the key is free, and then writes,
    and the file can have changed in between -- by another process, or by the same person in an
    editor. Without the read-back the duplicate the command exists to prevent is in the file and
    the command has reported success.

    What it confirms is that the file now parses as every entry it parsed as before, plus this
    one, and that the key occurs exactly once. On any disagreement the original bytes go back:
    the second occurrence of this defect outlived its own fix because a stale artifact from the
    broken state was still on disk, so a half-written state is never left behind.
    """
    original = bib.read_bytes()
    before = bibtex.read(bib)
    broken = unclosed(before)
    if broken is not None:
        raise BibFileError(
            bib,
            f"the entry {broken[0]} at line {broken[1]} never closes its braces, so nothing was "
            "added. BibTeX reads that as `I was expecting a `,' or a `}'` and skips the rest "
            "of the entry; close it first, or the next error will look like this addition "
            "caused it",
        )
    signature = [(kind, key) for kind, key, _body in bibtex.entries(before)]
    # One blank line between entries, and none introduced at the top of an empty file.
    trailing = len(before) - len(before.rstrip("\n"))
    lead = "" if not before.strip() else "\n" * max(0, 2 - trailing)
    bib.write_bytes(original + (lead + entry.text).encode("utf-8"))

    after = bibtex.read(bib)
    parsed = [(kind, key) for kind, key, _body in bibtex.entries(after)]
    occurrences = [ln for k, ln in bibtex.key_lines(after) if k.lower() == entry.key.lower()]
    if parsed != [*signature, (entry.kind, entry.key)] or len(occurrences) != 1:
        bib.write_bytes(original)
        raise BibFileError(
            bib,
            f"did not read back as its {len(signature)} entries plus {entry.key}, and was "
            f"restored: {entry.key} is on {len(occurrences)} line(s) of it. The file changed "
            "between the check that said the key was free and this write",
        )
    return len(signature), len(parsed)


def side_by_side(left: str, right: str, heads: tuple[str, str]) -> str:
    """Two entries in two columns, so the lines that differ sit opposite each other."""
    rows = [
        heads,
        ("-" * COLUMN, "-" * COLUMN),
        *itertools.zip_longest(left.splitlines(), right.splitlines(), fillvalue=""),
    ]
    out = []
    for a, b in rows:
        left_cell = a if len(a) <= COLUMN else a[: COLUMN - 3] + "..."
        right_cell = b if len(b) <= COLUMN else b[: COLUMN - 3] + "..."
        out.append(f"  {left_cell:<{COLUMN}}  {right_cell}".rstrip())
    return "\n".join(out)


def _stdin() -> str:
    """The entry from standard input.

    Read off the file descriptor rather than `sys.stdin` because nothing in this package imports
    `sys`: a function whose behavior depends on a process-global cannot be called twice, tested
    without monkeypatching, or run from anything that is not a terminal. This is the only place
    that touches the descriptor, and everything it feeds takes the text as an argument.
    `closefd=False` leaves the descriptor open for whoever else holds it.
    """
    with open(0, encoding="utf-8", errors="replace", closefd=False) as stream:
        return stream.read()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="citations add", description=__doc__.split("\n")[0])
    ap.add_argument("bib", help="the bibliography to add to")
    ap.add_argument("--key", help="the citation key; derived from the work when one is fetched")
    ap.add_argument(
        "--entry-file", metavar="FILE", help="the entry to add; omit to read it from stdin"
    )
    ap.add_argument("--doi", help="fetch the entry from Crossref, or DataCite where it has none")
    ap.add_argument("--arxiv", metavar="ID", help="fetch the entry from arXiv")
    ap.add_argument("--check", action="store_true", help="report what would happen, write nothing")
    a = ap.parse_args(argv)

    if a.doi and a.arxiv:
        print("  name one identifier: --doi or --arxiv, not both.")
        return 2
    if (a.doi or a.arxiv) and a.entry_file:
        print("  --entry-file adds the entry you have and --doi/--arxiv fetch one. Not both.")
        return 2

    bib = pathlib.Path(a.bib).expanduser().resolve()
    if not bib.is_file():
        raise CitationsError(
            f"no such file: {bib}\n"
            "    add appends to a bibliography that exists, so that a mistyped path cannot"
            " create one"
        )
    print(f"  bibliography  {bib}")

    if a.doi or a.arxiv:
        work = fetch(a.doi, a.arxiv)
        key = a.key or suggest_key(work)
        # Shown before anything is written, and the entry below carries every author the
        # registry listed -- the count is here so a reader can tell at a glance that it does.
        print(f"  fetched from  {work.source}")
        print(f"  authors       {len(work.authors)}, as the registry lists them")
        print(f"  key           {key}{'' if a.key else '  (derived; --key names another)'}")
        entry = Entry(kind=work.kind, key=key, text=render(work, key))
    else:
        source = (
            pathlib.Path(a.entry_file).expanduser()
            if a.entry_file
            else pathlib.Path("<standard input>")
        )
        if a.entry_file:
            try:
                raw = source.read_text(encoding="utf-8", errors="replace")
            except OSError as e:
                raise BibFileError(source, f"could not be read: {e}") from e
        else:
            raw = _stdin()
        entry = one_entry(raw, source)
        if a.key and a.key != entry.key:
            raise BibFileError(source, f"--key says {a.key} and the entry itself says {entry.key}")

    collision = existing_entry(bibtex.read(bib), entry.key)
    if collision is not None:
        found, line = collision
        print(f"\n  {bib.name} already defines {entry.key}, at line {line}.\n")
        print(
            side_by_side(
                found or "(an entry whose braces never close)",
                entry.text,
                (f"in the file, line {line}", "proposed"),
            )
        )
        print("\n  nothing was written. BibTeX keeps the copy a file defines first and skips the")
        print("  repeat, so this entry would never reach the reference list while the file read")
        print("  as though it had -- and where the two keys differ only in case, the citation")
        print("  goes undefined instead.")
        print("\n  cite the entry that is there, or give this one another key with --key.")
        return 1

    print(f"\n{entry.text}")
    if a.check:
        print(f"  --check: nothing written. {entry.key} would be appended to {bib.name}.")
        return 0

    was, now = append(bib, entry)
    print(f"  appended to {bib.name}: {was} entries, now {now}, {entry.key} in exactly one.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
