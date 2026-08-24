# One Evidence Contract for Quotations, Results, and Protocols

*Draft v1. Elliot Tower, elliot@elliottower.ai*

## Abstract

A quotation in a manuscript and a number in a results file are checked by different tools, in
different formats, with different vocabularies for what a check concluded. They are the same
object: a typed value extracted from a pinned artifact, offered in support of a sentence. We
specify that object as a discriminated union, verify all three kinds through one engine, and
report a four-state outcome. The fourth state separates a check that ran and found nothing
from a check that could not run at all — a distinction with different remedies, and one whose
absence lets a run in which nothing executed report that nothing failed. We implement the
contract over a corpus of 2,942 quotations pinned to 355 hashed sources across twelve
manuscripts, and report three defect classes the contract surfaces: sources edited after being
cited, identifiers resolving to works other than the one cited, and reported values absent from
the artifact said to produce them.

## 1. Introduction

Checking whether a paper's numbers come from its code is one tool. Checking whether its
quotations occur in the sources it cites is another. Checking whether its confirmatory
analyses postdate their preregistration is a third. Each has a format, a vocabulary, and a
notion of what a failure is, and none of them can read the others' output.

The three answer one question at different addresses: **does the artifact this claim points at
actually contain what the claim says it does?** A manuscript sentence citing a page of a PDF
and a manuscript sentence citing a key in a JSON file differ in how the value is extracted and
in nothing else that matters to a reader deciding whether to believe the sentence.

This paper specifies the shared object, and reports what falls out of treating it as one
thing.

**Contributions.** (1) An evidence contract: `quote`, `metric`, and `protocol` as variants of
one discriminated union, verified by one engine through a backend interface, with a new kind
being a registration rather than an engine change. (2) A four-state outcome refining the
three-label taxonomy of FEVER and SciFact, splitting `NOT ENOUGH INFO` into a checked absence
and an unrun check. (3) An implementation over a real corpus, and the defect classes it
surfaces in manuscripts under review.

## 2. The Distinction the Fourth State Carries

Consider a verifier that reads a PDF, extracts its text, and looks for a quoted passage. If
the extraction toolchain is not installed, the extractor returns nothing, and every quotation
in the corpus resolves to the same outcome as a quotation that was never in the source.

With two outcomes the tool must choose. Reporting every quotation as failing accuses a correct
bibliography of fabrication because a system package is absent. Reporting every quotation as
passing produces a run that examined nothing and says so nowhere. Both were observed in an
earlier version of the implementation described here: a missing `pdftotext` produced the string
`"no text extracted"`, which the report rendered as `unchecked`, under a summary line reading
`nothing failed`.

The same shape appears without a missing binary. An audit of eleven bibliography entries
against the registry each identifier resolves to returned four failures. All four were arXiv
identifiers under the `10.48550` prefix, which Crossref returns 404 for because they are
registered with DataCite. The identifiers were correct; the checker consulted the wrong
registry. Under two outcomes that run reports four bad identifiers in a bibliography that has
none.

| what happened | two-state report | four-state report |
|---|---|---|
| passage absent from the source | fail | `refuted` |
| extractor not installed | fail, or pass | `unchecked` |
| identifier in another registry | fail | `unchecked` |
| artifact read, silent on the claim | fail | `unchecked` |
| no evidence offered | pass | `no_evidence` |

The remedies differ: revise the claim, install a package, query DataCite, run the analysis that
produces the value, add a citation. A report that cannot distinguish them cannot direct any of
them.

**Silence is not refutation.** A results file with no `bootstrap_n` key does not assert that
the value is something other than what the manuscript reports; it asserts nothing about it.
That case is `unchecked` with reason `SELECTOR_ABSENT`, and grouping it with a genuine value
mismatch was a defect in an earlier revision of our own implementation.

## 3. The Contract

Evidence is a discriminated union on `kind`. Each variant declares what it needs to be
checked and nothing else.

| kind | value | located by | verified against |
|---|---|---|---|
| `quote` | a passage | page (optional) | extracted text of a hashed source |
| `metric` | a number | dotted selector | a hashed machine-readable artifact |
| `protocol` | a commitment | registration time | the digest of a frozen document |

A backend implements `check(claim, evidence, path) -> Decision` and raises
`BackendUnavailableError` when it cannot run. The engine converts that into `unchecked` with
the backend's own reason attached. A backend never decides that a claim failed because its own
toolchain is missing; the engine enforces this by construction, since the only way a backend
can report an unrun check is to raise.

Two properties of the engine are worth stating because they are load-bearing rather than
incidental. Each artifact's pin is compared once, before any evidence is read, so a source that
moved is reported ahead of the decisions computed against it. And a report with any broken pin
fails regardless of how its decisions went: a changed source invalidates the decisions that
agreed with it as much as the ones that did not.

## 4. Implementation

`repro` is a Python package. The contract is Pydantic v2 models with provenance-bearing
objects frozen; the engine is 226 lines; each backend is under fifty. The quotation backend
delegates extraction and normalization to `citations`, which handles unicode folding,
de-hyphenation across line breaks, and detection of a passage that stops mid-number.

Verification is offline. A backend that requires a registry declares it and is skipped unless
enabled, so a report is reproducible from the artifacts it names.

Nothing in the library prints, exits, or reads global state. `verify()` returns a
`VerificationReport`; the command-line interface is a renderer over it, and the same call
serves a test, a notebook, and an agent hook.

## 5. Evaluation

**Corpus.** 2,942 quotations across twelve manuscripts, pinned to 355 hashed source documents,
accumulated over eighteen months of ordinary research rather than assembled for this paper.

| | count |
|---|---|
| quotations verified | 2,942 |
| sources with a matching pin | 355 |
| sources carrying no pin | 9 |
| sources named and not on disk | 1 |

**Pin checking is not decorative.** A positive control copies a genuinely pinned source, flips
one bit, and confirms the pin reports `broken` where the untouched file reports `ok`. Before
this control existed, 355 sources carried recorded hashes that nothing compared against the
files on disk.

**Defect classes surfaced.** Three, in manuscripts under review at the time of writing.

*Sources cited by a resolving identifier that names another work.* Four entries in one
bibliography carried live DOIs resolving to journal **reviews of the cited books** rather than
the books: a review in *The Statistician* stood in for Howson and Urbach, a review in *The
Modern Schoolman* for Marr's *Vision*, a review in *Science Education* for Darden. Every entry
had a correct author, title, and year; only the identifier pointed elsewhere. The failure is
invisible to a link checker, since all four resolve.

*Identifiers introduced by automated resolution.* Of 180 identifiers written into a citation
library by a title-based resolver, 24 name a work whose first author does not appear in the
registry's author list for that identifier — a 13.3% error rate concentrated in records that
had no identifier when the resolver ran, which is where a title-only search most often returns
a review or a comment carrying the same title. A first-author guard rejects them.

*Values absent from the artifact said to produce them.* Reported in the demonstration set
below.

**Adversarial demonstrations.** Three, each run against the implementation.

| scenario | reported |
|---|---|
| results file edited after drafting | `broken_pins`, and the report fails although the edit made one further claim agree |
| extraction toolchain absent | affected quotations `unchecked`, reason `EXTRACTOR_MISSING`, report does not pass |
| registered plan edited after registration | `refuted`, reason `PLAN_CHANGED`, both digests named |

## 6. Related Work

| layer | prior art | what it lacks for this purpose |
|---|---|---|
| entity/activity/agent provenance | W3C PROV-O | no claim, evidence, or outcome |
| signed ordered attestation | in-toto, SLSA | software builds, not manuscript claims |
| research object packaging | RO-Crate | no verification engine |
| content-addressed pipelines | DVC | no claim binding, no registration |
| claim-to-evidence labels | FEVER, SciFact, CliniFact | statistical prediction against annotated gold labels, no artifact hashing |
| repository artifact auditing | adduce | no quotation or registration checking; one finding per repository |
| agent trace graphs | LEDGER | exposes claim-support paths for review; returns no verdict |

The claim-verification lineage defines the task this contract implements, as a prediction
problem: a model assigns a label to a claim given retrieved text, scored against human
annotation. The contract here trades statistical coverage for determinism. A passage is at a
byte offset in a file with a known hash, or it is not, and no model is in the loop for the
core check.

`adduce` audits whether a repository's code, configuration, and data agree with the numbers a
paper reports, and does so more thoroughly than this work does. Run against one of our own
manuscripts it reports, correctly, that *results are reported and run commands exist, but
nothing maps commands to specific results.* That mapping is what a `metric` evidence entry is.
The two tools address adjacent halves of one question and interoperate through a manifest
format rather than a shared dependency.

## 7. Limitations

The corpus is one researcher's, in mechanistic interpretability and computational biology, and
the quotation defect rates reported here are properties of that corpus.

Ordering — whether a confirmatory run postdates its registration — is specified and not
implemented. A manifest carrying run records is accepted and ignored.

The `protocol` backend verifies that a registered document has not changed. It cannot
establish that the registration is contemporaneous with what it claims, because the timestamp
is self-recorded. An external timestamp authority or a third-party registry closes this and is
not implemented.

Determinism is bought by requiring the manuscript to state where each value lives. A claim
whose evidence is not declared is reported as `no_evidence` rather than searched for, so
coverage is a property of what the author declared.

## 8. Conclusion

Quotations, reported values, and preregistered commitments differ in how a value is extracted
and in nothing else a reader needs. Specifying them as one contract makes a single engine
report on all three, and makes a fourth kind a registration rather than a rewrite. The
four-state outcome exists because the three-label taxonomy in the claim-verification literature
groups a check that found nothing with a check that never ran, and those have different
remedies. The distinction is cheap to specify and expensive to omit: in our own implementation
its absence produced a run that examined nothing and reported that nothing failed.
