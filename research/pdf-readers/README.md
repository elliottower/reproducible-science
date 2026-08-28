# Does poppler earn its system dependency?

`citations verify` reads a PDF by shelling out to `pdftotext -layout`. That binary is the one
thing `pip install citations` cannot supply, and it is the largest obstacle to installing the
package. Whether it is worth that cost is an empirical question, and this directory answers it
by measurement rather than by preference.

The unit is a **passage check**, not a document. Two readers never produce byte-identical text
— whitespace, reading order and hyphenation differ by construction — and reporting that as
disagreement measures nothing anyone acts on. What is measured is whether the outcome of
`citations verify` changes: for each quotation, is the passage `found` under poppler, under
pdfplumber, and under pypdf, after the normalization `citations.verify` already applies.

The numbers are in `results.json`, which also carries the decision criterion, stated before the
run and copied into the output so the threshold cannot be chosen after the result is known.

## The readers

| reader | engine | license |
|---|---|---|
| poppler | `pdftotext -layout`, a subprocess | GPL binary, shelled out, never linked |
| pdfplumber | pdfminer.six characters plus its own layout layer | MIT |
| pypdf | its own content-stream parser | BSD |

`pdfminer.six` is not a fourth reader: pdfplumber is built on it and shares its character
extraction, so the two cannot disagree about which characters are on a page, and counting both
would inflate agreement. PyMuPDF is excluded on licensing — it is AGPL, and linking it would
relicense an MIT package.

## The corpora

**Quotations.** Real quotations from `claims/*.yaml` files, against the PDFs they are pinned
to, restricted to sources whose digest still matches. Nobody wrote these passages by reading a
reader's output, so no reader is favoured. This is the corpus the decision rests on.

**Sampled.** ReScience and MLRC development articles, which carry no quotations. Passages are
drawn from each reader's own output in turn, in equal numbers, and checked against all three. A
passage drawn from reader A favours reader A, which is why every reader supplies an equal
share. Reported apart from the quotations and never pooled with them.

Only the 155 development articles are used. The sampling frame in
`reproducible-science-evaluations` reserves 60 for a registered sample, and `fetch_rescience.py`
excludes them, so a reader comparison cannot consume a sample another registration depends on.

## Running it

```bash
uv run python research/pdf-readers/fetch_rescience.py \
    --frame ../reproducible-science-evaluations/research/addressability/frame.json \
    --into  /tmp/rescience

uv run python research/pdf-readers/compare_readers.py \
    --claims-root ~/Documents/GitHub \
    --pdf-dir /tmp/rescience \
    --out research/pdf-readers/results.json
```

```bash
uv run python research/pdf-readers/characterize.py \
    --shard /tmp/quotations.jsonl --shard /tmp/sampled.jsonl --out /tmp/causes.json

uv run python research/pdf-readers/report.py \
    --quotations-shard /tmp/quotations.jsonl --sampled-shard /tmp/sampled.jsonl \
    --causes /tmp/causes.json --out research/pdf-readers/results.json
```

`compare_readers.py` appends one line per document to a `.jsonl` shard before starting the
next, so an interrupted run resumes rather than restarts. `characterize.py` re-reads each
document a divergence was found in and records what the reader that missed the passage did
with it instead. `report.py` assembles `results.json` from both and measures nothing itself,
so no number in the report lacks a document behind it.

`results.json` carries statistics, one row per document, and twelve worked examples. It does
not carry the 1,593 quotations the corpus checked: those belong to publishers who did not
license their redistribution, which is the same reason `paper/prior_art/reference/` is not in
this repository. The shards, which do carry them, stay outside the repository.

The corpora themselves are not here either. The ReScience articles are rebuildable from the
frame, and the claims corpora live in the repositories that wrote them, which is why both are
arguments rather than paths.
