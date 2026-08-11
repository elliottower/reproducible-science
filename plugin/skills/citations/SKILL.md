---
name: citations
description: Verify that quotations resolve in the sources they cite, and manage a library of verified quotations. Use before quoting a paper, when adding a citation, when asked to check whether a quote is real, or when a bibliography needs DOIs backfilled. Requires the `citations` CLI (`uv tool install citations`).
---

# citations

A library of quotations checked against the sources they came from.

## The rule that matters

**Never quote a source from memory. Look it up.**

Every fabricated quotation comes from generating text that sounds like what a paper says instead
of reading what it says. If a quotation is in the library it has been checked against a pinned
artifact; if it is not, check it before using it.

## Commands

```bash
citations verify                    # do the quotations resolve in their sources?
citations verify --claims <dir>     # check a paper's claims/ directory
citations verify --strict           # exit 1 on failure, for CI
citations resolve                   # backfill missing DOIs and arXiv ids
citations init                      # create a library here
citations lint                      # BibTeX correctness
```

## Reading the output

Five states. The distinction between them is the whole point.

| state | meaning |
|---|---|
| `ok` | found verbatim in the pinned artifact |
| `loose` | matched on the alphanumeric skeleton only. Reported, never failed — a skeleton match cannot tell `a - b` from `a + b` |
| `too-short` | resolves, but short or truncated enough that the source may qualify it two words later |
| `no-source` | the artifact is not on disk. **Nothing was checked** |
| `missing` | the artifact was read and the text is not in it |

**`missing` means look at this. It never means fabricated.** A mirror-reversed scan, a
column-order extraction failure, or an image-only PDF all produce the same signal as an invented
quotation. Read the source before concluding anything about the author.

**`no-source` is not a pass.** If the tool reports it, nothing was verified. Do not describe a
claim as checked on the strength of a run that could not reach its artifact.

**A run that checked zero quotations exits non-zero.** If that happens, the library or the
`--claims` path is wrong — not that everything passed.

## Why `too-short` exists

A short quotation can resolve cleanly and still support a claim its source contradicts. A real
case: the substring `"We trained 50"` verifies against a source that continues `"...each for 2,
4, and 8 layered variants and 5 refits each for 12 layered (GPT2-small)"`. The record claimed
fifty; the true number for the architecture in question was five.

Quote enough text to carry its own qualifiers, and never end a pin mid-clause.

## When to reach for this

- Before writing any sentence that quotes a paper
- When adding a citation, to pin the artifact and its sha256
- When asked whether a quotation is real
- When a bibliography has entries with no DOI or arXiv id — `citations resolve`
- In CI, as `citations verify --strict`

## What it will not do

It cannot catch misinterpretation. A real, resolving quotation attached to a claim it does not
support passes every check here. Verification is not comprehension.
