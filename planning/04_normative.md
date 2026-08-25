# 4. Normative — artifacts should be stored in formats that declare their addressing

## Claim

An artifact should be stored in a format that declares how its values are addressed. That
property is absent at a measurable rate, and its absence — not model capability — is what
bounds automated checking.

## The reframe this position depends on

The obvious version does not survive: *"papers should make their numbers addressable"*
means, given that addressability is relational, *"addressable under my grammar."* That is
vendor behavior and no wording fixes it, because it is structural.

**Nor does "self-describing," the first attempt at a fix.** Test it against the case that
motivated it. The CORE-Bench stdout contains `test_accuracy:` and contains
`-------nb with ngram on Combined Corpus-----------------------`. Both names are in the
file. A reader can name the position — "the test accuracy in the nb-with-ngram section" — so
by that definition the artifact *is* self-describing, and the motivating example becomes a
counterexample.

What is missing is not names. It is **a declaration of how names compose into an address**.
The section is a row key and the label is a column, and nothing in the file says so; the
relationship is implied by layout and recovered by a human who reads it.

### The claim that survives

> An artifact should be stored in a format that declares its own addressing scheme.

CSV declares it: the header row names columns, each subsequent row is a record. JSON
declares it: keys address values. SQLite, npz, Parquet all declare it. **Plain text declares
nothing** — any addressing scheme over a log is inferred from layout, and a layout can be
correct, unique, and still not be a declaration.

Three properties make this the right form of the claim:

- **Grammar-independent.** It says nothing about which locator kinds exist. An artifact in a
  self-addressing format is reachable by tools that have not been written yet; a log is not.
- **Format-level, not file-level.** The property belongs to the format, so it is checkable
  without inspecting content and cannot be satisfied by one well-organized file.
- **It survives its own counterexample.** Stdout has names and no addressing scheme. That is
  exactly the distinction, stated in one sentence.

The specification appears only as evidence the property is precise enough to check. It is
not the ask.

## Why this can be written now

- **It does not depend on the rate.** The claim is true whether addressability is 20% or
  80%; the empirical work establishes urgency, not validity.
- **The specification already exists**, which is unusual for advocacy in this space. Most
  normative pieces about research practice have no artifact demonstrating the property is
  decidable.
- **Being unaffiliated is close to neutral here**, and arguably favorable. Open-science
  advocacy has substantially come from outside institutions; preregistration itself was
  pushed by people arguing against their own field's incentives.

## Two artifacts, different audiences

**LessWrong post.** Fast, no venue, and read by exactly the people running agent-mediated
research without a floor under it. Comments are free adversarial review from practitioners,
which is worth more than a desk rejection teaching the same lesson six weeks later. It
should go out **before** the paper so its objections are already answered in the paper.

The version that lands is self-implicating: *everyone doing agent-mediated research right
now, including me, is running without a floor — here is the floor, here is what it caught,
here is a case where it demoted my own result.* Diagnosis rather than dunking.

**Do not name specific labs.** It makes the post about the fight, costs standing with
people who are potential collaborators, and is unnecessary — "no lab I am aware of
publishes preregistrations or provenance records for agent-run experiments" is a checkable
claim about a category and strictly stronger than an insult about one company. It also has
to actually be checked before it is written.

**Position paper.** The longer form, spec'd separately in `exposure/SPEC_v3.md` — that
document covers the agent-exposure and preregistration argument, which is the same
normative family: what a confirmatory claim requires when an agent is in the loop.

## The three asks, in ascending cost to the asked

1. Emit structured output. One line in most analysis scripts.
2. Name the values a paper prints, in whatever format is already in use.
3. Ship the mapping from printed claim to stored position.

Only (3) resembles adopting a contract, and it is the one to put last and softest.

## The objection most likely to kill it

**"You built a tool and are now advocating a standard that happens to require it."**

The reframe is the answer, and it must be visible in the abstract rather than defended in
discussion. The paper's ask is a property; the specification demonstrates the property is
checkable; nothing requires the reader to install anything. If a draft's conclusion can be
paraphrased as "use my package," the reframe has failed and the draft should be cut rather
than softened.

## Second objection

**"A self-addressing format is a low bar most artifacts already meet."** This is where the
empirical work earns its place: 58.2% of one benchmark's questions are figure-reading, and
the entire numeric remainder of the capsule examined lived in a plain-text log. But that
evidence sits in positions 1 and 2, so the normative piece cites rather than establishes it,
and until those run the LessWrong post carries what evidence exists and says so.

## Sequencing

The post can go out on the strength of the argument plus the CORE-Bench pilot. The paper
should wait for position 1 to have run, because its second objection is otherwise
unanswerable.

## Next actions

1. Check whether anyone has published on provenance floors for agent-run experiments —
   the category claim must be verified before it is made.
2. Draft the LessWrong post; keep it self-implicating and unnamed.
3. Hold the paper until position 1 reports.
