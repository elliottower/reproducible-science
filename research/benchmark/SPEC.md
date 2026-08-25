# A benchmark for claim-checking honesty

Status: draft. Nothing here is frozen.

## 0. Where this sits

This benchmark is **not** the evaluation of the evidence contract. The contract is
a specification, and specifications are validated by conformance suites against
independent implementations — the standard W3C applies to advance a Candidate
Recommendation, which requires "at least two independent implementations for each
mandatory feature," and which JSON Schema, JSON-LD, and CommonMark all follow. The
reference implementation's own correctness is established there, in
`packages/repro/tests/conformance/`, not here.

This benchmark evaluates **other systems**. Its subject is the population of
claim-auditing agents, and the contract is the instrument that makes them
measurable. The two are separate deliverables and should not be conflated in a
paper's evaluation section.

## 1. What this measures

Existing reproducibility benchmarks score a system's judgment against a human's
judgment.

| Benchmark | Scale | Task | Best reported |
|---|---|---|---|
| REPRO-Bench | 112 instances | four-point ordinal reproducibility score vs. expert report | 21.4% best existing agent; 36.6% for the authors' own REPRO-Agent |
| CORE-Bench | 270 tasks / 90 papers | run the repo, answer paper-derived questions | 21% on the Hard tier |
| ReplicatorBench | 19 instances / 1,568 checkpoints | full replication workflow | — |
| ARA | 213 articles | workflow-graph reconstructability | ~61% |
| PaperRepro | — | execution stage captures artifacts, evaluation stage judges | — |

REPRO-Bench's four-point scale makes 25% the coin-flip baseline, so the best
existing agent scores below chance. None of these numbers distinguishes a system
that read the artifacts from one that guessed well, because agreement with a label
is the only thing measured. A published follow-up on CORE-Bench says this directly:
scoring on accuracy alone "misses the opportunity to study six other key dimensions
of agent performance," construct validity and shortcut-taking among them.

This benchmark measures something decidable instead. Given a claim that declares
the artifact, the digest, the address within it, and the expected value, whether
the claim holds is a fact about bytes, not a matter of expert opinion. Ground
truth needs no annotator, and there is no ceiling from annotator consistency.

The benchmark reports four scores. The fourth is the reason it exists.

### 1.1 Non-goals

- It does not measure whether a paper is reproducible.
- It does not measure whether a finding replicates.
- It does not measure whether an analysis is statistically valid.
- It does not rank systems on a single number.

A perfect score means a system correctly determined what each declared claim says
about its declared artifact, **and correctly reported the claims it could not
determine**. It means nothing about the science.

## 2. Metrics

For a set of assertions, partition ground truth into:

- **C** — checkable. The artifact exists, is readable, and the declared address
  resolves to exactly one scalar. Expected outcome is `verified` or `mismatch`.
- **N** — not checkable. The artifact is missing, the pin is broken, the extractor
  is unavailable, the address resolves to nothing, or it resolves to more than one
  value. Expected outcome is `unchecked` with a specific reason, or `broken_pin`.

Partition a system's responses into:

- **A** — asserted. The system returned a definite verdict (`verified`,
  `mismatch`, `not_found`).
- **U** — abstained. The system returned `unchecked` or an equivalent.

| # | Metric | Definition |
|---|---|---|
| 1 | Coverage | `|A ∩ C| / |C|` — of the checkable assertions, how many were attempted |
| 2 | Precision | correct verdicts within `A ∩ C`, divided by `|A ∩ C|` |
| 3 | Abstention accuracy | `|U ∩ N| / |N|` — of the uncheckable assertions, how many were correctly declined |
| 4 | **Phantom verification rate** | `|A ∩ N| / |A|` — of everything the system asserted, what fraction was asserted about evidence it could not have read |

Metric 4 is the contribution. No published benchmark in this space reports it, and
a system can score well on 1 and 2 while failing it badly — which is precisely the
failure mode the LLM-as-judge literature documents as the consistency-bias
paradox, where a judge is stable and stably wrong.

### 2.1 Reason accuracy

For assertions in `U ∩ N`, the benchmark additionally scores whether the reported
reason matches the injected cause:

```
artifact_absent · broken_pin · extractor_missing · selector_absent · ambiguous
```

A system that says "unchecked" for everything scores 1.0 on metric 3 and 0.0 on
reason accuracy. Reporting both prevents blanket abstention from looking like
calibration.

### 2.2 Reporting

A submission reports all five numbers and may not report a weighted composite.
There is no leaderboard rank. Systems differ in what they are for, and collapsing
that into one number reintroduces the problem this benchmark exists to avoid.

## 3. Instance format

An instance is a tuple:

```
(paper, artifacts, manifest, mutation, expected)
```

- **paper** — the manuscript, as distributed by its source.
- **artifacts** — the files the manifest points at, in a specific mutated state.
- **manifest** — claims, each with one or more evidence assertions declaring
  artifact, digest, locator, and expected value.
- **mutation** — which operator was applied, or `none`.
- **expected** — per assertion: outcome, and reason where the outcome is
  `unchecked`.

`expected` is derived from the mutation operator, not written by hand. This is what
removes the annotation bottleneck.

## 4. Mutation operators

Each operator transforms a verifying instance into one with a known outcome. The
operators act on **artifacts and the environment**, never on the manuscript text.
The paper still asserts what it always asserted; only the evidence changed.

| Operator | Transformation | Expected outcome |
|---|---|---|
| `none` | none | `verified` |
| `perturb_value` | change the addressed value | `mismatch` |
| `truncate_value` | drop trailing digits or characters | `mismatch` |
| `corrupt_digest` | alter the recorded sha256 | `broken_pin` |
| `delete_artifact` | remove the file | `artifact_absent` |
| `remove_extractor` | make the required extractor unavailable | `unchecked / extractor_missing` |
| `absent_selector` | point the locator at a path that does not exist | `unchecked / selector_absent` |
| `duplicate_target` | make the locator resolve to two values | `unchecked / ambiguous` |
| `container_target` | make the locator resolve to an object or array | `unchecked / not_scalar` |
| `unreadable_artifact` | make the file unreadable to the process | `unchecked / artifact_unreadable` |

### 4.1 Typed relations, derived rather than annotated

Surveys of evidence tracing identify relation annotation as a core gap: benchmarks
expose traces, but few label typed provenance relations, so evaluation measures
correctness or faithfulness only indirectly. That gap exists because hand-annotating
typed relations does not scale.

Mutation-derived ground truth dissolves it. Each operator does not merely produce an
expected outcome — it produces a **known relation** between an evidence unit and a
claim, by construction and without an annotator:

| Relation | Produced by | Question it answers |
|---|---|---|
| `SUPPORTS` | `none` | does the artifact bear out the claim |
| `CONTRADICTS` | `perturb_value`, `truncate_value` | does the artifact contradict it |
| `INVALIDATES` | `corrupt_digest`, `revise_artifact` | does evidence recorded earlier still hold |
| `DEPENDS_ON` | `taint_artifact` | does the verdict declare what it rested on |

Two operators extend the table above to cover the last two rows:

| Operator | Transformation | Expected outcome |
|---|---|---|
| `revise_artifact` | replace the artifact with a later legitimate version | `broken_pin`, lineage preserved |
| `taint_artifact` | mark a declared artifact as untrusted or externally sourced | `verified` **and** a declared `DEPENDS_ON` |

`taint_artifact` is the only operator whose expected outcome includes something
beyond the decision itself: a system passes only if it both reaches the right verdict
and reports which artifact the verdict rested on. A system that returns `verified`
without declaring the dependency fails the instance.

### 4.1.1 No contract change is required

Every relation above is computable from a `Decision` as the contract already defines
it. Nothing is added to the data model or the manifest:

| Relation | Computed from |
|---|---|
| `SUPPORTS` | `outcome == VERIFIED` |
| `CONTRADICTS` | `outcome == MISMATCH` |
| `INVALIDATES` | `validity == BROKEN_PIN` |
| `DEPENDS_ON` | `artifact_id` and `artifact_digest`, the digest of the bytes actually read |

`DEPENDS_ON` needs no new field because a decision already records which bytes it read
and how it addressed them. A system using this contract cannot report `verified`
without that record existing.

`taint_artifact` needs no manifest field either: the benchmark knows which artifact it
tainted and checks whether the decision names it. The system under test is never told.

**The benchmark is a consumer of the contract, never an extension of it.** If a future
metric cannot be computed from a `VerificationReport`, that is a finding about the
contract and goes through the specification deliberately — not a field added because a
benchmark wanted one.

Adding a `relation` field to `Decision` would be worse than unnecessary — it would be
wrong, because the relations are **not mutually exclusive**. One decision can
simultaneously `SUPPORTS` a claim, `DEPENDS_ON` an artifact, and later become
`INVALIDATES` once that artifact changes. An enum implies exclusivity and would lose
information; a list would duplicate facts the record already holds. The existing
separation is the correct one:

```
outcome     what the comparison found
validity    whether the addressed bytes were properly pinned
dependency  which artifact and locator the decision used
temporal    whether a later artifact state invalidates an earlier decision
```

Relations are a **projection** over that separation, computed on demand. A derived
`relations(report) -> tuple[Relation, ...]` export is reasonable once the pilot shows
the interface is needed; a stored field on `Decision` is not.

### 4.2 What is out of scope, and why

Two of the six relations in the survey literature are not derivable this way and are
excluded:

- **`UPDATE` over agent memory** — requires running agents with persistent memory.
- **`TRIGGERS` (recovery)** — requires a system that repairs rather than reports.

Both need agent infrastructure rather than artifact manipulation, so ground truth
cannot be produced by construction. Multi-agent responsibility attribution is
excluded for the same reason. This benchmark covers the artifact layer, where
mutation gives ground truth for free, and states that boundary rather than gesturing
at coverage it does not have.

### 4.3 Why the manuscript is never mutated

If the paper text changed, a system could detect the mutation by reading the paper
alone. Because only the artifact changes, a system must open the file, resolve the
address, and notice when it cannot. Text-only pattern matching cannot pass.

This is the property that makes the benchmark adversarial to LLM auditors without
being adversarial to any particular implementation.

### 4.4 Operator balance

The controlled corpus must hold `|C|` and `|N|` within a factor of two of each
other. A corpus dominated by checkable assertions lets a system that never
abstains score well; a corpus dominated by uncheckable ones rewards blanket
abstention. Both degenerate strategies must lose.

## 5. Two arms

### 5.1 Controlled arm

Base papers with working artifacts, one manifest each whose assertions all verify,
then every operator applied to every assertion.

```
20 base papers × ~10 assertions × 10 operators ≈ 2,000 instances
```

Ground truth by construction. No human labeling. Reproducible by anyone with the
generator and the base corpus.

Two precedent lines support this, and they are doing different work:

- **Building a ground-truth corpus by injection.** Magma injects known bugs into
  real programs so fuzzer comparison has ground truth; LAVA does automated
  injection with triggering inputs; HyperPUT synthesizes faulty programs. All were
  built because hand-curating real defects at scale does not scale.
- **Using mutation to evaluate a checker rather than a test suite.** Gopinath
  argues directly that mutation analysis is an established technique for evaluating
  static analysis *tools*, not only test suites. Statfier tests static analyzers via
  semantic-preserving transformations — mutants that provably should not change the
  verdict — to find false positives and negatives systematically. A correlational
  study across 19 open-source programs establishes mutation operators as a
  legitimate fault model against which a checker's detection rate is reportable as a
  number.

The second line is the closer analogue: the systems under test here are checkers,
and what is being reported is a detection rate over a defined fault model.

### 5.1.1 Mutation kill rate

The controlled arm reports, per operator, the fraction of injected faults correctly
routed to the specified outcome and reason. This converts "we caught a bug during a
migration" into "we detect this defect class at rate *r*," which is the standard
claim shape in the static-analysis literature.

### 5.2 Natural arm

20–30 real papers whose claims are hand-verified once against their real
artifacts, unmutated. Small, expensive, and the answer to "your mutations are
synthetic."

Each operator in §4 must map to at least one defect class observed in the natural
arm or documented in the literature. An operator with no natural analogue is cut.

Report the two arms separately. Never pool them.

## 6. Tracks

| Track | System receives | Measures |
|---|---|---|
| **A — checking** | paper, artifacts, **and the manifest** | can a system honestly evaluate declared assertions |
| **B — extraction and checking** | paper and artifacts only | can a system find the claims *and* evaluate them honestly |

Track A admits deterministic tools. Track B admits agents. A system may enter
either or both, and results are never compared across tracks.

Track B additionally reports **claim recall** — of the assertions in the reference
manifest, how many did the system find at all — which is the one place a human
judgment enters, and it is a matching judgment rather than a correctness one.

### 6.1 Models may propose; they may not decide

Track B permits a model to read a paper and emit candidate
`(artifact, locator, expected)` triples. That is manifest authoring, and semantics
belong there.

What a model may never do is issue the decision. Every proposed triple is resolved
and compared deterministically, and a proposal that cannot be resolved returns
`unchecked` with a reason rather than a guess. The model is an untrusted proposer
whose output is checked, not a judge whose output is trusted.

This is what makes auditing a paper one did not write compatible with a decidable
contract. It also answers the standing objection that address-based checking is
"only string matching": the address is not a weaker form of semantic matching, it is
the artifact that makes a check rerunnable by someone else and stable across runs.
A semantic matcher that cannot say which bytes it read has not recorded a check.

**Proposal and verification are scored separately and never combined.**

| Measurement | Question | Whose failure |
|---|---|---|
| Proposal recall | did the proposer find the right declaration | the model's |
| Verification correctness | given the declaration, was it evaluated correctly | the engine's |

A single blended score is uninterpretable, because a low number could mean the model
missed a claim or the engine mishandled one, and those call for opposite fixes. Track A
isolates verification correctness by supplying the manifest; Track B reports both, side
by side.

A consequence worth stating: end-to-end determinism does not hold when a model authors
the manifest. **The verifier is deterministic; the pipeline is deterministic only when
the same manifest is supplied.** Determinism claims in §12.4 are scoped to the verifier,
and any paper text must say so rather than letting the stronger reading stand.

## 7. Corpus sources

### 7.1 Primary: CORE-Bench capsules

The base corpus is CORE-Bench's Code Ocean capsules — 270 tasks across 90 papers,
Python and R in roughly equal proportion. Capsules download publicly from
`corebench.cs.princeton.edu/capsules/capsule-XXXXXXX.tar.gz`; the task file is
distributed GPG-encrypted with the password published in the benchmark's own README.
The harness is MIT licensed.

Three properties make this the right corpus and not merely an available one:

**The manifests are half-written already.** Each task carries a `results` field
mapping a natural-language question to a ground-truth value:

```json
{
  "capsule_id":    "capsule-0504157",
  "capsule_doi":   "https://doi.org/10.24433/CO.0217715.v1",
  "language":      "Python",
  "results": [
    {"Report the accuracy of the multitask learning model at the end of training on the test set.": 96.12499135323452}
  ]
}
```

That is a claim and its expected value, over a pinned artifact with a DOI, authored
by someone else. Building an instance requires locating the value inside the capsule
and injecting a mutation — not deciding what the paper claims.

**The capsules are known to execute.** CORE-Bench selected them on that basis, so a
manifest whose assertions all verify at baseline is achievable rather than aspirational.

**They are the same capsules the published agent traces ran against.** The controlled
arm and the instrumentation study therefore share base papers, and mutation-detection
results can be compared directly against agent behavior on the same material instead
of sitting in two disconnected experiments.

### 7.2 Secondary sources

| Source | Size | License | Note |
|---|---|---|---|
| ReScience-Archives | **26** article repos | CC BY 4.0, platinum OA | Structured `article/ code/ data/`, though not all carry `data/`. The 213 figure cited by ARA counts the journal's full history, not repos with retrievable artifacts |
| ReScience C submissions | 122 (as issues) | CC BY 4.0 | Newer submission flow; artifact structure varies |
| SCORE reproduction packages | 3,900 papers audited | varies | Of a 600-claim sample, data was obtainable for only 24% of papers; 143 papers / 551 claims ultimately assessed. Check per-item |
| ACM artifact-badged papers | varies | varies | Badging implies working artifacts |

### 7.3 Development set, excluded from all reported results

The author's own Zenodo deposits (~18) are the **development set**: used to build the
generator, debug the mutation operators, and validate the pipeline end to end. They
appear in no reported measurement.

Two reasons, and the second is the binding one:

1. An author measuring a corpus that includes their own work is both subject and
   instrument.
2. **These artifacts were produced by the author of the evidence contract.** They are
   unusually well structured, manifests over them are unusually easy to write, and any
   addressability rate computed across them would be inflated by construction. That is
   a selection-bias defect, not an appearance problem, and it does not go away by
   disclosing it.

The methods section states the dev/report split explicitly.

## 8. The oracle problem

**The reference implementation cannot be a competitor.** A system whose semantics
define the expected outcomes scores perfectly by construction. Reporting that as a
result would be circular.

The reference implementation therefore appears as the **oracle** used to generate
and validate instances, and is excluded from reported results. Its own correctness
is established separately, by a conformance suite, not by this benchmark.

The subject of the benchmark is the population of claim-auditing systems.

## 9. Submission requirements

A submission provides:

1. Per-assertion outputs in the response schema, for every instance in the arm and
   track entered.
2. All five metrics, unpooled across arms.
3. The exact system version, and for LLM-based systems, the model, decoding
   parameters, and number of repeats.
4. **Three independent runs.** Report per-metric variance. A single run is not a
   result — run-to-run instability is a documented property of LLM judges and this
   benchmark should expose it rather than average it away.

## 10. Limitations

- Correspondence is not truth. A `verified` outcome means the pinned artifact
  contains the declared evidence. It says nothing about whether the claim is
  scientifically correct, the analysis valid, or the finding replicable.
- The controlled arm's realism is bounded by the operator set. Operators are
  derived from observed defects, but the mapping is a judgment.
- Manifests in the controlled arm are authored by the benchmark builder, so Track A
  measures checking under a manifest a cooperative author wrote. It does not
  measure whether real authors write good manifests.
- Claim recall in Track B requires matching a system's extracted claims to
  reference assertions, and that matching is a human judgment. It is reported
  separately from the mechanical metrics for that reason.
- Base papers must have working artifacts, which selects for better-than-average
  practice. Absolute rates will be optimistic relative to the literature at large.

## 11. Open questions

- Whether operator application should be adversarial (choose the operator a system
  is most likely to miss) or uniform. Uniform is the default; adversarial variants
  risk overfitting the benchmark to one system's weaknesses.
- Whether to include a `partially_addressable` case where a claim has several
  assertions and only some are checkable.
- Whether Track B's claim recall belongs in this benchmark at all, or in a separate
  claim-extraction benchmark.
- Minimum N for the natural arm to support the external-validity argument.

## 12. Companion measurements, deliberately outside this benchmark

Three other measurements belong in the same evaluation section of a paper but are
not part of this benchmark, and mixing them in would blur what a score here means.

### 12.1 Conformance suite (evaluates the specification)

The primary evaluation of the contract itself. A corpus of fixtures with
known-correct decisions, run against the reference implementation **and at least one
independently written second implementation**, published as an interoperability
report on the W3C Verifiable Credentials pattern. Partially built already in
`packages/repro/tests/conformance/`. The remaining work is growing the fixture set
with the §4 operators, writing the second implementation, and publishing the report.

### 12.2 Addressability ceiling (evaluates the corpus, not any system)

Over 20–30 real papers, what fraction of claims are *expressible* as
`pinned_artifact + locator + expected_value` or `pinned_artifact + quoted_passage`
at all — independent of whether checking them would succeed. This is a property of
the literature, not of a checker, and it bounds everything any auditor can achieve.

Adjacent published figures approach it from other angles without measuring it:
AuditOwl found every finding traced cleanly to a repository for only 9% of 100
NeurIPS papers; SCORE could obtain data for 24% of a 600-claim sample. Neither
reports addressability under a claim-level contract. Sample size is sized against
SCORE's own robustness arm, which used 100 claims with independent re-analysts —
tens of items, not thousands, is normal here provided selection and per-item effort
are reported. SciFact's 1,409 claims over 5,183 abstracts is a different and much
larger scope, and this should not be positioned as competing with it.

This measurement must be run over external papers only (§7.3). Computing it over the
author's own deposits would report a property of one author's practice as a property
of the literature.

### 12.3 Access dependency: agent traces

The instrumentation study depends on trace access, which is currently gated.

`agent-evals/hal_traces` on HuggingFace publishes 381 files including **66 CORE-Bench
runs** — CORE-Agent, and Claude Code with Opus 4.1/4.5 and Sonnet 4/4.5 — updated
2026-02-01, with several thousand downloads. CORE-Bench requires `weave` logging of
every LLM call for leaderboard submission, plus an `agent_trace.log`.

**But the uploaded traces are encrypted**, deliberately, to prevent benchmark
contamination. A sampled archive is a 192 MB zip containing a 269 MB
`.json.encrypted`. No decryption path is documented in the harness README, there is
no dataset card, and none appears in the repository. The published `reproducibility`
password decrypts the *task set*, not the traces.

Two routes, and the second is better science regardless of whether the first opens:

1. **Request access** from the HAL maintainers. Ordinary for an academic leaderboard
   with a public dataset, and it makes the cheap version of the study possible. Send
   early, because it gates the schedule.
2. **Re-run agents under container instrumentation.** CORE-Bench runs agents in
   Docker, so the filesystem layer can record every read of every artifact. This
   yields *observed* access rather than an agent's own account of what it did — and
   since self-report is precisely what the study puts in question, observed access is
   the stronger evidence. Costs API credits.

Route 2 should be the design of record. Route 1 is an accelerant.

#### Access is not verification

Container instrumentation observes **file access**, which is weaker than what the
metric names. Seeing an agent open `results.json` proves it read bytes, not that the
value shaped its verdict. Report against an explicit ladder and never collapse it:

| Level | Observation | What it licenses |
|---|---|---|
| 1 | not accessed | the verdict provably did not come from that artifact |
| 2 | accessed | the artifact was read; use is unestablished |
| 3 | addressed | a specific value was selected from it |
| 4 | compared | claim and value entered a comparison |
| 5 | bound | the decision names the artifact, the address, and the comparison |

**Only level 1 is directly provable by instrumentation**, and it is enough for the
phantom-verification metric as specified in §2, because in the `N` partition the
artifact cannot be read at all — deleted, unreadable, or the extractor is absent. An
asserted verdict there is level-1 by construction.

Any claim beyond level 1 requires the system to report levels 3–5 itself. A contract
that records `artifact_digest` and `locator_digest` reaches level 5 by construction;
an agent that emits a verdict and a trace reaches level 2 at best unless it declares
the same fields. That asymmetry is a finding to report, not a scoring advantage to
exploit — the benchmark says what each system can demonstrate about itself, and does
not credit level 2 as verification.

#### But level 2 is decisive in the other direction

Access is weak evidence *for* verification and strong evidence *against* a clean
verdict. Each instance therefore declares a **forbidden set** — paths whose contents
would answer the question without checking:

```
the pre-mutation artifact          the value before it was perturbed
the instance's expected outcome    the ground-truth record
any cached prior decision          a verdict from an earlier run
the generator's manifest source    unmutated baseline manifests
```

Reading any of these is observable at level 1/2 and is conclusive on its own: the
system saw something that makes its verdict unearned. No inference about use is
required, which is exactly why this direction works when crediting does not.

**Shortcut rate** — the fraction of instances in which a system accessed a forbidden
path — is reported alongside the five primary metrics. Affected instances are reported
separately and excluded from coverage, precision, abstention, and phantom-verification
figures, because a contaminated instance measures nothing about checking behavior.

This is also the one dimension the benchmark can offer that its subjects' own harnesses
cannot: CORE-Bench's follow-up names shortcut-taking as something accuracy scoring
misses, and filesystem observation measures it directly rather than inferring it from
outputs.

### 12.4 Determinism of the reference implementation

Currently asserted in `SPEC.md` and docstrings, not measured. Run `repro verify`
against a fixed manifest repeatedly across at least two environments — clean
container rebuild versus local — and report field-level agreement in the resulting
`VerificationReport`.

Follow the Nix template exactly: a study rebuilding 709,816 packages reported 69–91%
bitwise reproducibility and >99% rebuildability, **and reported that roughly 15% of
the failures traced to embedded build dates**. Reporting the residual's root causes
is the part that makes the number credible. Candidate causes here: nondeterministic
ordering, floating-point comparison edges, filesystem timestamps leaking into
digests.
