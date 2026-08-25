"""Fetch a source's full text through Paperclip, write it down, and pin the bytes.

Paperclip indexes open-access full text -- PubMed Central, arXiv, bioRxiv, medRxiv -- and
answers with the text of a document given a DOI or an identifier it knows. That is a fetch, and
a fetch is the only thing it does here.

**It is never in the verification path.** The text comes down once, it is written to a file,
that file is hashed, and the hash goes into the claims file. Every later `citations verify`
reads the local file and nothing else, exactly as it does for a PDF. Paperclip does not see the
quotation, does not decide whether it matches, and does not have to be reachable, subscribed to,
or still serving the same corpus for a check to run. A remote service answering "yes, that
passage is in the paper" is an answer nobody can re-derive; a digest over bytes on disk is one
anybody can.

Three outcomes, and they are not interchangeable:

    pinned        the full text arrived complete, is on disk, and carries a digest
    unresolved    Paperclip answered and has no full text for this identifier
    unavailable   nothing was established -- the extra is absent, no key is set, the service
                  refused, or what came back was not the whole document

Only the first produces something checkable. The other two are recorded as sources with no local
copy, so their quotations come out of `verify` as `unchecked`: no measurement was made. Full text
is open access only, so a bibliography of Elsevier and Springer articles yields a large
`unchecked` fraction. That is the true report of what could be checked, not a failure of the
quotations, and it is not worth hiding.

    citations resolve --via paperclip 10.1101/2025.10.22.681631

## Why a partial document is refused

Paperclip cuts its own output at 250,000 characters. The cut lands mid-sentence and the body
carries `[output truncated at 250000 chars]` after it, so a long paper arrives as a prefix: one
4,960-line article delivered 2,179 of its 2,485 lines that way. Pinning a prefix would put part
of a paper on disk under the name of the whole one, and every quotation past the cut would be
reported `not found` -- a checker manufacturing misquotations out of a transfer limit.

So the file's last line number is read first, with `tail -n 1`, and a body that does not run
from `L1` to that line contiguously is refused as `unavailable`. Both the marker and the extent
are checked: the marker proves a truncation happened, and the extent would catch one that did
not announce itself. Refusing a document that might be whole costs an `unchecked`; accepting
one that is not costs a false accusation against a paper.

The extent comes from `tail -n 1` and never from `ls`, whose printed `(N lines)` counts
something else for a PubMed Central document -- 1,626 against a file ending at L829, 4,960
against one ending at L2485. For bioRxiv the two agree, which is what makes believing `ls` easy
and wrong: it refuses whole PMC documents as though they had been cut.

## Talking to it

The transport is one authenticated JSON-RPC POST to Paperclip's MCP endpoint, whose single tool
takes a command string. `PAPERCLIP_API_KEY` carries the credential and is never written anywhere
this package produces.

`resolve_document(..., client=...)` takes anything satisfying `Client`, so nothing here needs a
credential or a network to be exercised.
"""

from __future__ import annotations

import dataclasses
import datetime
import json
import os
import pathlib
import re
from typing import Any, Protocol

import yaml
from provenance_core import sha256_of_file
from pydantic import BaseModel, ConfigDict

from citations.exceptions import CitationsError

try:  # the optional extra; absent by design in a default install
    import requests
except ImportError:  # pragma: no cover - exercised by setting the module attribute to None
    requests = None  # type: ignore[assignment]

#: What to install, named here so one message can say it.
EXTRA = "citations[paperclip]"

#: Where a claim file's artifacts go, relative to the parent of the claims directory. `verify`
#: resolves a `local` path against that parent, so this literal is both the directory to write
#: and the prefix that goes into the file.
SOURCES = "sources/paperclip"

#: Where the credential comes from. Paperclip's own client reads the same variable.
KEY_VAR = "PAPERCLIP_API_KEY"

#: Overridable for a local or staging deployment, as Paperclip's own client allows.
BASE_URL_VAR = "PAPERCLIP_BASE_URL"
DEFAULT_BASE_URL = "https://paperclip.gxl.ai"

#: The one tool Paperclip's MCP endpoint declares. Its input schema is `{"command": string}`.
TOOL = "paperclip"

#: `L12: some text`. Every line of a `.lines` file arrives with this gutter, and the gutter is
#: removed before the text is written: it lands inside any passage spanning a line break, and
#: no honest quotation of the paper could match it.
GUTTER = re.compile(r"^L(\d+): ?(.*)$")

#: `content.lines  (1626 lines)` inside an `ls` listing. **Not the length of the file** and not
#: used as one: for a PubMed Central document it over-reports, and by a lot -- PMC7254001 lists
#: 1626 against a file whose last line is L829, and PMC8371605 lists 4960 against L2485. For
#: bioRxiv the two agree, which is what makes the disagreement easy to miss. The extent comes
#: from `tail -n 1` on the file itself instead; this pattern is kept only to read the listing.
LISTED_LINES = re.compile(r"content\.lines\s+\((\d+)\s+lines\)")

#: A trailing `[23ms]` or `[1.7s]` is appended to every response and is not part of the file.
TIMING = re.compile(r"^\[\d+(?:\.\d+)?m?s\]$")

#: `[exit 1]` accompanies a failed command. Its absence means the command succeeded.
EXIT = re.compile(r"^\[exit (\d+)\]$")

#: Paperclip appends this when it cuts its own output, which it does at exactly 250,000
#: characters of body, mid-line. It is checked alongside the extent rather than instead of it:
#: the marker proves a truncation happened, and the extent catches one that did not say so.
TRUNCATED = re.compile(r"^\[output truncated")

#: Document ids as they appear in a listing, one per result line. Three spellings are in use and
#: which one comes back depends on the command: `search` prints the short prefixed form and
#: `lookup` prints the underlying uuid for the same document. Matching only the prefixed form
#: made every bioRxiv DOI resolve to nothing, which is indistinguishable from a paper nobody
#: indexes.
DOCUMENT_ID = re.compile(
    r"(?m)^\s*("
    r"PMC\d+"
    r"|(?:arx|bio|med|fda|tri)_[0-9a-z]{6,}"
    r"|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
    r")\b"
)

#: How Paperclip says a document is not in the corpus, as distinct from any other failure. The
#: difference decides `unresolved` against `unavailable`, so it is matched deliberately and
#: anything unrecognized falls to `unavailable` -- the outcome that claims less.
ABSENT = ("document not found", "no such file", "no documents found")


class PaperclipUnavailableError(CitationsError):
    """Paperclip could not be asked, or did not answer with a whole document.

    Distinct from Paperclip answering that it has no full text for an identifier. A client that
    cannot be built, a service that refuses, and a body that arrived short all say nothing about
    whether the document exists, and a resolver that reported them alike would turn every
    machine without a key into a bibliography of works nobody indexes.
    """


class PaperclipResponseError(PaperclipUnavailableError):
    """Paperclip answered and the answer was not usable.

    A subclass rather than a sibling because the consequence is identical -- nothing was
    established -- and a caller that wants to tell a transport failure from a malformed body
    can still catch this one.
    """


class Document(BaseModel):
    """One document's full text, as Paperclip served it.

    `text` is what gets written to disk and hashed. Empty means Paperclip answered and has
    nothing checkable for the identifier, which is an outcome and not an error.
    """

    model_config = ConfigDict(frozen=True, extra="allow")

    identifier: str
    """The DOI, arXiv id or accession that was asked for."""

    document_id: str = ""
    """Paperclip's own id for the document, where it resolved one."""

    path: str = ""
    """The virtual-filesystem path the text was read from, so the fetch can be repeated."""

    text: str = ""
    """The full text, with the line-number gutter removed."""

    lines: int = 0
    """How many lines it ran to, checked against the length Paperclip declared for the file."""

    corpus_version: str = ""
    """The corpus build this text came out of. Paperclip publishes no corpus build identifier
    -- only per-source fetch dates in its documentation -- so this is empty today and is kept
    so a build it starts reporting has somewhere to land."""


class Provenance(BaseModel):
    """What was fetched, from where, by what, and when.

    Written into the claims file beside the digest. The digest says which bytes a quotation was
    checked against; this says where those bytes came from, which a digest cannot.
    """

    model_config = ConfigDict(extra="allow")

    identifier: str
    """The identifier the fetch was made for."""

    document: str = ""
    """Paperclip's document id."""

    path: str = ""
    """The virtual-filesystem path within that document."""

    lines: int = 0
    """The document's length in Paperclip's own parse, at the time it was fetched. Recorded
    because it is what a later fetch would have to agree with to be the same document."""

    corpus_version: str = ""
    """The corpus build, where Paperclip reports one."""

    service_version: str = ""
    """The Paperclip release that served the request, from its public version endpoint."""

    client: str = ""
    """What made the request."""

    fetched: str = ""
    """When, as an ISO 8601 instant with an offset."""


class RepoClaim(BaseModel):
    """One claim committed against a paper in a Paperclip repo."""

    model_config = ConfigDict(extra="allow")

    text: str
    """The claim, in the words whoever committed it used. Not a passage from the paper."""

    lines: str = ""
    """The range they recorded, spelled `L45-L52`. A hint, never an address."""


class RepoPaper(BaseModel):
    """One paper in a Paperclip repo, and the claims committed against it."""

    model_config = ConfigDict(extra="allow")

    paper_id: str
    title: str = ""
    doi: str = ""
    claims: list[RepoClaim] = []

    @property
    def identifier(self) -> str:
        """What to resolve full text by. A DOI where there is one, the document id otherwise."""
        return self.doi or self.paper_id


class Repo(BaseModel):
    """A Paperclip paper repo, read at one branch."""

    model_config = ConfigDict(extra="allow")

    name: str
    branch: str = ""
    papers: list[RepoPaper] = []


class Client(Protocol):
    """The two things this package needs from Paperclip.

    A protocol rather than a base class, so a test supplies fixed answers and nothing here
    learns the difference. Implementations raise `PaperclipUnavailableError` when they could not
    ask or could not finish, and return a `Document` with empty `text` when Paperclip answered
    and has no full text.
    """

    name: str

    def fetch(self, identifier: str) -> Document: ...

    def repo(self, name: str) -> Repo: ...


@dataclasses.dataclass(frozen=True)
class Resolution:
    """What became of one identifier."""

    identifier: str
    state: str
    """`pinned`, `unresolved` or `unavailable`."""
    detail: str = ""
    artifact: pathlib.Path | None = None
    digest: str = ""
    provenance: Provenance | None = None

    @property
    def checkable(self) -> bool:
        """Whether a quotation against this source can be measured at all."""
        return self.state == "pinned"


# --------------------------------------------------------------------------------------------
# Reading what Paperclip sends back
# --------------------------------------------------------------------------------------------


def body(output: str) -> tuple[list[str], int]:
    """The command's own lines and its exit status, with the response furniture removed.

    Every answer carries a trailing elapsed-time line, and a failed command carries `[exit N]`.
    Neither is content, and leaving the timing line in a document would put `[23ms]` into the
    bytes a quotation is checked against.
    """
    lines = output.splitlines()
    status = 0
    kept: list[str] = []
    for line in lines:
        stripped = line.strip()
        if TIMING.match(stripped):
            continue
        exited = EXIT.match(stripped)
        if exited:
            status = int(exited.group(1))
            continue
        kept.append(line)
    return kept, status


def failure(lines: list[str]) -> str:
    """The error Paperclip reported, or an empty string when it reported none."""
    for line in lines:
        if line.startswith("ERR:"):
            return line[4:].strip()
    return ""


def listed_length(listing: str) -> int:
    """The line count an `ls` listing prints for `content.lines`.

    Read for reporting only. It is not the file's extent -- see `LISTED_LINES` -- and using it
    as one refuses whole PubMed Central documents as incomplete.
    """
    found = LISTED_LINES.search(listing)
    return int(found.group(1)) if found else 0


def last_line_number(tail: str) -> int:
    """The number of the file's final line, from `tail -n 1` on the file itself.

    This is the extent a fetched body has to reach. It comes from the same command surface
    serving the body, so the two count the same thing, which `ls` does not.

    Zero when the answer carries no numbered line, which is "cannot tell" and not "empty".
    """
    numbered = [int(m.group(1)) for m in (GUTTER.match(line) for line in tail.splitlines()) if m]
    return numbered[-1] if numbered else 0


def document_ids(listing: str) -> list[str]:
    """Every document id in a lookup listing, in the order Paperclip ranked them."""
    return DOCUMENT_ID.findall(listing)


def plain_text(lines: list[str], extent: int) -> str:
    """The document's text, with the gutter removed, or a refusal if it is not all there.

    Raises `PaperclipResponseError` unless the body runs from `L1` to `extent` with no gap,
    where `extent` is the file's last line number from `tail -n 1`. Paperclip cuts its own
    output at 250,000 characters and says so, so the marker is checked too -- the marker
    proves a truncation happened and the extent catches one that did not announce itself.
    """
    numbered = [(int(m.group(1)), m.group(2)) for m in map(GUTTER.match, lines) if m]
    if any(TRUNCATED.match(line.strip()) for line in lines):
        raise PaperclipResponseError(
            f"Paperclip truncated the document at {len(numbered)} of {extent} lines"
        )
    if not numbered:
        raise PaperclipResponseError("Paperclip returned no line-numbered content")
    got = [n for n, _ in numbered]
    if got != list(range(1, len(got) + 1)):
        raise PaperclipResponseError(
            f"Paperclip returned lines {got[0]}-{got[-1]} with gaps; the document is not whole"
        )
    if extent and len(got) != extent:
        raise PaperclipResponseError(
            f"Paperclip returned {len(got)} lines of a document whose last line is L{extent}; "
            "a partial document is not pinned"
        )
    return "\n".join(text for _, text in numbered) + "\n"


# --------------------------------------------------------------------------------------------
# The transport
# --------------------------------------------------------------------------------------------


class HttpClient:
    """Paperclip over its MCP endpoint: one authenticated POST per command.

    The endpoint declares a single tool taking a command string, so every operation here is one
    of Paperclip's own commands -- `ls`, `cat --full`, `lookup` -- and this class parses what
    they print. Nothing is inferred about a request shape that was not observed.
    """

    name = "citations-paperclip/http"

    def __init__(
        self,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 180.0,
        session=None,
    ) -> None:
        if session is None and requests is None:
            raise PaperclipUnavailableError(
                f"Paperclip support is not installed -- pip install '{EXTRA}'"
            )
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        # `requests` by default, a caller's session when one is given. The seam is here rather
        # than around the whole client so the command strings stay under test. Typed `Any`
        # because the two are interchangeable only in the three calls below, and a protocol
        # covering them would describe `requests` rather than anything this package needs.
        self.session: Any = session if session is not None else requests
        self._calls = 0

    def command(self, command: str) -> str:
        """Run one Paperclip command and return everything it printed."""
        self._calls += 1
        payload = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {
                "name": TOOL,
                "arguments": {"command": command, "skip_truncation": True},
            },
            "id": self._calls,
        }
        try:
            response = self.session.post(
                f"{self.base_url}/mcp",
                json=payload,
                headers={"X-API-Key": self.api_key, "Content-Type": "application/json"},
                timeout=self.timeout,
            )
        except Exception as e:  # requests raises its own hierarchy; none of it is ours
            raise PaperclipUnavailableError(f"could not reach Paperclip: {e}") from e
        if response.status_code == 401:
            raise PaperclipUnavailableError(
                f"Paperclip rejected the credential in ${KEY_VAR} (HTTP 401)"
            )
        if response.status_code != 200:
            raise PaperclipUnavailableError(f"Paperclip answered HTTP {response.status_code}")
        try:
            answer = response.json()
        except ValueError as e:
            raise PaperclipResponseError("Paperclip did not answer with JSON") from e
        if "error" in answer:
            raise PaperclipResponseError(f"Paperclip reported {answer['error']}")
        blocks = (answer.get("result") or {}).get("content") or []
        return "\n".join(b.get("text", "") for b in blocks if b.get("type") == "text")

    def service_version(self) -> str:
        """The Paperclip release serving this host, from its public version endpoint."""
        try:
            response = self.session.get(f"{self.base_url}/version.json", timeout=30)
            return str(response.json().get("version", ""))
        except Exception:
            # Provenance, not a precondition. A version nobody could read is recorded as
            # unknown; refusing the fetch over it would trade a checkable source for a label.
            return ""

    def resolve_identifier(self, identifier: str) -> str:
        """Paperclip's document id for a DOI, or an empty string when it indexes none."""
        if DOCUMENT_ID.match(identifier):
            return identifier
        lines, _ = body(self.command(f"lookup doi {identifier} -n 1"))
        found = document_ids("\n".join(lines))
        return found[0] if found else ""

    def fetch(self, identifier: str) -> Document:
        document_id = self.resolve_identifier(identifier)
        if not document_id:
            return Document(identifier=identifier)

        path = f"/papers/{document_id}/content.lines"

        # The last line first, so there is something to hold the body against. `ls` prints a
        # count too and it is a different number: for a PubMed Central document it over-reports
        # by a factor of two, and believing it refuses complete documents as truncated.
        tail, status = body(self.command(f"tail -n 1 {path}"))
        problem = failure(tail)
        if status or problem:
            if any(marker in problem.lower() for marker in ABSENT):
                return Document(identifier=identifier, document_id=document_id, path=path)
            raise PaperclipUnavailableError(problem or f"tail exited {status}")
        extent = last_line_number("\n".join(tail))

        content, status = body(self.command(f"cat --full {path}"))
        problem = failure(content)
        if status or problem:
            if any(marker in problem.lower() for marker in ABSENT):
                return Document(identifier=identifier, document_id=document_id, path=path)
            raise PaperclipUnavailableError(problem or f"cat exited {status}")

        text = plain_text(content, extent)
        return Document(
            identifier=identifier,
            document_id=document_id,
            path=path,
            text=text,
            lines=extent or text.count("\n"),
        )

    def rest(self, path: str, params: dict | None = None) -> dict:
        """One of Paperclip's REST resources, decoded."""
        try:
            response = self.session.get(
                f"{self.base_url}{path}",
                params=params or {},
                headers={"X-API-Key": self.api_key},
                timeout=self.timeout,
            )
        except Exception as e:
            raise PaperclipUnavailableError(f"could not reach Paperclip: {e}") from e
        if response.status_code == 404:
            raise PaperclipResponseError(f"Paperclip has nothing at {path}")
        if response.status_code != 200:
            raise PaperclipUnavailableError(f"Paperclip answered HTTP {response.status_code}")
        try:
            decoded = response.json()
        except ValueError as e:
            raise PaperclipResponseError(f"{path} did not answer with JSON") from e
        return decoded if isinstance(decoded, dict) else {}

    def repo(self, name: str) -> Repo:
        detail = self.rest(f"/api/paper-repos/by-name/{name}")
        repo_id = str(detail.get("id") or "")
        if not repo_id:
            raise PaperclipResponseError(f"no Paperclip repo named {name}")
        branch = str(detail.get("active_branch") or "")
        status = self.rest(f"/api/paper-repos/{repo_id}/status")
        return Repo(name=name, branch=branch, papers=papers_from_status(status))


def papers_from_status(status: dict) -> list[RepoPaper]:
    """The papers and committed claims out of a repo's status payload.

    A claim is an annotation on a paper entry, carrying the claim text under `note` and the
    range under `lines`. Older entries carry a single `note` on the paper instead of a list, so
    both spellings are read: reading one would make a repo written the other way import as a
    set of papers with no claims, which looks exactly like a repo nobody has annotated.
    """
    papers: list[RepoPaper] = []
    for paper_id, entry in (status.get("papers") or {}).items():
        if not isinstance(entry, dict):
            continue
        annotations = entry.get("annotations") or []
        if not annotations and entry.get("note"):
            annotations = [{"note": entry["note"]}]
        claims = [
            RepoClaim(text=str(a.get("note") or ""), lines=str(a.get("lines") or ""))
            for a in annotations
            if isinstance(a, dict) and a.get("note")
        ]
        papers.append(
            RepoPaper(
                paper_id=str(paper_id),
                title=str(entry.get("title") or ""),
                doi=str(entry.get("doi") or ""),
                claims=claims,
            )
        )
    return sorted(papers, key=lambda p: p.paper_id)


def default_client() -> Client:
    """The client the extra and a credential make possible, or a refusal naming what is missing.

    Both refusals are `PaperclipUnavailableError`, so a caller never has to tell "you have not
    installed this" from "you have not configured this" in order to decide that nothing was
    checked.
    """
    if requests is None:
        raise PaperclipUnavailableError(
            f"Paperclip support is not installed -- pip install '{EXTRA}'"
        )
    key = os.environ.get(KEY_VAR, "").strip()
    if not key:
        raise PaperclipUnavailableError(
            f"${KEY_VAR} is not set -- Paperclip needs an account key to answer"
        )
    return HttpClient(key, os.environ.get(BASE_URL_VAR, "").strip() or DEFAULT_BASE_URL)


# --------------------------------------------------------------------------------------------
# Fetching, writing, pinning
# --------------------------------------------------------------------------------------------


def slug_for(identifier: str) -> str:
    """A filename for an identifier, legible enough to recognize in a directory listing.

    DOIs carry slashes and periods and arXiv ids carry periods, so all of it folds to
    `[a-z0-9-]`. A hash would collide less and tell a reader nothing.
    """
    return re.sub(r"[^a-z0-9]+", "-", identifier.strip().lower()).strip("-") or "unidentified"


def resolve_document(
    identifier: str,
    out_dir: pathlib.Path,
    client: Client | None = None,
    now: datetime.datetime | None = None,
) -> Resolution:
    """Fetch one identifier's full text, write it, hash it, and say what happened.

    Never raises for a document Paperclip does not have and never raises for a client that could
    not be built. Both are things a bibliography legitimately contains, and a resolver that
    raised on them would stop at the first paywalled reference in a list of two hundred.
    """
    if client is None:
        try:
            client = default_client()
        except PaperclipUnavailableError as e:
            return Resolution(identifier, "unavailable", str(e))

    try:
        doc = client.fetch(identifier)
    except PaperclipUnavailableError as e:
        return Resolution(identifier, "unavailable", str(e))

    if not doc.text.strip():
        return Resolution(
            identifier,
            "unresolved",
            "Paperclip indexes no full text for this identifier; full text is open access only",
        )

    out_dir.mkdir(parents=True, exist_ok=True)
    artifact = out_dir / f"{slug_for(identifier)}.txt"
    artifact.write_text(doc.text, encoding="utf-8")
    # `verify.sha256` memoizes on the path, and this path was just rewritten. Hashing through
    # the shared primitive reads the file that is there rather than the one that was.
    digest = sha256_of_file(artifact)

    stamp = (now or datetime.datetime.now(datetime.UTC)).astimezone(datetime.UTC)
    provenance = Provenance(
        identifier=identifier,
        document=doc.document_id,
        path=doc.path,
        lines=doc.lines,
        corpus_version=doc.corpus_version,
        service_version=getattr(client, "service_version", lambda: "")(),
        client=getattr(client, "name", type(client).__name__),
        fetched=stamp.isoformat(),
    )
    return Resolution(identifier, "pinned", "", artifact, digest, provenance)


# --------------------------------------------------------------------------------------------
# Writing it down
# --------------------------------------------------------------------------------------------

HEADER = """\
# Written by citations from a Paperclip fetch. The digest below is what `citations verify`
# reads; Paperclip is not consulted again and does not decide whether a quotation matches.
# A claim's `hint` is a range in Paperclip's own parse of the document: somewhere to start
# reading, never an address a result is computed from.
"""


def source_block(resolution: Resolution, citation: str = "", local: str = "") -> dict:
    """The `source:` mapping for a claims file, as YAML wants it.

    An unresolved or unavailable identifier gets **no** `local` and **no** `sha256`. That is what
    makes its quotations come out `unchecked` rather than `not found`: there is no artifact, so
    nothing was read, so nothing can be said to be absent from it. Naming a file that was never
    fetched would make every quotation under it read as a passage the source does not contain.
    """
    block: dict[str, object] = {}
    if citation:
        block["citation"] = citation
    if resolution.state == "pinned":
        block["local"] = local or str(resolution.artifact)
        block["sha256"] = resolution.digest
        # The artifact is already text and `verify` reads it directly. Naming an extractor
        # would claim a step that never ran.
        block["extract_cmd"] = "none"
    else:
        block["note"] = f"paperclip {resolution.state}: {resolution.detail}"
    if resolution.provenance is not None:
        block["paperclip"] = json.loads(resolution.provenance.model_dump_json())
    return block


def provenance_of(source) -> Provenance | None:
    """The Paperclip provenance a claims file's source carries, if it carries any.

    `ClaimSource` keeps fields it does not declare, so the block survives a round trip without
    this integration reaching into the core model. Reading it back through the model is what
    makes it typed rather than a dict nobody validates.
    """
    raw = (
        source.get("paperclip") if isinstance(source, dict) else getattr(source, "paperclip", None)
    )
    return Provenance.model_validate(raw) if isinstance(raw, dict) else None


def write_claim_file(path: pathlib.Path, source: dict, claims: dict) -> pathlib.Path:
    """One claims file, with a header saying where it came from.

    An existing file keeps its claims: the source block is what a re-fetch knows about, and
    overwriting the block below it would delete quotations somebody wrote by hand.
    """
    if path.exists():
        existing = yaml.safe_load(path.read_text()) or {}
        kept = existing.get("claims") or existing.get("evidence") or {}
        claims = {**claims, **kept}
    path.parent.mkdir(parents=True, exist_ok=True)
    document = {"source": source, "claims": claims}
    path.write_text(HEADER + yaml.safe_dump(document, sort_keys=False, allow_unicode=True))
    return path


__all__ = [
    "EXTRA",
    "KEY_VAR",
    "SOURCES",
    "Client",
    "Document",
    "HttpClient",
    "PaperclipResponseError",
    "PaperclipUnavailableError",
    "Provenance",
    "Repo",
    "RepoClaim",
    "RepoPaper",
    "Resolution",
    "body",
    "default_client",
    "document_ids",
    "failure",
    "last_line_number",
    "listed_length",
    "papers_from_status",
    "plain_text",
    "provenance_of",
    "resolve_document",
    "slug_for",
    "source_block",
    "write_claim_file",
]
