"""Write a quotation into a claims file, and refuse one that does not resolve.

A claims file is written by hand, and `verify` reads it afterwards. Between those two moments
sits the whole error class this command exists to close: a passage transcribed from a PDF
viewer with a ligature the extractor renders differently, a line-wrapped hyphen that is not in
the text, a quotation taken from a version of the source that is not the pinned one. Each is
found later, in a run over a corpus, attributed to a file nobody is currently looking at.

    citations pin claims/woodward2000.yaml --id domain \
        --quote "the set or range of changes over which a relationship ... is invariant"

The passage is resolved against the pinned artifact before anything is written. A quotation
that does not resolve is a quotation the file should not contain, so the command exits
non-zero, prints what the reader did see, and writes nothing.

Where the claim also carries a characterization, `--says` requires `--whose`. The requirement
is the schema's, not this command's: a characterization with no owner reads as though the
source made it, which is the shape the error takes when a reading belonging to one document is
recorded against another.

    citations pin claims/openai2025preparedness.yaml --id autonomy \
        --quote "In conjunction with a Long-" \
        --says "The safeguard obligation is conditioned on long-range autonomy" \
        --whose openai2026codexcard --status contested \
        --contest "The phrase sits in the column describing risks."

`--check` resolves the passage and reports what would be written, as `citations add --check`
does for a bibliography.
"""

from __future__ import annotations

import argparse
import pathlib

import yaml

from . import verify as V
from .exceptions import CitationsError
from .models import ClaimFile


class PinRefused(CitationsError):
    """The quotation did not resolve, or the file cannot take it."""


def _artifact(cf: ClaimFile) -> pathlib.Path | None:
    return cf.artifact()


def resolve(
    cf: ClaimFile,
    quote: str,
    page: int | None,
    allowed: frozenset[str],
) -> V.Result:
    """Read the pinned source and decide whether the passage is in it."""
    return V.check_one(quote, _artifact(cf), page, cf.source.extract_cmd, allowed)


def entry(
    quote: str,
    section: str | None,
    page: int | None,
    says: str | None,
    whose: str | None,
    status: str,
    contest: str | None,
) -> dict:
    """The claim block as it will be written, with keys in the order a reader wants them."""
    claim: dict = {}
    if says is not None:
        reading: dict = {"says": says, "whose": whose}
        if status != "source":
            reading["status"] = status
        if contest:
            reading["contest"] = contest
        claim["interpretation"] = reading
    q: dict = {"exact": quote}
    if section:
        q["section"] = section
    if page is not None:
        q["page"] = page
    claim["quotes"] = [q]
    return claim


def add_to(path: pathlib.Path, claim_id: str, claim: dict) -> None:
    """Append one claim to the file, preserving what is already there.

    The file is re-read and re-written as data rather than patched as text: a claims file is
    the input to a check, and a command that edited it with a regular expression would be the
    kind of tool this package exists to argue against.
    """
    doc = yaml.safe_load(path.read_text()) or {}
    claims = doc.setdefault("claims", {})
    if claim_id in claims:
        raise PinRefused(
            f"{path.name} already defines the claim {claim_id!r}. "
            "Two claims under one identifier are two claims; give this one its own."
        )
    claims[claim_id] = claim
    path.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=100))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="citations pin", description=__doc__)
    ap.add_argument("claims_file", type=pathlib.Path, help="the claims/*.yaml to add to")
    ap.add_argument("--id", required=True, help="the claim's identifier within the file")
    ap.add_argument("--quote", required=True, help="the passage, exactly as the source has it")
    ap.add_argument("--section", help="where in the source it sits")
    ap.add_argument("--page", type=int, help="the page the passage is on")
    ap.add_argument("--says", help="the characterization the quotation is offered for")
    ap.add_argument("--whose", help="whose reading that is: a citation key, or `ours`")
    ap.add_argument(
        "--status",
        default="source",
        choices=["source", "ours", "third-party", "contested"],
        help="how the reading stands",
    )
    ap.add_argument("--contest", help="what is wrong with the reading, where it is contested")
    ap.add_argument(
        "--allow-extractor",
        action="append",
        default=[],
        metavar="NAME",
        help="let the file's extract_cmd run this program",
    )
    ap.add_argument("--check", action="store_true", help="resolve and report, write nothing")
    a = ap.parse_args(argv)

    if a.says is not None and not a.whose:
        # The schema's requirement, enforced at the point a characterization is written rather
        # than at the point someone later reads the file and cannot tell whose reading it is.
        print("--says needs --whose: a characterization with no owner reads as the source's.")
        return 2

    path: pathlib.Path = a.claims_file
    if not path.exists():
        print(f"no such claims file: {path}")
        return 2

    cf = ClaimFile.model_validate(yaml.safe_load(path.read_text()) or {})
    cf.path = path

    allowed = V.DEFAULT_EXTRACTORS | frozenset(a.allow_extractor)
    r = resolve(cf, a.quote, a.page, allowed)

    if r.state != "found":
        print(f"{r.state}  {a.quote[:60]}")
        if r.detail:
            print(f"  {r.detail}")
        print("nothing written. read the source before recording the passage.")
        return 1

    claim = entry(a.quote, a.section, a.page, a.says, a.whose, a.status, a.contest)
    if a.check:
        print(f"found     {a.quote[:60]}")
        print(f"would add {a.id} to {path.name}")
        if r.warnings:
            print(f"  warnings: {', '.join(r.warnings)}")
        return 0

    add_to(path, a.id, claim)
    print(f"found     {a.quote[:60]}")
    print(f"added     {a.id} to {path.name}")
    if r.warnings:
        print(f"  warnings: {', '.join(r.warnings)}")
    if a.says is not None:
        print(f"  reading recorded as {a.whose}'s, unchecked")
    return 0
