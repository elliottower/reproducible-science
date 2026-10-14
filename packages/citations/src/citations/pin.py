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

A passage the source has more than once is refused as `ambiguous`, because the record would
not say which occurrence it quotes. `--occurrence N` names one, counting from 1 in the source's
order, and writes the `prefix` and `suffix` that single it out: the source's own text on either
side, taken as far out as it takes for `verify` to find the anchored passage once, up to
`verify.MAX_ANCHOR_CHARS` characters a side. Past that the passage is refused, and the anchors
are for the author to write. The quotation is written without white space at its ends, which is
how a claims file is read back.

A pin is also when the source is on disk and about to be committed with everything else. Where
git tracks the source, or no ignore rule covers it, the command says so in one line and edits
nothing: the sha256 in the claims file is what pins the source, and the text itself is somebody
else's. See `tracked`.

A source read by a PDF reader is anchored in the text of the reader that reads it first. A
passage that reader misses and a fallback reader finds twice is `ambiguous` and cannot be
pinned with `--occurrence`.

`--url` pins against a web page, and is the one case where the claims file need not exist.
The page is the most recent retrieval of that URL in the `retrieved` library, or is captured
now where the library holds none; `--recapture` fetches it again. The claims file is written
with a `source` block naming the URL, the sha256 of the bytes, when they were retrieved and
where they are inside the library, and the page itself is never copied into the project. A
file that already pins that retrieval takes the quotation as any other does. One that pins
another source, or another retrieval of the page, is refused: a claims file pins one copy of
one source. Needs the `web` extra. See `web`.

    citations pin claims/guide.yaml --url https://docs.example.org/guide --id scope \
        --quote "the passage, exactly as the page has it"

    citations pin claims/notes2026.yaml --id second-run --occurrence 2 \
        --quote "the model reached an accuracy of 0.94 on the split"

Where a built-in extractor reads the source, named in it or chosen by its suffix, the first
quotation pinned also records `extractor` where the source names none, `extractor_version`
and `derived_sha256` in the source block: the extractor and version that read the file and the
digest of the text it produced. Nobody computes that digest by hand, and a field
nobody fills in is a check nobody runs. A later quotation is refused where the extractor no
longer produces that text, because the file would then hold quotations taken from two
different readings under one digest.
"""

from __future__ import annotations

import argparse
import pathlib

import yaml
from provenance_core import atomic_write, exclusive_lock

from . import extractors, tracked, web
from . import verify as V
from .exceptions import CitationsError
from .fetch import has_location
from .models import ClaimFile, load_claim_file


class PinRefused(CitationsError):
    """The quotation did not resolve, or the file cannot take it."""


def _artifact(cf: ClaimFile) -> pathlib.Path | None:
    return cf.artifact()


def from_url(path: pathlib.Path, url: str, recapture: bool) -> tuple[ClaimFile, dict, str]:
    """The claims file as it will read with the page at `url` as its source.

    Returns it with the `source` fields to write, which are none where the file already pins
    this retrieval, and one line saying which retrieval was read. A file that is not there, and
    one whose source records no more than this URL, take the whole block. Raises `PinRefused`
    where the file pins something else, before anything is fetched where the file alone says
    so, and `web.WebSourceError` where there is no page to pin.
    """
    held = load_claim_file(path) if path.exists() else ClaimFile()
    source = held.source
    if source.local or (source.url and source.url != url):
        raise PinRefused(
            f"{path.name} already pins {source.local or source.url}, and a claims file pins "
            f"one source. Name another file for this page."
        )
    page = web.obtain(url, path.resolve().parent.parent, recapture)
    said = (
        f"captured now, at {page.fetched_at}"
        if page.captured
        else f"the retrieval of {page.fetched_at}, already in the library"
    )
    said = f"{said}: {page.sha256[:12]} in {page.path.parent.parent}"
    pinned = (source.sha256 or "").strip().lower()
    if pinned and pinned != page.sha256:
        when = f", retrieved at {source.retrieved_at}" if source.retrieved_at else ""
        raise PinRefused(
            f"{path.name} pins {pinned[:12]}{when}, and this is another retrieval: {said}. "
            f"A claims file pins one copy of its source. Leave out --url to add to the copy it "
            f"pins, or name a new claims file for this one."
        )
    block = {} if source.retrieved else page.source()
    cf = held.model_copy(update={"source": source.model_copy(update=block)})
    cf.path = path
    return cf, block, said


def resolve(
    cf: ClaimFile,
    quote: str,
    page: int | None,
    allowed: frozenset[str],
    prefix: str = "",
    suffix: str = "",
) -> V.Result:
    """Read the pinned source and decide whether the passage is in it."""
    return V.check_one(
        quote, _artifact(cf), page, cf.source.reader, allowed, prefix=prefix, suffix=suffix
    )


def anchors(cf: ClaimFile, quote: str, occurrence: int, allowed: frozenset[str]) -> tuple[str, str]:
    """The prefix and suffix that single out one occurrence of a passage the source repeats.

    Read from the text `resolve` just decided against, so the anchors and the verdict rest on
    one reading. Raises `PinRefused` where the source has no such occurrence.
    """
    artifact = _artifact(cf)
    assert artifact is not None
    reader = V.declared_extractor(cf.source.reader)
    got = V.reading(artifact, None, reader, allowed) if reader else V.reading(artifact)
    found = V.single_out(quote, got.text, occurrence)
    if found is None:
        n = V.resolve_in(quote, got.text).count
        if occurrence > n:
            raise PinRefused(
                f"the passage occurs {n} times in the source, so there is no occurrence "
                f"{occurrence}. --occurrence takes 1 to {n}."
            )
        raise PinRefused(
            f"no prefix and suffix of up to {V.MAX_ANCHOR_CHARS:,} characters each single out "
            f"occurrence {occurrence} of {n}: the text around it repeats for longer than that, "
            f"or the passage begins or ends on a hyphen that folds differently beside its "
            f"neighbours. Write `prefix`/`suffix` into the claims file by hand."
        )
    return found


def reading_record(cf: ClaimFile, r: V.Result) -> dict:
    """What the source block gains from this pin: the extractor's version and its text's digest.

    The version recorded is the one that read the file for this pin, which `r` names. A source
    naming no extractor that a built-in extractor read by its suffix gains the extractor's name
    too, so a later version of it never reads quotations pinned under this one. Empty for a
    source no built-in extractor read, and for one that already records all of it. Raises
    `PinRefused` where the recorded digest is not the digest of the text this passage was just
    found in.
    """
    if not (cf.source.extractor or extractors.is_builtin(r.extractor)):
        return {}
    name, _, version = r.extractor.split()[0].partition("@") if r.extractor else ("", "", "")
    recorded = (cf.source.derived_sha256 or "").strip().lower()
    if recorded and recorded != r.extraction_digest:
        raise PinRefused(
            f"{cf.source.extractor or name} now produces other text from this source than the "
            f"text its quotations were pinned in (recorded {recorded[:12]}, produced "
            f"{r.extraction_digest[:12]}). Run `citations verify` to see which quotations still "
            f"resolve before adding another."
        )
    record: dict = {}
    if not cf.source.extractor and name:
        record["extractor"] = name
    if cf.source.extractor_version is None and version.isdigit():
        record["extractor_version"] = int(version)
    if not recorded:
        record["derived_sha256"] = r.extraction_digest
    return record


def entry(
    quote: str,
    section: str | None,
    page: int | None,
    says: str | None,
    whose: str | None,
    status: str,
    contest: str | None,
    prefix: str = "",
    suffix: str = "",
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
    if prefix:
        q["prefix"] = prefix
    if suffix:
        q["suffix"] = suffix
    if section:
        q["section"] = section
    if page is not None:
        q["page"] = page
    claim["quotes"] = [q]
    return claim


def add_to(path: pathlib.Path, claim_id: str, claim: dict, source: dict | None = None) -> None:
    """Append one claim to the file, preserving what is already there.

    `source` is merged into the source block in the same write: see `reading_record`. A file
    that is not there yet is created, which is how a page pinned by `--url` gets its claims
    file, and a `source` that names a sha256 other than the one the file holds is refused.

    The file is re-read and re-written as data rather than patched as text: a claims file is
    the input to a check, and a command that edited it with a regular expression would be the
    kind of tool this package exists to argue against.

    The whole document is rewritten, so the read is held under the lock with the write. Two
    `pin` calls that read the same file each write a document carrying only their own claim, the
    second erases the first, and both print `added`: the quotation is gone and nothing says so.
    The duplicate-id guard reads that same snapshot, so unlocked it also admits two claims under
    one identifier -- the case it exists to refuse -- because neither caller can see the other's.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with exclusive_lock(path):
        doc = (yaml.safe_load(path.read_text()) if path.exists() else None) or {}
        pinned = (doc.get("source") or {}).get("sha256")
        if source and pinned and source.get("sha256", pinned) != pinned:
            # Two `pin --url` calls creating one file, with the page changed between them.
            raise PinRefused(
                f"{path.name} was written meanwhile and pins {pinned[:12]}; this quotation was "
                f"resolved in {source['sha256'][:12]}. Nothing was added."
            )
        if source:
            doc.setdefault("source", {}).update(source)
        claims = doc.setdefault("claims", {})
        if claim_id in claims:
            raise PinRefused(
                f"{path.name} already defines the claim {claim_id!r}. "
                "Two claims under one identifier are two claims; give this one its own."
            )
        claims[claim_id] = claim
        # Atomically: a claims file is the input to every later check, and a truncating write
        # that dies partway through leaves a document that no longer parses as one.
        atomic_write(path, yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=100))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="citations pin", description=__doc__)
    ap.add_argument("claims_file", type=pathlib.Path, help="the claims/*.yaml to add to")
    ap.add_argument("--id", required=True, help="the claim's identifier within the file")
    ap.add_argument("--quote", required=True, help="the passage, exactly as the source has it")
    ap.add_argument(
        "--occurrence",
        type=int,
        metavar="N",
        help="which occurrence of a passage the source repeats, counting from 1; "
        "the prefix and suffix that single it out are written with the quotation",
    )
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
    ap.add_argument(
        "--url",
        help="pin against the web page at this address, as the `retrieved` library holds it "
        "or captures it now; writes the claims file where there is none "
        f'(needs pip install "{web.EXTRA}")',
    )
    ap.add_argument(
        "--recapture",
        action="store_true",
        help="with --url, fetch the page again and pin that, whatever the library holds",
    )
    ap.add_argument("--check", action="store_true", help="resolve and report, write nothing")
    a = ap.parse_args(argv)
    # As the claims file will be read back: the model strips `exact` on load, and anchors
    # found for a quotation with a trailing space would be anchors for another string.
    a.quote = a.quote.strip()

    if a.occurrence is not None and a.occurrence < 1:
        print("--occurrence counts from 1.")
        return 2

    if a.says is not None and not a.whose:
        # The schema's requirement, enforced at the point a characterization is written rather
        # than at the point someone later reads the file and cannot tell whose reading it is.
        print("--says needs --whose: a characterization with no owner reads as the source's.")
        return 2

    if a.recapture and not a.url:
        print("--recapture needs --url: it fetches the page that --url names.")
        return 2

    path: pathlib.Path = a.claims_file
    page: dict = {}
    if a.url:
        try:
            cf, page, said = from_url(path, a.url, a.recapture)
        except (PinRefused, web.WebSourceError) as e:
            print(f"refused   {a.url}")
            print(f"  {e}")
            print("nothing written.")
            return 1
        print(f"page      {a.url}")
        print(f"  {said}")
    elif not path.exists():
        print(f"no such claims file: {path}")
        return 2
    else:
        cf = ClaimFile.model_validate(yaml.safe_load(path.read_text()) or {})
        cf.path = path

    allowed = V.DEFAULT_EXTRACTORS | frozenset(a.allow_extractor)
    r = resolve(cf, a.quote, a.page, allowed)

    prefix = suffix = ""
    if a.occurrence is not None and r.state in ("found", "ambiguous"):
        if r.state == "found" and a.occurrence != 1:
            print(f"found once  {a.quote[:60]}")
            print(
                f"  the passage occurs once in the source, so there is no occurrence {a.occurrence}."
            )
            print("nothing written.")
            return 1
        if r.state == "ambiguous":
            try:
                prefix, suffix = anchors(cf, a.quote, a.occurrence, allowed)
            except PinRefused as e:
                print(f"ambiguous  {a.quote[:60]}")
                print(f"  {e}")
                print("nothing written.")
                return 1
            # Through the same check `verify` will run, with the anchors as they will be
            # written: what goes into the file is what was seen to resolve.
            r = resolve(cf, a.quote, a.page, allowed, prefix, suffix)

    if r.state != "found":
        print(f"{r.state}  {a.quote[:60]}")
        if r.detail:
            print(f"  {r.detail}")
        print("nothing written. read the source before recording the passage.")
        return 1

    claim = entry(a.quote, a.section, a.page, a.says, a.whose, a.status, a.contest, prefix, suffix)
    record = page | reading_record(cf, r)
    singled = (
        f"  occurrence {a.occurrence}, singled out by the prefix and suffix written with it"
        if prefix or suffix
        else ""
    )
    if a.check:
        print(f"found     {a.quote[:60]}")
        print(f"would add {a.id} to {path.name}")
        if singled:
            print(singled)
        if r.warnings:
            print(f"  warnings: {', '.join(r.warnings)}")
        return 0

    add_to(path, a.id, claim, record)
    print(f"found     {a.quote[:60]}")
    print(f"added     {a.id} to {path.name}")
    if singled:
        print(singled)
    if r.warnings:
        print(f"  warnings: {', '.join(r.warnings)}")
    if a.says is not None:
        print(f"  reading recorded as {a.whose}'s, unchecked")
    if (artifact := _artifact(cf)) is not None and (kept := tracked.advice(artifact)):
        # Said here because this is when the source was put on disk, and the next `git add`
        # is when it stops being a private copy. Nothing is written to `.gitignore`.
        print(f"  {kept}")
    if not has_location(cf.source):
        # Said at the moment the source is in hand. A reader who clones the repository has the
        # pin and not the file, and without one of these `citations fetch` has nowhere to ask.
        print(
            f"  {path.name} records no url, doi or arxiv id for its source: add `url:` or "
            f"`doi:` under `source:` so `citations fetch` can retrieve it for a reader"
        )
    return 0
