"""Resolve a pinned snapshot for each article in the frame.

Stage two of three. Reads the frozen sample from `frame.json`, resolves each article to the
highest-priority snapshot that exists, and records which tier answered. Downloads nothing:
resolution and retrieval are separate so the retrieval rate is known before any bytes are
fetched, and so a failure to resolve is recorded as an observation rather than discovered
mid-download.

The tier hierarchy is fixed by the codebook and is not a preference:

    1  code_swh          Software Heritage identifier from the bibliography
    2  archival DOI      Zenodo or similar, linked from the article
    3  tag or release    explicitly associated with the article
    4  commit <= pubdate last commit at or before publication
    5  default HEAD      sensitivity analysis only, never primary

Tier 5 is resolved and recorded but flagged `sensitivity_only`, because a 2026 branch head
may hold files added years after the article and pinning it records what was inspected
rather than what accompanied the paper.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = pathlib.Path(__file__).parent
FRAME = HERE / "frame.json"
OUT = HERE / "snapshots.json"

SWH_API = "https://archive.softwareheritage.org/api/1/resolve/{swhid}/"
GITHUB_API = "https://api.github.com/repos/{owner}/{repo}"

USER_AGENT = "addressability-sample/1.0 (research; contact elliot@elliottower.ai)"

#: Courtesy delay between unauthenticated API calls. Both hosts rate-limit, and a study
#: that trips a limit halfway through produces a snapshot set whose composition depends on
#: when it ran.
DELAY_SECONDS = 1.0


class Unreachable(Exception):
    """The lookup could not be performed. Never a statement about the identifier.

    Distinguished from a 404 because they are different facts: a 404 says the snapshot is
    not there, and this says the question was not asked. Collapsing them would record an
    infrastructure failure as a scientific outcome, which is the error this study exists to
    measure in other people's work.
    """


def _ssl_context() -> ssl.SSLContext:
    """Python does not use the system trust store on macOS, so supply one explicitly.

    Without this every HTTPS lookup raises CERTIFICATE_VERIFY_FAILED, and a resolver that
    swallows the error codes 42 retrievable snapshots as absent.
    """
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


CONTEXT = _ssl_context()


def get_json(url: str, timeout: int = 20) -> dict | None:
    """Parsed JSON, None for an honest 404, and Unreachable for anything else."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=CONTEXT) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        raise Unreachable(f"HTTP {error.code}") from error
    except (urllib.error.URLError, TimeoutError, ValueError) as error:
        raise Unreachable(str(error)[:120]) from error


def github_slug(url: str) -> tuple[str, str] | None:
    """Owner and repository from a GitHub URL, or None if it is not one."""
    match = re.search(r"github\.com[/:]([^/]+)/([^/\s#?]+)", url or "")
    if not match:
        return None
    return match.group(1), re.sub(r"\.git$", "", match.group(2))


def tier1_swh(entry: dict) -> dict | None:
    """Resolve the core SWHID, discarding qualifiers.

    A SWHID may carry qualifiers after a semicolon (`;origin=`, `;visit=`, `;anchor=`).
    The core identifier is everything before the first one, and the resolve endpoint
    rejects the qualified form with HTTP 400 -- which is a malformed request, not a missing
    snapshot, and must not be recorded as either.
    """
    swhid = (entry.get("code_swh") or "").strip().split(";")[0].strip()
    if not swhid:
        return None
    payload = get_json(SWH_API.format(swhid=urllib.parse.quote(swhid, safe="")))
    if not payload:
        # A recorded SWHID that does not resolve is a finding, not a missing field.
        return {"tier": 1, "kind": "code_swh", "identifier": swhid, "resolved": False}
    return {
        "tier": 1,
        "kind": "code_swh",
        "identifier": swhid,
        "resolved": True,
        "detail": payload.get("browse_url") or "",
    }


def tier2_archival_doi(entry: dict) -> dict | None:
    doi = (entry.get("code_doi") or "").strip()
    if not doi:
        return None
    return {"tier": 2, "kind": "code_doi", "identifier": doi, "resolved": True}


def tier4_commit_before(entry: dict) -> dict | None:
    """Last commit at or before the publication year.

    Year granularity, not a date: the bibliography carries a year and the codebook says
    "at or before the article's publication date". Using 31 December of that year is the
    latest commit the article could have described, and the choice is recorded so it is
    visible rather than assumed.
    """
    slug = github_slug(entry.get("code_url") or "")
    year = (entry.get("year") or "").strip()
    if not slug or not re.fullmatch(r"\d{4}", year):
        return None
    owner, repo = slug
    until = f"{year}-12-31T23:59:59Z"
    url = f"https://api.github.com/repos/{owner}/{repo}/commits?until={until}&per_page=1"
    payload = get_json(url)
    if not payload or not isinstance(payload, list) or not payload:
        return None
    commit = payload[0]
    return {
        "tier": 4,
        "kind": "commit_before_publication",
        "identifier": commit.get("sha", ""),
        "resolved": True,
        "detail": f"{owner}/{repo} until {until}",
    }


def tier5_head(entry: dict) -> dict | None:
    slug = github_slug(entry.get("code_url") or "")
    if not slug:
        return None
    owner, repo = slug
    payload = get_json(GITHUB_API.format(owner=owner, repo=repo))
    if not payload:
        return None
    return {
        "tier": 5,
        "kind": "default_branch_head",
        "identifier": payload.get("default_branch", ""),
        "resolved": True,
        "sensitivity_only": True,
        "detail": f"{owner}/{repo}",
    }


def resolve(entry: dict) -> dict:
    """First tier that answers wins. Tier 3 is not automatable and is left for manual coding.

    An unreachable lookup stops resolution for that article and is recorded as such. It does
    not fall through to a lower tier, because a lower tier answering after a higher tier
    failed for infrastructure reasons would silently downgrade the snapshot and record the
    downgrade as the article's best available evidence.
    """
    unreachable: list[dict] = []
    for resolver in (tier1_swh, tier2_archival_doi, tier4_commit_before, tier5_head):
        try:
            result = resolver(entry)
        except Unreachable as error:
            unreachable.append({"resolver": resolver.__name__, "reason": str(error)})
            return {
                "tier": None,
                "kind": None,
                "identifier": "",
                "resolved": False,
                "retrieval_status": "unreachable",
                "unreachable": unreachable,
            }
        time.sleep(DELAY_SECONDS)
        if result and result.get("resolved"):
            if result.get("sensitivity_only"):
                # Reaching tier 5 means no primary snapshot exists for this article.
                return {**result, "retrieval_status": "sensitivity_only"}
            return {**result, "retrieval_status": "retrieved"}
        if result and not result.get("resolved"):
            # Recorded and then passed over: a stated identifier that does not resolve.
            entry.setdefault("unresolved_identifiers", []).append(result)
    return {
        "tier": None,
        "kind": None,
        "identifier": "",
        "resolved": False,
        "retrieval_status": "absent",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=0, help="resolve only the first N (dry run)")
    args = parser.parse_args()

    frame = json.loads(FRAME.read_text())
    selected = set(frame["selected"])
    articles = [e for e in frame["ordered_frame"] if e["key"] in selected]
    if args.limit:
        articles = articles[: args.limit]

    records = []
    for i, entry in enumerate(articles, 1):
        outcome = resolve(dict(entry))
        records.append(
            {
                "key": entry["key"],
                "doi": entry.get("doi", ""),
                "year": entry.get("year", ""),
                "domain": entry.get("domain", ""),
                **outcome,
            }
        )
        print(
            f"  [{i:2}/{len(articles)}] {entry['key'][:34]:36} "
            f"tier {outcome['tier']}  {outcome['retrieval_status']}"
        )

    if not args.limit:
        OUT.write_text(
            json.dumps(
                {
                    "resolved_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "records": records,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )
        print(f"\n  wrote {OUT}")

    counts: dict = {}
    for r in records:
        counts[r["retrieval_status"]] = counts.get(r["retrieval_status"], 0) + 1
    print("\n  retrieval_status:")
    for k, v in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"    {k:18} {v:3}  ({v / len(records):5.1%})")
    return 0


if __name__ == "__main__":
    import urllib.parse

    raise SystemExit(main())
