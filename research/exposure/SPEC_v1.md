# Position paper: preregistration when the analyst is an agent

Status: draft spec for a paper not yet written. Nothing here is frozen.

## 1. The claim

Preregistration asks researchers not to look at outcomes before the analysis plan is
fixed. That rule treats **exposure** as the thing to prevent. Exposure is not the harm;
it is a proxy for the harm, which is **propagation** — an analyst's knowledge of an
outcome shaping a subsequent analytic choice.

The proxy became the rule for a good reason. With a human analyst, exposure is
unobservable and propagation is unfalsifiable: nobody, including the analyst, can
demonstrate that a number they saw failed to influence a later decision. A rule written
on propagation would have been unenforceable, so the field wrote it on exposure.

Agents in the research loop change both halves of that. Exposure becomes **more
frequent** — an agent opens files opportunistically, in ways a careful human would not —
and it becomes **observable**, recorded by the harness rather than reported by the party
whose conduct is in question.

The paper's claim: where a plan's digest predates a logged exposure and nothing
downstream of that exposure authored the analysis, the confirmatory status of the
affected result holds. Not because the operator says they ignored it, but because the
record shows the analysis had no edge from it.

## 2. Why this is not the paper that already exists

`Preregistration for Experiments with AI Agents` (Vaccaro, ICML 2026) extends
preregistration to studies where **agents are the subjects** — in-silico behavioral
experiments, LLMs answering economic games. The degrees of freedom it catalogs belong to
the human researcher: prompt wording, model selection, decoding parameters, retry
policy, response parsing.

This paper addresses the other side: **agents as operators**, and what a registration
means when the party exposed to an outcome was the instrument rather than the
participant. Vaccaro is the anchor citation, not the competitor — that paper establishes
the topic is live at a top venue and that preregistration norms must be restated for
agentic research at all. This one restates a different clause.

## 3. Argument

### 3.1 The assumption

Preregistration's operational rule assumes an analyst who (a) is a person, (b) chooses
what to look at, and (c) cannot prove what they did not use. All three fail for an agent.

### 3.2 Exposure is not propagation

Distinguish four events that current doctrine collapses:

| Event | Observable | Propagates by default |
|---|---|---|
| Agent reads an outcome file | yes, via harness | only if that context later authors analysis |
| Agent prints an outcome into the transcript | yes | only if the human reads it |
| Human reads the printed outcome | no | yes — the human keeps writing the paper |
| Analysis authored after either | yes | this is the harm |

The user-visibility distinction matters, but not because human eyes are special. It
matters because the human is the party who continues to make analytic choices, so a
human exposure has a guaranteed downstream edge, and a discarded agent context does not.

### 3.3 The rule

A result retains confirmatory status when all three hold:

1. The plan's digest predates the exposure.
2. The exposure is in the log, disclosed rather than discovered.
3. No context downstream of the exposure authored, modified, or selected the analysis.

Failing (3) demotes **the affected analyses**, not the study. Blanket demotion is a
category error, and it is the reason exposures get hidden instead of logged: if the
penalty for disclosure is losing everything, disclosure stops.

### 3.4 Quarantine

The mitigation, and the reason this is a protocol rather than an argument: a contaminated
context does not author analysis. Spawn a fresh context, discard the contaminated
transcript, and the exposure has no downstream edge — demonstrably, because the authoring
context's own log shows no read of the outcome.

This is enforceable in a way "I ignored it" is not. The claim being made is about a
recorded edge in a graph, not about the operator's cognition.

## 4. Mechanism

The argument only works if exposure is actually logged, so the paper ships the logger.

`exposure/hooks/exposure_log.py` runs as a Claude Code `PostToolUse` hook, receives each
tool call as JSON on stdin, and appends JSONL: timestamp, session, tool, paths. The model
does not produce this record and cannot edit it. A `PreToolUse` variant can block reads of
declared outcome paths outright (exit code 2), making prevention the default and the log
the fallback for when prevention is off.

Three properties the paper must state plainly:

- **The log is one-sided evidence.** It establishes that a path *was* read. Because Bash
  path extraction is heuristic, it cannot establish that one was *not*. Claims of the form
  "no exposure occurred" are therefore weaker than claims of the form "this exposure
  occurred and here is what followed."
- **Append-only is doing work.** A log the operator can rewrite proves nothing. It should
  be hash-chained, which is what `results`' ledger already does.
- **Coverage is a parameter, not a guarantee.** Report what fraction of tool calls the
  hook observed.

## 5. Evidence

The paper is a practitioner report, not an essay. Its authority is the corpus.

- A taxonomy of real exposure events across a preregistered corpus (30+ studies), each
  classified by the §3.2 table.
- For each, what was done: quarantined, scoped demotion, or no action, and why.
- Base rates: how often agents read outcome files unprompted, and what fraction of those
  reads had a downstream authoring edge.
- The one worked case that most tests the rule — an exposure where the honest answer was
  demotion.

Without the base rates this is an opinion piece, and an opinion piece from an unaffiliated
author is easy to desk-reject. With them it is a report nobody else can write, because
nobody else has the corpus.

## 6. Limits, stated in the paper rather than found by a reviewer

**The selection carve-out.** Exposure-without-propagation covers analytic choices. It does
not cover selection: if a peeked-at null causes an arm to be quietly dropped, ignoring the
number was never available, because the decision to proceed *was* the propagation. This is
the sharpest objection and the paper should raise it first.

**The self-serving reading.** An author with a preregistered corpus arguing that certain
exposures do not invalidate preregistrations has an obvious interest. The mitigation is
that the rule must be capable of demoting the author's own results, and the paper must
show a case where it did.

**The unfalsifiability objection, taken seriously.** A reader may hold that exposure *is*
the harm, precisely because self-deception is undetectable. That position is coherent, and
the answer is not that operators are trustworthy. It is that the claim on offer is not
about trust: it is available only when a machine-produced log supports it, and unavailable
otherwise. A norm becomes a mechanism.

**Log coverage.** Heuristic extraction misses runtime-constructed paths, heredocs, and
shell-expanded globs.

**Scope.** This concerns exposure during analysis. It says nothing about training-data
contamination, benchmark leakage, or model memorization, which are separate literatures
with their own remedies.

## 7. What it asks for

Concrete asks make a position piece actionable rather than hortatory:

- Registries should accept an exposure log as an attachment to a registration.
- Journals should ask whether an agent was in the analysis loop, and if so whether
  exposures were logged — the way they now ask about data availability.
- Reviewers should treat a disclosed exposure with a clean propagation record as weaker
  evidence against confirmatory status than an undisclosed gap in the record.
- Preregister by default. The exposure question only bites when something ran
  unregistered, and the cost of freezing a plan has fallen to seconds. The rarity of
  preregistration reflects the friction of an earlier era, not a considered position.

## 8. Venue

Position and methods pieces, in rough order of fit:

| Venue | Fit | Note |
|---|---|---|
| Meta-Psychology | high | publishes preregistration doctrine, open, methods-focused |
| AMPPS | high | the standing venue for preregistration methodology |
| Royal Society Open Science | medium | accepts methods commentary |
| PLOS Biology essay / perspective | medium | broad readership, editorial gate |
| ICML position track | medium | where Vaccaro landed; audience already primed |

MetaArXiv preprint first regardless, since the argument's value is in being available
while agentic analysis is being normalized.

## 9. Open questions

- Whether the propagation rule needs a formal statement (a graph condition over the
  exposure log and authorship record) or whether prose suffices for this venue.
- Whether "context" is the right unit of quarantine, or whether it should be finer.
- Whether to report agent-exposure base rates from the corpus at all, given they also
  reveal how often the tooling misbehaves.
- Whether this merges with the contract paper's registration-ordering material or stays
  separate.
