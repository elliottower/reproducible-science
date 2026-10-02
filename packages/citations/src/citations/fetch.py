"""Fetch the sources a claims directory pins, and keep only the bytes each pin names.

A claims file carries a sha256, and usually a DOI or a URL, for a source the repository cannot
ship: a publisher's PDF is not the author's to redistribute. A reader who clones the repository
therefore has every pin and no source, and `verify` answers `unchecked` for every quotation.

This closes that gap without distributing anything. For each source that is absent, it asks
where an open copy is, downloads each candidate, and installs one only when its sha256 is the
one the claims file pins. Bytes that differ are reported and never written, because a file at
the pinned path with other contents is the broken pin `verify` exists to catch.

    citations fetch --claims claims/            fetch what is absent
    citations fetch --claims claims/ --dry-run  say what would be asked, write nothing

Candidates, in order: the arXiv PDF where the source names an arXiv id or links an arXiv page,
the URL the claims file records, then the open-access locations Europe PMC and OpenAlex list for the DOI.

A source that pins an original file and names what reads it -- `extractor`, or `extract_cmd`
-- may also record `derived_sha256`, the digest of the text that reading produced when the
quotations were taken. That is checked second, once the original is on disk and matches its
pin, and its two outcomes are kept apart from the first stage's: the bytes are right, and what
is in question is the reading of them.

Outcomes, one per source:

    present         already on disk, and it matches the pin
    fetched         downloaded, matched the pin, installed
    differs         a copy was downloaded and none matched the pin; nothing was written
    unavailable     no candidate answered with a file
    no location     the claims file records no url, doi or arxiv id, so there was nowhere to ask
    broken          on disk and not matching the pin; left untouched
    unpinned        no sha256 is recorded, so no download could be confirmed
    no path         the claims file names no local path to install to
    absent          not on disk; reported by `--dry-run`, which downloads nothing
    text differs    the original matches its pin, and its extractor now produces other text
                    than the text recorded as `derived_sha256`
    text unchecked  the original matches its pin, and its extractor could not be run here, so
                    the text was not compared
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import pathlib
import re
import urllib.error
import urllib.parse
from dataclasses import dataclass

from provenance_core import atomic_write_bytes, sha256_of_file

from citations import resolve
from citations import verify as V
from citations.exceptions import ClaimFileError, SourceUnreadableError
from citations.models import ClaimFile, ClaimSource, load_claim_file
from citations.services import polite

#: Reported in this order. An outcome absent here would be counted and never printed.
OUTCOMES = [
    "present",
    "fetched",
    "differs",
    "unavailable",
    "no location",
    "broken",
    "unpinned",
    "no path",
    "absent",
    "text differs",
    "text unchecked",
]

#: Wide enough for the longest outcome and a gap, so adding one does not ragged the table.
WIDTH = max(len(o) for o in OUTCOMES) + 2

#: Outcomes that leave a pinned source unreadable on this machine.
MISSING = frozenset({"differs", "unavailable", "no location", "broken"})

#: Outcomes where the original is here and the text its quotations were pinned in is not
#: established. `text unchecked` is among them: a comparison nobody made is not a match.
UNREAD = frozenset({"text differs", "text unchecked"})

#: Refuse a body larger than this. A source is a paper, and a response this size is not one.
MAX_BYTES = 200 * 1024 * 1024

_DOI = re.compile(r"10\.\d{4,9}/[^\s\"<>]+")
_ARXIV_DOI = re.compile(r"^10\.48550/arxiv\.(.+)$", re.I)
_ARXIV_URL = re.compile(r"arxiv\.org/(?:abs|pdf)/([^\s?#]+?)(?:\.pdf)?(?:[?#].*)?$", re.I)


@dataclass(frozen=True)
class Outcome:
    """What happened to one source."""

    name: str
    """The claims file's stem."""

    state: str
    """One of `OUTCOMES`."""

    detail: str = ""
    """Where a fetched copy came from, or why none was installed."""


def doi_of(source: ClaimSource) -> str:
    """The DOI a source names, from its `doi` field or from a URL that contains one."""
    declared = str((source.model_extra or {}).get("doi") or "").strip()
    if declared:
        return declared.removeprefix("https://doi.org/")
    found = _DOI.search(source.url or "")
    return found.group(0).rstrip(".,;)") if found else ""


def arxiv_of(source: ClaimSource) -> str:
    """The arXiv id a source names: its `arxiv` field, an arXiv-minted DOI, or an arXiv URL.

    A claims file usually records the abstract page, which is where a reader is sent and is not
    the paper. Downloading it yields HTML, which can never match a pin taken from the PDF.
    """
    declared = str((source.model_extra or {}).get("arxiv") or "").strip()
    if declared:
        return declared
    if minted := _ARXIV_DOI.match(doi_of(source)):
        return minted.group(1)
    linked = _ARXIV_URL.search(source.url or "")
    return linked.group(1) if linked else ""


def has_location(source: ClaimSource) -> bool:
    """Whether a reader holding only the claims file has anywhere to ask for this source.

    A download address written into `note` is prose, and nothing can fetch from prose.
    """
    return bool(source.url or doi_of(source) or arxiv_of(source))


def europepmc_pdfs(payload) -> list[str]:
    """Open PDF locations in a Europe PMC `search` answer, in the order it lists them."""
    out = []
    for result in ((payload or {}).get("resultList") or {}).get("result") or []:
        for link in (result.get("fullTextUrlList") or {}).get("fullTextUrl") or []:
            if link.get("documentStyle") == "pdf" and link.get("availabilityCode") in ("OA", "F"):
                out.append(link.get("url") or "")
        if pmcid := result.get("pmcid"):
            out.append(f"https://europepmc.org/articles/{pmcid}?pdf=render")
    return [u for u in out if u]


def openalex_pdfs(payload) -> list[str]:
    """Open PDF locations in an OpenAlex work, the one it ranks best first."""
    work = payload or {}
    locations = [work.get("best_oa_location") or {}, *(work.get("locations") or [])]
    return [u for loc in locations if (u := (loc or {}).get("pdf_url"))]


def locate(source: ClaimSource) -> list[tuple[str, str]]:
    """Every place a copy of this source may be had, as `(who said so, url)`, without repeats.

    A registry that does not answer contributes nothing and stops nothing: the remaining
    candidates are still tried, and a source nobody could locate is reported `unavailable`.
    """
    found: list[tuple[str, str]] = []
    if arxiv := arxiv_of(source):
        found.append(("arxiv", f"https://arxiv.org/pdf/{arxiv}"))
    if source.url and not _ARXIV_URL.search(source.url):
        found.append(("the claims file", source.url))
    if doi := doi_of(source):
        query = urllib.parse.urlencode(
            {"query": f'DOI:"{doi}"', "resultType": "core", "format": "json"}
        )
        registries = [
            (
                "europepmc",
                f"https://www.ebi.ac.uk/europepmc/webservices/rest/search?{query}",
                europepmc_pdfs,
            ),
            (
                "openalex",
                f"https://api.openalex.org/works/doi:{doi}?{urllib.parse.urlencode(polite({}))}",
                openalex_pdfs,
            ),
        ]
        for name, url, read in registries:
            try:
                found += [(name, u) for u in read(resolve.get(url.rstrip("?"), as_json=True))]
            except resolve.Throttled:
                continue
    first: dict[str, str] = {}
    for who, url in found:
        first.setdefault(url, who)
    return [(who, url) for url, who in first.items()]


def download(url: str) -> bytes | None:
    """The body at `url`, or None when nothing usable came back."""
    try:
        with resolve.fetch(url, timeout=60) as response:
            body = response.read(MAX_BYTES + 1)
    except (urllib.error.HTTPError, *resolve.NETWORK_ERRORS):
        return None
    return body if 0 < len(body) <= MAX_BYTES else None


def then_text(
    cf: ClaimFile, artifact: pathlib.Path, outcome: Outcome, allowed: frozenset[str]
) -> Outcome:
    """The second stage: with the original verified, is its extracted text the pinned text?

    Reached only once the bytes on disk match `sha256`, so a failure here is never the
    download's. `outcome` is returned unchanged where the source records no `derived_sha256`,
    which is every source pinned before the field existed, and where the text matches.

    Read uncached. `fetch` may have written the file a moment ago, and a memoized extraction
    keyed on the path would describe whatever was there before.
    """
    if not cf.source.derived_sha256:
        return outcome
    try:
        text = V.extract_uncached(artifact, None, cf.source.reader, allowed)
    except SourceUnreadableError as e:
        return Outcome(cf.name, "text unchecked", e.detail)
    derived = V.check_derived(text, cf.source.derived_sha256)
    if derived.state == "broken":
        return Outcome(
            cf.name,
            "text differs",
            f"pinned text {derived.expected[:12]}, extracted {derived.actual[:12]}",
        )
    return outcome


def fetch_one(
    cf: ClaimFile, dry_run: bool = False, allowed: frozenset[str] = V.DEFAULT_EXTRACTORS
) -> Outcome:
    """Bring one claims file's source onto this machine, if its pin can be met.

    Two stages, in order: the original against `sha256`, then the text its declared reading
    produces against `derived_sha256` where one is recorded. The second never runs on bytes
    that failed the first.
    """
    artifact = cf.artifact()
    if artifact is None:
        return Outcome(cf.name, "no path")
    if not cf.source.is_pinned:
        return Outcome(cf.name, "unpinned")
    pinned = (cf.source.sha256 or "").strip()
    if artifact.is_file():
        on_disk = sha256_of_file(artifact)
        if on_disk == pinned:
            return then_text(cf, artifact, Outcome(cf.name, "present"), allowed)
        return Outcome(cf.name, "broken", f"pinned {pinned[:12]}, on disk {on_disk[:12]}")

    if not has_location(cf.source):
        return Outcome(cf.name, "no location", "add `url:` or `doi:` to the source block")
    candidates = locate(cf.source)
    if dry_run:
        return Outcome(cf.name, "absent", f"would ask {len(candidates)} location(s)")
    tried = []
    for who, url in candidates:
        body = download(url)
        if body is None:
            continue
        got = hashlib.sha256(body).hexdigest()
        if got == pinned:
            artifact.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_bytes(artifact, body)
            return then_text(cf, artifact, Outcome(cf.name, "fetched", f"{who}: {url}"), allowed)
        tried.append(f"{who} gave {got[:12]}")
    if tried:
        return Outcome(cf.name, "differs", f"pinned {pinned[:12]}; " + ", ".join(tried))
    return Outcome(cf.name, "unavailable", f"{len(candidates)} location(s) asked")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="citations fetch", description=__doc__.split("\n")[0])
    ap.add_argument("--claims", default="claims", help="a paper's claims/ directory")
    ap.add_argument(
        "--dry-run", action="store_true", help="locate candidates, download and write nothing"
    )
    ap.add_argument(
        "--allow-extractor",
        action="append",
        default=[],
        metavar="NAME",
        help="let a claims file's extract_cmd run this program, to check the text it produces",
    )
    a = ap.parse_args(argv)
    allowed = V.DEFAULT_EXTRACTORS | frozenset(a.allow_extractor)

    root = pathlib.Path(a.claims).expanduser().resolve()
    if not root.is_dir():
        print(f"no claims directory at {root}")
        return 2

    outcomes: list[Outcome] = []
    for path in sorted(root.glob("*.yaml")):
        try:
            cf = load_claim_file(path)
        except ClaimFileError as e:
            print(f"  skipped  {path.name}: {e.detail.splitlines()[0]}")
            continue
        outcome = fetch_one(cf, a.dry_run, allowed)
        outcomes.append(outcome)
        if outcome.state not in ("present", "no path"):
            print(f"  {outcome.state:<{WIDTH}}{outcome.name[:38]:<40}{outcome.detail}")

    counts = collections.Counter(o.state for o in outcomes)
    print(f"\nclaims  {root}\n\n{len(outcomes):,} sources\n")
    for state in OUTCOMES:
        if counts.get(state):
            print(f"  {state:<{WIDTH}}{counts[state]:>7,}")
    missing = sum(counts.get(s, 0) for s in MISSING)
    unread = sum(counts.get(s, 0) for s in UNREAD)
    print()
    if a.dry_run:
        print("dry run: nothing was downloaded or written.")
        return 0
    if missing:
        print(
            f"{missing} pinned source(s) are still not readable here. A copy obtained another "
            f"way can be placed at the path its claims file names; `verify` checks it against "
            f"the pin."
        )
    if unread:
        print(
            f"{unread} source(s) match their pin, and the text their quotations were pinned in "
            f"was not reproduced here. The file is the right one; the reason beside each says "
            f"whether its extractor produced other text or could not be run."
        )
    if not (missing or unread):
        print("every pinned source is on disk and matches its pin.")
    return 1 if missing or unread else 0


if __name__ == "__main__":
    raise SystemExit(main())
