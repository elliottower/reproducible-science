---
title: Specification
description: Specification — Reproducible Science
---

<!-- Generated from docs/SPEC.md. Edit that file, not this one. -->

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
| `Evidence` | yes | an assertion about one artifact, or two, discriminated on `kind` |
| `Claim` | yes | a manuscript statement and the evidence offered for it |
| `Manifest` | yes | one project's artifacts and claims |
| `Decision` | yes | the outcome of evaluating one assertion |
| `DecisionSide` | yes | what one side of a two-sided assertion read, and where |
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

### 3.4 `correspondence`

```yaml
kind: correspondence
name: fixture-count
sides:
  - name: stated
    artifact: spec
    locator: {kind: prose, before: "suite holds", after: "fixtures", form: cardinal_word}
  - name: measured
    artifact: probe
    locator: {kind: tree, pointer: /probes/fixtures/value}
mode: printed_precision     # or absolute
tolerance: "0"
```

Assertion: these two artifacts hold the same value.

The other three kinds compare an artifact against a literal written in the manifest. A claim a
document makes about the code beside it has an artifact on both sides: `docs/SPEC.md` states a
fixture count, and `ls -1 packages/repro/tests/conformance/cases` returns one. Expressing that
with a `metric` requires transcribing one of the two into `reported`, and no assertion reads
the transcription — rewriting every `reported` field to the value the command measured, leaving
the quoted sentences untouched, passes a manifest whose documents are still wrong.

Exactly two sides, each with a name, an artifact, and a locator. The two must not address the
same value, since an assertion comparing a value with itself holds whatever the file contains.
The names are the author's and the engine attaches no meaning to them.

**Neither side is the reference.** A disagreement reports both values and says which artifact
each came from; it does not say which is wrong, because nothing in a byte comparison establishes
whether a specification or a suite is in error. `relative` is rejected for the same reason: its
tolerance is a fraction of the reported value, and there is no reported value to take a fraction
of. `printed_precision` compares at the coarser of the two precisions, so a sentence printing
one decimal agrees with a file holding four, and the outcome does not depend on which side the
manifest wrote first. NaN and the infinities have no precision for either side to be coarser
than, so a non-finite value on either side is `value_not_numeric` before any comparison, as it
is for a one-sided assertion.

**What it cannot establish.** Three limits, in decreasing order of how often they bite.

A prose claim usually carries no number. *The scanner reads the directory flat*, *the field is
honored*, *the walk skips symlinks* are propositions about behavior, and expressing one means
inventing a count — of matched files, of call sites — so the assertion then checks the encoding
rather than the proposition. A correspondence reaches a documented claim only where the document
states a quantity.

The subject of such a claim is usually a repository, and a repository is not a file a manifest
can declare: `Digest.of_file` addresses one file, so the directory a count is taken over cannot
be pinned as an input. The measured side is therefore an artifact holding a command's output,
pinned like any other, while the input to that command is not pinned at all. §7.6 puts declared
inputs in an empty directory so that a command needing an undeclared file fails; a command whose
subject cannot be declared reads it by absolute path and the record reports `reproduced` on
grounds nothing checked. **A correspondence over a repository makes no reproducibility claim,
and a manifest should declare no regeneration for one rather than collect a guarantee it has not
earned.** Closing this needs an artifact identified by a digest over a directory, which this
revision does not define.

Both sides being read does not make either side right. Two artifacts agree or they do not, and a
document and a script can agree on a number that is wrong.

### 3.5 Kinds that are not here

`protocol` was specified as a third kind and is not one. Its integrity check is the artifact
pin, which every artifact already carries; its content check — that a registered document
states a given hypothesis — is a `quote` against the plan. What remains distinct about a
protocol is temporal: whether a confirmatory run postdates its registration. That requires a
run record, is unimplemented (§7), and is not smuggled in as a third kind in the meantime.

## 3.6 Locators

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
| `prose` | a document, as text | two literal anchors bracketing the value |

Every variant enforces one invariant: a locator resolves to **exactly one scalar**. Zero is
absent, two or more is ambiguous, a container is not a value, and no backend takes the first
match. A format with no adapter — HDF5, NetCDF, Parquet, XLSX — reports `format_unsupported`
and stops. No backend falls back to searching a file for the printed number, which would find
it wherever it appears and call that verification.

`prose` is the one variant addressing a format that has no addressing scheme of its own. A
sentence is not a tree, a table, or an indexed array, so the address is the text on either side
of the value: `before` is the literal that precedes it and `after` the literal that follows,
and the value is the run of non-whitespace characters between them.

```yaml
locator: {kind: prose, before: "suite holds", after: "fixtures", form: cardinal_word}
```

Two alternatives were available and are worse under this document's own rules. A capture-group
pattern is a string expression language, which §3.6 rejects for predicates: it needs a dialect,
an escaping grammar, and a backtracking bound. A braced template — `holds {n} fixtures` — needs
an escaping grammar for the brace, and LaTeX sources are full of braces. Two literal anchors
need neither, and they make the author state the address rather than describe a number to
search for.

Anchors are matched against the text a `quote` resolves against, under the same normalization,
so an anchor and a quotation over one document cannot disagree about what the document says.
Whitespace at an anchor boundary is ignored, on the grounds that normalization collapses it
everywhere else. An anchor pair selecting two occurrences of one value resolves to that value;
selecting two *different* values is `passage_ambiguous`. A repeated count is ordinary prose and
a document stating two counts is a defect, which is the distinction a `quote` cannot draw:
a quotation is satisfied by any occurrence, so editing one of two statements of a number leaves
the assertion satisfied by the other.

`form` says how the selected text is read as a number. Under `decimal`, the default, digits are
parsed and nothing is converted. Under `cardinal_word`, an English cardinal below one hundred
written as one word is read as that number: `eighteen` is 18. **The conversion is declared, not
inferred.** Under `decimal` a recognized cardinal is refused with `number_as_word` rather than
converted, because reading a word as a number is a semantic decision and the engine makes none
on its own. The bound is not arbitrary: the value is one run of non-whitespace characters, and
every cardinal above ninety-nine is several words, so `one hundred and forty-five` is not
addressable this way whatever the table holds. `form` is part of the canonical locator, so the
decision digest binds what the manifest authorized.

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
| two sides agree | completed | extracted | match | `verified` |
| two sides disagree | completed | extracted | mismatch | `mismatch` |
| one side does not extract | completed | absent or invalid | n/a | `not_found` |
| passage absent from a readable source | completed | extracted | mismatch | `mismatch` |
| pointer does not resolve | completed | absent | n/a | `not_found` |
| value is not a number | completed | invalid | n/a | `not_found` |
| independent readers disagree | completed | invalid | n/a | `not_found` |
| extractor not installed | unavailable | not_attempted | n/a | `unchecked` |
| artifact missing or unparseable | unavailable | not_attempted | n/a | `unchecked` |
| backend defect | failed | not_attempted | n/a | `error` |

`Outcome` is derived from the three stages and never assigned, so the flattening cannot drift
from what the stages say.

**Silence is not contradiction.** A results file with no `bootstrap_n` key does not assert
that the value differs from what the manuscript reports; it asserts nothing. That is
`extraction=absent`, flattening to `not_found`, distinct from both a value that disagrees and
a check that could not run.

**Two extractions still make one comparison.** A `correspondence` reads a value from each
of two artifacts before comparing them, and the stages report that as they report everything
else. Where one side extracts and the other does not, the comparison did not happen: that is
`extraction=absent` or `extraction=invalid` with `comparison=not_applicable`, flattening to
`not_found`, and never `mismatch`. A results file silent on a value does not contradict a
document stating it, and a document that never states the number does not contradict the file.
The decision carries the failing side's own reason — `pointer_absent`, `number_as_word` — and
names which side failed, so a gap on one side is not reported as a disagreement between two.
The extraction stage of a two-sided assertion is the weaker of its two sides, and its validity
is the weaker of its two artifacts.

**A reader is not the document.** A pin establishes that a file's bytes have not changed. It
establishes nothing about whether the program that read them produced the right text, and a
mangled extraction reads exactly like a passage that was never written: a two-column layout
flattened in the wrong order yields a confident `not found` against a manuscript that quotes
its source correctly. Where two independent extractors disagree about whether a passage is
present, the document is not determinate under the readers available, which is
`extraction=invalid` — the same stage as a cell holding no number, and for the same reason.
There was nothing well formed to compare. It is emphatically not `comparison=mismatch`, which
asserts that the source contradicts the manuscript.

Disagreement is therefore a property of the reading, not a milder verdict about the passage,
and every decision names the reader and version that produced the text it was checked against.
A backend that substitutes one extractor for another records the substitution: two decisions
that disagree because they were taken with different readers are otherwise indistinguishable
from two decisions that disagree about the document.

**Availability is a claim-level fact, not an outcome.** Whether a claim offers evidence cannot
be the result of checking evidence, because there is none to pass to a backend. `Claim`
carries `availability: offered | not_offered`; `not_offered` appears in the flattened view for
display and is never a `Decision`.

### 4.1 Reasons and warnings

`Reason` is a typed field carrying why an outcome obtained: `passage_present`, `value_match`,
`passage_absent`, `value_mismatch`, `pointer_absent`, `value_not_numeric`,
`extractor_missing`, `artifact_missing`, `artifact_unreadable`, `artifact_undeclared`,
`backend_defect`, `not_offered`, and two a prose locator adds. `passage_ambiguous`: one pair of
anchors selected two different values, so the document states two numbers where the assertion
addresses one. `number_as_word`: the value is an English cardinal written out under a locator
that did not ask for one. It is distinct from `value_not_numeric` because the fix differs — the
value is there and a reader would call it a number, so an author told only that no number was
found goes looking for a broken anchor.

`Warning` is orthogonal to the outcome: `short`, `truncated`, `normalized`, `wrong_page`. A
decision may be `verified` and carry one. `truncated` exists because *"an accuracy of 0.9"*
genuinely occurs in a source reporting **0.95**, so the passage is present and the reader is
told a true thing that misstates the result.

## 5. Backends

```python
class Backend(Protocol):
    kind: str
    version: str

    tool: str

    @property
    def tool_version(self) -> str: ...

    def check(
        self, claim: Claim, evidence: Evidence, paths: Mapping[str, pathlib.Path]
    ) -> Decision: ...
```

`paths` holds one entry per artifact the assertion names, keyed by id. Every kind but
`correspondence` names one and takes it with `paths[evidence.artifact]`. It is a mapping rather
than a path because an assertion whose two sides are both artifacts has no single file to be
handed, and handing it one would make the engine choose a side before the backend has read
either. Widening this was not additive: a backend written against the earlier signature does
not satisfy the protocol.

Every decision names the backend and its version, because the same inputs can receive
different decisions after a backend upgrade and a stored decision that does not say which
backend produced it cannot be compared with a later one.

### 5.1 The extraction toolchain

`version` is the protocol version of the interface, written by hand. The program that turns
bytes into text or values is named separately, in `tool` and `tool_version`: the `pdftotext`
binary for a quotation, the installed distribution supplying the format adapters for a value.
Content addressing establishes that the bytes did not change and establishes nothing about how
they were read, so a `pdftotext` upgrade that resolves a ligature differently changes an
extracted passage with every digest in the manifest intact. A binary reports its version as it
prints it; a distribution reports `importlib.metadata`. A tool that cannot be interrogated is
recorded as `unknown`, never omitted: a field that disappears makes an uninterrogated
toolchain indistinguishable from an absent one.

`extraction_digest` records the sha256 of what the extractor produced — the whole extracted
text for a quotation, the extracted value for a number. The version string catches drift that
announces itself; the digest catches drift from any cause, including a rebuilt binary
reporting the same version and an environment that changes an encoding path. `unknown` where
the extraction produced nothing to hash. It establishes stability and not correctness: a first
extraction that reads a column wrong hashes perfectly and stays wrong.

A `correspondence` extracts twice, so it records a digest per side and one over both, in the
order the manifest declares the sides. The decision-level digest moves whenever either side's
extraction moves; which of the two moved is on the side. Leaving it `unknown` would say the
extraction was sought and not obtained, and it was sought twice. `tool` stays one field, which
is an approximation where the two sides are read by different programs: a `prose` side over a
paginated source reaches the same `pdftotext` a quotation does. The per-side extraction digest
is what catches a change in either program, since it moves whenever what a side read moves,
whatever did the reading. Naming a tool per side needs the adapters to report which one they
used, and this revision does not define that.

Both are provenance. Whether a changed tool version or a changed extraction invalidates a
stored decision the way a changed artifact does is a policy question, and §6 decides policy.

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

Each confirmatory claim reports one of four ordering states. `ordered`: every run producing
its evidence started after registration. `violated`: a run started first. `unchecked`: the
record does not settle it. `not_applicable`: the claim is not confirmatory.

An `unchecked` ordering carries a reason, because collapsing distinct conditions into one word
loses the only information that says what to fix: `no_run_record`, `no_registered_plan`,
`registered_plan_unpinned`, `registered_plan_changed`, `run_output_unlinked`,
`run_output_changed`, `timestamp_missing`, `ambiguous_producing_run`. A claim with no run
record is `unchecked` and never `violated` — an absent record is not evidence that a result
predates its plan.

Every artifact a claim's evidence names must have a covering run. Taking the runs that produce
any one of them would let a run record for an incidental artifact order a claim whose number
came from an artifact with no run at all.

Where `registered_plan` names a declared artifact, that document is pinned, so a plan edited
after the fact to match results breaks its pin and the ordering reverts to `unchecked`.

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

The declared inputs are copied into an empty directory and the command runs there, so a
command needing a file the manifest never declared fails, and a command that writes where it
was told to writes inside that directory. Every declared path is resolved and checked for
containment before it is used, since a path holding `..` otherwise lands outside.

This is a working directory, not a sandbox in the security sense: nothing stops a command
writing to an absolute path elsewhere. Running `--regenerate` on a manifest you have not read
is running a program you have not read. That makes the record a claim about sufficiency and not only about provenance.

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

The contribution is §3 and §4: one contract spanning quotations, reported values, and values
read from two artifacts at once, and a three-stage outcome that separates a value that
disagrees, a value that is absent, and a check that never ran.

## 9. Conformance

An implementation conforms when:

1. It reports the three stages separately and derives the flattened outcome from them.
2. A missing toolchain yields `execution=unavailable`, never `completed`.
3. A backend defect yields `execution=failed`, never `unavailable`.
4. A pointer that does not resolve yields `extraction=absent`, never `comparison=mismatch`.
5. `reported` is compared as a decimal at its printed precision, never as a binary float.
6. Every decision names the claim digest, artifact digest, backend, backend version,
   extraction toolchain, that toolchain's version, and the digest of what it produced. A
   decision over two artifacts names the artifact digest, the locator digest and the
   extraction digest of each side, since one field cannot hold two.
7. A version or digest that was sought and not obtained is recorded as `unknown`, never
   omitted, so it stays distinguishable from one that was never sought.
8. A broken pin marks every decision against that artifact non-authoritative.
9. The engine returns facts and computes no verdict.
10. No library entry point prints, exits, or mutates global state.
11. A two-sided assertion with one side unresolved yields `not_found`, never `mismatch`, and
    carries the failing side's reason.
12. A spelled-out number is converted only where the locator declares `cardinal_word`, and
    refused with `number_as_word` otherwise.

Conformance is executable: `packages/repro/tests/conformance/` holds 25 fixtures, each with
canonical expected JSON. They cover `verified`, `mismatch`, `not_found`, `unchecked` and
`not_offered`, the pointer-escaping and undeclared-artifact cases, an unpinned artifact, a
broken pin, five table-addressing cases, and six over `correspondence` and the prose locator:
two sides agreeing, two sides disagreeing, one side that does not resolve, a spelled-out number
refused, one pair of anchors selecting two different values, and a prose value against a
literal.

Each fixture declares its outcome, its reason, and the validity of every artifact. The outcome
alone cannot tell a defect in the tool from a fact about the document: three cases share
`unchecked` and eight share `not_found`, and only the reason separates an undeclared artifact
from an absent file, or an ambiguous anchor pair from a number written as a word.

Two rows of §4 have no fixture: `error`, which needs a backend defect, and the
extractor-missing form of `unchecked`. Neither is producible from a file on disk alone, so
they are exercised by the test suite rather than by the corpus. The expected JSON records the
flattened outcome; the three stages are asserted in the suite.
