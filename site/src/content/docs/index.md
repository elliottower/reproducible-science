---
title: Overview
---

<p class="venue-note">
  <span>Accepted at AI for Science @ NeurIPS 2026</span>
  <a href="/paper/reproducible_science.pdf">Paper</a>
  <a href="/slides/reproducible_science_slides.pdf">Slides</a>
</p>

Every claim in a paper comes from somewhere.

**A declarative, continuous, machine-checkable provenance layer for research claims, throughout
the whole research lifecycle.**

- **Recording:** every result is tied to the run that produced it, at the time it's produced.
- **Verifying:** every number against its results file, every quotation against its source, every analysis against its plan.
- **Agents:** reproducible by construction. The record is made as the agent works.

```bash
pip install reproducible-science
```

```text
/plugin marketplace add elliottower/reproducible-science
/plugin install reproducible-science@reproducible-science
```

<img class="framed narrow" src="/figures/fig-commands.png" alt="prereg, results and citations each feed repro verify" />

Like `git status`, for research provenance. In Claude Code, the state of a project's records
sits above the prompt, with a warning when something no longer matches.

<img class="framed narrow" src="/figures/status_number_mismatch.png" alt="Four status rows above the prompt and a warning that one number is mismatched" />

| tool | what it does |
|---|---|
| [`prereg`](/tools/prereg/) | freezes a plan before running, records what changed after |
| [`results`](/tools/results/) | seals inputs, records outputs, binds claims to runs |
| [`citations`](/tools/citations/) | checks that quotations resolve in the sources they cite |
| [`repro`](/tools/repro/) | verifies a paper's plans, numbers and quotations in one report |

Each is an independent distribution with its own public API, so installing citation
verification never drags in a preregistration tool. They live in one repository because a
change that crosses two of them should be one commit rather than a release sequence.

## The problem

AI tooling makes it quick to generate hypotheses, run analyses and draft manuscripts.
Verification and provenance have not kept pace:

1. Verifying that a finished paper agrees with the artifacts behind it takes manual or agentic
   checking, which is expensive and difficult to audit.
2. Verification usually reports no denominator for the sources or artifacts checked.
3. A verification snapshot goes stale quickly, and a second run is not guaranteed to find the
   same issues.
4. More experiments mean more researcher degrees of freedom and post-hoc analysis, even when
   unintentional, or done by an agent.
5. Verification is typically done after the fact, and does not cover every step of the research
   lifecycle.

As agents take over more of the research lifecycle, the artifacts they leave behind are worth
only as much as the claims inside them can be verified.

## The chain

A number in a manuscript names a claim. The claim names a run. The run names its outputs,
hashed when they were recorded. The inputs were hashed before the run started.

```bash
prereg freeze                          # lock the plan
results seal PREREG.md analysis.py     # hash the inputs
results run output.json --run-id exp_001
results claim "ICC = 0.42" --run-id exp_001 --location "Table 2"
repro verify                           # check the whole chain
```

## Limitations

It does not decide that a paper is reproducible. It checks relations:

- that a claim addresses an artifact;
- that the artifact is the one that was pinned;
- that the addressed value is what the manuscript prints;
- that a confirmatory run started after the plan it names was registered.

Everything it cannot establish is reported as unestablished rather than assumed.
