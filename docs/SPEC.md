# The evidence contract, v1

Draft. The version marker exists so a manifest can say which revision it was written against.

## 0. Scope

**This specifies the verification of evidence assertions, not of scientific claims.**

An evidence assertion is a proposition about an artifact: *this passage occurs in this file*,
*this file holds this value at this location*. A verifier here establishes whether that
proposition holds against bytes with a known hash.

It does not establish that the evidence supports the sentence citing it. A source can contain
a quotation verbatim while the quotation fails to support the claim it is offered for, and a
passage can be absent while the claim is true and supported elsewhere. Entailment between
evidence and claim is the subject of the claim-verification literature (FEVER, SciFact) and is
addressed there with model-based methods. Nothing in this document produces a judgment about
it.

This is why the outcome vocabulary is `match` and `mismatch` rather than `supported` and
`refuted`. Those name a semantic relation; a byte comparison does not establish one.

## 1. Objects

| object | frozen | what it is |
|---|---|---|
| `Digest` | yes | a content address: `sha256` and 64 lowercase hex characters |
| `ArtifactRef` | yes | a file the manifest names, pinned or not |
| `Evidence` | yes | an assertion about one artifact, discriminated on `kind` |
| `Claim` | yes | a manuscript statement and the evidence offered for it |
| `Manifest` | yes | one project's artifacts and claims |
| `Decision` | yes | the outcome of evaluating one assertion |
| `VerificationReport` | yes | every decision, and the state of every artifact |
| `Assessment` | yes | a policy's verdict on a report |

Everything is frozen. A decision that can be edited after the fact records nothing, and a
manifest whose path can be reassigned resolves relative artifact paths against whichever
directory was set last.

Every `Claim` has a `digest` over its identity, text, and location. Every `Decision` names the
claim digest it evaluated, so a stored decision cannot silently remain attached to text that
has since been edited.

## 2. Artifacts and pins

`ArtifactRef` carries a `digest` or does not. The two cases are reported separately, and an
unpinned artifact is never treated as verified: no hash was recorded, so nothing about the
file is confirmed.

| state | `Validity` | meaning |
|---|---|---|
| digest matches | `authoritative` | the file is the file that was pinned |
| digest differs | `broken_pin` | the file read is provably not the file declared |
| no digest | `unpinned_artifact` | nothing about the file is confirmed |

Pins are resolved before any evidence is read. Decisions computed against a broken or unpinned
artifact still run and are still reported, marked with that validity, because a diagnostic is
more useful than a blank — but they are not authoritative and a policy may reject the report
on the pin alone.

An artifact declares its digest once. Evidence refers to an artifact by id and never repeats a
digest, so there is one source of truth per file.

## 3. Evidence kinds

### 3.1 `quote`

```yaml
kind: quote
artifact: paper-source
text: "Model A exceeded Model B by 3.2 percentage points"
section: "Results"      # recorded, never verified
page: 4                 # verified when present
```

Assertion: this passage occurs in the extracted text of this artifact, after normalization
that preserves which words appear — NFKC, curly quotes and dashes folded, hyphenation across
line breaks removed, whitespace collapsed. Normalization never deletes a character without
substituting a separator, because deleting a control character welds the words on either side
into one appearing in neither text.

### 3.2 `metric`

```yaml
kind: metric
artifact: results
name: delta
reported: "3.20"                          # a string, always
pointer: /comparisons/primary/delta       # RFC 6901
mode: printed_precision                   # or absolute | relative
tolerance: "0"                            # a string; ignored for printed_precision
```

Assertion: this artifact holds this value at this location.

**`reported` is a string** because YAML parses `3.20` to the float `3.2`, discarding the
precision the manuscript chose, and because binary floats do not represent decimal fractions
exactly. Parsed with `decimal.Decimal`.

**`pointer` is an RFC 6901 JSON Pointer** because a dotted path cannot distinguish a mapping
key containing a period from a nesting level, nor list index `0` from mapping key `"0"`.
Specifying an escape grammar for a new selector language is work already done.

| mode | agrees when |
|---|---|
| `printed_precision` | the stored value, rounded half-even to the precision `reported` prints, equals `reported`. A paper printing `3.2` is not contradicted by `3.20001`; one printing `3.20000` is. |
| `absolute` | \|stored − reported\| ≤ tolerance |
| `relative` | \|stored − reported\| ≤ tolerance × \|reported\| |

### 3.3 Kinds that are not here

`protocol` was specified as a third kind and is not one. Its integrity check is the artifact
pin, which every artifact already carries; its content check — that a registered document
states a given hypothesis — is a `quote` against the plan. What remains distinct about a
protocol is temporal: whether a confirmatory run postdates its registration. That requires a
run record, is unimplemented (§7), and is not smuggled in as a third kind in the meantime.

## 4. Outcomes

A check must execute, extract, and compare. Each stage fails differently, and the report
records all three.

| stage | values |
|---|---|
| `execution` | `completed` · `unavailable` · `failed` |
| `extraction` | `extracted` · `absent` · `invalid` · `not_attempted` |
| `comparison` | `match` · `mismatch` · `not_applicable` |

Collapsing these is how a missing extractor becomes a quotation that failed to check out, and
how a file silent on a value becomes one that contradicts it.

| situation | execution | extraction | comparison | flattens to |
|---|---|---|---|---|
| passage present | completed | extracted | match | `verified` |
| passage absent from a readable source | completed | extracted | mismatch | `mismatch` |
| pointer does not resolve | completed | absent | n/a | `not_found` |
| value is not a number | completed | invalid | n/a | `not_found` |
| extractor not installed | unavailable | not_attempted | n/a | `unchecked` |
| artifact missing or unparseable | unavailable | not_attempted | n/a | `unchecked` |
| backend defect | failed | not_attempted | n/a | `error` |

`Outcome` is derived from the three stages and never assigned, so the flattening cannot drift
from what the stages say.

**Silence is not contradiction.** A results file with no `bootstrap_n` key does not assert
that the value differs from what the manuscript reports; it asserts nothing. That is
`extraction=absent`, flattening to `not_found`, distinct from both a value that disagrees and
a check that could not run.

**Availability is a claim-level fact, not an outcome.** Whether a claim offers evidence cannot
be the result of checking evidence, because there is none to pass to a backend. `Claim`
carries `availability: offered | not_offered`; `not_offered` appears in the flattened view for
display and is never a `Decision`.

### 4.1 Reasons and warnings

`Reason` is a typed field carrying why an outcome obtained: `passage_present`, `value_match`,
`passage_absent`, `value_mismatch`, `pointer_absent`, `value_not_numeric`,
`extractor_missing`, `artifact_missing`, `artifact_unreadable`, `artifact_undeclared`,
`backend_defect`, `not_offered`.

`Warning` is orthogonal to the outcome: `short`, `truncated`, `normalized`, `wrong_page`. A
decision may be `verified` and carry one. `truncated` exists because *"an accuracy of 0.9"*
genuinely occurs in a source reporting **0.95**, so the passage is present and the reader is
told a true thing that misstates the result.

## 5. Backends

```python
class Backend(Protocol):
    kind: str
    version: str

    def check(self, claim: Claim, evidence: Evidence,
              path: pathlib.Path) -> Decision: ...
```

Every decision names the backend and its version, because the same inputs can receive
different decisions after a backend upgrade and a stored decision that does not say which
backend produced it cannot be compared with a later one.

Exceptions are not interchangeable:

| raised | becomes | rationale |
|---|---|---|
| `BackendUnavailableError` | `execution=unavailable` | the toolchain is absent; the claim was not evaluated |
| `ArtifactUnreadableError` | `execution=unavailable` | the file exists and could not be parsed |
| anything else | `execution=failed` → `error` | a defect is a defect |

A `TypeError` must not become an abstention. Letting a programming error read as a benign
scientific outcome is the failure this document exists to prevent, one level up.

Backends do not print, and do not consult the network during verification.

## 6. Facts and policy

`verify()` returns facts and no verdict. Whether a project passes depends on what it is for:
an unchecked citation in a working draft is unremarkable, an unchecked confirmatory result in
a submission is not. Folding that judgment into the engine makes one project's standard
everyone's.

```python
report  = verify(manifest)              # facts
verdict = PUBLICATION.assess(report)    # judgment
```

A `Policy` maps each outcome to `error`, `warning`, or `ignore`, with a separate map applied
to claims marked confirmatory. Three profiles ship:

| profile | mismatch | not_found | unchecked | not_offered | unpinned |
|---|---|---|---|---|---|
| `exploratory` | error | warning | warning | ignore | ignore |
| `publication` | error | error | warning | warning | warning |
| `publication`, confirmatory claims | error | error | **error** | **error** | — |
| `strict` | error | error | error | error | error |

Every policy requires at least one assertion to have been evaluated. A run that checked
nothing is not a pass, and without that condition a project with no evidence anywhere
satisfies every other condition trivially.

## 7. Ordering (specified, not implemented)

A confirmatory claim asserts a preregistered outcome. Whether the run producing its evidence
postdates the registration is checkable against a run record:

```yaml
runs:
  - id: confirmatory-run
    registered_plan: plan
    registered_at: 2026-08-01T14:00:00Z
    started_at: 2026-08-03T09:12:00Z
    outputs: [results]
```

Nothing in the current release reports on ordering. A manifest carrying `runs` is accepted and
ignored.

Two limits will remain after it is implemented. The registration timestamp is self-recorded,
so the check establishes internal consistency and not that a registration is contemporaneous
with what it claims; an external timestamp authority closes that and is out of scope. And the
check reads a declared run record rather than observing execution.

## 8. What this composes with

| layer | prior art | relation |
|---|---|---|
| entity/activity/agent provenance | W3C PROV-O | export target; no ontology defined here |
| signed ordered attestation | in-toto, SLSA | wraps a report where external attestation is needed |
| packaging at rest | RO-Crate | export target |
| content-addressed pipelines | DVC | complementary; no claim model there |
| claim-to-evidence entailment | FEVER, SciFact, CliniFact | a different relation; see §0 |
| repository artifact auditing | adduce | interoperates via manifest format and rule entry point |
| agent trace graphs | LEDGER | exposes claim-support paths; returns no verdict |

The contribution is §3 and §4: one contract spanning quotations and reported values, and a
three-stage outcome that separates a value that disagrees, a value that is absent, and a check
that never ran.

## 9. Conformance

An implementation conforms when:

1. It reports the three stages separately and derives the flattened outcome from them.
2. A missing toolchain yields `execution=unavailable`, never `completed`.
3. A backend defect yields `execution=failed`, never `unavailable`.
4. A pointer that does not resolve yields `extraction=absent`, never `comparison=mismatch`.
5. `reported` is compared as a decimal at its printed precision, never as a binary float.
6. Every decision names the claim digest, artifact digest, backend, and backend version.
7. A broken pin marks every decision against that artifact non-authoritative.
8. The engine returns facts and computes no verdict.
9. No library entry point prints, exits, or mutates global state.

Conformance is executable: `tests/conformance/` holds one fixture per row of the table in §4,
each with canonical expected JSON.
