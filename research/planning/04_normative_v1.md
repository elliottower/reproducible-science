# 4. Normative — scientific artifacts should be self-describing

## Claim

An artifact should let a reader name the position of each number it holds. That property is
currently absent at a measurable rate, and its absence — not model capability — is what
bounds automated checking.

## The reframe this position depends on

The obvious version of this claim does not survive: *"papers should make their numbers
addressable"* means, given that addressability is relational, *"addressable under my
grammar."* That is vendor behavior and no amount of careful wording fixes it, because it is
structural.

**Self-description is grammar-independent.** A CSV with headers has it. A JSON object has
it. A stdout log with 21 structurally identical sections does not — its values are uniquely
determined and have no name. That holds under any locator grammar, including ones nobody
has written.

So the ask is not adoption of a specification. It is a property, and the specification
appears only as evidence the property is precise enough to check.

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

**"Self-description is a low bar that most artifacts already meet."** This is where the
empirical work earns its place: 58.2% of one benchmark's questions are figure-reading, and
the numeric remainder had no names. But that evidence lives in positions 1 and 2, so the
normative piece cites rather than establishes it — and until those run, the LessWrong post
carries what evidence there is and says so.

## Sequencing

The post can go out on the strength of the argument plus the CORE-Bench pilot. The paper
should wait for position 1 to have run, because its second objection is otherwise
unanswerable.

## Next actions

1. Check whether anyone has published on provenance floors for agent-run experiments —
   the category claim must be verified before it is made.
2. Draft the LessWrong post; keep it self-implicating and unnamed.
3. Hold the paper until position 1 reports.
