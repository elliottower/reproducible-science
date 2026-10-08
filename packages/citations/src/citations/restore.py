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

    the quotation is an omission under `verify.omission`'s rule. A changed word or digit, a
        number or a hyphenated word cut short, and a quotation that is simply absent are not;
    the tokens left out, over all gaps, number at most `--max-omitted-tokens`, which is 1
        unless more is asked for;
    it fits the source in exactly one way that leaves out no more than that
        (`verify.alignments`). Where a piece occurs twice near enough, or a cut could fall on
        either side of a repeated word, the passage it was taken from is not determined and
        none is chosen. A way that leaves out more than the limit is not counted: it would be
        refused on its own, so it is not a passage this could restore. Raising the limit
        therefore admits more ways and can turn a restoration into a refusal;
    the passage can be given in the source's own characters, and resolves as `found` on its
        own, exactly once;
    the source matches its pin, where the claims file records one.

The derived record, under `restored:` on the new claim:

    from       the id of the claim it was derived from
    notice     that the quotation is the source's text and not the quoting party's
    original   the original quotation, as the claims file has it
    source     the claims file's `citation` and `local`, and the sha256 of the bytes read
    text       what the offsets count in: the extractor, and the sha256 of the text it produced
    passage    start and end of the passage, in characters of that text
    omitted    for each stretch left out: start and end in that text, how many tokens, and
               the position of the first of them among the passage's tokens, counting from 1
    rule       `bounded-passage`, its version, and the limits it ran under
    software   the `citations` version, and the commit where it was installed from one

Nothing in it depends on when or where the command ran, so the same claims file and source
give the same bytes.
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
RULE_VERSION = 1

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
    if claim.restored is not None:
        raise RestoreRefused(f"{claim_id!r} is itself a restored claim.")
    quotes = [q for q in claim.quotes if q.text]
    if len(quotes) != 1:
        raise RestoreRefused(
            f"{claim_id!r} has {len(quotes)} quotations; this restores a claim that has one."
        )
    quote = quotes[0].text

    artifact = cf.artifact()
    if artifact is None or not artifact.is_file():
        raise RestoreRefused("the source is not on disk, so there is nothing to restore from.")
    pin = V.check_pin(artifact, cf.source.sha256)
    if pin.state == "broken":
        raise RestoreRefused(
            f"the source is not the file that was pinned (pinned {pin.expected[:12]}, on disk "
            f"{pin.actual[:12]})."
        )
    reader = V.declared_extractor(cf.source.reader)
    got = V.reading(artifact, None, reader, allowed) if reader else V.reading(artifact)

    state = V.resolve_in(quote, got.text, quotes[0].prefix, quotes[0].suffix).state
    if state != "not found":
        raise RestoreRefused(f"the quotation is `{state}` in the source; there is no omission.")
    found = V.omission(quote, got.text)
    if found is None:
        raise RestoreRefused(
            "the quotation is not the source with whole tokens left out. A changed word or "
            "number, or a token cut short, is a misquotation, and nothing is restored for one."
        )
    if found.folded:
        raise RestoreRefused(
            "the passage could not be recovered in the source's own characters, and a record "
            "of folded text would not be the source's."
        )
    tokens = [len(g.text.split()) for g in found.gaps]
    if sum(tokens) > limit:
        raise RestoreRefused(
            f"the quotation leaves out {sum(tokens)} tokens and the limit is {limit}. "
            f"--max-omitted-tokens N raises it; the default is {DEFAULT_MAX_OMITTED_TOKENS}."
        )
    if V.alignments(quote, got.text, max_omitted_tokens=limit) != 1:
        raise RestoreRefused(
            f"the quotation's pieces fit the source in more than one way that leaves out at "
            f"most {limit} token{'' if limit == 1 else 's'}, so the passage it was taken from "
            f"is not determined. None is chosen."
        )
    return {
        "restored": {
            "from": claim_id,
            "notice": NOTICE,
            "original": quote,
            "source": {
                "citation": cf.source.citation,
                "local": cf.source.local,
                "sha256": V.sha256(artifact),
            },
            "text": {"extractor": got.extractor, "sha256": V._digest(got.text)},
            "passage": {"start": found.start, "end": found.start + len(found.passage)},
            "omitted": [
                {
                    "start": found.start + g.offset,
                    "end": found.start + g.offset + len(g.text),
                    "tokens": n,
                    "position": len(found.passage[: g.offset].split()) + 1,
                }
                for g, n in zip(found.gaps, tokens, strict=True)
            ],
            "rule": {
                "name": RULE,
                "version": RULE_VERSION,
                "max_omitted_tokens": limit,
                "min_piece_chars": V.MIN_PIECE_CHARS,
            },
            "software": software(),
        },
        "quotes": [{"exact": found.passage}],
    }


def document(path: pathlib.Path, source: dict, new_id: str, derived: dict) -> str:
    """The sidecar as it will be written: what it holds already, and this claim."""
    doc = yaml.safe_load(path.read_text()) if path.exists() else None
    doc = doc or {"source": source, "claims": {}}
    claims = doc.setdefault("claims", {})
    if new_id in claims:
        raise RestoreRefused(
            f"{path.name} already defines the claim {new_id!r}. A restoration is written once; "
            f"--as names another id."
        )
    claims[new_id] = derived
    return yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=100)


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
    try:
        derived = derive(cf, a.id, a.max_omitted_tokens, allowed)
        with exclusive_lock(out):
            text = document(out, yaml.safe_load(path.read_text())["source"], new_id, derived)
            # What will be read back is what is checked: the passage after its trip through
            # the file, against the same source, resolving once on its own.
            written = yaml.safe_load(text)["claims"][new_id]["quotes"][0]["exact"]
            r = V.check_one(written.strip(), cf.artifact(), None, cf.source.reader, allowed)
            if r.state != "found":
                raise RestoreRefused(
                    f"the restored passage is `{r.state}` in the source on its own, so the "
                    f"record would not verify."
                )
            if not a.check:
                atomic_write(out, text)
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
