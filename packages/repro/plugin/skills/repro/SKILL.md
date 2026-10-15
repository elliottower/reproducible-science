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
claims verify            # check every assertion in it: the fast check
claims verify --policy strict
repro verify             # the claims, the plan, the ledger, the citations and staleness, in one report
```

`claims verify` checks the manifest's claims alone. `repro verify` checks those and every other
record the project keeps -- `prereg check`, `results verify --files`, `citations verify`, and
each declared command against its recorded re-runs -- naming a record the project does not keep
as not used. Both execute nothing a manifest declares, and both keep the record of checks.

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

A claim's `text` is the sentence as the manuscript prints it, or the question as it was asked,
word for word. Your own label for the claim goes in its `id`. A reader matching claims to a
paper matches on `text`, and a paraphrase has to be matched by hand.

## What can be declared

Six kinds of evidence. Each names an `artifact` by id, except `correspondence`, which names
one per side, and `aggregate`, which names one per member. `reported` is the number as the manuscript prints it, always a quoted string:
`"3.20"` is compared at two decimals and `"3.2"` at one.

| kind | asserts | fields |
|---|---|---|
| `metric` | a JSON or YAML file holds this number at a pointer | `name`, `reported`, `pointer` |
| `table` | a table holds this number in a cell | `name`, `reported`, `column`, and `where` or `row`; optional `delimiter` |
| `value` | a file holds this number at a locator, in any format below | `name`, `reported`, `locator` |
| `quote` | this passage occurs in the text of a document | `text`; optional `page` (checked where the document has pages, reported as `page_unchecked` where it has none), `section` (recorded only) |
| `correspondence` | two artifacts, or several places in a manuscript, hold the same number, none written in the manifest | `name`, `sides`: two or more of `{name, artifact, locator}`, every pair compared |
| `aggregate` | the printed number is a statistic over every member listed | `name`, `reported`, `statistic`, `count`, `members`: `count` of `{artifact, locator}` |

The five that compare a number take `mode` and `tolerance`: `printed_precision` (the default,
round to the digits `reported` prints), `absolute`, or `relative`, with `tolerance` a quoted
string. A `correspondence` has no `relative`.

`metric`, `table`, `value` and each side of a `correspondence` take an optional `conversion`,
for a file that stores a number in one unit where the manuscript prints another: `percent`
(the file holds the fraction `0.042`, the manuscript prints `4.2`) or `fraction` (the file
holds `4.2`, the manuscript prints `0.042`). The stored value is converted exactly and then
rounded to the digits `reported` prints. There is no multiplier and no other name.

`metric`, `table` and `value` take an optional `places`, the number of decimal places the
manuscript reports the value to. `reported` must then be written to exactly that many:
`"4.20"` with `places: 1` is a `mismatch` with reason `places_mismatch`, whatever the file
holds. Declare it where a table or a journal fixes the precision, and only under
`printed_precision`.

A stored value exactly halfway between two printed values, `4.25` at one place, verifies as
either `4.2` or `4.3`, because half-up and half-to-even rounding are both in use. The output
marks it `[exact tie: 4.2 or 4.3]`. Report it as a tie, not as an error and not as an
ordinary match.

```yaml
- {kind: metric, artifact: results, name: p, reported: "0.031", pointer: /primary/p}
- {kind: table, artifact: models, name: accuracy, reported: "0.648", column: accuracy, where: {model: lasso}}
- {kind: metric, artifact: results, name: attrition, reported: "4.2", pointer: /primary/attrition, conversion: percent}
- {kind: metric, artifact: results, name: effect, reported: "0.41", pointer: /primary/effect, places: 2}
- {kind: quote, artifact: paper, text: "We enrolled eighteen sites across the two regions."}
- kind: correspondence
  name: participants
  sides:
    - {name: stated, artifact: paper, locator: {kind: prose, before: "We analysed", after: "participants"}}
    - {name: measured, artifact: results, locator: {kind: tree, pointer: /primary/n}}
- kind: aggregate
  name: accuracy
  reported: "0.914"
  statistic: mean
  count: 3
  members:
    - {artifact: seed-0, locator: {kind: tree, pointer: /accuracy}}
    - {artifact: seed-1, locator: {kind: tree, pointer: /accuracy}}
    - {artifact: seed-2, locator: {kind: tree, pointer: /accuracy}}
```

Use an `aggregate` wherever the manuscript reports a number over several runs, such as "mean
over ten seeds". `statistic` is `mean`, `median`, `min`, `max`, `sum` or `count`, and `count`
must equal the number of members, so a run left out of the list is a manifest that does not
load. Every member must hold a number: a missing file is `unchecked` and a member that does
not resolve is `not_found`, each naming the member, and the statistic of the remaining members
is never compared. Binding the sentence to one run's file with a `metric` checks that run and
nothing about the others. An `aggregate` takes `conversion` and `places` as a `metric` does,
with the conversion applied to each member, and an exact tie verifies as either neighbor.
There is no standard deviation.

`metric` is short for a `value` with a `tree` locator, and `table` for one with a `table` or
`table_position` locator. Everything else is a `value`:

| locator | reads | fields |
|---|---|---|
| `tree` | `.json`, `.yaml`, `.yml` | `pointer`, RFC 6901 |
| `table` | `.csv`, `.tsv`, `.psv`, delimited `.txt`; `.parquet`, `.feather`, `.arrow`; `.dta`, `.sav`, `.zsav`; `.rds` | `column`, `where`; optional `delimiter` |
| `table_position` | the same | `column`, `row` counted from 0 below the header; passes with a warning |
| `sheet` | `.xlsx`, `.xlsm`, `.xls` | `column`, `where`; `sheet`, required with more than one |
| `sqlite` | `.db`, `.sqlite`, `.sqlite3` | `table`, `column`, `where` |
| `array` | `.npy`, `.npz`, `.h5`, `.hdf5`, `.nc` | `index`; `array`, the name or dataset path, omitted for `.npy` |
| `prose` | PDF, `.tex`, `.txt`, `.md`, `.rst`, `.html`, `.htm`, `.xml`, `.tei`, `.py` | `before`; optional `after`, `form` |

```yaml
- {kind: value, artifact: results, name: n, reported: "480", locator: {kind: tree, pointer: /primary/n}}
- {kind: value, artifact: models, name: accuracy, reported: "0.641", locator: {kind: table_position, column: accuracy, row: 1}}
- {kind: value, artifact: tables, name: auc, reported: "0.71", locator: {kind: sheet, sheet: Table 2, column: auc, where: {model: lasso}}}
- {kind: value, artifact: runs, name: loss, reported: "0.218", locator: {kind: sqlite, table: runs, column: loss, where: {seed: 3}}}
- {kind: value, artifact: acc, name: accuracy, reported: "0.95", locator: {kind: array, index: [1, 1]}}
```

`where` must match exactly one row; none is absent and two is ambiguous, never the first. The
columnar, workbook, array and HDF5 formats each need an extra, which an `unchecked` result
names. No locator takes a pattern, and a pickle is never opened.

## A number in a printed table or in running text

A `prose` locator is two literal anchors: `before` is the text that precedes the number and
`after` the text that follows it. The value is the run of non-whitespace characters between
them. Anchors and document are both lower-cased with every run of spaces and line breaks
folded to one space before matching, the folding a `quote` gets, so an anchor is written with
single spaces whatever the file's padding and may run across lines.

```text
## $north
##
## |   N (sites)| Slope|    se|   pval|
## |-----------:|-----:|-----:|------:|
## |           7| 0.318| 0.107| 0.0271|
```

```yaml
- kind: value
  artifact: output
  name: Slope (north)
  reported: "0.318"
  locator:
    kind: prose
    before: "$north ## ## | N (sites)| Slope| se| pval| ## |-----------:|-----:|-----:|------:| ## | 7|"
    after: "|"
- {kind: value, artifact: output, name: se (north), reported: "0.107", locator: {kind: prose, before: "| 7| 0.318|", after: "|"}}
- {kind: value, artifact: output, name: accuracy, reported: "93.1", locator: {kind: prose, before: "held-out split was", after: "%"}}
- {kind: value, artifact: output, name: sites, reported: "18", locator: {kind: prose, before: "We enrolled", after: "sites", form: cardinal_word}}
```

- **Name what touches the number.** A cell is printed against its divider, so `after: "|"`.
  With `after` left out the value runs to the next whitespace and is `0.318|`, reported as
  `value_not_numeric` with the text that was read. The same holds for `93.1%` and for a number
  that ends a sentence, `3.14.`, which `after: "."` reads as `3.14`. An anchor cannot split a
  number: `after: "8"` on `0.318` and `before: "0.3"` read nothing, and the output names the
  number. A sign is part of its number unless a digit or letter precedes it (`10-12`), and
  digits attached to a letter (`v0.5`, `H10`) are a name.
- **`before` is the row's leading cells**, with enough of the header or group label to be the
  only such row. Anchors selecting two different numbers are `passage_ambiguous`; the same
  number twice is fine.
- **A number written as a word** is refused with `number_as_word` until the locator says
  `form: cardinal_word`, which reads one word below one hundred.
- **`.html` and `.xml` are read as source**, tags and entities included: a table marked up as
  `<td>` cells has `</td>` after the number, and `<` in the text is `&lt;`.

## When a quote is the fallback

A `quote` passes where the passage, folded the same way, occurs once in the document. Use it
for what a source says in words, and for a number only where no locator reaches it: a value
with a space inside it (`1 234`, `one hundred and five`), or a file whose text cannot be
anchored on both sides. It establishes that the passage is there. It reads no number, so
nothing is compared at printed precision, a `correspondence` cannot use it, and a longer
number containing the quoted one satisfies it: `"accuracy of 0.9"` occurs in a source
reporting 0.95. Quote the whole row or sentence, and prefer a `value` wherever two anchors
fit.

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

- Before submitting a draft, over the whole project: `repro verify`
- After regenerating results, to see which claims moved
- To run the declared commands again and see whether the printed numbers survive: `repro reproduce`
- To see what a claim said at each check before it was edited: `repro why <claim-id>`, which reads the record every `claims verify` and `repro verify` keeps in the git directory
- In the project's CI job or before a release, so that record travels with the repository: `repro verify --record`, then commit `.repro/checks.jsonl` and `.repro/ledger.head`
- After editing an input or a script, before trusting a green verify: `repro stale`
- For one claim, what the record establishes and what it does not: `repro why <claim-id>`
- To count every number the manuscript prints, and which no claim accounts for: `repro numbers`
- When a reviewer asks where a number came from
- When a manuscript and its data may have drifted apart
- In CI: `repro ci init` writes a workflow for each record the repository keeps (`repro ci prereg`, `results`, `claims`, `citations`, `reruns`), each with a summary on the run page

## What it will not do

It checks evidence assertions, never whether a claim is true. A quotation can be present
word-for-word and still fail to support the sentence citing it; a number can match and the
analysis behind it be wrong. A passing run says the declared assertions held against the
artifacts pinned — not that the study replicates.

## Where this sits

`prereg` freezes the plan, `results` records what each run consumed and produced, `citations`
checks quotations against sources — including the passages a manuscript paraphrases rather
than prints, which are most of them. This reads all of it back and reports what holds.
