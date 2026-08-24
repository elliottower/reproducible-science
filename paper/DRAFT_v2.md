# Evidence Assertions: Deterministic Verification of Quotations and Reported Values

*Draft v2. Elliot Tower, elliot@elliottower.ai*

## Abstract

A quotation cited in a manuscript and a number reported in it make the same kind of assertion:
that a particular value can be extracted from a particular artifact. We specify that assertion
as a typed contract with two variants, verify both through one engine against content-addressed
artifacts, and report the outcome as three orthogonal stages — whether the check executed,
whether the value was located, and whether it matched. Separating those stages distinguishes a
value that disagrees, a value the artifact is silent on, and a check that never ran, three
cases a two-state report has to collapse and whose remedies differ. The engine returns facts
and computes no verdict; a policy maps outcomes to severities, so an unchecked citation can be
acceptable in a draft and disqualifying in a submission. We report a quotation corpus of 5,686
assertions over 365 content-addressed sources drawn from seventeen manuscripts, a conformance
suite of thirteen fixtures with canonical expected outputs, and fault injection covering source
tampering, absent toolchains, and backend defects.

## 1. Introduction

A manuscript sentence citing a page of a PDF and a manuscript sentence citing a key in a
results file differ in how a value is extracted and in nothing else that matters to a reader
deciding whether to check it. Both assert that a specific artifact contains a specific value.
Both are checkable mechanically. Neither is checked by the tool that checks the other.

We call that proposition an **evidence assertion**, specify it as a discriminated union, and
verify it deterministically: a passage is at a byte offset in a file with a known hash, or it
is not.

**What this does not do.** An evidence assertion is not a scientific claim. A source can
contain a quotation verbatim while the quotation fails to support the sentence citing it, and
a passage can be absent while the claim is true and supported elsewhere. Entailment between
evidence and claim is the subject of FEVER [Thorne et al. 2018] and SciFact [Wadden et al.
2020], which predict a label given retrieved text and score against human annotation. Our
outcomes are `match` and `mismatch`, which name what a byte comparison found, rather than
`supported` and `refuted`, which name a semantic relation this method does not establish.

**Contributions.** (1) An evidence contract with two implemented variants, `quote` and
`metric`, sharing one engine and one report. (2) A three-stage outcome model — execution,
extraction, comparison — distinguishing disagreement, absence, and non-execution, with the
flattened single-field view derived from the stages rather than assigned. (3) Separation of
facts from verdict, with three policy profiles over identical reports. (4) An executable
conformance suite, and evaluation over a quotation corpus accumulated during ordinary research.

## 2. Three Stages

A check must execute, extract, and compare. Each can fail differently.

| situation | execution | extraction | comparison | flattened |
|---|---|---|---|---|
| passage present | completed | extracted | match | `verified` |
| passage absent from a readable source | completed | extracted | mismatch | `mismatch` |
| pointer does not resolve | completed | absent | n/a | `not_found` |
| extractor not installed | unavailable | not_attempted | n/a | `unchecked` |
| backend defect | failed | not_attempted | n/a | `error` |

The rows differ in what a reader should do: revise the claim, fix the pointer or run the
analysis that produces the value, install a package, file a bug. A report that cannot
distinguish them directs none of them.

**Two failures from our own implementation motivate the separation.** In an earlier revision,
a missing `pdftotext` caused the extractor to return the empty string; the verifier recorded
this as an unreadable document, and the run summary read `nothing failed`. In a later
revision, a JSON pointer that did not resolve was recorded as a mismatch, which asserts that
the artifact holds a different value when in fact it holds none. Both were found by writing
this specification, not by testing.

**Silence is not contradiction.** A results file with no `bootstrap_n` key does not assert
that the value differs from the manuscript's; it asserts nothing about it.

**Availability is a property of the claim.** Whether a claim offers evidence cannot be the
outcome of checking evidence, since there is none to pass to a backend. It is recorded on the
claim and appears in the flattened view for display only.

## 3. The Contract

| kind | assertion | located by | compared how |
|---|---|---|---|
| `quote` | this passage occurs in this artifact | page, optionally | verbatim after normalization that preserves which words appear |
| `metric` | this artifact holds this value here | RFC 6901 JSON Pointer | decimal, at the precision the manuscript printed |

Two specification decisions carry more weight than their size suggests.

**Reported values are strings.** YAML parses `3.20` to the float `3.2`, discarding the
precision the manuscript chose, and binary floats do not represent decimal fractions exactly.
A manuscript printing `3.2` is not contradicted by a file holding `3.20001`; one printing
`3.20000` is. Values are carried as strings and compared with `Decimal`.

**Locations are JSON Pointers.** A dotted path cannot distinguish a mapping key containing a
period from a nesting level, nor list index `0` from mapping key `"0"`. RFC 6901 already
specifies the escaping.

**A kind we removed.** `protocol` was specified as a third variant. Its integrity check is the
artifact pin, which every artifact carries; its content check — that a registered document
states a given hypothesis — is a `quote` against the plan. What remains distinct is temporal:
whether a confirmatory run postdates its registration. That needs a run record, is
unimplemented, and is not carried as a third kind in the meantime.

## 4. Pins, Validity, and Defects

Artifacts are content-addressed. Pins are resolved before any evidence is read, so a source
that moved is known before decisions are computed against it. Decisions against a broken or
unpinned artifact still run and are reported, marked non-authoritative, because a diagnostic is
more useful than a blank.

Backend exceptions are not interchangeable. `BackendUnavailableError` and
`ArtifactUnreadableError` yield `execution=unavailable`; any other exception yields
`execution=failed`, which flattens to `error` and never to `unchecked`. Letting a `TypeError`
read as an abstention is the failure of §2, one level up.

## 5. Facts and Policy

`verify()` returns facts. Whether they constitute a pass depends on what the project is for.

| profile | mismatch | not_found | unchecked | not_offered | unpinned |
|---|---|---|---|---|---|
| exploratory | error | warning | warning | ignore | ignore |
| publication | error | error | warning | warning | warning |
| publication, confirmatory claims | error | error | **error** | **error** | — |
| strict | error | error | error | error | error |

Every profile requires that at least one assertion was evaluated, since a project with no
evidence anywhere otherwise satisfies every condition trivially. On one demonstration manifest
the three profiles return two, three, and five errors over identical facts.

## 6. Evaluation

Four separate studies. They are reported separately because they exercise different things,
and one of them uses a tool outside this contract.

### 6.1 Conformance

Thirteen fixtures, one per row of the outcome table plus escaping, undeclared-artifact, and
unpinned cases, each carrying canonical expected output. Twenty-eight assertions over them,
including that an absent pointer yields `extraction=absent` and never `comparison=mismatch`,
and that an injected `TypeError` yields `error` and never `unchecked`. Conformance is
executable rather than interpretive.

### 6.2 Quotation corpus

Assertions accumulated during ordinary research across seventeen manuscripts, not assembled
for this paper.

| | count |
|---|---|
| quotation assertions | 5,686 |
| manuscripts | 17 |
| source files declared | 366 |
| sources with a matching pin | 355 |
| sources carrying no pin | 9 |
| sources named and not present | 1 |
| declaration files that do not parse | 1 |

The largest single manuscript contributes 2,942 assertions, all of which resolve against their
pinned sources; 213 carry a `short` warning, 155 a `normalized` warning, and 8 a `truncated`
warning, the last flagging a quotation that stops mid-number.

A positive control copies a genuinely pinned source, flips one bit, and confirms the pin
reports broken where the untouched file reports authoritative. Before that control existed,
355 sources carried recorded hashes that nothing compared against the files on disk.

### 6.3 Fault injection

| injected | reported |
|---|---|
| results file edited after drafting | broken pin; decisions against it marked non-authoritative |
| extraction toolchain absent | `unchecked`, reason `extractor_missing` |
| registered plan edited after registration | broken pin on the plan artifact |
| backend raises `TypeError` | `error`, reason `backend_defect` |

### 6.4 Identifier resolution: a case study outside this contract

The following comes from a citation-library resolver, not from the evidence engine, and is
reported to characterize the corpus rather than to evaluate the contract.

Four entries in one bibliography carried live DOIs resolving to journal **reviews of the cited
books** rather than the books: a review in *The Statistician* stood in for Howson and Urbach, a
review in *The Modern Schoolman* for Marr's *Vision*, a review in *Science Education* for
Darden. Author, title, and year were correct in every case; only the identifier pointed
elsewhere, and all four resolve, so a link checker passes them.

A title-based resolver wrote 172 identifiers into that library. Of those, 21 have no record
file and 6 have a record listing no authors. The remaining **145 are checkable, and 12 name a
work whose first author does not appear in the registry's author list: 8.3%.** A first-author
guard rejects them.

Two properties of the checking matter as much as the rate. Surname matching must accept
transliteration variants — `Hölscher` against `Hoelscher` — or the guard rejects correct
entries at roughly the rate it catches wrong ones. And the checker must consult the registry a
DOI is registered with: 24 of these are arXiv and Zenodo identifiers under prefixes DataCite
carries and Crossref answers 404 for. Reading only Crossref reported all 24 as identifiers
that did not resolve, which is a false accusation against correct entries produced by asking
the wrong registry.

Identifier resolution is not modeled by the evidence contract. Whether it should be a third
evidence kind is open.

## 7. Related Work

| layer | prior art | relation |
|---|---|---|
| entity/activity/agent provenance | W3C PROV-O | export target; no ontology defined here |
| signed ordered attestation | in-toto, SLSA | wraps a report where external attestation is needed |
| packaging at rest | RO-Crate | export target |
| content-addressed pipelines | DVC | complementary; no claim model there |
| claim-to-evidence entailment | FEVER, SciFact, CliniFact | a different relation; see §1 |
| repository artifact auditing | adduce | interoperates via manifest format and rule entry point |
| agent trace graphs | LEDGER | exposes claim-support paths for review; returns no verdict |

`adduce` audits whether a repository's code, configuration, and data agree with the numbers a
paper reports, and does so more thoroughly than this work does. Run against one of our own
manuscripts it reports, correctly, that *results are reported and run commands exist, but
nothing maps commands to specific results*. That mapping is what a `metric` assertion is. The
two address adjacent halves of one question and interoperate through a manifest format rather
than a shared dependency.

## 8. Limitations

The quotation corpus is one researcher's, in mechanistic interpretability and computational
biology, and its defect rates are properties of that corpus. No external project has yet used
either backend.

The metric backend is evaluated on conformance fixtures and fault injection, not on a corpus
comparable to the quotation one. A metric corpus over published manuscripts, with an
independent check that each pointer addresses the value the manuscript intends, is the
evaluation this paper lacks.

Ordering is specified and unimplemented; manifests carrying run records are accepted and
ignored. When implemented it will establish internal consistency only, since a registration
timestamp is self-recorded.

Coverage is a property of what the author declared. A claim whose evidence is undeclared is
reported as offering none, and is not searched for.

## 9. Conclusion

Quotations and reported values assert the same kind of thing about an artifact, and differ in
how a value is extracted. Specifying the assertion once lets one engine report on both and
makes a third kind a registration rather than a rewrite. The three-stage outcome exists because
a value that disagrees, a value that is absent, and a check that never ran have different
remedies, and because collapsing them produced, in our own implementation, a run that examined
nothing and reported that nothing failed.
