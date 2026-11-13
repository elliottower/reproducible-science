"""The `citations` command.

citations init              make a library here
citations verify            do my quotations resolve in the sources I pinned?
citations manual-check      record that I compared one quotation with the page
citations coverage          is every quotation in my manuscript pinned at all?
citations audit             does the metadata match the record the identifier resolves to?
citations resolve           backfill missing identifiers
citations build             rebuild records from the papers' bibliographies
citations lint              BibTeX correctness, repeated keys, and author lists in a .bib
citations add               add one entry to a .bib, refusing a key it already has
citations pin               write a quotation into a claims file, refusing one that does not resolve
citations restore           write the source's passage for a quotation that leaves text out, apart
citations link              point pdfs/ at wherever the papers keep the artifacts
citations fetch             download the sources a claims directory pins, keeping only matching bytes
citations projects          which projects this library refers to, and which names are dead
citations tags              what the tag vocabulary declares, and what the records use
citations import-paperclip  turn a Paperclip paper repo into pinned claim files
"""

from __future__ import annotations

import argparse
import collections
import concurrent.futures
import json
import os
import pathlib

from provenance_core import atomic_write, atomic_write_bytes, exclusive_lock, hint

from citations import coverage as C
from citations import extraction_cache, paths, projects, tracked, web
from citations import manual_checks as MC
from citations import verify as V
from citations.entry import DELEGATED
from citations.entry import delegate as _delegate
from citations.exceptions import CitationsError, ClaimFileError, SourceUnreadableError
from citations.models import ClaimFile, Quote, load_claim_file, load_record

#: Every member of `verify.State`, in reporting order. An outcome absent here is
#: counted and never printed: the table stops summing to the number of quotations
#: above it, and a run whose only problem is that outcome reads as clean.
RESULTS = ["found", "corrected", "not found", "ambiguous", "indeterminate", "unchecked"]

#: Width of the outcome column, computed so adding an outcome does not silently ragged the
#: table. `indeterminate` is the longest, and naming an outcome for what it means rather than
#: for what fits is why this is derived instead of written down.
OUTCOME_WIDTH = max(len(r) for r in RESULTS) + 1
WARNINGS = {
    "truncated": "begins or stops mid-word or mid-number — the source continues it",
    "line-end hyphen": "begins or ends where the source breaks a word across lines with a hyphen "
    "— check it does not cut the word",
    "short": "the source may qualify this in the next clause",
    "normalized": "matched after ignoring punctuation and spacing",
    "page": "found, but not on the page recorded",
    "page unchecked": "a page is recorded and was not checked: the source has no pages to ask "
    "for, or the passage matched only with spacing ignored",
}

#: The warnings `verify.correct` adds to a `corrected` result, apart from `WARNINGS`: they say
#: what a correction typed by hand changes, and no check of a passage against a source's text
#: can raise them.
CORRECTION_WARNINGS = {
    "correction changes a number": "the passage recorded by hand has other numbers than what "
    "the extractor reads — compare it with the page",
    "correction changes a comparison": "the passage recorded by hand has another `<`, `>`, `=`, "
    "`≤` or `≥` than what the extractor reads — compare it with the page",
    "correction adds a negation": "the passage recorded by hand denies what the extractor "
    "reads — compare it with the page",
    "correction removes a negation": "the extractor reads a denial the passage recorded by hand "
    "drops — compare it with the page",
    "correction adds a hedge": "the passage recorded by hand hedges what the extractor reads — "
    "compare it with the page",
    "correction removes a hedge": "the extractor reads a hedge the passage recorded by hand "
    "drops — compare it with the page",
}


def _records() -> list:
    """Every record in the governing library, validated."""
    return [load_record(p) for p in sorted(paths.records().glob("*.yaml"))]


def _claim_files(root: pathlib.Path, skipped=None) -> list[ClaimFile]:
    """Every claims file under `root`, validated.

    A file that is refused when read is reported and skipped rather than ending the run: one
    malformed file should not hide the state of the other three hundred. `verify` fails the
    run on it all the same; see `verify.Report.ok`.
    """
    out: list[ClaimFile] = []
    skipped = [] if skipped is None else skipped
    for p in sorted(root.glob("*.yaml")):
        try:
            out.append(load_claim_file(p))
        except ClaimFileError as e:
            reason = e.detail.splitlines()[0]
            print(f"  skipped  {p.name}: {reason}")
            skipped.append((p.name, reason))
    return out


def _record_extractor(rep: V.Report, extractors, r: V.Result) -> None:
    """Note what read this source, why it was not the preferred extractor, and whether more
    than one was asked.

    Kept on the report rather than printed as it happens: a substitution that only ever
    appeared in a log line is one no later run can compare itself against.
    """
    if not r.extractor:
        return
    extractors[r.extractor] += 1
    if len(r.agreement) > 1:
        rep.triangulated += 1
    if r.fallback and r.extractor not in rep.fallback_reasons:
        rep.fallback_reasons[r.extractor] = r.fallback_reason or "pdftotext did not answer"


def _check_reading(rep: V.Report, cf: ClaimFile, artifact, allowed) -> None:
    """Note a source whose extractor no longer produces the text its quotations were pinned in.

    Only where the claims file records `derived_sha256` and the source could be read. A source
    nothing could read is not a reading that changed: its quotations are `unchecked`, each
    with the reason, and reporting it here as well would state a comparison nobody made.
    """
    if not cf.source.derived_sha256 or artifact is None or not artifact.is_file():
        return
    try:
        text = V.extract(artifact, None, cf.source.reader, allowed)
    except SourceUnreadableError:
        return
    derived = V.check_derived(text, cf.source.derived_sha256)
    if derived.state == "broken":
        rep.changed_readings.append((cf.name, derived))


def _corrected(
    rep: V.Report,
    name: str,
    q: Quote,
    r: V.Result,
    artifact: pathlib.Path | None,
    extract_cmd: str | None = None,
    allowed: frozenset[str] = V.DEFAULT_EXTRACTORS,
) -> V.Result:
    """The verdict on a quotation once the correction it carries is considered.

    A correction whose source text now holds the quotation is noted as possibly unneeded, and
    one that does not apply is noted with why; neither is applied. See `verify.correct`.
    """
    if q.correction is None:
        if "corrections" in (q.model_extra or {}):
            # A misspelt key would otherwise drop the correction without a word.
            rep.unapplied_corrections.append(
                (name, "`corrections` is not a field this package reads; it is `correction`")
            )
        return r
    if r.state in ("found", "ambiguous"):
        rep.unneeded_corrections.append(name)
        return r
    if r.state != "not found" or artifact is None:
        return r
    made = V.correct(q.text, q.page, q.correction, r, artifact, extract_cmd, allowed)
    if made.unapplied:
        rep.unapplied_corrections.append((name, made.unapplied))
    else:
        flags = tuple(w for w in made.result.warnings if w.startswith("correction "))
        c = q.correction
        rep.corrected.append(
            V.Corrected(name, q.text, made.note, c.reads, c.passage, made.diff, flags)
        )
    return made.result


COVERAGE = ["covered", "uncovered", "unresolvable"]
COVERAGE_WIDTH = max(len(s) for s in COVERAGE) + 1


def cmd_coverage(a) -> int:
    """Every quotation in the manuscript, against what is pinned."""
    manuscript = pathlib.Path(a.manuscript)
    if not manuscript.is_file():
        print(f"no manuscript at {manuscript}")
        return 2
    claims_dir = pathlib.Path(a.claims)
    if not claims_dir.is_dir():
        print(f"no claims directory at {claims_dir}")
        return 2

    quotes = C.quotations(manuscript.read_text(errors="replace"))
    print(f"manuscript  {manuscript}")
    print(f"claims      {claims_dir}")
    print()
    if not quotes:
        # Not a pass. A manuscript with no ``...'' may quote nothing, or may quote with a
        # convention this does not read, and the two are worth telling apart by eye.
        print("no ``...'' quotations found. nothing was checked.")
        return 1 if a.strict else 0

    skipped: list = []
    files = _claim_files(claims_dir, skipped)
    allowed = V.DEFAULT_EXTRACTORS | frozenset(a.allow_extractor or ())

    if a.attribute:
        by_key, missing = C.artifacts_by_key(files, claims_dir, allowed)
        findings = [C.attribute(q, by_key, missing) for q in quotes]
    else:
        pool = C.pinned_spans(files)
        findings = [C.cover(q, pool) for q in quotes]

    counts: collections.Counter = collections.Counter(f.status for f in findings)
    for status in COVERAGE:
        n = counts.get(status, 0)
        if n or status != "unresolvable":
            print(f"  {status:<{COVERAGE_WIDTH}}{n:>7,}")

    problems = [f for f in findings if f.status != "covered"]
    if problems:
        print()
        for f in problems:
            head = "UNCOVERED" if f.status == "uncovered" else "unresolvable"
            print(f"  {head}  {manuscript.name}:{f.quotation.line}")
            print(f"    ``{f.quotation.raw.strip()[:96]}''")
            print(f"    {f.detail}")

    print()
    uncovered = counts.get("uncovered", 0)
    unresolvable = counts.get("unresolvable", 0)
    if uncovered:
        print(f"{uncovered} quotation(s) the manuscript makes and nothing pins.")
        print("pin them, or stop quoting them. an unpinned quotation is not checked by anything.")
    elif unresolvable:
        print(f"nothing uncovered. {unresolvable} could not be decided; see the reasons above.")
    else:
        print(f"every quotation is {'attributed' if a.attribute else 'covered'}.")

    if a.strict:
        return 1 if (uncovered or unresolvable) else 0
    return 1 if uncovered else 0


def _extract_ahead(files: list[ClaimFile], allowed: frozenset[str]) -> None:
    """Read every source once, several at a time, before the quotations are checked in order.

    Each reading lands in the extraction cache, where the pass below finds it. A source that
    cannot be read is left for that pass to report. Two claims files naming one source are one
    reading: two threads asking for it together would each run the extractor.
    """
    wanted: dict[tuple[pathlib.Path, str | None], None] = {}
    for cf in files:
        artifact = cf.artifact()
        if artifact is not None and artifact.is_file():
            wanted[(artifact, V.declared_extractor(cf.source.reader))] = None

    def read(reading: tuple[pathlib.Path, str | None]) -> None:
        artifact, declared = reading
        try:
            if declared:
                V.extract(artifact, None, declared, allowed)
            else:
                V.extract(artifact, None)
        except SourceUnreadableError:
            return

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(8, os.cpu_count() or 1)) as pool:
        list(pool.map(read, wanted))


def cmd_verify(a) -> int:
    rep = V.Report()
    extraction_cache.use_default(disabled=getattr(a, "no_cache", False))
    counts: collections.Counter = collections.Counter()
    extractors: collections.Counter = collections.Counter()
    # Consent to run a program comes from whoever invokes the command, never from the file
    # being checked. See the trust model in `verify.py`.
    allowed = V.DEFAULT_EXTRACTORS | frozenset(a.allow_extractor or ())

    if a.claims:
        root = pathlib.Path(a.claims).expanduser().resolve()
        library = paths.find()
        files = list(_claim_files(root, skipped=rep.skipped))
        if extraction_cache.enabled() and len(files) > 1:
            _extract_ahead(files, allowed)
        read: list[tuple[str, pathlib.Path]] = []
        lists: list[MC.Listed] = []
        manual = MC.ManualChecks(sha256="")
        for cf in files:
            artifact, missing, held = _located(cf, library)
            if held and artifact is not None:
                rep.from_library.append((cf.name, artifact))
            pin = V.check_pin(artifact, cf.source.sha256)
            if pin.state == "broken":
                rep.broken_pins.append((cf.name, pin))
            elif pin.state == "unpinned":
                rep.unpinned.append(cf.name)
            rep.sources += 1
            if artifact is not None and artifact.is_file():
                read.append((cf.name, artifact))
            else:
                rep.absent_sources += 1
            _check_reading(rep, cf, artifact, allowed)
            if cf.version_inferred:
                rep.inferred.append((cf.name, cf.version_inferred))
            listed = _manual_list(cf)
            by_quote: dict[tuple[str, int], MC.Entry] = {}
            if listed is not None:
                lists.append(listed)
                matched = MC.match(listed, cf)
                by_quote = matched.found
                manual.problems += listed.problems + matched.problems
                manual.unknown += [MC.Unknown(path=listed.path, id=e.id) for e in matched.unknown]
            for cid, claim in cf.claims.items():
                if claim.interpretation is not None:
                    rep.interpretations += 1
                    whose = claim.interpretation.whose
                    if whose not in {"ours", cf.source.citation}:
                        rep.foreign_readings += 1
                    if claim.interpretation.status == "contested":
                        rep.contested_readings += 1
                for i, q in enumerate(claim.quotes):
                    if not q.text:
                        continue
                    rep.checked += 1
                    rep.restored += claim.is_restored
                    r = V.check_one(
                        q.text,
                        artifact,
                        q.page,
                        cf.source.reader,
                        allowed,
                        a.triangulate,
                        q.prefix,
                        q.suffix,
                        missing,
                    )
                    r = _corrected(
                        rep, f"{cf.name}:{cid}", q, r, artifact, cf.source.reader, allowed
                    )
                    counts[r.state] += 1
                    _record_extractor(rep, extractors, r)
                    if r.state != "found" or r.warnings:
                        rep.problems.append((f"{cf.name}:{cid}", q.text, r))
                    if (entry := by_quote.get((cid, i))) is not None:
                        _manual_check(manual, cf, f"{cf.name}:{cid}", q.text, r, entry)
        manual.orphans = MC.orphans(root, files)
        if lists or manual.orphans:
            manual.lists, manual.sha256, manual.passages = lists, MC.digest(lists), rep.checked
            rep.manual_checks = manual
        rep.counts = dict(counts)
        rep.extractors = dict(extractors)
        rep.from_cache = extraction_cache.hits()
        # Asked once for the whole run, a directory at a time. See `tracked`.
        in_git = tracked.tracked(artifact for _, artifact in read)
        rep.tracked_sources = [(name, artifact) for name, artifact in read if artifact in in_git]
        in_head = tracked.committed(artifact for _, artifact in read) - in_git
        rep.committed_sources = [(name, artifact) for name, artifact in read if artifact in in_head]
        return _report(rep, counts, a, f"claims  {root}")

    lib, origin = paths.find_with_origin()
    source = f"library {lib}" + (
        "  (user-level: no .citations/ in this directory or above it)" if origin == "user" else ""
    )
    for rec in _records():
        if a.only and a.only not in rec.cited_by:
            continue
        artifact = (paths.home() / rec.local) if rec.local else None
        if rec.quotes:
            pin = V.check_pin(artifact, rec.sha256)
            if pin.state == "broken":
                rep.broken_pins.append((rec.slug, pin))
            elif pin.state == "unpinned":
                rep.unpinned.append(rec.slug)
        for q in rec.quotes:
            if not q.text:
                continue
            rep.checked += 1
            r = V.check_one(
                q.text, artifact, q.page, None, allowed, a.triangulate, q.prefix, q.suffix
            )
            r = _corrected(rep, rec.slug, q, r, artifact, None, allowed)
            counts[r.state] += 1
            _record_extractor(rep, extractors, r)
            if r.state != "found" or r.warnings:
                rep.problems.append((rec.slug, q.text, r))
    rep.counts = dict(counts)
    rep.extractors = dict(extractors)
    rep.from_cache = extraction_cache.hits()
    return _report(rep, counts, a, source)


def _located(cf: ClaimFile, library: pathlib.Path | None) -> tuple[pathlib.Path | None, str, bool]:
    """Where a claims file's source is on this machine, the reason recorded where it is not,
    and whether the copy read is the library's."""
    artifact = cf.artifact()
    if artifact is None or artifact.exists():
        return artifact, V.MISSING, False
    if not cf.source.local:
        # A web page pinned by its URL, on a machine whose `retrieved` library does not hold
        # it. Its bytes are named by their digest, so there is no second place to look, and
        # the reason says which store was asked.
        return artifact, web.missing(cf), False
    # The path as given first, and the library only where that is empty. A copy there is read
    # only where it matches the pin: see `verify.library_copy`.
    held, missing = V.library_copy(
        artifact.name, cf.source.sha256, library / "pdfs" if library else None
    )
    return (held, missing, True) if held is not None else (artifact, missing, False)


def cmd_manual_check(a) -> int:
    """Record that a person compared one quotation with the page: print it, then append its line
    to the list beside its claims file, with the fingerprint it has now.

    One id per call, and no form that names several: the line says a person looked at this
    passage, and a command that wrote it for every quotation at once would say that of passages
    nobody looked at.
    """
    if a.note and ("\n" in a.note or "\r" in a.note):
        raise CitationsError("--note is one line: it is written after a `#` on the quotation's")
    if a.page is not None and a.page < 1:
        raise CitationsError(f"--page is 1 or more; read {a.page}")
    path = pathlib.Path(a.claims_file).expanduser().resolve()
    cf = load_claim_file(path)
    key = next((k for k, names in MC.quotation_ids(cf).items() if MC.nfc(a.id) in names), None)
    if key is None:
        raise CitationsError(f"{path}: no quotation has the id `{a.id}`")
    cid, i = key
    q = cf.claims[cid].quotes[i]
    allowed = V.DEFAULT_EXTRACTORS | frozenset(a.allow_extractor or ())
    artifact, missing, _ = _located(cf, paths.find())
    r = V.check_one(
        q.text, artifact, q.page, cf.source.reader, allowed, False, q.prefix, q.suffix, missing
    )
    fingerprint = MC.now(q.text, cf.source, r.extraction_digest)
    if not fingerprint:
        raise CitationsError(
            f"{path}: the source was not read here ({r.detail or r.state}) and the claims file "
            "records no derived_sha256, so there is no reading to fingerprint"
        )
    list_file = MC.list_path(path)
    # Read, decided and written under one lock: two calls that read the same list each write it
    # back with only their own line, and the second erases the first. The lock is the resolved
    # file's, as the write goes through a link to it, so two links to one list share one lock.
    with exclusive_lock(os.path.realpath(list_file)):
        listed = MC.read(list_file, cf.name) if _present(list_file) else None
        if listed is not None and listed.problems:
            # Written into, a list must parse: a line appended below one that does not would be
            # recorded beside a problem nobody has looked at.
            raise CitationsError("\n".join(listed.problems))
        entry = MC.match(listed, cf).found.get(key) if listed is not None else None
        if entry is not None and entry.fingerprint == fingerprint:
            raise CitationsError(
                f"{list_file}:{entry.line}: `{a.id}` is listed already, as `{entry.id}`, with the "
                "fingerprint it has now"
            )
        if entry is not None and not a.again:
            raise CitationsError(
                f"{list_file}:{entry.line}: `{a.id}` was checked as `{entry.id}` with fingerprint "
                f"{entry.fingerprint or 'none'}, and has {fingerprint} now; compare it with the "
                "page again, then rerun with --again to replace that line"
            )
        if entry is None and a.again:
            raise CitationsError(
                f"{list_file}: --again replaces an earlier check of `{a.id}`, and none is listed"
            )
        # `--again` keeps the earlier line's page and note where none is given.
        page = a.page if a.page is not None or entry is None else entry.page
        note = a.note if a.note is not None or entry is None else entry.note
        try:
            line = MC.line(a.id, fingerprint, page, note or "")
        except ValueError as e:
            raise CitationsError(f"{list_file}: not written: {e}") from e
        written = _rewritten(list_file, listed, entry, line)
        if len(written) > MC.MAX_BYTES:
            # `verify` reads no list past this size, so the line would be recorded nowhere.
            raise CitationsError(
                f"{list_file}: not written: the list would be {len(written):,} bytes, and verify "
                f"reads none larger than {MC.MAX_BYTES:,}"
            )

        print(f"claims  {path}")
        print(f"source  {cf.source.citation}  ({artifact or 'no copy named'})")
        print(f"page    {q.page if q.page is not None else 'none recorded'}")
        print(f"quote   {q.text}")
        print(f"computed outcome: {r.state}; a manual check changes no outcome")
        atomic_write_bytes(list_file, written)
        if entry is not None:
            print(f"replaces the earlier check on line {entry.line}: {entry.written()}")
    print(f"wrote   {line}")
    print(f"to      {list_file}")
    return 0


def _present(path: pathlib.Path) -> bool:
    """Whether anything is at `path`: a file, a directory, or a link to nothing, so a list that
    is there and cannot be read is recorded rather than taken for no list."""
    return path.exists() or path.is_symlink()


def _rewritten(
    list_file: pathlib.Path, listed: MC.Listed | None, entry: MC.Entry | None, line: str
) -> bytes:
    """The list's bytes with `line` replacing `entry`'s, or appended, keeping the file's
    byte-order mark and each line's own ending; an appended line takes the first line's."""
    raw = list_file.read_bytes() if listed is not None else b""
    bom = raw.startswith(b"\xef\xbb\xbf")
    lines = raw.decode("utf-8-sig").splitlines(keepends=True)
    ending = next((x[len(x.rstrip("\r\n")) :] for x in lines if x.endswith(("\r", "\n"))), "\n")
    if entry is not None:
        was = lines[entry.line - 1]
        lines[entry.line - 1] = line + was[len(was.rstrip("\r\n")) :]
    else:
        if lines and not lines[-1].endswith(("\r", "\n")):
            lines[-1] += ending
        lines.append(line + ending)
    return (b"\xef\xbb\xbf" if bom else b"") + "".join(lines).encode("utf-8")


def _manual_list(cf: ClaimFile) -> MC.Listed | None:
    """The list of manual checks beside this claims file, where there is one. One that is there
    and cannot be read is returned with the reason in its `problems`."""
    if cf.path is None or not _present(path := MC.list_path(cf.path)):
        return None
    return MC.read(path, cf.name)


def _manual_check(
    manual: MC.ManualChecks, cf: ClaimFile, claim: str, text: str, r: V.Result, entry: MC.Entry
) -> None:
    """Record a listed quotation as covered, with its computed outcome, or as stale where its
    text, its source's digest, its reader or the reading are not what they were when it was
    listed."""
    now = MC.now(text, cf.source, r.extraction_digest)
    if not now:
        manual.unverifiable.append(
            MC.Unverifiable(claim=claim, id=entry.id, listed=entry.fingerprint)
        )
        return
    if entry.fingerprint != now:
        manual.stale.append(MC.Stale(claim=claim, id=entry.id, listed=entry.fingerprint, now=now))
        return
    manual.covered.append(
        MC.Covered(
            claim=claim, id=entry.id, quote=text, state=r.state, page=entry.page, note=entry.note
        )
    )


def _manual_lines(manual: MC.ManualChecks) -> list[str]:
    """The manual checks, printed only under `--show-manual`: provenance, never a verdict."""
    lines = [
        f"\nmanual checks: {len(manual.covered):,} of {manual.passages:,} passages, "
        f"list sha256 {manual.sha256[:12]}; they change no outcome"
    ]
    if manual.covered:
        said = ", ".join(f"{manual.outcomes[s]:,} {s}" for s in RESULTS if manual.outcomes.get(s))
        lines.append(f"  of those, as computed: {said}")
        for c in manual.covered:
            page = f"  p.{c.page}" if c.page is not None else ""
            lines.append(f"    {c.state:<{OUTCOME_WIDTH}}{c.claim[:38]:<40}{c.id}{page}")
    for s in manual.stale:
        lines.append(
            f"  stale    {s.claim[:38]:<40}{s.id}  listed {s.listed or 'none'}  now {s.now}"
        )
    for u in manual.unverifiable:
        lines.append(
            f"  unverifiable  {u.claim[:38]:<40}{u.id}  listed {u.listed or 'none'}; the source "
            "was not read here and no derived_sha256 is recorded"
        )
    for u in manual.unknown:
        lines.append(f"  unknown  {u.id}  in {u.path}")
    for path in manual.orphans:
        lines.append(f"  beside no claims file read  {path}")
    for problem in manual.problems:
        lines.append(f"  not read  {problem}")
    return lines


def _refused(rep: V.Report) -> list[str]:
    """The claims files refused when read, each with why. Their quotations were never examined,
    so none of them is in any count, and the run fails on them with or without `--strict`."""
    n = len(rep.skipped)
    lines = [f"{n} claims file{'' if n == 1 else 's'} refused when read, quotations unchecked"]
    lines += [f"  refused  {name}: {why}" for name, why in rep.skipped[:10]]
    if n > 10:
        lines.append(f"  ... and {n - 10} more")
    return lines


def _warned(rep: V.Report) -> dict[str, list[dict[str, str]]]:
    """Each warning, with the quotations carrying it: the claims file and claim, and the text."""
    out: dict[str, list[dict[str, str]]] = {}
    for slug, text, r in rep.problems:
        for w in r.warnings:
            out.setdefault(w, []).append({"claim": slug, "quote": text, "state": r.state})
    return out


def _report(rep: V.Report, counts, a, source: str = "") -> int:
    # What was checked, before how it went. A clean run against the wrong library reads exactly
    # like a clean run against the right one, and the path is the only thing that separates them.
    if source:
        print(f"{source}\n")
    if getattr(a, "json", None):
        # The counts below, as one object. `sources` and `absent_sources` are counted only
        # with `--claims`, where each file names the one source it pins.
        atomic_write(
            a.json,
            json.dumps(
                {
                    "quotes": rep.checked,
                    "counts": {state: counts.get(state, 0) for state in RESULTS},
                    "sources": rep.sources,
                    "absent_sources": rep.absent_sources,
                    "broken_pins": len(rep.broken_pins),
                    "unpinned_sources": len(rep.unpinned),
                    "skipped_files": len(rep.skipped),
                    "unapplied_corrections": len(rep.unapplied_corrections),
                    "unneeded_corrections": len(rep.unneeded_corrections),
                    "corrected": [
                        {
                            "claim": c.claim,
                            "quote": c.quote,
                            "note": c.note,
                            "reads": c.reads,
                            "passage": c.passage,
                            "diff": c.diff,
                            "flags": list(c.flags),
                        }
                        for c in rep.corrected
                    ],
                    "warnings": _warned(rep),
                    "manual_checks": (
                        None
                        if rep.manual_checks is None
                        else rep.manual_checks.model_dump(mode="json")
                        | {"outcomes": rep.manual_checks.outcomes}
                    ),
                },
                indent=2,
            )
            + "\n",
        )
    if rep.checked == 0 and rep.skipped:
        # Not "nothing to check": there were claims files, and none of them could be read.
        print("\n".join(_refused(rep)))
        return 1
    if rep.checked == 0:
        print("nothing to check.\n")
        print("quotes live in a paper's claims/ directory. point at one:")
        print("    citations verify --claims <path>")
        return 2

    print(f"{rep.checked:,} quotes\n")
    for s in RESULTS:
        n = counts.get(s, 0)
        if not n and s == "not found":
            print(f"  {s:<{OUTCOME_WIDTH}}{n:>7}")
            continue
        if not n:
            continue
        why = ""
        if s == "not found" and (
            omitted := sum(r.reason == V.OMISSION for _, _, r in rep.problems if r.state == s)
        ):
            # Its own count, because the remedy differs: every piece is in the source. That
            # says nothing about the text left out, which can be what the sentence turns on.
            why = f"   {omitted:,} in the source only in pieces, with text left out between them"
        if s == "corrected":
            # Never folded into `found`: the passage was compared with text a person recorded.
            why = "   in a passage recorded by hand where the extractor misreads the page"
        if s in ("unchecked", "indeterminate", "ambiguous"):
            # Untruncated: the reason is the only thing that says what to fix, and the one
            # that matters most -- "which this run does not allow" -- is at the end of it.
            reasons = collections.Counter(r.detail for _, _, r in rep.problems if r.state == s)
            why = (
                "   " + " · ".join(f"{c:,} {d}" for d, c in reasons.most_common())
                if len(reasons) > 1
                else f"   {reasons.most_common(1)[0][0]}"
            )
        print(f"  {s:<{OUTCOME_WIDTH}}{n:>7,}{why}")
        if s == "corrected":
            # What each correction changed, always: they are few, and a change of meaning
            # typed by hand is read here or nowhere.
            for c in rep.corrected:
                flagged = f"   ({'; '.join(c.flags)})" if c.flags else ""
                if getattr(a, "verbose", False):
                    print(f"             {c.claim[:38]:<40}{c.quote[:60]}")
                    print(f"             {'':<40}{c.diff}{flagged}")
                else:
                    print(f"             {c.claim[:38]:<40}{c.diff}{flagged}")

    # Which extractor a verdict rests on, before the verdicts. A `found` taken through a
    # declared renderer and one taken through `pdftotext` are different records, and a report
    # that does not separate them cannot be compared with a later run.
    if rep.extractors:
        print("\nread by")
        for name, n in sorted(rep.extractors.items(), key=lambda kv: (-kv[1], kv[0])):
            why = rep.fallback_reasons.get(name, "")
            print(f"  {n:>7,}  {name}" + (f"   fallback: {why[:50]}" if why else ""))
    # A version this run chose for a source that records none, said where it was chosen: a
    # reader who expected another version learns which one read the file and how to name it.
    for name, said in rep.inferred:
        print(f"  {name}: {said}")
    # Which readings no extractor produced in this run.
    if rep.from_cache:
        n = rep.from_cache
        print(
            f"\n{n:,} extraction{'' if n == 1 else 's'} taken from the cache, filed under the "
            f"source's sha256 and the extractor's version; --no-cache reads every source again"
        )
    # Where the bytes came from. The same claims directory resolves on the machine that holds
    # the library and is `unchecked` on one that does not, and the counts alone do not say which
    # of those this run was.
    if rep.from_library:
        n = len(rep.from_library)
        print(
            f"\n{n:,} source{'' if n == 1 else 's'} absent at the path the record names and read "
            f"from the library, matched to the pinned sha256"
        )
        print(f"  {rep.from_library[0][1].parent}")
    if a.triangulate:
        # What was triangulated, not what was asked for. A source that declares a command has
        # one extractor and a machine may have one reader, and reporting the request as the
        # result would claim an agreement nothing measured.
        consulted = V.available_extractors()
        print(
            f"\ntriangulated  {rep.triangulated:,} of {rep.checked:,} over {', '.join(consulted)}"
            if rep.triangulated
            else "\ntriangulation established nothing: every source was read by one extractor."
        )

    # The second axis. Quotations are measured; characterizations are not, and a report that
    # printed only the first would let "all found" read as an endorsement of statements
    # nothing examined.
    if rep.interpretations:
        print(
            f"\nreadings  {rep.interpretations:,} — unchecked; this package does not measure them"
        )
        if rep.foreign_readings:
            print(f"  {rep.foreign_readings:>7,}  attributed to a party other than the source")
        if rep.contested_readings:
            print(f"  {rep.contested_readings:>7,}  contested")

    # Never mixed in silently. A restored passage is the source's text, so its resolving says
    # nothing about the quotation it was restored from, which is still `not found` in its file.
    if rep.restored:
        print(
            f"\nrestored  {rep.restored:,} of the {rep.checked:,} — the source's own passage, "
            f"written by `citations restore`; not what the quoting party wrote"
        )

    # A person's reading of the page: provenance, printed only when asked for.
    if getattr(a, "show_manual", False) and rep.manual_checks is not None:
        print("\n".join(_manual_lines(rep.manual_checks)))

    # A record that is not committed exists on one machine, and a verdict resting on it cannot
    # be appealed to later. Counted and reported, never blocking: a library mid-edit is the
    # ordinary state of working in one.
    try:
        pending = projects.uncommitted(paths.home())
    except CitationsError:
        pending = 0
    if pending:
        print(
            f"\n{pending} record(s) in the library are not committed. A pin is evidence once it "
            f"is in history."
        )

    warned = _warned(rep)
    if warned:
        print("\nwarnings")
        for w, which in sorted(warned.items(), key=lambda kv: (-len(kv[1]), kv[0])):
            print(f"  {len(which):>7,}  {w} — {(WARNINGS | CORRECTION_WARNINGS).get(w, '')}")
            # Which quotations, under `--verbose`. A count says how many to open and not
            # which; finding them meant calling `check_one` from a script.
            if getattr(a, "verbose", False):
                for one in which:
                    print(f"             {one['claim'][:38]:<40}{one['quote'][:60]}")
        if not getattr(a, "verbose", False):
            print("  `--verbose` lists the quotations carrying each warning.")

    # About the sources and not about any quotation, so it sits apart from the counts above
    # and changes neither verdict: a tracked source resolves exactly as an untracked one does.
    if rep.tracked_sources:
        n = len(rep.tracked_sources)
        print(
            f"\ngit tracks {n:,} source{'' if n == 1 else 's'} read here, so publishing the "
            f"repository republishes {'its' if n == 1 else 'their'} text"
        )
        for name, artifact in rep.tracked_sources[:10]:
            print(f"  tracked  {name[:38]:<40}{artifact}")
        if n > 10:
            print(f"  ... and {n - 10:,} more; `citations lint --claims <dir>` lists every one")
        print(f"  {tracked.REMEDY}.")
        print("  a warning only: it fails nothing, with or without `--strict`.")
    # Worded so that no line opens `N sources`: `repro audit` reads lines of that form into
    # what the run found.
    if rep.committed_sources:
        n = len(rep.committed_sources)
        print(
            f"\nthe last commit still holds {n:,} source{'' if n == 1 else 's'} read here that "
            f"git no longer tracks: commit the removal"
        )
        for name, artifact in rep.committed_sources[:10]:
            print(f"  in HEAD  {name[:38]:<40}{artifact}")
        if n > 10:
            print(f"  ... and {n - 10:,} more; `citations lint --claims <dir>` lists every one")
        print("  a warning only: it fails nothing, with or without `--strict`.")

    # A broken pin is reported before the quotation failures. Every result computed against
    # that source describes a document the record does not describe, so it changes how the
    # numbers above should be read.
    if rep.broken_pins:
        print(
            f"\n{len(rep.broken_pins)} source{'s' if len(rep.broken_pins) > 1 else ''} "
            f"changed since being pinned"
        )
        for name, pin in rep.broken_pins[:10]:
            print(f"  {name[:38]:<40}pinned {pin.expected[:12]}  on disk {pin.actual[:12]}")
        if len(rep.broken_pins) > 10:
            print(f"  ... and {len(rep.broken_pins) - 10} more")

    # The same, one step along: the bytes are the pinned ones and the extractor makes other
    # text of them than it did when the quotations were taken.
    if rep.changed_readings:
        n = len(rep.changed_readings)
        print(
            f"\n{n} source{' no longer extracts' if n == 1 else 's no longer extract'} "
            f"to the text that was pinned"
        )
        for name, derived in rep.changed_readings[:10]:
            print(
                f"  {name[:38]:<40}pinned {derived.expected[:12]}  extracted {derived.actual[:12]}"
            )
        if len(rep.changed_readings) > 10:
            print(f"  ... and {len(rep.changed_readings) - 10} more")

    # A correction applies where its `reads` names one place in this machine's reading. One
    # that does not is said here with why and not applied, and one applied under another
    # reader than it was recorded under says both, so neither passes as the recorded reading.
    if rep.unapplied_corrections:
        n = len(rep.unapplied_corrections)
        print(f"\n{n} correction{'' if n == 1 else 's'} not applied")
        for name, why in rep.unapplied_corrections[:10]:
            print(f"  {name[:38]:<40}{why}")
        if n > 10:
            print(f"  ... and {n - 10} more")
    if noted := [(c.claim, c.note) for c in rep.corrected if c.note]:
        n = len(noted)
        print(
            f"\n{n} correction{'' if n == 1 else 's'} applied under another reading than "
            f"{'it was' if n == 1 else 'they were'} recorded under"
        )
        for name, note in noted[:10]:
            print(f"  {name[:38]:<40}{note}")
        if n > 10:
            print(f"  ... and {n - 10} more")
    if rep.unneeded_corrections:
        n = len(rep.unneeded_corrections)
        print(
            f"\n{n} correction{'' if n == 1 else 's'} may no longer be needed: the extractor's "
            f"text holds the quotation as written"
        )
        for name in rep.unneeded_corrections[:10]:
            print(f"  {name}")
        if n > 10:
            print(f"  ... and {n - 10} more")

    # Before the quotations' failures: every count above leaves these files out.
    if rep.skipped:
        print()
        print("\n".join(_refused(rep)))

    bad = [(s, q, r) for s, q, r in rep.problems if r.state == "not found"]
    if bad and not a.quiet:
        print()
        for slug, text, r in bad[:20]:
            print(f"  not found  {slug[:30]:<32}{text[:44]}")
            # The detail carries where the passage stopped matching and what the source reads
            # there, which is the only part that says what to do. Printing the row without it
            # leaves a reader with an accusation and no way to act on it.
            if r.detail:
                for line in r.detail.splitlines():
                    print(f"             {line.strip()}" if line.strip() else "")
        if len(bad) > 20:
            print(f"             ... and {len(bad) - 20} more")

    print()
    if bad:
        print(f"{len(bad)} not found. read the source before concluding anything.")
    elif rep.broken_pins:
        print("every quote resolved, but against a source that is not the one pinned.")
    elif rep.changed_readings:
        print(
            "every quote resolved, but in text that is not the text recorded when they were "
            "pinned: the extractor's output changed. Read the difference, then pin again."
        )
    elif rep.skipped:
        n = len(rep.skipped)
        print(
            f"{n} claims file{'' if n == 1 else 's'} refused when read, so the quotations in "
            f"{'it' if n == 1 else 'them'} went unchecked. The run fails until "
            f"{'it is' if n == 1 else 'they are'} fixed, with or without `--strict`."
        )
    elif rep.checked and rep.unresolved >= rep.checked:
        # Distinct from the partial case below, and the reason this branch exists: "nothing
        # failed" over a run that read no source at all was read as a pass, and the quotations
        # were reported as verified. Nothing was measured, so nothing is owed that word.
        print(
            f"nothing was measured. all {rep.checked} quotation(s) went unresolved, so this run "
            f"says nothing about the manuscript either way. The reasons are above; a run that "
            f"read no source is not a run that found no fault."
        )
    elif counts.get("indeterminate"):
        print(
            f"nothing failed. {counts['indeterminate']} indeterminate — the extractors here "
            "disagree about those passages, which is not the same as their being absent."
        )
    elif counts.get("unchecked"):
        print(
            f"nothing failed. {counts['unchecked']} unchecked — no measurement was made for those."
        )
    elif counts.get("ambiguous"):
        print(
            f"nothing failed. {counts['ambiguous']} ambiguous — those passages occur more than "
            "once in their sources, so the record does not say which occurrence it pinned."
        )
    elif counts.get("corrected"):
        print(
            f"nothing failed. {counts['corrected']} corrected — found in a passage recorded by "
            "hand, not in the extractor's text."
        )
    else:
        print("all found.")
    # Named where it is needed. `--strict` is what turns an unresolved quotation into a build
    # failure, and a reader who has some has no other way to learn the flag exists.
    if rep.ok and rep.unresolved and not a.strict:
        print(f"  {rep.unresolved} unresolved here is not a failure; `--strict` refuses them.")
    if a.strict and (rep.unresolved or rep.unpinned):
        if rep.unresolved:
            print(f"\n{rep.unresolved} quotation(s) could not be checked at all.")
            # Which ones, and why. The count on its own says a build should fail and not
            # what to open; the reason is already on the Result and was being discarded.
            unresolved = [
                (s, q, r)
                for s, q, r in rep.problems
                if r.state in ("unchecked", "indeterminate", "ambiguous")
            ]
            for slug, text, r in unresolved[:20]:
                print(f"  {r.state:<14}{slug[:30]:<32}{text[:44]}")
                if r.detail:
                    for line in r.detail.splitlines():
                        print(f"                {line.strip()}" if line.strip() else "")
            if len(unresolved) > 20:
                print(f"                ... and {len(unresolved) - 20} more")
        if rep.unpinned:
            print(f"{len(rep.unpinned)} source(s) carry no digest: {', '.join(rep.unpinned[:3])}")
        print("--strict fails on these: nothing was established about them either way.")
    return 0 if (rep.strict_ok if a.strict else rep.ok) else 1


def main(argv: list[str] | None = None) -> int:
    code = _main(argv)
    # After the work, never before it, and never instead of it: the note is about how this
    # project could be run, and a command that has not yet said what it found should not be
    # interrupted to say that.
    hint.note("citations")
    return code


def _main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="citations", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd")

    v = sub.add_parser("verify", help="do my quotations resolve in their pinned sources?")
    v.add_argument("--claims", help="a paper's claims/ directory, where quotations live")
    v.add_argument("--only", help="restrict to records cited by this paper")
    v.add_argument("--strict", action="store_true", help="exit 1 on any failure, for CI")
    v.add_argument(
        "--allow-extractor",
        action="append",
        metavar="NAME",
        help="let a claims file's extract_cmd run this program, named exactly as it writes it "
        f"(allowed unasked: {', '.join(sorted(V.DEFAULT_EXTRACTORS))})",
    )
    v.add_argument(
        "--no-cache",
        action="store_true",
        help="run the extractor over every source, and keep nothing for the next run",
    )
    v.add_argument(
        "--triangulate",
        action="store_true",
        help="ask every installed reader; report disagreement as indeterminate",
    )
    h = sub.add_parser(
        "manual-check",
        help="record that I compared one quotation with the page; run it only after doing so",
    )
    h.add_argument("claims_file", help="the claims file the quotation is in")
    h.add_argument("id", help="the claim id, or <claim id>/<n> for its n-th quotation")
    h.add_argument("--page", type=int, help="the page compared, written as p.N")
    h.add_argument("--note", help="a note, written after a `#`")
    h.add_argument(
        "--again",
        action="store_true",
        help="replace an earlier check whose fingerprint the quotation no longer has",
    )
    h.add_argument(
        "--allow-extractor",
        action="append",
        metavar="NAME",
        help="let the claims file's extract_cmd run this program",
    )
    h.set_defaults(fn=cmd_manual_check)

    c = sub.add_parser("coverage", help="is every quotation in my manuscript pinned at all?")
    c.add_argument("manuscript", help="the .tex the paper is written in")
    c.add_argument("--claims", default="claims", help="where the claim files live")
    c.add_argument(
        "--attribute",
        action="store_true",
        help="also check each quotation against the artifact of a source cited near it",
    )
    c.add_argument(
        "--allow-extractor",
        action="append",
        metavar="PROGRAM",
        help="let a claims file's extract_cmd run this program, for --attribute",
    )
    c.add_argument(
        "--strict", action="store_true", help="also fail on a quotation that could not be decided"
    )
    c.set_defaults(fn=cmd_coverage)

    v.add_argument(
        "--json",
        metavar="PATH",
        help="also write the counts to this file as JSON: quotations by outcome, sources, and "
        "the quotations carrying each warning",
    )
    v.add_argument(
        "--verbose", action="store_true", help="also list the quotations carrying each warning"
    )
    v.add_argument("--quiet", action="store_true")
    v.add_argument(
        "--show-manual",
        action="store_true",
        help="also print the manual checks beside each claims file, which change no outcome",
    )
    v.set_defaults(fn=cmd_verify)

    for name, helptext in [
        ("init", "make a library here"),
        ("audit", "does the stored metadata match the registry record?"),
        ("resolve", "backfill missing identifiers"),
        ("build", "rebuild records from the papers' bibliographies"),
        ("lint", "BibTeX correctness, repeated keys, and author lists in a .bib"),
        ("add", "add one entry to a .bib, refusing a key it already has"),
        ("pin", "write a quotation into a claims file, refusing one that does not resolve"),
        ("restore", "write the source's passage for a quotation that leaves text out, apart"),
        ("projects", "which projects this library refers to, and which names are dead"),
        ("tags", "the tag vocabulary, what uses it, and any tag nothing declares"),
        ("link", "point pdfs/ at the papers' artifacts"),
        ("fetch", "download the sources a claims directory pins, keeping only matching bytes"),
        ("import-paperclip", "turn a Paperclip paper repo into pinned claim files"),
    ]:
        p = sub.add_parser(name, help=helptext, add_help=False)
        p.set_defaults(fn=None, delegate=DELEGATED[name])

    args, rest = ap.parse_known_args(argv)
    if args.cmd == "manual-check" and rest:
        # A flag mistyped here would otherwise be dropped, and the line written without it.
        h.error(f"unrecognized arguments: {' '.join(rest)}")
    if not args.cmd:
        ap.print_help()
        return 0
    try:
        if getattr(args, "fn", None):
            return args.fn(args)
        return _delegate(args.delegate, rest)
    except CitationsError as e:
        print(str(e))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
