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

### 3.3 `table`

```yaml
kind: table
artifact: results-csv
name: c-index
reported: "0.648"
column: accuracy
where: {model: VAECox}      # or: row: 2
delimiter: ""               # inferred from suffix, then from the header
mode: printed_precision
tolerance: "0"
```

Assertion: this table holds this value in this cell.

Most published result artifacts are delimited tables rather than JSON, so this is the variant
a manuscript's own tables usually need.

A cell is named by its column and by exactly one of two row selectors. `where` selects the row
whose named columns hold the given values; `row` is a zero-based index among data rows.
**`where` is preferred**, because a row index silently addresses a different cell when a table
is reordered or a row inserted, and a reordered table is precisely the case a checker exists to
notice.

| situation | reported |
|---|---|
| `where` matches no rows | `extraction=absent`, reason `row_absent` |
| `where` matches more than one | `extraction=invalid`, reason `row_ambiguous` |
| the column is not in the header | `extraction=absent`, reason `column_absent`, listing the columns that are |
| both `row` and `where`, or neither | `extraction=invalid`, reason `row_selector_invalid` |
| the cell holds no number | `extraction=invalid`, reason `value_not_numeric` |

An ambiguous selector is reported rather than resolved to the first match, since resolving it
would make the answer depend on row order.

The delimiter comes from the file suffix where one is known, and from the header line
otherwise. Suffix first: a `.tsv` whose header contains commas is still tab separated, and
sniffing it would split every row in the wrong place.

### 3.4 Kinds that are not here

`protocol` was specified as a third kind and is not one. Its integrity check is the artifact
pin, which every artifact already carries; its content check — that a registered document
states a given hypothesis — is a `quote` against the plan. What remains distinct about a
protocol is temporal: whether a confirmatory run postdates its registration. That requires a
run record, is unimplemented (§7), and is not smuggled in as a third kind in the meantime.

## 3.5 Locators

A locator says where a value sits. JSON Pointer works because JSON has one tree data model and
a pointer resolves to at most one value; it says nothing about table keys, multidimensional
indices, or database rows. Rather than extend one syntax to cover every file, the contract is
a discriminated union whose variants address each format the way that format already addresses
itself.

| kind | addresses | identity |
|---|---|---|
| `tree` | JSON, and YAML restricted to a JSON-compatible tree | RFC 6901 pointer |
| `table` | CSV, TSV, PSV | column plus a predicate matching exactly one row |
| `table_position` | the same, by row index | column plus position, carrying a warning |
| `sqlite` | a database file | table, column, and a predicate matching one row |
| `array` | `.npy`, `.npz` | array name plus a multidimensional index |

Every variant enforces one invariant: a locator resolves to **exactly one scalar**. Zero is
absent, two or more is ambiguous, a container is not a value, and no backend takes the first
match. A format with no adapter — HDF5, NetCDF, Parquet, XLSX — reports `format_unsupported`
and stops. No backend falls back to searching a file for the printed number, which would find
it wherever it appears and call that verification.

Predicates are typed key-value mappings, not a string expression language: a string predicate
needs a parser, coercion rules, and an escaping grammar, and every implementation would
disagree about the edges. In a delimited file, predicate values are compared as text and never
coerced, so `"001"` and `1` address different rows. YAML is read with duplicate mapping keys
rejected, since a file that resolves one way with nothing said about the other is not
addressable.

`metric` and `table` evidence remain as shorthand for the two commonest locators and resolve
through the same adapters, so a manifest never chooses between a convenient spelling and a
supported one.

Locators are canonicalized — sorted keys, no whitespace, no coercion — and hashed. A decision
records that digest beside the artifact digest, so it binds how a value was addressed as well
as what was read: a selector edited after the fact changes the record even where the file does
not.

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

    def check(self, claim: Claim, evidence: Evidence, path: pathlib.Path) -> Decision: ...
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
report = verify(manifest)  # facts
verdict = PUBLICATION.assess(report)  # judgment
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

## 7. Ordering

A confirmatory claim asserts a preregistered outcome. Whether the run producing its evidence
postdates the registration is checked against a run record:

```yaml
runs:
  - id: confirmatory-run
    registered_plan: plan
    registered_at: 2026-08-01T14:00:00Z
    started_at: 2026-08-03T09:12:00Z
    outputs: [results]
```

Both timestamps must carry an offset. A naive timestamp compared against an aware one is
either a crash or a silently wrong ordering, so a manifest cannot express one.

A claim declares one of three registration states. `confirmatory`: it reports a preregistered
outcome, and the ordering check applies. `exploratory`: a plan could have fixed the outcome and
did not — the default, since a claim that says nothing about registration is exploratory rather
than exempt. `not_applicable`: no outcome was selected from alternatives, so registration has
nothing to bind, which is the case for an exhaustive deterministic measurement that reports
every result it produced. `not_applicable` requires a reason, on the same convention a
preregistration uses for an inapplicable heading, because a state that can be entered silently
is a way for any claim to opt out of being graded. A manifest written with `confirmatory: true`
or `false` still parses; `false` becomes `exploratory`, never `not_applicable`, since the
boolean never carried that distinction.

Each confirmatory claim reports one of four ordering states. `ordered`: every run producing its
evidence started after registration. `inverted`: a run started first. `undeclared`: no run
covers its artifacts, a timestamp is missing, or the plan is a declared artifact whose pin is
broken. `not_applicable`: the claim is not confirmatory. A claim with no run record is
`undeclared` and never `inverted` — an absent record is not evidence that a result predates
its plan.

Where `registered_plan` names a declared artifact, that document is pinned, so a plan edited
after the fact to match results breaks its pin and the ordering reverts to `undeclared`.

Two limits are structural. The registration timestamp is self-recorded, so the check
establishes internal consistency and not that a registration is contemporaneous with what it
claims; an external timestamp authority closes that and is out of scope. And the check reads
a declared run record rather than observing execution.

## 7.5 Output formats

A renderer reads a report and an assessment and produces bytes. None computes anything, so two
renderers over one report always say the same thing.

`sarif` emits SARIF 2.1.0, which GitHub renders inline on a pull request. Two parts of that
format fit: `artifacts[].hashes` carries a sha-256 per file, so the digests a report was
computed against travel with it; and `result.kind` is separate from `result.level`, so a check
that could not run is `notApplicable` rather than a low-severity failure. Most report formats
cannot express that difference, and it is the one this document exists to preserve.

A policy raises a result's `level` and never changes its `kind`: what happened does not depend
on what a project considers acceptable.

## 7.6 Regeneration

Ordering asks whether a confirmatory run followed its plan. That question has no meaning for a
measurement no plan could have registered: an exhaustive count over a declared corpus selects
no outcome, so nothing was there for a registration to fix. What can be asked of such a number
is whether it is still the output of the code that claims to produce it.

```yaml
regenerations:
  - id: figures
    command: [python, scripts/build_figures.py]
    inputs:
      - {artifact: corpus, digest: {algorithm: sha256, value: ...}}
      - {artifact: script, digest: {algorithm: sha256, value: ...}}
    output: {artifact: figures, digest: {algorithm: sha256, value: ...}}
    volatile: ["/generated_at"]
```

The declared inputs are copied into an empty directory and the command runs there, so nothing
in the working tree is written to, and a command needing a file the manifest never declared
fails. That makes the record a claim about sufficiency and not only about provenance.

Three states. `reproduced`: the command produced the pinned artifact. `diverged`: it produced
something else, produced nothing, or exited non-zero. `unchecked`: it was not requested, an
input has moved since the record was written, or the runner is absent. An input that changed
yields `unchecked` rather than `diverged`, because different inputs producing a different
output is not a failure to reproduce.

Comparison is exact but canonical. An output carrying a timestamp or an absolute path never
reproduces byte for byte, so a record names those fields as `volatile` JSON Pointers and they
are removed before hashing; where a record names them, the digest it pins is the canonical one.
Naming the fields keeps the comparison exact everywhere else, which loosening the whole
comparison would not.

Regeneration is off by default and runs only under `repro verify --regenerate`. Verifying a
manifest should never execute what the manifest names. Commands are argv, never shell strings:
a shell string needs quoting rules, brings a shell's expansion with it, and turns a manifest
into something that can run anything.

Regeneration is orthogonal to registration. A `not_applicable` claim need not declare one —
methods statements and externally sourced facts are inapplicable without being script-generated
— and a confirmatory claim may declare both.

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

Conformance is executable: `packages/repro/tests/conformance/` holds eighteen fixtures, one per row of the
table in §4 plus the escaping, undeclared-artifact, unpinned and table-addressing cases,
each with canonical expected JSON.
