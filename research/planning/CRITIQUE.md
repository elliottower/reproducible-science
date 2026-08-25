# Critique of the four specs

Adversarial pass. Ordered by severity within each position. Items marked **FATAL** would
sink the position as currently written; **STRUCTURAL** requires redesign; the rest are
repairs.

---

## 1. Descriptive

### FATAL — H1 may be underpowered for its own threshold

The preregistration states that 60 articles resolve the mean to roughly ±0.10, and that the
sample "separates 0.20 from 0.50 and nothing finer than about ten points."

H1's evidential criterion is a **one-sided 95% upper bound below 0.25**. With ±0.10
precision, that bound clears 0.25 only if the point estimate lands near 0.15 or lower. If
the true rate is 0.22 — comfortably supporting the descriptive target — the criterion
fails, and H1 is reported unsupported while being true.

The preregistration anticipates this ("where a target holds and its criterion does not,
both are reported") but that is a reporting rule, not a fix. Either the threshold moves,
the sample grows, or H1 is knowingly registered as a test the design may not be able to
pass.

Worth noting the design is honest about this in a way most are not. The problem is that
the honesty is in the sample-size section and the consequence is in the inference section,
and nothing connects them.

### STRUCTURAL — "coverage" and "addressability" are used as if interchangeable

H1 measures "mean article coverage." H3 measures "mean article addressability." The
Indices section defines article coverage but never defines addressability separately. If
they are the same quantity over different subsets, one word should be used. If they differ,
the difference is undefined and H3 cannot be scored.

### The harness cannot be built on frame articles

`results/` and `tests/` are empty; the coding harness does not exist. Building it after the
freeze is fine. Building it *against articles in the frame* is contamination, and the
blinding rule — no searching an artifact for the printed numeric string — has to be
enforced by that harness, which means the harness must be exercised on something.

Nothing states where the development articles come from. They must be drawn from outside
the 60, and that exclusion should be recorded before the harness is written.

### Where H1's 0.25 came from is unstated

The preregistration derives H2's 0.90 target from foreknowledge, explicitly and well. H1's
0.25 appears without derivation. A registered threshold with no rationale invites the
reading that it was chosen to be passable.

---

## 2. Diagnostic

### FATAL — one run per configuration is not a comparison

`written_accuracy 0.722` and `vision_accuracy 0.853` come from a single run of a single
agent. Run-to-run variance for LLM agents is documented as large — it is a central finding
of the judge-reliability literature this project cites elsewhere.

Two point estimates from n=1 with no interval do not support a claim about which is higher,
let alone about mechanism. The Gemini run inverts the ordering (0.444 written, 0.412
vision), which is either noise or a model-dependent effect, and one run each cannot tell
those apart.

**This is the most serious problem across all four specs**, because the surprising finding
that makes position 2 worth writing is currently a difference between two numbers that have
no error bars.

Repairable: nine Opus-family runs are published, plus other agents. Pooling across runs and
reporting per-run variance turns this into a real comparison. Until that is done, the
inversion is an observation, not evidence.

### STRUCTURAL — the denominators are unknown

`written_accuracy` and `vision_accuracy` are reported over unstated question counts. If
vision spans 138 questions and written spans 99, the two rates have different precision.
Whether they are per-question or per-task is also unstated. Neither can be assumed from the
field names.

### The execution-conditioned test may not separate the accounts

The proposed discriminator — does written still trail vision among tasks where execution
succeeded — assumes execution success and parse difficulty are independent. They are not. A
task can execute and still emit output the agent cannot parse, which *is* addressability;
it can also emit parseable output the agent then reasons about wrongly, which is capability.
Conditioning on execution removes one confound and leaves the other.

With 35 successful tasks, the subset carrying written questions is likely under 20. That is
thin for a difference test even before variance is accounted for.

### The claim is causal and the design is observational

"The bottleneck is documentation practice" is a causal claim supported by a correlation
across two question types that differ in more than addressability. An intervention would
settle it: take capsules with unaddressable stdout, emit the same values as JSON, and
re-run the agent. If written accuracy rises, the mechanism is established. That is a real
experiment, it is affordable, and it is not currently in the spec.

---

## 3. Instrument

### FATAL — no plan for the second implementation, and the position collapses without it

The spec says "find a second implementer" and calls it the load-bearing requirement, which
is right, and then offers nothing on how. A solo unaffiliated author asking someone to
implement a specification for free is a large ask with a low base rate, and if it does not
happen the position reduces to "my code agrees with itself."

Three fallbacks the spec should evaluate rather than ignore:

- **A second implementation by the same author in a different language.** Weak — shared
  misreadings of the spec survive — but non-zero, and it catches spec ambiguity that a
  single implementation hides.
- **An implementation generated from the specification alone by a model that has not seen
  the code.** Cheap, genuinely independent in the sense that matters (no shared
  implementation assumptions), and an interesting result either way: if a competent model
  cannot produce a conforming implementation from the spec, the spec is underspecified,
  which is itself a finding about the artifact.
- **Partial conformance by an existing tool.** If some other checker can be driven to
  satisfy a subset of fixtures, that subset is independently validated.

### The conformance suite tests the implementation against the spec, and nothing tests the spec against reality

A specification can be perfectly implementable and describe nothing anyone needs. Position
1 is the only thing that tests whether the grammar reaches real artifacts, so position 3
depends on position 1 more than the spec admits — it is not the independent foundation it
presents itself as.

### "Determinism measured across two environments" is weaker than it sounds

Two environments chosen by the author, running the same implementation, is close to a
tautology. The Nix comparison flatters: 709,816 packages across a distribution's build farm
is a different kind of evidence than one tool run twice. Either scope the claim to
"identical across reruns and across these two environments," or do not invoke Nix.

---

## 4. Normative

### FATAL — "self-description" may collapse under pressure

The reframe claims self-description is grammar-independent. Test it against the case that
motivated it.

The CORE-Bench stdout contains `test_accuracy:` and contains
`-------nb with ngram on Combined Corpus-----------------------`. **Both names are present
in the file.** A reader can name the position: "the test accuracy in the nb-with-ngram
section." So by the stated definition — an artifact should let a reader name the position
of each number it holds — that artifact *is* self-describing, and the example the whole
reframe rests on becomes a counterexample to it.

What is actually missing is not names. It is a **schema**: a declaration of how names
compose into an address. The section is a row key and the label is a column, and nothing in
the file says so — that relationship is implied by layout and recovered by a human reading
it.

That is a more precise concept and it is repairable, but "self-describing" as written does
not survive its own motivating example, and the whole normative position rests on it.

The repaired claim is roughly: *an artifact should declare how its values are addressed,
not merely contain the words that address them.* That is closer to "ships a schema" than to
"is self-describing," and it is a larger ask — which weakens the "one line in most scripts"
framing in the three-asks section.

### Publishing the argument before the evidence carries a retraction risk

The spec says the LessWrong post should precede the paper so its objections are answered in
advance. That is right about review economics and wrong about exposure: a public argument
that position 1 later contradicts becomes a public correction, and the audience for the
post is the audience for the paper.

Mitigation is to write the post as a question rather than a thesis — here is what I found
in one benchmark, here is what I think it means, here is the study that will test it. That
keeps the free review and loses nothing if the rate comes back high.

### The category claim is unverified and load-bearing

"No lab I am aware of publishes preregistrations or provenance records for agent-run
experiments" is stated as checkable and strictly stronger than naming a company. It has not
been checked. Until it is, it cannot appear in either artifact.

---

## Cross-cutting

**Positions 2 and 4 both currently rest on the same single observation** — the written/vision
inversion from one run. If that inversion is noise, position 2 loses its finding and
position 4 loses its motivating example in the same stroke. Nine more runs are published and
cost minutes to pull; doing that before either position is drafted further is the highest
-value action available.

**Three of four positions depend on position 1 having run.** The spec presents them as
parallel. They are not: 2 needs the rate to interpret the bottleneck, 3 needs it to show the
grammar reaches anything, 4 needs it to answer "isn't this a low bar." Only position 1 is
genuinely independent, and it is the one not yet frozen.
