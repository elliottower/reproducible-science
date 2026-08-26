"""Turn a Paperclip paper repo into claim files whose sources are pinned by digest.

A Paperclip repo holds papers and, against each, claims somebody committed: a sentence and
optionally the range of lines they read it out of. That is a working record, and it is held on
Paperclip's servers, addressed by a document id, against a parse of a PDF that can be re-run.
None of it is checkable from a repository six months later.

This reads one and writes what is:

    claims/<slug>.yaml            the claims, and a source pinned by sha256
    sources/paperclip/<slug>.txt  the bytes that digest is over

After which `citations verify --claims claims` reads the local files and nothing else.

## What is carried across, and what is not

A committed claim becomes a `statement`. It is not a quotation: it is the sentence the person
committing it wrote, and Paperclip's repo holds no verbatim passage from the paper. Writing it
under `quotes` would make the tool check the source for a sentence nobody claims is in it and
report `not found` -- a misquotation manufactured out of a format conversion. So the quotes list
comes out empty and is for whoever writes the paper to fill in.

A `--lines L45-L52` range becomes the claim's `hint`. It is recorded and never verified; a
remote parse of a PDF can be re-run and renumber every line, so the range says where to start
reading and cannot say what a passage is. It is never written to `page`, which is the locator
`verify` checks.

## A source with no full text

Paperclip indexes open-access full text. A paywalled article resolves to metadata and nothing
readable, so its claim file is written with the claims and **no** `local` and **no** `sha256`.
Its quotations then come out of `verify` as `unchecked`. A repo of Elsevier and Springer
articles will import mostly unchecked, which is what is true about it.

    citations import-paperclip my-review --claims paper/claims
    citations import-paperclip my-review --check
"""

from __future__ import annotations

import argparse
import hashlib
import pathlib

from citations import paperclip
from citations.paperclip import SOURCES, PaperclipUnavailableError, Resolution


def claim_id(text: str) -> str:
    """A stable key for a claim, from its text.

    Position would be simpler and would rename every claim below an inserted one, so a file
    re-imported after a commit would show every later claim as removed and re-added.
    """
    return "c-" + hashlib.sha256(text.strip().encode()).hexdigest()[:10]


def claims_block(paper: paperclip.RepoPaper) -> dict:
    """One paper's committed claims, in the shape a claims file wants."""
    block: dict[str, dict] = {}
    for claim in paper.claims:
        entry: dict[str, object] = {"statement": claim.text, "quotes": []}
        if claim.lines:
            entry["hint"] = claim.lines
        block[claim_id(claim.text)] = entry
    return block


def import_paper(
    paper: paperclip.RepoPaper,
    claims_dir: pathlib.Path,
    client: paperclip.Client | None = None,
    write: bool = True,
) -> Resolution:
    """Resolve one paper's full text and write its claim file. Returns what became of it."""
    slug = paperclip.slug_for(paper.identifier)
    resolution = paperclip.resolve_document(
        paper.identifier, claims_dir.parent / SOURCES, client=client
    )
    if not write:
        return resolution
    source = paperclip.source_block(resolution, local=f"{SOURCES}/{slug}.txt")
    if paper.title:
        source["title"] = paper.title
    paperclip.write_claim_file(claims_dir / f"{slug}.yaml", source, claims_block(paper))
    return resolution


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="citations import-paperclip", description=__doc__.split("\n")[0]
    )
    ap.add_argument("repo", help="the Paperclip paper repo, by name")
    ap.add_argument("--claims", default="claims", help="where the claim files go")
    ap.add_argument("--check", action="store_true", help="report, write nothing")
    a = ap.parse_args(argv)

    claims_dir = pathlib.Path(a.claims).expanduser().resolve()

    try:
        client = paperclip.default_client()
        repo = client.repo(a.repo)
    except PaperclipUnavailableError as e:
        # Not an error in the repo and not a finding about it. Nothing was read, so nothing is
        # reported about any source, and the exit code says the command did not run.
        print(f"  {e}")
        print("  nothing was imported, and nothing is claimed about the repo's sources.")
        return 2

    print(f"  {repo.name}{f' @ {repo.branch}' if repo.branch else ''}: {len(repo.papers)} papers\n")

    counts = {"pinned": 0, "unresolved": 0, "unavailable": 0}
    claims = 0
    for paper in repo.papers:
        resolution = import_paper(paper, claims_dir, client=client, write=not a.check)
        counts[resolution.state] = counts.get(resolution.state, 0) + 1
        claims += len(paper.claims)
        label = paper.title or paper.identifier
        print(f"  {resolution.state:<12}{paper.identifier[:34]:<36}{label[:40]}")

    print(f"\n  {claims} claims across {len(repo.papers)} papers")
    for state in ("pinned", "unresolved", "unavailable"):
        print(f"  {state:<12}{counts[state]:>5}")
    if a.check:
        print("\n  --check: nothing written.")
        return 0

    print(f"\n  written to {claims_dir}")
    if counts["pinned"]:
        print(f"    citations verify --claims {claims_dir}")
    # Statements are the claim as its author wrote it, and the quotes list is empty on purpose.
    # Saying so here is the difference between a file somebody finishes and one they assume is
    # already checking something.
    print("  claims carry statements and no quotations: quote the pinned text to check one.")
    if counts["unresolved"] or counts["unavailable"]:
        left = counts["unresolved"] + counts["unavailable"]
        print(f"  {left} source(s) have no pinned copy; their quotations will read `unchecked`.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
