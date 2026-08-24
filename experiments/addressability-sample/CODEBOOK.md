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
