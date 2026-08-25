"""Does poppler earn its system dependency?

`citations verify` reads a PDF by shelling out to `pdftotext -layout`. That binary is the one
thing `pip install citations` cannot supply, and it is the largest single obstacle to
installing the package. Whether it is worth that cost is an empirical question: if a
pure-Python reader reaches the same verdict on the same passages, the dependency should go.

The unit is a **passage check**, not a document. Extracted text is never byte-identical across
readers -- whitespace, reading order and hyphenation differ by construction -- and reporting
that as disagreement measures nothing anyone acts on. What is measured here is whether the
outcome of `citations verify` changes: for each quotation in the corpus, is the passage
`found` under poppler, under pdfplumber, and under pypdf, after the normalization
`citations.verify` already applies.

Three readers, three independent pipelines:

    poppler      pdftotext -layout, a subprocess; GPL, shelled out, never linked
    pdfplumber   pdfminer.six character extraction plus its own layout layer; MIT
    pypdf        its own content-stream parser; BSD

`pdfminer.six` is deliberately not a fourth reader. pdfplumber is built on it and shares its
character extraction, so the two cannot disagree about which characters are on a page, and
counting both would inflate apparent agreement. PyMuPDF is excluded on licensing: it is AGPL
and would relicense an MIT package.

Two corpora, reported apart:

    quotations   real quotations from claims files, against the PDFs they are pinned to.
                 The passages were written by a human reading the rendered page, so no
                 reader authored them and none is favoured.

    sampled      documents with no quotations attached -- the ReScience/MLRC development
                 articles. Passages are drawn from each reader's own output in turn, in
                 equal numbers, and checked against all three. A passage drawn from reader
                 A favours reader A, which is why every reader supplies an equal share; the
                 statistic that survives is how often B and C find what A produced. This is
                 a proxy for a quotation and is never pooled with the real ones.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import pathlib
import random
import re
import subprocess
import time
from typing import Any

from citations import verify as V
from citations.exceptions import ClaimFileError
from citations.models import load_claim_file

#: Stated before the measurement was run and copied into the output, so the threshold cannot
#: be chosen after the result is known.
DECISION_CRITERION = {
    "question": "Does poppler earn its system dependency?",
    "unit": "one passage check: is this quotation found in this document under this reader",
    "outcome_compared": "found / not found, after citations.verify normalization",
    "drop_poppler_if": (
        "the pure-Python readers reproduce poppler's outcome on every passage check "
        "(divergences == 0)"
    ),
    "small_divergence_if": (
        "fewer than 1 per cent of passage checks diverge; each is then reported "
        "individually with its document, its passage and its cause"
    ),
    "substantial_divergence_if": (
        "1 per cent or more of passage checks diverge, in which case poppler stays and "
        "triangulation is worth building"
    ),
    "directions_reported_separately": [
        "poppler_only: poppler found the passage and the pure-Python reader did not",
        "python_only: the pure-Python reader found the passage and poppler did not",
    ],
    "pooling_forbidden": (
        "the two directions are never pooled into one disagreement rate; a pure-Python "
        "reader that is sometimes better matters as much as the reverse"
    ),
}

#: Sampled passages are this many characters, starting at a word boundary. Above
#: `citations.verify.MIN_QUOTE_CHARS`, so no sampled passage carries the `short` warning that
#: a real quotation of the same length would.
SAMPLE_CHARS = 110

#: Sampled passages drawn per reader per document. Three readers, so a document contributes
#: at most three times this many checks.
SAMPLES_PER_READER = 6

#: A line must carry this many alphabetic tokens before a passage is drawn from it. A table
#: row and a page footer are text a reader may legitimately place anywhere, and sampling them
#: measures reading order rather than whether a quotation resolves.
MIN_PROSE_TOKENS = 10

#: A run of spaces this long is a column gutter or a table's alignment, not a word break.
#: `pdftotext -layout` reconstructs the page geometry, so a line of its output can splice the
#: left column of one paragraph onto the right column of another; a passage drawn across that
#: splice exists in no other reader's output and in no reader of the rendered page either. A
#: first pass without this filter reported 20 divergences in 79 sampled passages, and reading
#: them showed most were splices of exactly this kind: figure captions from two panels welded
#: into one line, and table headers from adjacent columns. They measure how poppler lays out a
#: page, not whether a quotation resolves.
GUTTER = re.compile(r"   +")

WORD = re.compile(r"[A-Za-z]{3,}")
NUMBER = re.compile(r"\d")
LIGATURES = "ﬀﬁﬂﬃﬄﬅﬆ"


# --- readers -----------------------------------------------------------------------------


@dataclasses.dataclass
class Reading:
    """One reader's attempt at one document."""

    reader: str
    text: str | None
    error: str | None
    seconds: float

    @property
    def opened(self) -> bool:
        return self.text is not None


def read_poppler(pdf: pathlib.Path) -> Reading:
    started = time.monotonic()
    try:
        proc = subprocess.run(
            ["pdftotext", "-layout", str(pdf), "-"], capture_output=True, text=True, timeout=300
        )
    except FileNotFoundError:
        return Reading("poppler", None, "pdftotext is not on PATH", time.monotonic() - started)
    except subprocess.TimeoutExpired:
        return Reading("poppler", None, "timed out after 300s", time.monotonic() - started)
    except OSError as e:
        return Reading("poppler", None, f"could not be run: {e}", time.monotonic() - started)
    if proc.returncode != 0:
        detail = (proc.stderr or "").strip().splitlines()
        return Reading(
            "poppler",
            None,
            f"exited {proc.returncode}" + (f": {detail[-1]}" if detail else ""),
            time.monotonic() - started,
        )
    return Reading("poppler", proc.stdout, None, time.monotonic() - started)


def read_pdfplumber(pdf: pathlib.Path) -> Reading:
    import pdfplumber

    started = time.monotonic()
    try:
        with pdfplumber.open(pdf) as doc:
            pages = [page.extract_text() or "" for page in doc.pages]
    except Exception as e:
        return Reading(
            "pdfplumber", None, f"{type(e).__name__}: {e}"[:200], time.monotonic() - started
        )
    return Reading("pdfplumber", "\n".join(pages), None, time.monotonic() - started)


def read_pypdf(pdf: pathlib.Path) -> Reading:
    import pypdf

    started = time.monotonic()
    try:
        reader = pypdf.PdfReader(str(pdf))
        pages = [page.extract_text() or "" for page in reader.pages]
    except Exception as e:
        return Reading("pypdf", None, f"{type(e).__name__}: {e}"[:200], time.monotonic() - started)
    return Reading("pypdf", "\n".join(pages), None, time.monotonic() - started)


READERS = {"poppler": read_poppler, "pdfplumber": read_pdfplumber, "pypdf": read_pypdf}
PYTHON_READERS = ("pdfplumber", "pypdf")


def reader_versions() -> dict[str, str]:
    import pdfminer
    import pdfplumber
    import pypdf

    try:
        banner = subprocess.run(
            ["pdftotext", "-v"], capture_output=True, text=True, timeout=30
        ).stderr
        poppler = banner.strip().splitlines()[0] if banner.strip() else "unknown"
    except (OSError, subprocess.SubprocessError):
        poppler = "absent"
    return {
        "poppler": poppler,
        "pdfplumber": pdfplumber.__version__,
        "pypdf": pypdf.__version__,
        "pdfminer.six": getattr(pdfminer, "__version__", "unknown"),
    }


# --- the check ---------------------------------------------------------------------------


def check(quote: str, text: str | None) -> str:
    """`citations.verify`'s own matching, against one reader's text.

    Four outcomes rather than three: `verify` collapses a verbatim match and a
    whitespace-insensitive one into `found`, and the two are separated here so the share of
    agreement that rests on normalization can be reported apart from the share that does not.
    """
    if text is None:
        return "unchecked"
    folded = V.fold(quote)
    if not folded:
        return "empty"
    if folded in V.fold(text):
        return "found_verbatim"
    if V.skeleton(quote) and V.skeleton(quote) in V.skeleton(text):
        return "found_normalized"
    return "not_found"


def found(outcome: str) -> bool:
    return outcome.startswith("found")


# --- why two readers disagreed -------------------------------------------------------------


def diagnose(quote: str, agreeing: str, dissenting: str | None) -> dict[str, Any]:
    """What the reader that missed the passage did with it instead.

    The halves test is the useful one. A passage whose first and second halves both occur in
    the dissenting reader's text, but not adjacently, was reordered -- a column break read in
    the wrong order, a footnote spliced mid-sentence. A passage neither half of which occurs
    was dropped, which is a font or an encoding the reader could not decode. The two have
    different fixes and a single "not found" hides which one happened.
    """
    if dissenting is None:
        return {"class": "unreadable"}
    q = V.skeleton(quote)
    doc = V.skeleton(dissenting)
    half = len(q) // 2
    first, second = q[:half], q[half:]
    here, there = first in doc, second in doc
    if here and there:
        finding = "reordered"
    elif here or there:
        finding = "partial"
    else:
        finding = "absent"

    folded_quote = V.fold(quote)
    hyphen_broken = _hyphen_broken_word(folded_quote, dissenting)
    return {
        "class": finding,
        "ligature_in_agreeing": any(c in agreeing for c in LIGATURES),
        "ligature_in_dissenting": any(c in dissenting for c in LIGATURES),
        "hyphen_broken_word": hyphen_broken,
        "numeric_dense_line": _numeric_dense(folded_quote, agreeing),
        "spans_a_line_in_agreeing": _spans_a_line(folded_quote, agreeing),
        "dissenting_is_empty": not dissenting.strip(),
    }


def _hyphen_broken_word(folded_quote: str, text: str) -> str | None:
    """A word of the quote that the other reader left split by a hyphen.

    `fold` removes a hyphen followed by a newline, so a word the extractor broke across a line
    survives. A hyphen followed by a space does not fold away, and is what a reader that keeps
    the line break but loses the newline leaves behind.
    """
    folded_text = V.fold(text)
    for word in WORD.findall(folded_quote):
        if len(word) < 6:
            continue
        for cut in range(2, len(word) - 1):
            if f"{word[:cut]}- {word[cut:]}" in folded_text:
                return word
    return None


def _numeric_dense(folded_quote: str, text: str) -> bool:
    """Is the passage in a line carrying four or more numbers -- a table row rather than prose?"""
    for line in text.splitlines():
        if folded_quote in V.fold(line):
            return len(re.findall(r"\d+(?:\.\d+)?", line)) >= 4
    return False


def _spans_a_line(folded_quote: str, text: str) -> bool:
    """Does the passage cross a line break in the reader that found it?"""
    return not any(folded_quote in V.fold(line) for line in text.splitlines())


# --- corpora ----------------------------------------------------------------------------


def quotation_corpus(roots: list[pathlib.Path]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Every quotation in the claims files under `roots` whose PDF is present and pins clean.

    A source whose digest does not match is skipped rather than measured: the quotations were
    taken against the bytes the record names, and a reader comparison run on different bytes
    would report a change of document as a disagreement between readers.
    """
    documents: dict[str, dict[str, Any]] = {}
    skipped = {"unpinned": 0, "broken": 0, "missing": 0, "unparseable": 0, "not_pdf": 0}
    for root in roots:
        for claims_dir in sorted(root.glob("*/claims")) + sorted(root.glob("*/*/claims")):
            if "/.git/" in str(claims_dir):
                continue
            for path in sorted(claims_dir.glob("*.yaml")):
                try:
                    claim_file = load_claim_file(path)
                except ClaimFileError:
                    skipped["unparseable"] += 1
                    continue
                artifact = claim_file.artifact()
                if artifact is None or artifact.suffix.lower() != ".pdf":
                    skipped["not_pdf"] += 1
                    continue
                pin = V.check_pin(artifact, claim_file.source.sha256)
                if pin.state != "ok":
                    skipped[pin.state if pin.state in skipped else "missing"] += 1
                    continue
                quotes = [
                    {"claim": name, "text": quote.text, "page": quote.page, "file": str(path)}
                    for name, claim in claim_file.claims.items()
                    for quote in claim.quotes
                    if quote.text and quote.text.strip()
                ]
                if not quotes:
                    continue
                key = str(artifact)
                entry = documents.setdefault(
                    key, {"pdf": key, "sha256": pin.actual, "quotes": [], "sources": []}
                )
                entry["quotes"].extend(quotes)
                entry["sources"].append(str(path))
    return list(documents.values()), skipped


def sampled_passages(readings: dict[str, Reading], rng: random.Random) -> list[dict[str, Any]]:
    """Passages drawn from each reader's own output in equal numbers.

    Drawn from prose lines only. A reader is free to place a table row or a running footer
    anywhere in its output, so a passage drawn from one measures reading order rather than
    whether a quotation of the document resolves.
    """
    drawn = []
    for reader, reading in readings.items():
        if not reading.opened:
            continue
        candidates = [
            line.strip()
            for line in (reading.text or "").splitlines()
            if len(line.strip()) >= SAMPLE_CHARS + 10
            and len(WORD.findall(line)) >= MIN_PROSE_TOKENS
            and len(NUMBER.findall(line)) <= 3
            and not GUTTER.search(line.strip())
        ]
        if not candidates:
            continue
        for line in rng.sample(candidates, min(SAMPLES_PER_READER, len(candidates))):
            start = rng.randrange(0, max(1, len(line) - SAMPLE_CHARS))
            start = line.rfind(" ", 0, start + 1) + 1 if start else 0
            passage = line[start : start + SAMPLE_CHARS].rsplit(" ", 1)[0].strip()
            if len(passage) >= V.MIN_QUOTE_CHARS:
                drawn.append({"drawn_from": reader, "text": passage})
    return drawn


# --- the run ------------------------------------------------------------------------------


def measure_document(
    pdf: pathlib.Path, quotes: list[dict[str, Any]], corpus: str, rng: random.Random
) -> dict[str, Any]:
    readings = {name: read(pdf) for name, read in READERS.items()}
    V.fold.cache_clear()
    V.skeleton.cache_clear()

    passages = quotes if corpus == "quotations" else sampled_passages(readings, rng)
    checks = []
    for passage in passages:
        outcomes = {name: check(passage["text"], r.text) for name, r in readings.items()}
        record = {**passage, "outcomes": outcomes}
        if diverges(outcomes):
            record["diagnosis"] = _diagnose_divergence(passage["text"], outcomes, readings)
            record["excerpts"] = {
                name: _excerpt(passage["text"], r.text) for name, r in readings.items()
            }
        checks.append(record)

    return {
        "corpus": corpus,
        "pdf": str(pdf),
        "name": pdf.name,
        "bytes": pdf.stat().st_size,
        "readings": {
            name: {
                "opened": r.opened,
                "error": r.error,
                "chars": len(r.text or ""),
                "seconds": round(r.seconds, 2),
            }
            for name, r in readings.items()
        },
        "checks": checks,
    }


def diverges(outcomes: dict[str, str]) -> bool:
    """Do the readers that opened the document disagree about whether the passage is there?"""
    verdicts = {found(o) for o in outcomes.values() if o not in ("unchecked", "empty")}
    return len(verdicts) > 1


def _diagnose_divergence(
    quote: str, outcomes: dict[str, str], readings: dict[str, Reading]
) -> dict[str, Any]:
    agreeing = next(
        (readings[n].text for n, o in outcomes.items() if found(o) and readings[n].text), None
    )
    dissenting = next(
        (
            readings[n].text
            for n, o in outcomes.items()
            if o == "not_found" and readings[n].text is not None
        ),
        None,
    )
    if agreeing is None:
        return {"class": "no reader found it"}
    return diagnose(quote, agreeing, dissenting)


def _excerpt(quote: str, text: str | None, width: int = 130) -> str:
    """Where the passage sits in this reader's text, or the closest thing to it."""
    if text is None:
        return ""
    folded = V.fold(text)
    at = folded.find(V.fold(quote))
    if at < 0:
        head = V.fold(quote)[: max(12, len(V.fold(quote)) // 3)]
        at = folded.find(head)
    if at < 0:
        return ""
    return folded[max(0, at - 20) : at + width]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--claims-root",
        type=pathlib.Path,
        action="append",
        default=[],
        help="a directory holding repositories with claims/*.yaml",
    )
    parser.add_argument(
        "--pdf-dir",
        type=pathlib.Path,
        action="append",
        default=[],
        help="a directory of PDFs with no quotations, measured by sampled passages",
    )
    parser.add_argument("--out", type=pathlib.Path, required=True)
    parser.add_argument("--seed", type=int, default=20260825)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    shard = args.out.with_suffix(".jsonl")
    done = set()
    if shard.exists():
        for line in shard.read_text().splitlines():
            if line.strip():
                done.add(json.loads(line)["pdf"])

    documents, skipped = quotation_corpus(args.claims_root)
    for directory in args.pdf_dir:
        for pdf in sorted(directory.glob("*.pdf")):
            documents.append({"pdf": str(pdf), "quotes": [], "sources": [], "sha256": ""})
    if args.limit:
        documents = documents[: args.limit]

    rng = random.Random(args.seed)
    for i, entry in enumerate(documents, 1):
        if entry["pdf"] in done:
            continue
        corpus = "quotations" if entry["quotes"] else "sampled"
        result = measure_document(
            pathlib.Path(entry["pdf"]), entry["quotes"], corpus, random.Random(rng.randrange(2**32))
        )
        result["sha256"] = entry["sha256"]
        result["claim_files"] = entry["sources"]
        with shard.open("a") as fh:
            fh.write(json.dumps(result) + "\n")
        print(
            f"[{i}/{len(documents)}] {result['name']} {corpus} "
            f"checks={len(result['checks'])} "
            + " ".join(
                f"{n}={'ok' if r['opened'] else 'FAIL'}" for n, r in result["readings"].items()
            ),
            flush=True,
        )

    records = [json.loads(line) for line in shard.read_text().splitlines() if line.strip()]
    report = {
        "decision_criterion": DECISION_CRITERION,
        "inputs": {
            "claims_roots": [str(p) for p in args.claims_root],
            "pdf_dirs": [str(p) for p in args.pdf_dir],
            "seed": args.seed,
            "sample_chars": SAMPLE_CHARS,
            "samples_per_reader": SAMPLES_PER_READER,
            "documents": len(records),
            "claim_files_skipped": skipped,
        },
        "reader_versions": reader_versions(),
        "results": summarize(records),
        "documents": records,
    }
    args.out.write_text(json.dumps(report, indent=1))
    print(json.dumps(report["results"], indent=1))


def distinct(checks: list[tuple[dict[str, Any], dict[str, Any]]]) -> list[tuple[dict, dict]]:
    """One entry per distinct passage-and-document, keyed by digest rather than by path.

    Two repositories in this corpus hold the same claims file against their own copy of the
    same PDF, and one sampled passage can be drawn from two readers that both produced it.
    Counting either twice inflates the denominator and, worse, reports one divergence as two.
    """
    seen: set[tuple[str, str]] = set()
    out = []
    for record, check in checks:
        key = (record.get("sha256") or record["pdf"], V.fold(check["text"]))
        if key in seen:
            continue
        seen.add(key)
        out.append((record, check))
    return out


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Everything the report claims, computed from the shards rather than from a running tally."""
    out: dict[str, Any] = {}
    for corpus in ("quotations", "sampled"):
        paths = [r for r in records if r["corpus"] == corpus]
        raw = [(r, c) for r in paths for c in r["checks"]]
        checks = distinct(raw)
        # One entry per distinct document. Two repositories keeping their own copy of one PDF
        # is one document that opened or did not, not two.
        docs = list({r.get("sha256") or r["pdf"]: r for r in paths}.values())
        opens = {name: sum(1 for r in docs if r["readings"][name]["opened"]) for name in READERS}
        failures = [
            {"pdf": r["name"], "reader": name, "error": r["readings"][name]["error"]}
            for r in docs
            for name in READERS
            if not r["readings"][name]["opened"]
        ]
        three_way = sum(1 for _, c in checks if not diverges(c["outcomes"]))
        pairwise: dict[str, dict[str, int]] = {}
        for a, b in (("poppler", "pdfplumber"), ("poppler", "pypdf"), ("pdfplumber", "pypdf")):
            agree = dissent_a = dissent_b = comparable = 0
            for _, c in checks:
                oa, ob = c["outcomes"][a], c["outcomes"][b]
                if oa in ("unchecked", "empty") or ob in ("unchecked", "empty"):
                    continue
                comparable += 1
                if found(oa) == found(ob):
                    agree += 1
                elif found(oa):
                    dissent_a += 1
                else:
                    dissent_b += 1
            pairwise[f"{a} vs {b}"] = {
                "comparable_checks": comparable,
                "agree": agree,
                "agreement_rate": round(agree / comparable, 5) if comparable else None,
                f"{a}_only_found": dissent_a,
                f"{b}_only_found": dissent_b,
            }
        lone = dict.fromkeys(READERS, 0)
        for _, c in checks:
            verdicts = {
                n: found(o) for n, o in c["outcomes"].items() if o not in ("unchecked", "empty")
            }
            if len(verdicts) == 3 and len(set(verdicts.values())) == 2:
                odd = [n for n, v in verdicts.items() if list(verdicts.values()).count(v) == 1]
                if odd:
                    lone[odd[0]] += 1
        by_reader = {
            name: {
                "found_verbatim": sum(
                    1 for _, c in checks if c["outcomes"][name] == "found_verbatim"
                ),
                "found_normalized": sum(
                    1 for _, c in checks if c["outcomes"][name] == "found_normalized"
                ),
                "not_found": sum(1 for _, c in checks if c["outcomes"][name] == "not_found"),
                "unchecked": sum(1 for _, c in checks if c["outcomes"][name] == "unchecked"),
            }
            for name in READERS
        }
        out[corpus] = {
            "document_paths": len(paths),
            "documents": len(docs),
            "passage_checks": len(checks),
            "duplicate_checks_dropped": len(raw) - len(checks),
            "documents_opened": opens,
            "open_failures": failures,
            "three_way_agreement": three_way,
            "three_way_agreement_rate": round(three_way / len(checks), 5) if checks else None,
            "divergent_checks": len(checks) - three_way,
            "divergence_rate": round((len(checks) - three_way) / len(checks), 5)
            if checks
            else None,
            "exactly_one_reader_dissents": lone,
            "pairwise": pairwise,
            "by_reader": by_reader,
            "divergences": [
                {
                    "pdf": r["name"],
                    "claim": c.get("claim"),
                    "claim_file": c.get("file"),
                    "drawn_from": c.get("drawn_from"),
                    "passage": c["text"],
                    "outcomes": c["outcomes"],
                    "diagnosis": c.get("diagnosis"),
                    "excerpts": c.get("excerpts"),
                }
                for r, c in checks
                if diverges(c["outcomes"])
            ],
        }
    return out


if __name__ == "__main__":
    main()
