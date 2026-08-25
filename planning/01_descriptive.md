# 1. Descriptive — what fraction of published numbers are addressable

## Claim

Under a frozen locator grammar, a measurable and low fraction of the numbers printed in
published articles can be named at a position in a released artifact.

## Status

**This is already designed and preregistered.** `experiments/addressability-sample/`
holds `PREREG.md`, `CODEBOOK.md`, a frozen `frame.json`, a vendored `published.bib`, and
`select_sample.py`. It has been through one external review round. Every log line reads
`nothing run`.

Do not restate it here. This file records only what surrounds it.

```
frame   ReScience C, 215 research articles, 60 drawn by sha256(seed||doi), seed 20260824
H1      mean article coverage < 0.25
H2      agreement >= 0.90                      the outcome that strengthens the articles
H3      addressability < 0.50 among articles with a retrievable machine-readable
        result file                            "H3 carries the design"
H4      table-primary vs structured-primary
```

## What remains before it can freeze

- `results/` and `tests/` are empty. The coding harness that turns `CODEBOOK.md` into
  executed measurement does not exist yet.
- The second coder for the 12-article reliability subset is unidentified.
- Status line still reads `DRAFT — not frozen`.

## H1's detectable range, computed

The stated +/-0.10 half-width implies SE ~ 0.051, so the one-sided 95% upper bound sits
0.084 above the point estimate. H1's criterion — upper bound below 0.25 — is therefore met
only when the observed mean coverage is below **0.166**.

| observed mean | upper bound | target < 0.25 | criterion met |
|---|---|---|---|
| 0.10 | 0.184 | yes | yes |
| 0.15 | 0.234 | yes | yes |
| 0.20 | 0.284 | yes | **no** |
| 0.22 | 0.304 | yes | **no** |
| 0.25 | 0.334 | no | no |

**The dead zone is 0.166 to 0.250** — a third of the plausible range, where H1 is reported
unsupported while being true. H3's criterion is roomier and passes below 0.416, so the
problem is specific to H1.

Three responses, and only the third is available at n = 60:

1. Raise H1's threshold. Makes the criterion reachable and the claim weaker.
2. Grow the sample. Halving the interval needs roughly 240 articles, and the
   preregistration already states 60 is the most one person can code in the window.
3. **State the detectable range in the preregistration before the data.** The criterion
   stays, the dead zone is named, and an unsupported H1 in that band is read as a precision
   statement rather than as evidence coverage is high.

Option 3 is a paragraph in the sample-size section. It does not improve power; it stops the
result being misread, which is what a registration is for.

## The objection most likely to kill it

**"Your rate measures your grammar, not the literature."**

The preregistration already concedes this by construction — addressability is defined
against a digest-pinned grammar. The paper must carry the concession into the framing,
not bury it in methods. A reader who discovers the relativity themselves will treat the
headline as overclaimed; a reader told up front will read the number as what it is.

The strongest form of the reply: the grammar covers JSON Pointer, delimited tables,
SQLite, and arrays. An artifact unreachable by all four is not withholding its numbers
behind an exotic format — it is failing to name them at all. That reply is available only
if the grammar's coverage is stated plainly, so it belongs in the paper.

## Second objection

**ReScience C is a purposive, reproducibility-oriented population.** The preregistration
handles this correctly — low addressability in a favorable setting establishes a problem
without bounding other genres, and it explicitly claims no such bound.

The temptation to resist is generalizing anyway in the discussion. The CORE-Bench pilot
suggests the rate is worse elsewhere, and that suggestion must stay in position 2 or in a
registered sensitivity analysis, not leak into this paper's conclusions.

## Relationship to tonight's CORE-Bench findings

The pilot measured a different frame: 58.2% of CORE-Bench questions are figure-reading,
and the numeric remainder sits in stdout as a 21x3 table with no names. That is an
addressability observation on a non-ReScience population.

It attaches as **a registered sensitivity analysis**, not as evidence for H1 — "does the
rate replicate outside a reproducibility-oriented journal" is precisely the question this
preregistration declines to answer.

## Venue

Meta-Psychology, AMPPS, or Royal Society Open Science. MetaArXiv preprint on freeze.

## Next actions

1. Build the coding harness against `CODEBOOK.md`.
2. Identify the second coder.
3. Freeze with `prereg freeze`; record the digest.
4. Run. Nothing before step 3.
