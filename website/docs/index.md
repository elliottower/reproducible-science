---
title: Overview
sidebar_position: 0
slug: /
---

# Reproducible Science

Four command-line tools that bind what a paper says to what its artifacts contain. Freeze a
plan before running it, seal the inputs, record the outputs, bind every number in the
manuscript to the run that produced it, and check that quoted passages appear in their
sources.

```bash
pip install reproducible-science
```

| tool | install | what it does |
|---|---|---|
| [`prereg`](tools/prereg) | `pip install prereg` | freezes a plan before running, records what changed after |
| [`citations`](tools/citations) | `pip install citations` | checks that quotations resolve in the sources they cite |
| [`results`](tools/results) | `pip install results-cli` | seals inputs, records outputs, binds claims to runs |
| [`repro`](tools/repro) | `pip install reproducible-science` | verifies declared evidence against hash-pinned artifacts |

Each is an independent distribution with its own public API, so installing citation
verification never drags in a preregistration tool. They live in one repository because a
change that crosses two of them should be one commit rather than a release sequence.

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

## What it does not do

It does not decide that a paper is reproducible. It checks relations: that a claim addresses
an artifact, that the artifact is the one that was pinned, that the addressed value is what
the manuscript prints, and that a confirmatory run started after the plan it names was
registered. Everything it cannot establish is reported as unestablished rather than assumed.
