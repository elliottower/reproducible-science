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

## Other people's files

Papers, full texts, abstracts, datasets and any other file somebody else wrote do not go into
the project's repository. A committed copy is published with the repository, and taking it
out later means rewriting every commit that held it.

- Keep each in an ignored folder. `repro init` writes the rule for `sources/` into the
  project's `.gitignore`, except where git already tracks a file under `sources/`: the
  project's own files are there, so it says so and another folder has to be ignored.
- Pin each by sha256, with the address it came from. For a quoted source that is the `source:`
  block of its claims file, which takes `sha256:` and `url:`. For a file no claims file names,
  such as a dataset, keep a manifest of your own: one line per file, its sha256 and its
  address. `repro.yaml` pins a file by digest and records no address.
- A reader then gets the same bytes with `citations fetch --claims <dir>`, which downloads
  each source a claims file pins and keeps only the bytes that match the pin.
- A freeze commit holds the plan, the code and the tests, and nothing else.

`prereg freeze` already refuses one case. Where `citations` is installed, it asks which
sources the project's quotations are pinned to are held by git, in the index or in the last
commit, and with any held it exits 1 before anything is written. `--allow-tracked-sources`
lets that freeze go ahead and names the sources after its report; it is for text whose licence
allows redistribution. Where the question cannot be asked, as in a project with no claims
directory, the freeze goes ahead.

## When to reach for this

- Before submitting a draft, over the whole manifest
- After regenerating results, to see which claims moved
- To run the declared commands again and see whether the printed numbers survive: `repro reproduce`
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
