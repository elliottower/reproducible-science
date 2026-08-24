"""Find a fetchable identifier for records that have none, and persist it.

Each service in `services.py` is asked in turn until one answers with a work that matches.
A match is accepted only when the returned title is close to ours AND the first author's
surname appears in the returned author list AND, where we know the year, it agrees within a
year. Title alone is how you end up citing a different paper by an author with the same
surname, which this project has done five times -- and the guard still earns its place: a
Crossref search for "Attention Is All You Need" returns "Is Attention All You Need?" at 0.88
similarity, above the threshold, by different authors, in a different year.

Where a work exists in several versions, the venue is used to prefer the one we cite -- the
journal article rather than the working paper, the original rather than a reprint.

Results go to enrichment.yaml, not into records/, because records/ is generated and would lose
them on the next build.

    citations resolve --check          # report, write nothing
    citations resolve --paper mechanistic-reference
    citations resolve --verify         # re-check that every stored link still resolves
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import socket
import time
import urllib.error
import urllib.request

import yaml

from citations import paths
from citations.models import Record, load_record
from citations.services import SERVICES, Service
from citations.text import fold as norm
from citations.text import surname_variants

UA = "citations/1.0 (mailto:elliot@elliottower.ai)"

#: How close two titles must be, after normalization, before anything else is considered.
TITLE_MIN = 0.87

#: A matching venue is worth this much against title similarity when choosing between several
#: acceptable candidates. High enough that the journal version beats the preprint.
VENUE_WEIGHT = 1.5

#: Errors that mean the request did not complete. `HTTPError` subclasses `URLError`, so it is
#: caught ahead of these wherever the status code carries information.
NETWORK_ERRORS = (
    urllib.error.URLError,
    socket.timeout,
    TimeoutError,
    ConnectionError,
    json.JSONDecodeError,
    UnicodeDecodeError,
)

#: Status codes that mean "ask again later" rather than "no such work".
RETRY_CODES = (429, 503, 504)


class Throttled(Exception):
    """The service refused to answer. Distinct from answering that it has nothing."""


# --------------------------------------------------------------------------------------------
# Transport
# --------------------------------------------------------------------------------------------


def fetch(url: str, timeout: int = 25, headers: dict | None = None):
    """An open response. The caller closes it.

    Closing it here -- which a `with` block around the `urlopen` does -- returns a response
    whose `read()` yields zero bytes. Every decode then fails, every failure is retried, and
    the resolver concludes that every service refused it.
    """
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    return urllib.request.urlopen(req, timeout=timeout)


def get(url: str, as_json: bool, tries: int = 4, headers: dict | None = None):
    """The payload, or None when the service answered and had nothing.

    Raises `Throttled` when it did not answer. Collapsing those two into None is how a batch of
    sixty lookups reported sixty works as unfindable when the real answer was that Crossref had
    started rate-limiting after the first few. A resolver that cannot tell "absent" from "I was
    blocked" will confidently delete information.
    """
    delay = 2.0
    for _ in range(tries):
        try:
            with fetch(url, headers=headers) as r:
                body = r.read().decode()
            return json.loads(body) if as_json else body
        except urllib.error.HTTPError as e:
            if e.code in RETRY_CODES:
                time.sleep(delay)
                delay *= 2
                continue
            return None
        except NETWORK_ERRORS:
            time.sleep(delay)
            delay *= 2
    raise Throttled(url)


# --------------------------------------------------------------------------------------------
# The one matching rule
# --------------------------------------------------------------------------------------------


def close(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, norm(a), norm(b)).ratio()


def year_ok(ours: str, theirs: int | None) -> bool:
    """Unknown on either side is not a mismatch. A year apart is a preprint and its paper."""
    if not ours or not theirs:
        return True
    try:
        return abs(int(ours) - int(theirs)) <= 1
    except ValueError:
        return True


def match(rec: Record, candidates) -> tuple[str, str] | None:
    """The best acceptable candidate's identifier, or None if none is acceptable.

    Acceptability and ranking are separate. A candidate that fails any guard is out regardless
    of how well it scores; among those that pass, the venue decides which version of the same
    work to take.
    """
    first = rec.authors[0] if rec.authors else ""
    want = surname_variants(first)
    best: tuple[float, tuple[str, str]] | None = None

    for c in candidates:
        if c.identifier is None:
            continue
        title_score = close(c.title, rec.title)
        if title_score < TITLE_MIN:
            continue
        if want and not (want & c.surnames):
            continue
        if not year_ok(rec.year, c.year):
            continue
        venue_score = close(c.venue, rec.venue) if (rec.venue and c.venue) else 0.0
        score = title_score + VENUE_WEIGHT * venue_score
        if best is None or score > best[0]:
            best = (score, c.identifier)
    return best[1] if best else None


def search(service: Service, rec: Record) -> tuple[str, str] | None:
    """Ask one service about one record. Raises `Throttled` if it refused."""
    headers = None
    if service.needs_key:
        key = os.environ.get(service.needs_key, "")
        headers = {"x-api-key": key} if key else None
    payload = get(service.url(rec), as_json=service.json, headers=headers)
    if payload is None:
        return None
    return match(rec, service.candidates(payload))


# --------------------------------------------------------------------------------------------
# The overlay
# --------------------------------------------------------------------------------------------


def load_overlay() -> dict:
    enrichment = paths.enrichment()
    if not enrichment.exists():
        return {}
    return yaml.safe_load(enrichment.read_text()) or {}


def save_overlay(overlay: dict) -> None:
    paths.enrichment().write_text(
        "# Facts resolved after the bibliographies were written, keyed by record slug.\n"
        "# Regenerating records/ does not touch this file; build.py applies it as an overlay.\n"
        "# Identifiers were accepted only on title, first-author surname and year together.\n"
        + yaml.safe_dump(overlay, sort_keys=True, allow_unicode=True)
    )


URL_FOR = {
    "doi": "https://doi.org/{}",
    "arxiv": "https://arxiv.org/abs/{}",
    "openalex": "https://openalex.org/{}",
}


# --------------------------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------------------------


def verify() -> int:
    """Every stored link still resolves. A dead link is worse than a missing one."""
    bad: list[tuple[str, str, object]] = []
    checked = 0
    for p in sorted(paths.records().glob("*.yaml")):
        rec = load_record(p)
        url = rec.url or (f"https://doi.org/{rec.doi}" if rec.doi else None)
        if not url:
            continue
        checked += 1
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA}, method="HEAD")
            with urllib.request.urlopen(req, timeout=20) as resp:
                if resp.status >= 400:
                    bad.append((rec.slug, url, resp.status))
        except urllib.error.HTTPError as e:
            if e.code in (403, 429):  # blocked or throttled, not absent
                continue
            bad.append((rec.slug, url, e.code))
        except NETWORK_ERRORS as e:
            bad.append((rec.slug, url, type(e).__name__))
        time.sleep(0.15)
    print(f"  checked {checked} links, {len(bad)} did not resolve")
    for slug, url, why in bad[:30]:
        print(f"    {why}  {slug[:38]:<40}{url[:60]}")
    return 1 if bad else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="citations resolve", description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true", help="report, write nothing")
    ap.add_argument("--verify", action="store_true", help="re-check every stored link")
    ap.add_argument("--paper", help="only records this paper cites")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args(argv)

    if a.verify:
        return verify()

    todo: list[Record] = []
    for p in sorted(paths.records().glob("*.yaml")):
        rec = load_record(p)
        if rec.url or rec.doi or rec.arxiv:
            continue
        if a.paper and a.paper not in rec.cited_by:
            continue
        todo.append(rec)
    if a.limit:
        todo = todo[: a.limit]
    print(f"  {len(todo)} records without an identifier\n")

    overlay = load_overlay()
    found = blocked = consecutive_blocks = 0
    for rec in todo:
        # Each service is tried independently: one of them rate-limiting must not stop the
        # others from answering. A record only counts as blocked when every service refused,
        # which is different from every service having nothing.
        hit, refused = None, 0
        for service in SERVICES:
            try:
                hit = search(service, rec)
            except Throttled:
                refused += 1
            time.sleep(1.5)
            if hit:
                break

        if not hit and refused == len(SERVICES):
            blocked += 1
            consecutive_blocks += 1
            print(f"  BLOCKED {rec.title[:60] or '?'}")
            if consecutive_blocks >= 4:
                print(
                    f"\n  every service refusing -- stopping rather than grinding; "
                    f"{found} saved. Re-run later to continue."
                )
                break
            time.sleep(20)
            continue

        consecutive_blocks = 0
        if not hit:
            print(f"  ---     {rec.title[:60] or '?'}")
            continue

        kind, ident = hit
        found += 1
        print(f"  {kind:<6} {ident:<34}{rec.title[:40]}")
        if not a.check:
            entry = overlay.setdefault(rec.slug, {})
            entry["url"] = URL_FOR[kind].format(ident)
            entry[kind] = ident
            save_overlay(overlay)  # after each hit: a killed run keeps what it found

    print(
        f"\n  resolved {found} of {len(todo)}"
        + (f", {blocked} blocked and not retried" if blocked else "")
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
