"""Write the source's passage for a quotation that leaves text out, as a separate record.

`verify` reports a quotation made of pieces of the source, with text left out between them
and nothing marking the gap, as `not found` with the reason `omission`. It shows the text left
out and the passage as the source reads it, and changes nothing. This command is the explicit
next step for an author who has read both and wants the source's passage on record:

    citations restore claims/notes2026.yaml --id joined

It never edits the claims file it is given. The original quotation stays where it is, exactly
as written, and stays `not found`. What is written is a derived claim, `joined-restored`, in a
file beside it, `claims/notes2026.restored.yaml`, which carries the same `source` block and is
read by `citations verify --claims claims` like any other claims file. The derived claim's
quotation is the bounded passage: the source from the start of the quotation's first piece to
the end of its last, and no further. Not the sentence, and no context.

That quotation is the source's text. It is not what the quoting party wrote, the record says
so in its `notice`, and `verify` counts restored quotations on a line of their own. Restoring
corrects a quotation against its source. It does not show that what was left out did not
matter: that is a judgment about the text, and the record gives the offsets of every stretch
left out so that it can be made.

Refused, with nothing written, unless all of these hold:

    the quotation is an omission under `verify.omission`'s rule, decided as `verify` decides
        it: through `check_one`, so a passage any installed reader finds whole is `found` and
        is not restored. A changed word or digit, a number or a hyphenated word cut short,
        and a quotation that is simply absent are not omissions;
    the passage is the only one the quotation can have been taken from. Every way the
        quotation fits the source is listed, and the one with the shortest passage is restored
        only where every other way spans a passage that contains it and is longer: a closing
        phrase the source repeats a paragraph on gives such a way, and it is not a second
        candidate. Where two ways span the same passage, or neither of two passages contains
        the other (`In men A significantly B. In women A not once B.`), none is chosen. This
        does not depend on `--max-omitted-tokens`, so raising the limit never turns a
        restoration into a refusal or into another passage. The listing stops at
        `verify.MAX_FITTINGS` ways, and a quotation with that many is refused;
    the tokens that passage puts back, over all gaps, number at most `--max-omitted-tokens`,
        which is 1 unless more is asked for. Tokens are counted as `verify.omission` counts
        them, and that count is the one recorded;
    the passage can be given in the source's own characters, and resolves as `found` on its
        own, exactly once;
    the claims file pins its source by sha256 and the file on disk matches. An unpinned
        source may have changed since the quotation was taken, and a record of it would not
        verify under `--strict`;
    the file the record goes into, if it exists, is a claims file with the same `source`
        block as the original. One written against an earlier pin or another source is left
        alone, since a record added to it would be checked against a source it was not
        taken from.

The derived record, under `restored:` on the new claim:

    from       the id of the claim it was derived from
    notice     that the quotation is the source's text and not the quoting party's
    original   the original quotation, as the claims file has it
    source     the claims file's `citation` and `local`, and the sha256 of the bytes read
    text       what the offsets count in: the extractor, and the sha256 of the text it produced
    passage    start and end of the passage, in characters of that text
    omitted    for each stretch left out: start and end in that text, how many tokens, and
               the position of the first of them among the passage's tokens, counting from 1
    fittings   how many ways the quotation fits the source, and that every other one spans a
               passage containing this one
    rule       `bounded-passage`, its version, and the limits it ran under
    software   the `citations` version, and the commit where it was installed from one

Nothing in it depends on when or where the command ran, so the same claims file and source
give the same bytes. `--check` decides and reports, and leaves the directory as it found it.
"""

from __future__ import annotations

import argparse
import json
import pathlib
from importlib.metadata import PackageNotFoundError, distribution

import yaml
from provenance_core import atomic_write, exclusive_lock

from . import verify as V
from .exceptions import CitationsError
from .models import ClaimFile, load_claim_file

#: The repair rule's name and version, written into every record. The version changes when
#: the same quotation and source would restore to a different passage.
RULE = "bounded-passage"
RULE_VERSION = 2

#: How many tokens a quotation may leave out, over all its gaps, and still be restored unless
#: `--max-omitted-tokens` says otherwise. One: a dropped word is the case a restoration is
#: least likely to change the sense of, and anything longer is asked for by number.
DEFAULT_MAX_OMITTED_TOKENS = 1

NOTICE = (
    "The quotation in this claim is the source's own text, restored by `citations restore` "
    "around text the original quotation left out. It is not what the quoting party wrote; "
    "that is `original`, which is not found in the source as written."
)


class RestoreRefused(CitationsError):
    """The quotation is not one this command restores, or the record cannot be written."""


def sidecar(claims_file: pathlib.Path) -> pathlib.Path:
    """Where derived claims for `claims_file` are written: beside it, never in it."""
    return claims_file.with_name(f"{claims_file.stem}.restored.yaml")


def software() -> dict:
    """The `citations` version, and the commit where the installation records one."""
    try:
        dist = distribution("citations")
    except PackageNotFoundError:  # a source tree with nothing installed
        return {"citations": "0+unknown"}
    record = {"citations": dist.version}
    # PEP 610: present where the package was installed from a URL, with the commit where
    # that URL was a repository.
    direct = dist.read_text("direct_url.json")
    commit = json.loads(direct).get("vcs_info", {}).get("commit_id") if direct else None
    if commit:
        record["commit"] = commit
    return record


def derive(cf: ClaimFile, claim_id: str, limit: int, allowed: frozenset[str]) -> dict:
    """The derived claim for one quotation, or `RestoreRefused` saying why there is none."""
    claim = cf.claims.get(claim_id)
    if claim is None:
        raise RestoreRefused(f"{cf.name} has no claim {claim_id!r}.")
    if claim.is_restored:
        raise RestoreRefused(f"{claim_id!r} is itself a restored claim.")
    quotes = [q for q in claim.quotes if q.text]
    if len(quotes) != 1:
        raise RestoreRefused(
            f"{claim_id!r} has {len(quotes)} quotations; this restores a claim that has one."
        )
    quote = quotes[0]

    artifact = cf.artifact()
    if artifact is None or not artifact.is_file():
        raise RestoreRefused("the source is not on disk, so there is nothing to restore from.")
    pin = V.check_pin(artifact, cf.source.sha256)
    if pin.state == "unpinned":
        raise RestoreRefused(
            "the claims file records no sha256 for its source, so nothing says the file on "
            "disk is the one the quotation was taken from. Pin the source first."
        )
    if pin.state != "ok":
        raise RestoreRefused(
            f"the source is not the file that was pinned (pinned {pin.expected[:12]}, on disk "
            f"{pin.actual[:12]})."
        )

    # The verdict `verify` gives, reached the way `verify` reaches it: a passage the first
    # reader misses and another finds is `found` there, and is no omission here.
    r = V.check_one(
        quote.text,
        artifact,
        quote.page,
        cf.source.reader,
        allowed,
        prefix=quote.prefix,
        suffix=quote.suffix,
    )
    if r.state != "not found":
        raise RestoreRefused(f"the quotation is `{r.state}` in the source; there is no omission.")
    if r.reason != V.OMISSION:
        raise RestoreRefused(
            "the quotation is not the source with whole tokens left out. A changed word or "
            "number, or a token cut short, is a misquotation, and nothing is restored for one."
        )
    reader = V.declared_extractor(cf.source.reader)
    got = V.reading(artifact, None, reader, allowed) if reader else V.reading(artifact)
    found = V.omission(quote.text, got.text)
    if found is None or V._digest(got.text) != r.extraction_digest:
        raise RestoreRefused(
            "the text the verdict was reached in is not the text that can be read back, so "
            "there are no offsets to record."
        )
    if found.capped:
        raise RestoreRefused(
            f"the quotation's pieces fit the source in more than {V.MAX_FITTINGS:,} ways, "
            f"which is where the listing stops. The passage it was taken from is not "
            f"determined, and none is chosen."
        )
    if not found.unique:
        raise RestoreRefused(
            f"the quotation's pieces fit the source in {found.fittings} ways, and the "
            f"shortest passage is not inside all the others, so the passage it was taken "
            f"from is not determined. None is chosen, whatever the limit."
        )
    if found.folded:
        raise RestoreRefused(
            "the passage could not be recovered in the source's own characters, and a record "
            "of folded text would not be the source's."
        )
    tokens = sum(g.tokens for g in found.gaps)
    if tokens > limit:
        raise RestoreRefused(
            f"the quotation leaves out {tokens} tokens and the limit is {limit}. "
            f"--max-omitted-tokens N raises it; the default is {DEFAULT_MAX_OMITTED_TOKENS}."
        )
    return {
        "restored": {
            "from": claim_id,
            "notice": NOTICE,
            "original": quote.text,
            "source": {
                "citation": cf.source.citation,
                "local": cf.source.local,
                "sha256": pin.actual,
            },
            "text": {"extractor": got.extractor, "sha256": V._digest(got.text)},
            "passage": {"start": found.start, "end": found.start + len(found.passage)},
            "omitted": [
                {
                    "start": found.start + g.offset,
                    "end": found.start + g.offset + len(g.text),
                    "tokens": g.tokens,
                    "position": g.position,
                }
                for g in found.gaps
            ],
            "fittings": {"found": found.fittings, "others_contain_passage": True},
            "rule": {
                "name": RULE,
                "version": RULE_VERSION,
                "max_omitted_tokens": limit,
                "min_piece_chars": V.MIN_PIECE_CHARS,
                "max_fittings": V.MAX_FITTINGS,
            },
            "software": software(),
        },
        "quotes": [{"exact": found.passage}],
    }


def document(path: pathlib.Path, source: dict, new_id: str, derived: dict) -> str:
    """The sidecar as it will be written: what it holds already, and this claim.

    A sidecar that is already there has to be one this command could have written for the
    same original: a mapping, with a mapping of claims, under the original's `source` block
    exactly. Anything else is refused and left as it is.
    """
    doc: dict = {"source": source, "claims": {}}
    if path.exists():
        try:
            held = yaml.safe_load(path.read_text())
        except (yaml.YAMLError, OSError) as e:
            raise RestoreRefused(f"{path.name} is there and cannot be read as YAML: {e}") from e
        if held is not None:
            if isinstance(held, dict) and held.get("claims") is None:
                held["claims"] = {}  # `claims:` with nothing under it holds none
            if not isinstance(held, dict) or not isinstance(held["claims"], dict):
                raise RestoreRefused(
                    f"{path.name} is there and is not a claims file: a mapping with a "
                    f"mapping of `claims` was expected."
                )
            if held.get("source") != source:
                raise RestoreRefused(
                    f"{path.name} is there with another `source` block than the claims file "
                    f"has now: it was written against an earlier pin or another source. A "
                    f"record added to it would be checked against a source it was not taken "
                    f"from. Move it aside, or restore its claims again."
                )
            doc = held
    if new_id in doc["claims"]:
        raise RestoreRefused(
            f"{path.name} already defines the claim {new_id!r}. A restoration is written once; "
            f"--as names another id."
        )
    doc["claims"][new_id] = derived
    return yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=100)


def checked(text: str, new_id: str, cf: ClaimFile, allowed: frozenset[str]) -> str:
    """`text`, once the passage in it is seen to resolve after its trip through the file."""
    written = yaml.safe_load(text)["claims"][new_id]["quotes"][0]["exact"]
    r = V.check_one(written.strip(), cf.artifact(), None, cf.source.reader, allowed)
    if r.state != "found":
        raise RestoreRefused(
            f"the restored passage is `{r.state}` in the source on its own, so the record "
            f"would not verify."
        )
    return text


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="citations restore", description=__doc__.split("\n")[0])
    ap.add_argument("claims_file", type=pathlib.Path, help="the claims/*.yaml holding the claim")
    ap.add_argument("--id", required=True, help="the claim whose quotation leaves text out")
    ap.add_argument("--as", dest="new_id", help="the derived claim's id (default: <id>-restored)")
    ap.add_argument(
        "--max-omitted-tokens",
        type=int,
        default=DEFAULT_MAX_OMITTED_TOKENS,
        metavar="N",
        help="refuse a quotation that leaves out more than N tokens over all its gaps "
        f"(default: {DEFAULT_MAX_OMITTED_TOKENS})",
    )
    ap.add_argument(
        "--allow-extractor",
        action="append",
        default=[],
        metavar="NAME",
        help="let the file's extract_cmd run this program",
    )
    ap.add_argument("--check", action="store_true", help="decide and report, write nothing")
    a = ap.parse_args(argv)

    if a.max_omitted_tokens < 1:
        print("--max-omitted-tokens counts tokens left out, from 1.")
        return 2
    path: pathlib.Path = a.claims_file
    if not path.exists():
        print(f"no such claims file: {path}")
        return 2

    cf = load_claim_file(path)
    new_id = a.new_id or f"{a.id}-restored"
    out = sidecar(path)
    allowed = V.DEFAULT_EXTRACTORS | frozenset(a.allow_extractor)
    source = yaml.safe_load(path.read_text())["source"]
    try:
        derived = derive(cf, a.id, a.max_omitted_tokens, allowed)
        if a.check:
            # No lock: taking one leaves a lock file, and `--check` writes nothing at all.
            checked(document(out, source, new_id, derived), new_id, cf, allowed)
        else:
            with exclusive_lock(out):
                atomic_write(
                    out, checked(document(out, source, new_id, derived), new_id, cf, allowed)
                )
    except RestoreRefused as e:
        print(f"refused   {a.id}")
        print(f"  {e}")
        print("nothing written.")
        return 1

    record = derived["restored"]
    tokens = sum(o["tokens"] for o in record["omitted"])
    print(f"{'would restore' if a.check else 'restored'}  {a.id} as {new_id} in {out.name}")
    print(
        f"  {tokens} token{'' if tokens == 1 else 's'} of the source put back in "
        f"{len(record['omitted'])} place{'' if len(record['omitted']) == 1 else 's'}; "
        f"{path.name} is unchanged, and {a.id} is still `not found` as written"
    )
    print("  the restored passage is the source's text, not what the quoting party wrote")
    return 0
