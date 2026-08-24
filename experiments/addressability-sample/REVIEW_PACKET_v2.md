# Review request, round two: what changed and what is still open

Round one found four binding defects: unspecified value selection, pseudoreplication, inference
rules that did not test their own wording, and a snapshot rule that could retrieve artifacts
created after publication. All four are addressed. Nothing has been run: no article opened, no
repository retrieved, no manifest written.

## What changed

| round one | now |
|---|---|
| "census" of 60 of 215 | **sample**; the word census is gone |
| values selected at some unstated point | enumerated from the article alone in a frozen traversal, hashed, then up to ten drawn by `sha256(seed ‖ doi ‖ text ‖ ordinal)` — **before** any repository is opened |
| 600 values treated as independent | **the article is the inferential unit**; article-level means, 95% intervals by bootstrapping whole articles; pooled value rates demoted to secondary |
| H1 "estimate < 0.25 and upper bound < 0.40" | separate **target** (estimate < 0.25) and **evidential criterion** (one-sided 95% upper bound < 0.25), neither reported as proving the other |
| H2 "≥ 0.90 and lower bound ≥ 0.80" | same split; the 0.80 bound is named the minimum supported level, not evidence for 0.90 |
| H3 mismatch-ratio hypothesis | **demoted to exploratory**; a ratio over a handful of events carries no weight |
| H4 counted files | counts **articles** by primary addressable artifact |
| blanket void below 40 retrievable repositories | removed; H1 is reported for all 60, and an unretrievable repository is coverage 0, an observation |
| "default branch head otherwise" | snapshot hierarchy: Software Heritage id → archival DOI/release → article-linked tag → last commit at or before publication; branch head only as a labelled sensitivity analysis |
| "addressable" | **machine-addressable under the registered locator grammar**, with the grammar frozen and formats outside it coded `unsupported_format`, never pooled with absent |
| primary / derived | `artifact_relation`: `stored_directly`, `recomputable_from_released_inputs`, `not_recomputable` |
| one four-level addressability variable | `retrieval_status` (repository) split from `value_status` (value) |
| one coder | second coder on 12 articles, Krippendorff's alpha per variable, both codings preserved |
| authors contacted, results adjusted | primary results frozen and hashed first; replies produce a separate adjudicated sensitivity analysis |
| "ReScience C bounds from above" | removed; a purposive reproducibility-oriented benchmark population, bounding nothing |
| "nobody has measured this" | "no prior estimate was found", with databases and terms to be reported |

Three artifacts are now frozen and pinned by digest from the registration: `CODEBOOK.md` (the
eligibility rules, traversal order, locator grammar, numeric equivalence rules, coding scheme,
snapshot hierarchy), `frame.json` (the ordered frame and the 60 selected identifiers, drawn by
hash order rather than a language's shuffle), and the locator grammar itself at `docs/SPEC.md`
§3.5.

The drawn sample: 60 articles, **all 60** carrying a code link, 42 carrying a Software Heritage
identifier, spanning 16 domains.

## Also acted on, in the instrument

The locator vocabulary is implemented rather than promised. `tree` (RFC 6901 over JSON, and
YAML restricted to a JSON-compatible tree with duplicate keys rejected), `table` (column plus a
predicate matching exactly one row), `table_position` (by index, carrying a warning), `sqlite`,
and `array` for `.npy`/`.npz`. Every variant enforces one invariant — exactly one scalar, never
the first match — and HDF5, NetCDF, Parquet and spreadsheets report `format_unsupported` rather
than being approximated. No backend searches a file for the printed number.

The ordering check now separates outcome from reason, as round one asked: `ordered`,
`violated`, `unchecked` with one of ten reason codes, `not_applicable`. Runs bind their outputs
by digest, so a later file at the same path cannot be presented as an earlier run's output, and
every run declares a `registration_authority` (`self_recorded` through `trusted_timestamp`) that
a policy can require a minimum of.

## Still open — this is what I want from round two

1. **H1's 0.25 has no external anchor.** Round one did not supply one either. Is there a
   published rate — artifact evaluation, badging, a reproduction study — that a target should be
   reasoned from, or should H1 drop the threshold and register as estimation only?
2. **Is the evidential criterion achievable at n = 60?** A one-sided 95% upper bound below 0.25
   needs a fairly low point estimate. If the design cannot clear it under plausible values, I
   would rather know now and register H1 as estimation than register a criterion I expect to
   miss.
3. **Twelve articles for the second coder.** Enough for Krippendorff's alpha on a four-level
   nominal variable, or does that need more?
4. **Is `machine-addressable under the registered locator grammar` the right name** for the
   estimand, or does it still overclaim?
5. **The exploratory `artifact_relation` comparison** — worth carrying at all, or noise?
6. **Anything still unfalsifiable or trivially satisfiable.**

Do not be polite about it.

---

# The preregistration, verbatim

# What fraction of published articles make their reported numbers machine-addressable in a released artifact?

**Status:** DRAFT — not frozen.

Sections use the [OSF Preregistration](https://osf.io/prereg/) question titles verbatim; a
question that does not apply is answered **N/A** with the reason, never deleted.

Frozen alongside this file: `CODEBOOK.md` (`f2670fb6bdff8ca2`) for the operational rules,
`frame.json` (`5ee293dbc5ca1463`) for the drawn sample, and `docs/SPEC.md` §3.5
(`5cce41d2f71e882a`) for the locator grammar. Digests are sha256, first 16 hex.

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
`_bibliography/published.bib` on the `sources` branch of `ReScience/rescience.github.io`
(sha256 `9b2c637135f5828c2b6213fef5f90155cb0c0350997846c28e1a17552a7e58e4`) holds 223 entries:
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

```
2026-08-24  created                              nothing run
2026-08-24  sample drawn and frozen              nothing run
2026-08-24  revised after external review        nothing run
```

---

# The codebook, verbatim

# Codebook

Frozen with the registration and referenced from it by digest. Every rule here is applied
before any repository is opened.

## 1. Eligible values

A candidate is a numeric value the article states as its own result.

**Eligible.** Point estimates; test statistics; p-values stated numerically; counts and
sample sizes reported as findings; each component of an interval or `mean ± SD`, enumerated
separately; percentages; runtimes and resource measurements presented as results.

**Ineligible.** Values quoted from the work being reproduced; sample sizes stated in Methods
as design parameters; figure axis labels and tick values; values readable only from a plot;
inequalities (`p < 0.001`, `< 1 ms`) since no single value is stated; version numbers, dates,
page and section numbers; values inside quoted text.

## 2. Enumeration order

Traverse in this order, taking every eligible value: **abstract → results prose → tables →
figure captions → discussion**. Enumerate the whole article. Do not stop at ten: stopping
lets article structure decide inclusion, and section-first sampling estimates section-specific
addressability rather than the quantity of interest.

Record per candidate before any artifact is opened: printed text verbatim, section, table or
figure identifier, page, stated unit, and eligibility. Hash the candidate list.

## 3. Selecting up to ten

Where an article yields more than ten candidates, order them by
`sha256(study_seed || article_doi || printed_text || ordinal)` and take the first ten. The
study seed is `20260824`. Articles yielding ten or fewer contribute all of them.

Selection is frozen and hashed before the repository is retrieved. This is the single ordering
rule the design depends on: values chosen after an artifact is inspected can be driven, even
unconsciously, in either direction.

## 4. Repository snapshot

Take the first that resolves:

1. `code_swh` — the Software Heritage identifier in the bibliography entry.
2. An archival DOI or release linked from the article.
3. A git tag or release explicitly associated with the article.
4. The last commit at or before the article's publication date.
5. Default branch head — **only** as a separately reported `current_snapshot` sensitivity
   analysis, never as the primary measurement.

The default branch head in 2026 may hold files added years after publication, so pinning it
records what was inspected and not what accompanied the article.

Git LFS pointers that do not resolve, unresolved submodules, and data hosted outside the
snapshot are `inaccessible`, not `absent`. Release assets count as part of the snapshot where
the article links them. Generated outputs committed to the repository count as released.

## 5. Locator grammar

A value is **machine-addressable** when it resolves under the locator grammar frozen at
`docs/SPEC.md` §3.5 of this repository. That grammar admits:

| format | locator |
|---|---|
| JSON | RFC 6901 pointer |
| YAML restricted to a JSON-compatible tree | RFC 6901 pointer |
| CSV, TSV, PSV | column plus a predicate matching exactly one row |
| SQLite | table, column, and a predicate matching exactly one row |
| NPY, NPZ | array name plus a multidimensional index |

HDF5, NetCDF, Parquet, Arrow and spreadsheet formats are **outside instrument scope** and are
coded `unsupported_format`, which is reported separately and never pooled with values that are
absent. A value in one of these files is not evidence about addressability in general.

Positional row addressing is admissible and recorded as such, since a row index names a
different cell once a table is reordered.

The measured quantity is therefore *machine-addressability under this grammar*, not
checkability in general, and is reported under that name.

## 6. Agreement

Compared with `decimal.Decimal` at the precision the article printed, rounding half to even.
Consequences, fixed here:

- `1.2e-3` and `0.0012` agree; exponent notation is not a difference.
- `3.2` in the article is satisfied by `3.2001` stored; `3.20` is not.
- A stored proportion against a printed percentage agrees only where the artifact states its
  unit in the file or its documentation. Where the unit must be inferred, the value is
  `present_unaddressable`, not a mismatch.
- A sign difference arising from a different reference category is a mismatch, and flagged.
- Non-finite stored values (`NaN`, `Infinity`) are `not_assessable`.

## 7. Coding scheme

Two variables, because retrieval describes the repository and addressability describes the
value.

```
retrieval_status:   retrieved | absent | inaccessible | unsupported_format
value_status:       addressable | present_unaddressable | absent_from_retrieved_artifacts
                  | not_assessable
artifact_relation:  stored_directly | recomputable_from_released_inputs | not_recomputable
```

`artifact_relation` replaces a primary/derived split, which was the wrong pair: a stored value
can itself be a derived statistic, and an artifact can hold raw observations from which the
article computes a mean. The scientific character of the value — raw, summary, contrast,
model-derived — is coded separately and used only descriptively.

Locating a value is by field and row name only. Searching an artifact for the article's
printed numeric string is prohibited; a value not locatable by name is `present_unaddressable`.

## 8. Two coders

A second coder independently codes value eligibility, `value_status` and `artifact_relation`
for 12 articles drawn by the same permutation rule. Pre-adjudication agreement is reported as
raw agreement and Krippendorff's alpha per variable, and both original codings are preserved.
Disagreements are adjudicated against this codebook; the adjudicated coding is used for the
primary estimates.

## 9. Author contact

Primary results are frozen and hashed before any author is contacted. An author identifying a
pointer as wrong produces a separately reported adjudicated sensitivity analysis; it never
silently replaces the initial measurement.
