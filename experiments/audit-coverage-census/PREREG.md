# What fraction of published computational papers make their reported numbers checkable against a released artifact?

**Status:** DRAFT — not frozen.

Sections use the [OSF Preregistration](https://osf.io/prereg/) question titles verbatim; a
question that does not apply is answered **N/A** with the reason, never deleted.

## Research questions or hypotheses

Two rates, asked separately. **Coverage** is whether a released artifact holds an article's
printed numbers at a nameable position — an RFC 6901 pointer into a structured file, or a
column plus a row selector in a delimited table. **Agreement** is whether the stored value
equals the printed one at the precision the article printed.

**H1.** Fewer than 25% of sampled ReScience C articles have any reported value locatable at an
addressable position in a released file.

**H2.** Among addressable values, at least 90% agree with the article at printed precision.

**H3.** The mismatch rate for derived values — means over runs, deltas, percentages the article
computed — is at least twice the rate for values the artifact stores directly.

**H4.** Among files holding addressable values, delimited tables outnumber structured files
(JSON, YAML, HDF5) by at least two to one.

**H5.** Among articles whose repository is retrievable and holds a machine-readable result
file, fewer than half the sampled values are addressable.

H5 carries the design. All but one article in the frame links code, so H1 alone is consistent
with artifacts that were never released; H5 locates the failure at addressing, not release.

**H2 is the registered outcome that strengthens the articles examined.** Agreement at or above
0.90 makes H1 a documentation gap rather than an error rate.

## Foreknowledge of data or evidence

A quotation corpus of 5,686 assertions over 366 declared sources across 17
manuscripts has been run: 355 sources match their recorded pin, 9 carry none, 1 is named and
absent. Two manuscripts have been audited at the value level: one agrees with its stored
results on all 39 values it prints, the other disagrees on 9 of the 10 table rows with a stored
file. Every audited manuscript is by the author of this plan and none is in the frame sampled
here.

Two manuscripts by one author cannot separate an author effect from a literature effect, so
that corpus anchors H2 without settling it. H2's threshold of 0.90 sits closer to the
39/39 result than to the midpoint because seven of the nine disagreements in the smaller audit
were third-significant-figure differences that decimal comparison at printed precision
resolves.

The sampling frame was read before the hypotheses were written.
`_bibliography/published.bib` on the `sources` branch of `ReScience/rescience.github.io`
(sha256 `9b2c637135f5828c2b6213fef5f90155cb0c0350997846c28e1a17552a7e58e4`) holds 223 entries: 197
replications, 18 reproductions, 7 editorials, 1 letter. Of the 215 research articles, 214
carry a non-empty `code_url` or `code_doi`, 160 a `code_swh`, and 29 a data link. That reading cost H1 an interpretation: H1 cannot be read
as a statement about whether artifacts are released, since in this frame they nearly always
are.

ReScience C is the frame because reproduction is its stated premise: its authors expect
scrutiny, so its coverage bounds from above a journal without that premise. No article in the frame has been opened, no repository cloned, no manifest written, no
verification run.

## Explanation of foreknowledge and managing unintended influences

Foreknowledge fixes what H1 can mean and where H2's threshold sits. Neither constraint is
revisited after data.

## Study type

Observational census of a defined publication frame.

## Intention for causal interpretation

N/A — the rates are descriptive and no intervention is applied.

## Blinding of experimental treatments

N/A — no treatment.

## Additional blinding during research or analysis

Pointers are located by field and row name only. Searching an artifact for the article's
printed numeric string is prohibited, and a value not locatable by name is scored
unaddressable.

## Study design

Two stages: score every sampled value for addressability, then declare `metric` or `table`
assertions for the addressable ones and run `repro verify` under the `publication` profile.

## Randomization

Articles are drawn without replacement by a seeded permutation of the frame, the seed recorded
here before drawing: `20260824`.

## Data collection procedures

Repositories are retrieved at the `code_swh` identifier where the entry carries one — 160 of
215 do — otherwise at the default branch head; every file is pinned by sha256 before a value
is read.

## Data collection procedures - File upload

N/A — no instrument or questionnaire.

## Sample size

n = 60 articles from the 215 research entries. At an observed coverage of 0.20 the 95% Wilson
interval on 60 is [0.118, 0.318]; at 0.50 it is [0.377, 0.623]. The sample separates H1's
threshold of 0.25 from a coverage of one half and resolves nothing finer than about ten points.

Up to ten reported values are taken per article, so the value-level denominator is at most 600.
If coverage runs near 0.20 the addressable denominator carrying H2 is 100 to 150; at 150 an
observed 0.90 has the interval [0.842, 0.938], which excludes 0.80 and not 0.95.

H3 and H4 are carried by the addressable set rather than the article sample, and take the
gates below instead of a power calculation: their mismatch counts cannot be estimated before
H1 is measured.

## Sample size rationale

Stated above; 60 is the largest sample whose per-article manifests one person can write inside
the study window.

## Starting and stopping rules

Collection stops when all 60 sampled articles are scored; no interim analysis is run and no
article is added after the first `repro verify`.

## Manipulated variables

N/A — observational.

## Measured variables

Per value: addressability (`addressable`, `present_unaddressable`, `absent`, `unretrievable`),
artifact format, value class (`primary`, `derived`), and for addressable values the `repro`
outcome and reason.

## Measured variables - File upload

N/A — the coding scheme is stated above.

## Indices

Coverage rate = articles with at least one addressable value ÷ 60; agreement rate = `verified`
÷ (`verified` + `mismatch`) over addressable values.

## Indices - File upload

N/A — both indices are two counts and a division.

## Statistical models

N/A — the estimands are proportions, reported with 95% Wilson intervals.

## Statistical models - File upload

N/A — no model is fitted.

## Transformations

N/A — counts and proportions are analyzed as collected.

## Inference criteria

| hypothesis | holds when |
|---|---|
| H1 | coverage < 0.25, upper Wilson bound < 0.40 |
| H2 | agreement ≥ 0.90, lower Wilson bound ≥ 0.80 |
| H3 | derived mismatch rate ≥ 2 × primary, ≥ 5 mismatches in each class |
| H4 | table artifacts ≥ 2 × structured-file artifacts |
| H5 | addressability < 0.50 among articles with a retrievable result file |

**All hypotheses are void if fewer than 40 of the 60 sampled articles yield a retrievable
repository snapshot.** **H2 is void if fewer than 50 values are addressable.** **H3 is void if
fewer than 15 mismatches are observed.** **H4 is void if fewer than 20 articles contribute an
addressable value.**

A `not_found` outcome on a value scored addressable means the pointer was written wrong. Each
is re-adjudicated once under the name-only rule; a pointer that still fails is recoded
`present_unaddressable`, leaves the H2 denominator, and is reported as a count.

## Data inclusion and exclusion

Editorials and letters are out of frame. Within an article, values quoted from the paper being
reproduced, sample sizes in Methods, and figure axis labels are out of scope: the assertion
concerns the reproduction's own numbers.

## Missing data

An unretrievable repository is a scored outcome rather than a missing value, and a sampled
article is never replaced.

## Other planned analysis

Rates grouped by domain, language, and publication year are exploratory and labeled so.

## Context and additional information

| finding | how it is reported |
|---|---|
| no addressable artifact | named; release is an open choice |
| artifact present, value unaddressable | named; format is a documentation fact |
| printed value disagrees with the stored value | aggregate until authors are contacted |

**No article is named in connection with a mismatch before its authors have been sent the
manifest, the pointer, and the stored value, and given 30 days to reply.** An author who
identifies the pointer as wrong closes the finding; correspondence is reported as counts,
never quoted.

---

## Log

Append only. Never edit above the line.

The last column is what distinguishes an amendment from a deviation, so you do not have to
decide which word to use: `nothing run`, `no results seen`, `results not opened`, `results seen`.

```
2026-08-24  created                              nothing run
```
