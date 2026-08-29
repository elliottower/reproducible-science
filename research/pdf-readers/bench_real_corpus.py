"""Every reader against every source a real audit pins, scored on passages resolved.

The existing agreement run answered a different question than it looked like it answered. Its
corpus is 51 documents from four repositories in which `pdftotext -layout` already resolves 245
of 249 passages, so every alternative reader was measured against a primary that was not
failing. It contains no document from the audit set, and in particular not the two-column paper
where `-layout` loses 110 of 160 quotations -- the case that motivated asking about readers at
all. A ranking taken there says which reader is best where the question does not arise.

This runs the sixteen audited claims against their own pinned sources: one extraction per
(document, reader), then every quotation from that document resolved against it. What it
reports is passages resolved, because that is the quantity a quotation checker exists to
maximize. Characters produced is not a proxy for it -- a reader can emit more text and resolve
fewer passages, which is what `-layout` does on two columns.
"""

from __future__ import annotations

import collections
import json
import os
import pathlib
import subprocess
import time

import yaml
from citations import verify as V

ROOT = pathlib.Path(os.environ.get("CORPUS_ROOT", "corpus"))
PDFRS = pathlib.Path(
    "/private/tmp/claude-501/-Users-elliottower-Documents-GitHub-factorization-circuits"
    "/914b66f3-5004-41f9-a015-a12f8e4f8d15/scratchpad/pdfrs/target/release/pdfrs"
)
OUT = pathlib.Path(__file__).parent / "real_corpus_by_reader.json"
TIMEOUT = 300


def rust(mode: str):
    def read(pdf: pathlib.Path) -> str:
        p = subprocess.run(
            [str(PDFRS), mode, str(pdf)], capture_output=True, text=True, timeout=TIMEOUT
        )
        if p.returncode != 0:
            raise RuntimeError((p.stderr or "").strip()[:120] or f"exited {p.returncode}")
        return p.stdout

    return read


def pdfium(pdf: pathlib.Path) -> str:
    import pypdfium2

    doc = pypdfium2.PdfDocument(str(pdf))
    return "\n".join(page.get_textpage().get_text_range() for page in doc)


READERS = {
    "poppler-layout": lambda p: V.reading_with(p, extractor="pdftotext -layout").text,
    "poppler-flow": lambda p: V.reading_with(p, extractor="pdftotext").text,
    "pypdf": lambda p: V.reading_with(p, extractor="pypdf").text,
    "pdfium": pdfium,
    "lopdf": rust("lopdf"),
    "pdf-extract": rust("extract"),
}


def main() -> None:
    documents, quote_total = [], 0
    for claims_file in sorted((ROOT / "claims").glob("*.yaml")):
        d = yaml.safe_load(claims_file.read_text()) or {}
        src = d.get("source") or {}
        if not src.get("local"):
            continue
        pdf = ROOT / src["local"]
        if not pdf.exists() or pdf.suffix.lower() != ".pdf":
            continue
        quotes = [
            (cid, q["exact"])
            for cid, c in (d.get("claims") or {}).items()
            for q in (c.get("quotes") or [])
            if q.get("exact")
        ]
        quote_total += len(quotes)
        documents.append({"claim": claims_file.stem, "pdf": pdf, "quotes": quotes})

    print(
        f"{len(documents)} documents, {quote_total} quotations, {len(READERS)} readers\n",
        flush=True,
    )

    per_quote: dict[tuple[str, str, int], dict[str, str]] = {}
    per_reader = {
        name: {
            "seconds": 0.0,
            "opened": 0,
            "failed": [],
            "chars": 0,
            "outcomes": collections.Counter(),
        }
        for name in READERS
    }

    for doc in documents:
        print(f"  {doc['claim']:<20} {len(doc['quotes']):>4} quotes", end="", flush=True)
        for name, read in READERS.items():
            t = time.perf_counter()
            try:
                text = read(doc["pdf"])
            except Exception as e:
                per_reader[name]["failed"].append({"pdf": doc["pdf"].name, "error": str(e)[:150]})
                for i, (cid, _) in enumerate(doc["quotes"]):
                    per_quote.setdefault((doc["claim"], cid, i), {})[name] = "unreadable"
                continue
            per_reader[name]["seconds"] += time.perf_counter() - t
            per_reader[name]["opened"] += 1
            per_reader[name]["chars"] += len(text)
            for i, (cid, q) in enumerate(doc["quotes"]):
                state = V.resolve_in(q, text).state
                per_reader[name]["outcomes"][state] += 1
                per_quote.setdefault((doc["claim"], cid, i), {})[name] = state
            print(".", end="", flush=True)
        print(flush=True)

    names = list(READERS)
    resolved = {n: sum(1 for o in per_quote.values() if o.get(n) == "found") for n in names}
    rescues = {
        a: {
            b: sum(1 for o in per_quote.values() if o.get(a) == "found" and o.get(b) != "found")
            for b in names
        }
        for a in names
    }
    union = sum(1 for o in per_quote.values() if any(v == "found" for v in o.values()))

    OUT.write_text(
        json.dumps(
            {
                "question": "which reader resolves the most passages on the corpus that motivated asking",
                "corpus": {
                    "root": str(ROOT),
                    "documents": len(documents),
                    "quotations": quote_total,
                    "claims": [d["claim"] for d in documents],
                },
                "per_reader": {
                    n: {
                        "seconds": round(per_reader[n]["seconds"], 2),
                        "opened": per_reader[n]["opened"],
                        "failed": per_reader[n]["failed"],
                        "chars": per_reader[n]["chars"],
                        "resolved": resolved[n],
                        "outcomes": dict(per_reader[n]["outcomes"]),
                    }
                    for n in names
                },
                "rescues_row_over_column": rescues,
                "resolved_by_at_least_one_reader": union,
                "per_quote": {"|".join(map(str, k)): v for k, v in per_quote.items()},
            },
            indent=2,
        )
    )

    print(f"\n{'reader':<18}{'seconds':>9}{'opened':>8}{'resolved':>10}{'of':>7}")
    for n in sorted(names, key=lambda n: -resolved[n]):
        print(
            f"{n:<18}{per_reader[n]['seconds']:>9.1f}{per_reader[n]['opened']:>8}"
            f"{resolved[n]:>10}{quote_total:>7}"
        )
    print(f"\nresolved by at least one reader: {union} of {quote_total}")
    print(f"written: {OUT}")


if __name__ == "__main__":
    main()
