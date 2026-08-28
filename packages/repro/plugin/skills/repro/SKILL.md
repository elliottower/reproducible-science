---
name: repro
description: Verify that a manuscript's declared claims resolve in the artifacts they name — quotations against sources, reported numbers against result files, table cells against tables. Use before submitting a draft, when asked whether the numbers in a paper still hold, after regenerating results, when a reviewer asks where a figure came from, or when a manuscript and its data may have drifted apart. Requires the `repro` CLI (`uv tool install reproducible-science`).
---

# repro

Every claim in a paper, checked against the file it says it came from.

## The rule that matters

**A number is verified when it is fetched from a stated address, not when it is found somewhere
in a file.** Searching a results file for `0.42` finds it wherever it appears, including places
that have nothing to do with the claim. Give the address; let the tool fetch it.

## Commands

```bash
repro demo               # a worked example, run for real and then broken on purpose
repro init my-paper      # scaffold repro.yaml
repro verify             # check every assertion in it
repro verify --policy strict
```

`repro demo` writes `repro-demo/`, a self-contained project that verifies clean and then fails
two different ways: a pinned file that was edited, and a number the manuscript reports that the
run does not hold. Offline and under a second per command, so it is somewhere to try a change
and see which check catches it.

## What a manifest says

```yaml
artifacts:
  - id: results
    path: analysis/results.json
    digest: {algorithm: sha256, value: 9f635f9a...}

claims:
  - id: primary
    text: The treatment reduced the primary outcome
    registration: confirmatory
    evidence:
      - kind: metric
        artifact: results
        name: p_value
        pointer: /primary/p
        reported: "0.031"
```

## Reading the output

```text
repro.yaml

  ok    icc          metric   /icc = 0.42
  MISS  pvalue       metric   p: manuscript prints 0.031, results.json holds 0.051
  GONE  n            metric   /n does not resolve in results.json

  1 mismatch, 1 not_found, 1 verified
  policy publication: FAILED  (2 errors, 0 warnings)
```

The first column is the outcome, the second the claim id, the third the kind of evidence.
Six outcomes exist: `ok` verified, `MISS` mismatch, `GONE` the address no longer resolves,
`--` the check could not run, `none` the claim offered no evidence, `ERR` the source could
not be read. The enum names — `verified`, `mismatch`, `unchecked` — appear under
`--format json`, never in the text output.

The distinction that matters is between `MISS` and `--`. `MISS` says the artifact was read
and disagrees. `--` says no comparison happened, from a missing file or an extractor that is
not installed. Reporting the second as a pass is the failure this exists to catch, so it
never does.

A fourth field, validity, says whether the bytes read are the bytes pinned. Every number can
agree and the run still fail, because they agreed with a document nobody pinned.

## When to reach for this

- Before submitting a draft, over the whole manifest
- After regenerating results, to see which claims moved
- When a reviewer asks where a number came from
- When a manuscript and its data may have drifted apart
- In CI, as `repro verify --policy strict`

## What it will not do

It checks evidence assertions, never whether a claim is true. A quotation can be present
word-for-word and still fail to support the sentence citing it; a number can match and the
analysis behind it be wrong. A passing run says the declared assertions held against the
artifacts pinned — not that the study replicates.

## Where this sits

`prereg` freezes the plan, `results` records what each run consumed and produced, `citations`
checks quotations against sources. This reads all of it back and reports what holds.
