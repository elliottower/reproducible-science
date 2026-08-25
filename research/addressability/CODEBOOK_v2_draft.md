# Codebook — v2 draft

Not frozen. `CODEBOOK.md` (v1) is the version cited by the registration; this file records
rule refinements made during development on articles **outside the sampled 60**, each one
traceable to a specific rater disagreement.

The frame is untouched by this process. Only rules change.

---

## Changes from v1

### C1 — Bounded and approximated values are ineligible, whatever their type

**Disagreement that produced it.** `Moens:2023`, "The experiments were run on a CPU, taking
10 minutes at most per setting." Rater A excluded it as an inequality; raters B and C
included it as a runtime measurement. All three found the same and only candidate, so the
entire spread came from this one rule.

**The gap in v1.** §1 lists runtimes as eligible and separately lists inequalities as
ineligible. "10 minutes at most" is both, and v1 does not say which rule wins. Rater A
identified this unprompted and named it as the decision the whole count turned on.

**Rule.** A value is ineligible when its printed form does not state a single quantity.
This covers, without limitation:

```
comparison   p < 0.001,  < 1 ms,  > 4,  at least 30
bounding     at most 10 minutes,  up to 5%,  no more than 3
approximate  ~0.9,  approximately 12,  about 40,  roughly 2x
rounding     >99%,  <0.001
```

**Why bounds go out rather than in.** The measurement compares a printed value with a
stored one at the printed precision. A bound cannot be compared: an artifact holding 4
minutes neither agrees nor disagrees with "at most 10 minutes." Admitting bounds would
require a second comparison semantics for a small class of values, and the values it admits
are the ones the authors themselves declined to state exactly.

**Consequence.** `Moens:2023` yields **zero** eligible values, which is a permitted outcome:
an article that prints no checkable number leaves the article-level coverage denominator
and is reported separately, per PREREG §"Missing data".

### C2 — Location does not confer eligibility

**Disagreement that produced it.** Raters flagged the `Figure 6`/`Figure 7` sub-caption
group sizes (`300, 125, 75`; `350 (1x), 125 (2x), 75 (2x)`) as arguable. v1 §2 names figure
captions as a place to traverse, which a rater applying it mechanically reads as making
caption values eligible. Rater A: "a coder applying 'figure caption = eligible location'
mechanically would wrongly harvest ~13 values here."

**Rule.** §2 defines where to *look*, never what qualifies. Eligibility is decided by §1
alone. A design parameter is ineligible in a caption exactly as it is in Methods.

### C3 — Values not recoverable as a verbatim string are `extraction_failed`

**Disagreement that produced it.** Rater C noted that the Figure 1 caption arithmetic
extracts as `ξ2 (W2 ) = √442 = 4` and `ξ2 (W1 ) = √ 42 = √1610 > 4` — mathematically
mangled by pdftotext, with no clean verbatim string recoverable.

**Rule.** Where the extraction does not yield a verbatim printed string, the candidate is
coded `extraction_failed` and reported separately. It is neither eligible nor ineligible:
the article was not read at that position.

**Why it is a third outcome.** Coding a mangled extraction as ineligible records a tooling
limit as a property of the article, which is the confusion this study exists to measure.

---

## Development record

| round | articles | raters | agreement | rules changed |
|---|---|---|---|---|
| 1 | Moens:2023 | 3 | 2/3 on the single candidate; identical exclusion lists | C1, C2, C3 |
| 2 | *pending* | 3 | | |

Development articles are drawn from the 155 outside the sample and are named here before
use. Round 1: `Moens:2023`.

**Freezing rule.** The codebook freezes when a round produces no rule change. The frozen
version and its digest are recorded in the registration before any sampled article is
opened.
