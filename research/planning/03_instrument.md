# 3. Instrument — a specification precise enough to make "addressable" decidable

## Claim

The contribution is a contract under which "this claim is addressable in this artifact" has
a determinate answer, computed identically by independent implementations. Everything else
in this body of work is demonstration.

## Why this position exists separately

Positions 1 and 2 both depend on "addressable" meaning something exact. If it does not,
position 1 measures nothing and position 2 explains nothing. This is the position that
makes the others sayable, and it is the most durable of the four — a specification with a
conformance suite outlives any particular measurement.

It is also the least exciting, which is why it must not be the paper that carries the
argument.

## How specifications are validated

Not by accuracy benchmarks. By conformance suites against independent implementations.
W3C's rule for exiting Candidate Recommendation is "at least two independent
implementations for each mandatory feature"; JSON Schema ships a language-agnostic suite of
6,000+ declarative cases across 45 feature categories; CommonMark's specification and its
test corpus are the same artifact.

The property being demonstrated is not "does this make correct judgments about ambiguous
input" but "given unambiguous input, does this implementation compute the mandated output."
That is exactly the shape of `Backend.check(claim, evidence, path) -> Decision`.

## What exists

- `packages/repro/tests/conformance/` — fixture scaffolding, partially populated.
- A locator grammar pinned by digest, already cited by position 1's preregistration.
- Mutation operators specified in `benchmark/SPEC.md` §4 with known-correct outcomes.

## What is missing, in order of difficulty

1. **A second independent implementation.** The load-bearing requirement, and the one that
   cannot be faked. Without it the claim is that the code agrees with itself.

   A solo unaffiliated author asking someone to implement a specification for free has a low
   base rate, so the fallbacks matter, ordered by how much independence they buy:

   - **Generated from the specification alone by a model that has not seen the code.**
     Independent in the sense that matters — no shared implementation assumptions — and
     cheap. Informative either way: if a competent model cannot produce a conforming
     implementation from the specification, the specification is underspecified, which is a
     finding about the artifact rather than a failed experiment.
   - **Partial conformance driven out of an existing tool.** Whatever subset of fixtures
     another checker satisfies is independently validated, and the boundary is informative.
   - **A second implementation by the same author in a different language.** Weakest, since
     shared misreadings survive, but it still catches specification ambiguity that a single
     implementation hides.
2. **Fixture coverage of the mutation operators.** Each operator in §4 should appear as a
   declarative case with its expected outcome and reason code.
3. **Determinism measured rather than asserted.** Currently a docstring claim. The Nix
   template is the model: 709,816 packages rebuilt, 69–91% bitwise reproducible, and —
   the part that matters — ~15% of failures traced to embedded build dates. Report the rate
   *and* the root causes of the residual.
4. **An interoperability report** on the W3C pattern, published alongside.

## The determinism scope, which must be stated

The verifier is deterministic. **The pipeline is not, when a model authors the manifest.**
Same-manifest determinism is the claim; end-to-end determinism is not, and a
formal-methods reader will go straight at any sentence that blurs them.

## The objection most likely to kill it

**"This is a Pydantic schema around three small scripts."**

What answers it: a language-independent specification, a suite a third party can implement
against without seeing the code, a demonstration that adding an evidence kind requires
registering a backend rather than editing the engine, and mutation tests showing each
injected defect produces its specified decision.

What does not answer it: a test count.

## Second objection

**"You use 'contract' and 'verification' without formal semantics."** Two honest options:
define verification operationally and avoid the phrase "formal verification" entirely, or
supply inference rules per decision plus invariants — determinism, and failure
monotonicity. The first is sufficient for the venue; the second is a different paper.

## Venue

A software or systems track, or a specification deposit with a DOI that positions 1, 2, and
4 cite as method. It may not need to be a paper at all — a versioned, digest-pinned
specification with a conformance report is citable, and that may serve the other three
better than a publication would.

## Next actions

1. Populate conformance fixtures for every mutation operator.
2. Find a second implementer — the only step with an external dependency, so start it first.
3. Run the determinism measurement across two environments and report residual causes.
