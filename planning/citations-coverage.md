# `citations coverage` — manuscript-side quotation coverage

**Status:** specified, not started. Deferred 2026-08-26.

## The gap

`citations verify` takes `--claims/--only/--strict/--allow-extractor/--triangulate/--verbose/
--quiet` and **no manuscript input**. It answers "do my pinned quotations resolve in their
sources?" and cannot answer "is every quotation in the paper pinned at all?"

So a quotation added to the manuscript and never pinned is invisible: `verify` reports clean.
That is the README's own *a check that never ran*, which the three-outcome model exists to keep
distinct from `found` and `not found` — and the tool currently collapses it by not looking.

## Interface

```console
citations coverage paper/draft.tex --claims claims [--strict]
    -> N quotations, N covered, K uncovered (uncovered listed with line numbers)

citations coverage paper/draft.tex --claims claims --attribute
    -> additionally: does each quotation appear in the stored artifact of a source cited NEAR it?
```

Report **covered / uncovered / unresolvable** as distinct outcomes, never pass-fail.
`--strict` exits 1 for CI, matching `verify`.

## Two checks, from two working prototypes

Both are already written, and duplicated per-repo, which is why this belongs in the tool.

- **Check B — coverage.** For every ``…'' in the .tex, is it a span of some pinned quote in
  `claims/*.yaml`? Deterministic, offline, no heuristics.
- **Check C — attribution.** For every ``…'' in the .tex, does it appear in the stored artifact
  of a source cited near it (700 chars back / 400 forward)? Catches misattribution, not just
  absence. The prototype's docstring names its own known gap; carry that over as a documented
  limitation rather than dropping it.

Prototype locations are in the handoff note, not repeated here: they live in two private
repositories and this file is in a public one.

## The hard part, already solved twice — carry it over verbatim

- **Normalization:** curly quotes, `\%`, `---`/`--`, `\emph{}` stripping, `{}` removal.
- **Ellipsis means omitted text:** each fragment must appear; contiguity is NOT required.
- **Skip fragments under ~12 characters**, which otherwise match noise.

## Design notes

The `prose` locator merged in #17 normalizes through `citations.verify.fold`, so `coverage`
should fold the same way or the two will disagree about what the document says.

A `.tex` manuscript is not readable by the default extractor chain — `.tex` is not in
`TEXT_SUFFIXES` and `pdftotext` reports `Couldn't read xref table`. `coverage` needs the same
`extract_cmd` affordance `verify` has, or a declared `detex`. Note that `detex` drops `tabular`
content, so a quotation inside a table is invisible to it; the repository's own `scripts/detex.py`
exists for this reason and should be preferred.
