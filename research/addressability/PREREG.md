# What fraction of published articles make their reported numbers machine-addressable in a released artifact?

**Status:** DRAFT — not frozen.

Sections use the [OSF Preregistration](https://osf.io/prereg/) question titles verbatim; a
question that does not apply is answered **N/A** with the reason, never deleted.

Frozen alongside this file: `CODEBOOK.md` (`1d8aebf8cae14546`) for the operational rules,
`frame.json` (`5ee293dbc5ca1463`) for the drawn sample, and `docs/SPEC.md` §3.5
(`22b13c3b484c278a`) for the locator grammar. Digests are sha256, first 16 hex.

## Research questions or hypotheses

Two rates, both estimated **per article**. **Coverage** is whether a released artifact holds an
article's printed numbers at a nameable position under the frozen locator grammar.
**Agreement** is whether the stored value equals the printed one at the precision the article
printed. Ten values from one article share a result file, a table convention and a
documentation practice, so pooling 600 as if independent would give intervals too narrow to
mean anything.

**H1.** Mean article coverage — the proportion of an article's sampled values that are
machine-addressable, averaged over articles — is below 0.25.

**H2.** Among addressable values, agreement is at or above 0.90.

**H3.** Among articles whose repository is retrievable and holds a machine-readable result
file, mean article addressability is below 0.50.

**H4.** Among articles contributing an addressable value, more have a delimited table as their
primary addressable artifact than a structured non-tabular file.

H3 carries the design. All 60 sampled articles link code, so H1 alone is consistent with
artifacts that were never released; H3 locates the failure at addressing rather than release.

**H2 is the registered outcome that strengthens the articles examined.** Agreement at or above
0.90 makes H1 a documentation gap rather than an error rate.

## Foreknowledge of data or evidence

The engine and its locator grammar are built and evaluated. A quotation corpus of 5,686
assertions over 366 declared sources across 17 manuscripts has been run: 355 sources match
their pin, 9 carry none, 1 is named and absent. Two manuscripts were audited at the value
level: one agrees on all 39 values it prints, the other disagrees on 9 of 10 table rows. Both
are by the author of this plan; neither is in the frame sampled here.

Two manuscripts by one author cannot separate an author effect from a literature effect, so
that corpus anchors H2 without settling it. Its target of 0.90 sits closer to the 39/39 result
than to the midpoint because seven of the nine disagreements were third-significant-figure
differences that decimal comparison at printed precision resolves.

The frame was read and the sample drawn before the hypotheses were written.
`_bibliography/published.bib` on the `sources` branch of `ReScience/rescience.github.io`,
vendored here as `published.bib` (sha256 `9b2c637135f5828c`) so the draw reproduces without
network access, holds 223 entries:
197 replications, 18 reproductions, 7 editorials, 1 letter. Of the 215 research articles, 214
carry a non-empty `code_url` or `code_doi`, 160 a `code_swh`, and 29 a data link. All 60 drawn
articles carry a code link, 42 carry a `code_swh`, and they span 16 domains. That reading cost
H1 an interpretation: H1 cannot be read as a claim about whether artifacts are released, since
in this frame they nearly always are.

No article has been opened, no repository retrieved, no manifest written, no verification run.

ReScience C is a purposive, reproducibility-oriented benchmark population. Addressability that
is low even where reproduction is the stated premise establishes a problem in a favorable
setting; it does not bound rates in other genres, and no such bound is claimed. No prior
empirical estimate was found in a preliminary search; the manuscript reports the databases and
terms searched and claims that none was found, not that none exists.

## Explanation of foreknowledge and managing unintended influences

Foreknowledge fixes what H1 can mean and where H2's target sits; neither is revisited after
data. The sample is frozen before any article is opened, and candidates are hashed before each
repository is retrieved.

## Study type

Observational sample of a defined publication frame.

## Intention for causal interpretation

N/A — the rates are descriptive and no intervention is applied.

## Blinding of experimental treatments

N/A — no treatment.

## Additional blinding during research or analysis

Values are located by field and row name only; searching an artifact for the printed numeric
string is prohibited (`CODEBOOK.md` §7).

## Study design

Three stages, each frozen before the next begins: enumerate and hash eligible candidates from
the article alone (`CODEBOOK.md` §§1–2); draw up to ten (§3); retrieve the snapshot and code
each selected value (§§4–7).

## Randomization

Articles are ordered by `sha256(seed || doi)` ascending, seed `20260824`, and the first 60
taken. A language's shuffle is an implementation detail and two implementations seeded alike
diverge, so the permutation is a hash order. The ordered frame and the 60 selected identifiers
are in `frame.json`.

## Data collection procedures

Snapshots follow the hierarchy in `CODEBOOK.md` §4, preferring the Software Heritage identifier
and falling back to the last commit at or before publication. Default branch head is a separate
sensitivity analysis only, since a 2026 head may hold files added years after the article.
Every retrieved file is pinned by sha256 before a value is read.

## Data collection procedures - File upload

N/A — no instrument or questionnaire.

## Sample size

n = 60 articles from the 215 research entries, up to ten values each. Precision is governed by
60 articles, not by the value count. At a mean coverage near 0.20, an article-clustered
bootstrap over 60 resolves the mean to roughly ±0.10: the sample separates 0.20 from 0.50 and
nothing finer than about ten points.

Near that coverage, 100 to 150 values carry H2. Its interval bootstraps articles rather than
values, so it is wider than a pooled Wilson interval over the same count. H4 takes a gate below
rather than a power calculation, since the article count it needs cannot be estimated before
H1.

## Sample size rationale

Stated above; 60 is also the largest sample whose per-article candidate enumeration and manifest
one person can write inside the study window.

## Starting and stopping rules

Collection stops when all 60 sampled articles are coded. No interim analysis is run, and no
article is added or replaced after the first `repro verify`.

## Manipulated variables

N/A — observational.

## Measured variables

Per value: `retrieval_status`, `value_status`, `artifact_relation`, artifact format, and for
addressable values the `repro` outcome and reason (`CODEBOOK.md` §7). Retrieval describes the
repository and addressability the value, so the two are coded separately.

## Measured variables - File upload

N/A — the coding scheme is in `CODEBOOK.md`.

## Indices

Article coverage = addressable ÷ eligible sampled values within an article; H1 and H3 estimate
its mean across articles. Agreement = `verified` ÷ (`verified` + `mismatch`). Pooled
value-level rates are secondary description.

## Indices - File upload

N/A — each index is two counts and a division.

## Statistical models

N/A — the estimands are means of article-level proportions, with 95% intervals from a bootstrap
resampling whole articles. A multilevel model would add assumptions 60 articles cannot check.

## Statistical models - File upload

N/A — no model is fitted.

## Transformations

N/A — counts and proportions are analyzed as collected.

## Inference criteria

Each hypothesis has a descriptive target and a separate evidential criterion. The target is
what the estimate shows; the criterion is what the interval supports. Neither is reported as
proving the other.

| | target | evidential criterion |
|---|---|---|
| H1 | mean article coverage < 0.25 | one-sided 95% upper bound < 0.25 |
| H2 | agreement ≥ 0.90 | one-sided 95% lower bound ≥ 0.80 |
| H3 | mean addressability < 0.50 among eligible articles | one-sided 95% upper bound < 0.50 |
| H4 | table-primary articles > structured-primary articles | 95% interval on the difference excludes 0 |

All bounds come from the article-level bootstrap. Where a target holds and its criterion does
not, both are reported and the hypothesis is unsupported at the registered level — a statement
about this sample's precision, not about the estimate.

**H2 is void if fewer than 50 values are addressable.** **H4 is void if fewer than 20 articles
contribute an addressable value.** **H3 is void if fewer than 20 articles yield a retrievable
machine-readable result file.** H1 is reported for all 60 articles whatever the retrieval rate:
an article whose repository cannot be retrieved has coverage 0, which is an observation and not
a missing value.

A `not_found` outcome on a value coded addressable means the locator was written wrong; each is
re-adjudicated once, then recoded `present_unaddressable` and counted.

## Data inclusion and exclusion

Editorials and letters are out of frame. Value eligibility is `CODEBOOK.md` §1. Values in
formats outside the frozen locator grammar are coded `unsupported_format` and reported
separately from values that are absent.

## Missing data

An unretrievable repository is a scored outcome, not a missing value, and no article is
replaced. An article yielding no eligible value leaves the denominator and is counted.

## Other planned analysis

Exploratory, and labeled so: mismatch rate by `artifact_relation`, on the expectation that
values recomputable from released inputs disagree more often than values stored directly; rates
by domain, language and year; and the default-branch-head sensitivity analysis. The
`artifact_relation` comparison stays exploratory because a ratio over a handful of events
carries no weight, and the count cannot be estimated before H1.

## Context and additional information

| finding | how it is reported |
|---|---|
| no addressable artifact | named; release is an open choice |
| artifact present, value unaddressable | named; format is a documentation fact |
| printed value disagrees with the stored value | aggregate until authors are contacted |

**No article is named in connection with a mismatch before its authors have been sent the
manifest, the locator, and the stored value, and given 30 days to reply.** Primary results are
frozen and hashed first; replies produce a separately reported adjudicated sensitivity analysis
and never silently replace a measurement. Correspondence is counted, never quoted.

A second coder independently codes 12 articles (`CODEBOOK.md` §8); pre-adjudication agreement is
reported per variable and both codings preserved.

---

## Log

Append only. Never edit above the line.

The last column is what distinguishes an amendment from a deviation, so you do not have to
decide which word to use: `nothing run`, `no results seen`, `results not opened`, `results seen`.

```text
2026-08-24  created                              nothing run
2026-08-24  sample drawn and frozen              nothing run
2026-08-24  revised after external review        nothing run
```
