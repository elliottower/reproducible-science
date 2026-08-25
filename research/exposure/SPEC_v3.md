# Position paper: confirmatory research with agents in the loop

Status: draft spec for a paper not yet written. Nothing here is frozen.

## 1. Thesis

Preregistration asks researchers not to look at outcomes before the analysis plan is
fixed. That rule treats **exposure** as the thing to prevent. Exposure is not the harm —
it is a proxy for the harm, and the proxy became the rule because with a human analyst
exposure is unobservable and its influence unfalsifiable. Nobody, including the analyst,
can demonstrate that a number they saw failed to shape a later decision.

Agents in the research loop change both halves. Exposure becomes **more frequent**, since
an agent opens files opportunistically in ways a careful human would not, and it becomes
**observable**, recorded by the harness rather than reported by the party whose conduct
is in question.

> Confirmatory status should depend on whether consequential decisions were fixed before
> the relevant results became available — not on whether some process happened to read
> them. Because agent contexts are observable and isolatable, preregistration can govern
> information flow rather than infer it.

The framework appears as reference implementation and proof of feasibility, never as a
premise the reader must accept.

## 2. Position relative to existing work

`Preregistration for Experiments with AI Agents` (Vaccaro, ICML 2026) covers experiments
where **agents are the subjects** — in-silico behavioral studies, LLMs answering economic
games. Its degrees of freedom belong to the human researcher: prompts, model choice,
decoding, retries, parsing.

| Vaccaro asks | This paper asks |
|---|---|
| how to preregister experiments *on* agents | how agents participate in *running* preregistered research |
| which model and prompting choices must be fixed | which agent actions and information flows must be fixed or logged |
| how agent responses are collected and analyzed | when an agent's exposure to results compromises confirmatory analysis |
| how outputs should be shared | how a contaminated context is quarantined from downstream decisions |

Do not claim nobody has written about agents in research; semi-autonomous systems already
run parts of scientific workflows. The defensible gap is narrower: **preregistration
doctrine for agents acting as operators or analysts** — accidental exposure, propagation,
scoped demotion, quarantine.

Prior-work search so far is preliminary. It is evidence of a gap, not a completed novelty
review, and the paper must not claim priority on the strength of one search.

## 3. Three concepts the field currently collapses

### Exposure

A context — human or agent — receives outcome information. Exposure is evidence of
possible contamination. It is not contamination.

### Propagation

Information from an exposure reaches a consequential choice: selecting an analysis,
changing an exclusion, modifying a hypothesis, editing the code that computes the
confirmatory result. Propagation is the mechanism that threatens confirmatory
interpretation.

### Selection

An exposed result influences whether an experiment, analysis, or report continues to
exist at all. Stopping, retrying, branching, withholding, and promoting one result over
another are all result-contingent actions.

Selection is a separate concept rather than an exception, because it defeats the rule
that would otherwise be tempting:

> "No analysis code changed, so no contamination occurred."

That rule is wrong. Silently abandoning an arm after a null is a data-contingent decision
even though nothing was edited.

## 4. Decision taxonomy

The normative core. Each row is a situation, a status, and the reason.

| Situation | Status | Rationale |
|---|---|---|
| Plan frozen before execution; no premature exposure | confirmatory | ordinary preregistered analysis |
| Agent saw results after all consequential choices were frozen | confirmatory, exposure logged | exposure cannot alter fixed choices |
| Agent saw results accidentally, was terminated, no downstream edge **within the monitored boundary** | confirmatory, quarantine event, assurance level stated | exposure isolated before propagation, so far as the boundary observes |
| Exposed context changed the analysis or selected follow-up work | exploratory for the affected decisions | outcome information propagated |
| Human saw results and then made discretionary choices | exploratory unless those choices were already fixed | cognitive propagation cannot be ruled out |
| Unregistered run, results sealed, plan fixed before authorized inspection | potentially confirmatory under §5 | order of plan and authorized access is demonstrable |
| Unregistered run, results seen before the plan was fixed | exploratory | registration was retrospective |
| A null caused an arm to be dropped | exploratory / selection deviation | continuation was data-contingent |
| Retry followed a predeclared failure rule | confirmatory | the retry policy was fixed in advance |
| Retry chosen after inspecting substantive outcomes | exploratory | the retry may optimize the result |

Demotion is **scoped to the affected decisions**, never automatic across a study. Blanket
demotion is a category error and it is why exposures get hidden rather than logged: if
disclosure costs everything, nobody discloses.

## 5. Prospective analysis registration over sealed outcomes

The controversial row, and it needs its own protocol because the tempting shortcut —
"it already ran, but I didn't look, so it counts" — does not survive review.

```
experiment runs
      ↓
outputs sealed: encrypted or access-controlled
      ↓
plan fixed and timestamped, by a context that cannot reach the seal
      ↓
authorized reveal
      ↓
registered analysis executes
```

What this licenses and what it does not:

- The **analysis** may be prospectively registered.
- The **completed experimental design cannot be retroactively preregistered.** Sample
  collection, stopping, measurement, exclusions, and allocation were already decided.
- Earlier decisions remain exploratory, or fixed by other evidence.
- The system must demonstrate the registering context had no path to the sealed outputs.

Naming it precisely — *prospective analysis registration over sealed outcomes*, not
preregistration — is what makes the claim defensible rather than convenient.

## 6. Quarantine

A fresh context window is not quarantine. Quarantine is a property of the dependency
graph, and claiming it requires seven things:

1. **Predeclared access policy.** Which context may read plans, outcomes, expected
   answers, prior decisions.
2. **Exposure event recorded.** Artifact, digest, time, context, operation, and whether
   content reached a human.
3. **Context termination.** The exposed context does not author confirmatory analysis or
   select subsequent work.
4. **Clean replacement.** A new context receives the frozen plan and permitted inputs, not
   the exposed transcript.
5. **Dependency enforcement.** Analysis artifacts descend only from permitted contexts and
   inputs — including prompts, memory stores, summaries, caches, parent-agent messages,
   and human instructions.
6. **Scoped disposition.** Demote affected decisions, not the study.
7. **The human rule.** If outcome information reaches a human who subsequently exercises
   relevant discretion, non-propagation cannot be *demonstrated*. Those decisions
   therefore cannot receive the quarantine-based protection available to isolated
   computational contexts. This is an epistemic rule about what can be shown, not a claim
   that propagation occurred.

Point 7 is not a caveat, it is a boundary. Infrastructure isolates computational contexts;
it does not erase a result from a person's memory. The paper must never use agent
observability to license a claim about human unlearning.

## 7. Preregistration by default

The practical argument is economic, and it has actually changed:

- Detailed preregistration used to cost a day of writing.
- An agent drafts a structured plan in seconds.
- Deterministic infrastructure freezes its digest and timestamp before execution, and
  later compares the run against the declaration.
- When marginal cost approaches zero, the default should flip.

Stated carefully, because an agent-drafted plan is not automatically a good one:

> Agents make preregistration cheap by drafting concrete declarations; humans authorize
> the consequential choices; deterministic infrastructure freezes and verifies the result.

**Models propose; humans authorize; infrastructure records and verifies.**

### 7.1 Four levels, not one

"Preregister everything" is too blunt. Registration comes in tiers with different costs and
different authority:

| Level | Fixes | Can an agent generate it? |
|---|---|---|
| **Run** | inputs, code version, environment, command | yes, for nearly everything |
| **Analysis** | outcome, estimator, exclusions, transformations, inferential rule | draft yes, authorize no |
| **Decision** | stopping, retry, branching, promotion criteria | draft yes, authorize no |
| **Full study** | hypotheses, design, collection, analysis | no |

The defensible proposal is **default machine-generated run registration**, with human
authorization for inferential and decision commitments. An agent can make registration
cheap; it cannot turn an exploratory thought into a confirmatory study.

This also dissolves most of §3. If every experiment carries a frozen plan predating its
run, an agent printing an unexpected number contaminates nothing, because the analysis was
already fixed. The exposure question only bites where something ran unregistered.

## 8. Mechanism, and what it can currently license

Three things are mixed together here and the paper must not let them blur: a logger that
exists, a prevention layer that does not, and an attestation story that is a proposal.

### 8.1 Assurance levels

| Level | Evidence available | Claim it licenses |
|---|---|---|
| **Observational** | heuristic tool-call log | a recorded exposure occurred |
| **Procedural** | context terminated, replacement created | the declared quarantine procedure was invoked |
| **Controlled** | all relevant I/O passes an enforced policy | no prohibited access was observed within the boundary |
| **Attested** | controlled runtime, immutable logs, context and artifact lineage | the confirmatory outputs have no recorded dependency on prohibited inputs |

**The shipped hook sits between observational and procedural.** §4 and §6 describe
controlled and attested quarantine. A position paper may propose systems it has not built;
it may not narrate the proposal as though it were the prototype, and every claim in the
taxonomy must carry the level it was established at.

### 8.2 The monitored boundary

"No downstream edge" is meaningless without saying where the edges were watched. The
boundary must be declared per study, and a `PostToolUse` hook does not see:

- paths constructed at runtime inside a shell command
- reads performed by Python, R, a subprocess, a container, or over the network
- values copied into prompts, task descriptions, summaries, or memory stores
- parent-to-subagent messages
- a human paraphrasing an exposed number
- cached tool results
- anything read outside Claude Code

So the licensed form is **"no downstream edge within the declared and monitored
boundary,"** and the boundary is part of the claim rather than background.

### 8.3 What is built

`exposure/hooks/exposure_log.py` — a Claude Code `PostToolUse` hook that receives each tool
call as JSON on stdin and appends JSONL: timestamp, session, cwd, tool, paths. The model
neither produces this record nor can edit it. **Observational prototype.**

Not built: the `PreToolUse` guard that blocks reads of declared outcome paths, per-context
read/write policy, dependency enforcement over analysis artifacts, and attestation.

### 8.4 The log is one-sided

It establishes that a path *was* read. Because extraction is heuristic it cannot establish
that one was not. "This exposure occurred and these actions followed" is supportable;
"no exposure occurred" is not.

### 8.5 It is a bounded operational log, not a ledger

The hook rotates at a size cap and keeps one previous generation. That is disk hygiene, and
it is **incompatible with calling the file append-only**: anyone can delete or rewrite the
rotated segment, and the live file cannot reveal that history was removed.

Describe it honestly as a bounded operational log. Becoming an evidence ledger requires
rotation to close each segment with its digest, open the next with the previous segment's
digest, record the rotation as an event, and anchor segment digests externally — a commit,
a registration, or a timestamping service. `results` already does this for run ledgers, so
the work is wiring rather than design.

Until then the lifecycle is:

```
global operational log
      ↓  identify the study interval
extract the relevant records
      ↓  record source-segment digest and extraction rule
commit the study-specific evidence
      ↓
routine global rotation continues
```

One global log stays the source; a study's evidence is a derived artifact with its
provenance recorded.

### 8.6 Coverage is a parameter

Report what fraction of tool calls the hook observed, per study.

### 8.7 The protocol stays outside the contract

An executable form of §4 and §6 — per-context read/write permissions, exposures recorded
against them — belongs in this paper as a proposed protocol. It must **not** enter the
Evidence Contract: it introduces agent contexts, permissions, exposure events, and
downstream causality, which are new objects beyond claim verification. Let real cases
reveal the abstraction.

## 9. Evidence

A practitioner case series, not an essay. The authority is the record, not the author.

**Do not claim a corpus size that cannot be enumerated.** "30+ papers" needs a defined
unit and a list. Build the table from records that exist:

| Field | Purpose |
|---|---|
| study id | stable, anonymized where needed |
| agent role | planning, execution, analysis, writing, review |
| exposure type | accidental read, displayed output, cached result, prior run |
| exposed party | isolated agent, persistent agent, human |
| plan status | frozen, amendable, absent |
| downstream action | none, code edit, branch selection, rerun, reporting change |
| mitigation | quarantine, amendment, demotion, rerun |
| classification | confirmatory, qualified, exploratory |
| evidence | commit, digest, timestamp, transcript segment, ledger event |

Publish the taxonomy, counts, decision rules, and deidentified examples. Private
transcripts stay private.

**The paper must show at least one case where the rule demoted the author's own result.**
A rule that has never bitten its proposer is a rationalization, and §10's first objection
is unanswerable without it.

## 10. Objections, conceded rather than deflected

| Objection | Response |
|---|---|
| The author has an interest in this conclusion | true; the rule must be able to demote his own work, and the paper must show a case where it did |
| Seeing a result changes cognition | correct for humans; the paper claims control over isolated computational contexts only |
| A fresh subagent can inherit leaked information indirectly | correct; §6.5 requires dependency control over prompts, memory, summaries, caches, and parent messages |
| This privileges technically sophisticated researchers | correct; the ask is for integration into common environments and sane defaults, not adoption of one package |
| Preregistering everything yields boilerplate | correct; cheap drafting reduces cost, it does not establish quality. Default registrations still need falsifiable hypotheses, outcomes, exclusions, stopping and retry rules |
| Agents can fabricate timestamps and logs | correct; content hashes, external timestamps, append-only ledgers, optional signed attestation. Self-reported agent traces are not authoritative |
| Scoped demotion invites convenient compartmentalization | correct; propagation boundaries are declared before exposure where possible, and uncertain boundaries classify conservatively |
| This is just registered reports | registered reports are stronger, because review precedes results. This improves ordinary agent-mediated work and claims no equivalence |
| Exposure *is* the harm, since self-deception is undetectable | coherent, and the answer is not that operators are trustworthy. The claim is available only when a machine-produced log supports it, and unavailable otherwise. A norm becomes a mechanism |

## 11. Structure

1. Agents changed the workflow
2. What preregistration protects, and what it uses as a proxy
3. Exposure, propagation, selection
4. The decision taxonomy
5. Sealed outcomes and prospective analysis registration
6. Quarantine as a dependency property
7. Preregistration by default
8. A machine-checkable protocol
9. Practitioner case series
10. Limits and failure modes
11. What registries, journals, and reviewers should ask for

## 12. Title

Not "Preregister the Agent" — it is a slogan, and it misdescribes the paper. You do not
preregister the agent; that is closer to Vaccaro's subject.

| Candidate | Note |
|---|---|
| **Confirmatory Research with Agents in the Loop** | plain, accurate, noun phrase |
| Exposure, Propagation, and Confirmatory Status in Agent-Mediated Research | names the three concepts; long |
| Preregistration as an Execution Protocol | names the shift; abstract |
| Information Flow Control for Preregistered Research | accurate, borrows a security frame that may mislead |

Working choice: **Confirmatory Research with Agents in the Loop**, subtitle naming the
protocol.

## 13. Asks

- Registries accept an exposure log as a registration attachment.
- Journals ask whether an agent was in the analysis loop and whether exposures were
  logged, as they now ask about data availability.
- Reviewers treat a disclosed exposure with a clean propagation record as weaker evidence
  against confirmatory status than an undisclosed gap in the record.
- Preregister by default.

## 14. Venue

arXiv preprint, deposited only once the paper has a serious prior-work section, the
normative model, several real deidentified cases, a versioned protocol, a reference
implementation demonstration, explicit limits, and no unearned priority claim.

Journal targets, in order of fit: Meta-Psychology; AMPPS; Royal Society Open Science;
an ICML position track, where Vaccaro landed and the audience is primed.

## 15. Do not

- Fold this into the benchmark paper.
- Change the Evidence Contract schema around it.
- Argue that any accidental agent read invalidates a study.
- Argue that any isolated agent read is harmless.
- Equate a fresh context window with proven quarantine.
- Claim human exposure can be erased.
- Describe retrospective registration as ordinary preregistration.
- Make adoption of the package the conclusion.
- Use the author's authority as the principal evidence. Use the records.

## 16. Sequence

Before routine logging or any publishable statistic:

1. Preserve `SPEC_v1.md` and `SPEC_v2.md` as provenance.
2. Freeze the one-page position declaration below.
3. **Threat-model the logger** — omissions, sensitive data, tampering, rotation, context
   inheritance.
4. Freeze a minimal exposure-event schema.
5. Build a three-case controlled demonstration: clean execution; exposed-and-quarantined
   context; exposure forcing scoped demotion.
6. Only then enable routine logging and open the case series.

**Step 3 gates step 6, and not for tidiness.** A global logger records every path an agent
touches, and those paths carry client names, cohort identifiers, embargoed dataset
locations, and directory structures that are themselves disclosive. Enabling it across all
work before reviewing what it captures creates a new confidentiality surface in service of
a paper about research hygiene.

Step 4 gates step 5 for the paper's own reason: collecting statistics under a schema that
later changes is exactly the exploratory-presented-as-confirmatory move the paper argues
against. The paper's thesis applies to the paper.

## 16.1 Position declaration

A one-page position declaration, frozen with `prereg` before the prose is drafted — which
is the paper's own thesis applied to itself:

> Research agents should preregister experiments by default. Confirmatory status is
> evaluated at the level of preregistered consequential decisions and demonstrated
> information flow. Accidental agent exposure does not automatically demote a study;
> exposure that propagates into analysis, continuation, or reporting decisions demotes the
> affected claims. Quarantine preserves confirmatory analysis only where the exposed
> context has no downstream path to those decisions. Human exposure remains categorically
> harder, because non-propagation through cognition cannot be verified.
