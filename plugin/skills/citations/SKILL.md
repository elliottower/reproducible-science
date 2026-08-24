---
name: citations
description: Verify that quotations resolve in the sources they cite, and manage a library of verified quotations. Use before quoting a paper, when adding a citation, when asked to check whether a quote is real, when a bibliography needs DOIs backfilled, or when checking whether the authors and years in a reference list match the records their identifiers resolve to. Requires the `citations` CLI (`uv tool install citations`).
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
citations audit                     # does the stored metadata match the registry record?
citations audit --bib refs.bib      # check a BibTeX file directly
citations resolve                   # backfill missing DOIs and arXiv ids
citations init                      # create a library here
citations lint                      # BibTeX correctness
```

## Reading the output

Three results, exhaustive:

| | |
|---|---|
| `found` | the passage is in the source |
| `not found` | the source was read and the passage is not in it |
| `unchecked` | the source could not be read — **no measurement was made** |

Warnings sit on their own axis. A passage can be `found` and still carry one: `truncated` (stops
mid-word or mid-number and the source continues it), `short` (the source may qualify it in the next
clause), `normalized` (matched ignoring punctuation), `page` (found, but not where the record says).

**`truncated` is the one to stop for.** `"an accuracy of 0.9"` is genuinely present in a paper
reporting **0.95**, so it passes every other check while misstating the result. Length is not the
tell — a long quote ending one digit early is the convincing version — so `short` will not fire.
Extend the quote through the end of the number or the word.

**`unchecked` is not a pass.** Do not describe a claim as verified on the strength of it.

**`not found` means read the source.** A broken extraction reads the same as a passage that
was never there.

**A run with nothing to check exits non-zero.** The path is wrong, not everything passing.

**Check which library you are on before believing a clean run.** The library resolves in order:
`$CITATIONS_HOME`, else `.citations/` found by walking up from the current directory, else the
shared one from `citations init --user`. So the same command run one directory over can verify a
different set of records and still report `all found`.

## Quote enough text

`"We trained 50"` resolves against a sentence that continues `"...and 5 refits each for 12
layered"`. Quote through the qualifiers; never end a pin mid-clause.

## A resolving identifier says nothing about the metadata beside it

`verify` checks quotations. `audit` checks the reference itself: do the authors, year, volume
and pages stored beside a DOI match the record that DOI resolves to?

The failure is a real DOI carrying an invented author list. It resolves, the link is live, and
the quotations pinned to it are genuine, because the DOI does point at the right paper — the
names written beside it belong to someone else. A DOI checker passes it, a link checker passes
it, and `citations verify` passes it. Found in one 75-entry bibliography: four author lists
belonging to nobody on the cited paper, one PMID resolving to an unrelated article in another
field, and four lists stopping early with no `and others` marker, which is invisible because a
truncated list looks complete.

Never write an author list from memory. If a reference was assembled without reading the
record, run `citations audit` before it ships.

## When to reach for this

- Before writing any sentence that quotes a paper
- When adding a citation, to pin the artifact and its sha256
- When asked whether a quotation is real
- When a bibliography has entries with no DOI or arXiv id — `citations resolve`
- Before a bibliography ships, and after any reference was written out by hand — `citations audit`
- In CI, as `citations verify --strict` and `citations audit --strict`

## What it will not do

It cannot catch misinterpretation. A real, resolving quotation attached to a claim it does not
support passes every check here, and `audit` compares a reference against a registry rather
than against the paper it is cited for. Verification is not comprehension.
