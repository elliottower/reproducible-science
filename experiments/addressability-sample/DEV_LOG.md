# Development log

Bugs found building the harness, before the registration is frozen and before any value is
coded. Recorded because two of them would have produced a wrong published number rather
than a crash, and because the registration's credibility rests on the harness having been
debugged on something other than the frame it will measure.

Nothing here is a deviation. Nothing has run against the study's hypotheses.

---

## 2026-08-25 — SSL verification failure silently coded as `absent`

**Symptom.** Snapshot resolution reported 75% `absent` on a dry run, against a
preregistration stating that 42 of the 60 sampled articles carry a Software Heritage
identifier.

**Cause.** Python does not use the macOS system trust store. Every HTTPS lookup raised
`CERTIFICATE_VERIFY_FAILED`, and the fetch helper caught `URLError` and returned `None`.
The resolver read `None` as "this identifier does not resolve" and fell through to
`retrieval_status: absent`.

**Why it matters more than an ordinary bug.** An infrastructure failure was being recorded
as a scientific outcome — the exact confusion this study exists to measure in other
people's work, committed by the study's own instrument. Forty articles with resolvable
snapshots would have been published as having none, and the run would have completed
successfully with no error to notice.

**Fix.** Two parts, and the second matters more than the first:

1. Supply the CA bundle explicitly via `certifi`, pinned in `requirements.txt`. The trust
   store becomes a declared dependency rather than a property of the machine, so the
   retrieval rate is a fact about the literature rather than about the operating system
   that ran the script.
2. Separate the outcomes. `get_json` now returns `None` only for an honest 404 and raises
   `Unreachable` for anything else. `resolve()` records `retrieval_status: unreachable` and
   **stops**, rather than falling through to a lower tier — a lower tier answering after a
   higher one failed for infrastructure reasons would silently downgrade the snapshot and
   record the downgrade as the article's best available evidence.

## 2026-08-25 — SWHID qualifiers rejected with HTTP 400

**Symptom.** After the fix above, 58 of 60 resolved and two returned `unreachable`
(`Teule:2021`, `Kirca:2022`) with HTTP 400.

**Cause.** Both identifiers carry a trailing `;`. A SWHID may append qualifiers
(`;origin=`, `;visit=`, `;anchor=`) after a semicolon, and the bibliography parser captured
the delimiter. The resolve endpoint rejects the qualified form.

**Why the distinction held.** 400 is a malformed request and 404 is a missing snapshot.
Because the previous fix separated them, these two surfaced as `unreachable` rather than
being absorbed into `absent`, which is what made them findable at all.

**Fix.** Resolve the core identifier — everything before the first `;` — per the SWHID
specification. Both then resolve at tier 1.

## Not a bug: SWHIDs are not truncated

Recorded because it cost time. A debug print sliced identifiers to 44 characters, which is
exactly `swh:1:dir:` plus 34 hex, and the display truncation was diagnosed as data
corruption. The bibliography, `select_sample.py`, and `frame.json` all carry the full 40
hex characters, and all three digests match the value stated in the registration.

---

## Where the harness is developed

`CODEBOOK.md` §7 prohibits searching an artifact for a printed numeric string, and the
harness has to enforce that rather than rely on the coder respecting it. Enforcement has to
be exercised against something.

**Development uses articles outside the 60.** The frame holds 215 research entries and the
sample takes 60; the remaining 155 are available and are not measured. Any article used to
build or test the harness is recorded here before it is used, so the exclusion is visible
rather than asserted.

Articles used for development so far: none. Resolution was exercised against the sampled
60 directly, which is admissible because it retrieves identifiers without opening an
artifact or coding a value — no hypothesis is touched by knowing which tier answered.

---

## 2026-08-25 — Enumeration pilot, ten articles outside the sample

**Problem.** `CODEBOOK.md` §§1–2 require enumerating every eligible value from each article
before any artifact is opened. At roughly 40–80 candidates per article across 60 articles
that is the largest single cost in the study, and it is not affordable by hand for one
person.

**Design under test.** Split the task, because only half of it is judgment:

- **Extraction** — what number is printed, verbatim, where. Checkable: if a coder reports
  `0.9489` in §4.1, a string match confirms it. A model may propose; code verifies.
- **Eligibility** — is this the authors' own result or a value quoted from the work being
  reproduced? Genuinely evaluative and not settleable by string match. Three independent
  coders, agreement reported per article, disagreements adjudicated against the codebook.

This is the same boundary the project applies everywhere else: models propose, deterministic
code verifies, and the evaluative residue is where multiple coders and reported agreement
earn their place.

**Why not on the sampled 60.** The registration's stopping rule is that collection ends when
all 60 are coded; coding a subset is a deviation, and an article once opened cannot be
returned to the frame. The pilot therefore runs on ten articles drawn from the 155 outside
the sample.

**Pilot set** (all outside the sample, table counts from `pdftotext -layout`):

```
Obadage:2025     14 tables      Broman:2020       4 tables
Moalla:2023       8 tables      Livernoche:2023   4 tables
Boraud:2021       6 tables      Wallrich:2022     2 tables
Kim:2021          5 tables      Eglen:2021        1 table
                                Moens:2023        0 tables
```

`Moens:2023` is included deliberately as the degenerate case: it has no tables and reports
every result as a figure, so it tests whether coders correctly return near-nothing rather
than manufacturing candidates out of scattered axis ticks.

**What the pilot measures.** Inter-coder agreement on eligibility; wall-clock and token cost
per article; and whether the codebook's categories survive contact with real articles. It
does not estimate any registered quantity.

---

## 2026-08-25 — Classifier bugs found on the nine development articles

Each was found by reading the classified output rather than the counts. Five of the seven
moved numbers between the traceable and untraceable groups, so each would have changed a
published rate rather than raising an error. Categories are documented in `CATEGORIES.md`.

**Running-header detection deleted table rows.** Blanking a line's digits to find the page
template collapses every numeric row of a table onto one normalised form. The form then
repeats once per row, clears the threshold, and the table is coded as page furniture. In
`Obadage:2025` this took 208 of 300 `structural`, including the whole of Table 4. Fixed by
requiring twelve alphabetic characters before a repeating line counts as a header, which no
numeric row has.

**And missed the real headers.** `ReScience C 7.2 (#8) – Kim et al. 2021` normalised
differently on each page, because the footer sets its page number in a fixed column and the
padding before it changes as the number changes width. Fixed by collapsing whitespace runs
along with digits.

**Table rows discarded as figure content.** In `Obadage:2025` a block of Table 5 sits
eighteen lines below its own caption and five lines above the caption of Figure 2. Choosing
the nearer caption discarded the table. Fixed by preferring a table caption anywhere in the
window; the errors are not symmetric, since reading tick labels as cells costs a few
unmatched values and reading a table as a figure costs the paper's most checkable numbers.

**Prose read as a table.** Three consecutive sentences naming `VGG-16`, `PreAct-18`,
`DenseNet-121`, `ResNeXt-29` and `CIFAR-10` put numbers at stable offsets and cleared the
alignment test. Fixed with a word-to-number ratio: the block ran 2.0 to 3.0 words per number
and a table row runs 0.0.

**Bare prepositions read as cross-reference cues.** `resulting in 360 reproduced values`
matched `in\s*\(?$` and was coded a cross-reference to equation 360. Fixed by restricting
the cue words to those naming a document object.

**A closing bracket read as a superscript.** The rule for a subscript flattened onto the
baseline tested only for a preceding `)`, so the axis label `Accuracy (%)     40` and the
sub-figure marker `(a) 3-grouped graph` were coded `extraction_failed`. Fixed by requiring
the digit to be flush against the bracket.

**The identifier rule applied to whole lines.** A sentence citing a dataset URL and then
stating a measurement had the measurement coded bibliographic. Fixed by matching the
identifier as a span and testing whether the number falls inside it.

**Numbers inside display equations had no category.** They were reaching `measurement` or
`extraction_failed` depending on how badly the surrounding math survived extraction. A
display equation is recognised by its label — a bare `(N)` closing a line — and the body is
the run of lines above it carrying a relation or a math symbol. What the equation asserts is
traceable; the label naming it is not. The two are separated where they can be, and where
the equation itself ends in a parenthesised number the two are indistinguishable and the
value stays with the equation.

### Effect on the nine

| | before | after |
|---|---:|---:|
| traceable | 25% | 63% |
| untraceable | — | 24% |
| reported separately | — | 13% |

The largest single movement is `table_cell`, which did not exist before: 2,565 of 6,139
tokens. `Kim:2021` alone holds 1,325 of them, and every one was previously in a bucket
labelled "a flattened figure or a table row" that no downstream stage could act on.
