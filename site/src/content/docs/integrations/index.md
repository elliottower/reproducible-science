---
title: Integrations
description: What each integration reads and writes, and where it stops.
---

Reproducible Science reads the records other tools keep. Each page in this section says what one integration reads, what it writes, the
command, what it refuses, and what it does not claim. Each page describes the code on `main`;
the integrations marked 0.7.0 are on `main` and in no published release yet.

`repro mcp` serves the checks to any agent that uses the Model Context Protocol, and is the
way an agent fills the open items the readers below leave.

None of the projects, venues or standards named here has endorsed or reviewed this toolkit, and
the toolkit is not affiliated with any of them.

## Readers

CODECHECK, CORE-Bench, ClawBio and PaperDelta each keep records of the results they check or
produce. We provide integrations to read these records into a draft manifest, to be reviewed and
confirmed.

| integration | direction | command | release |
|---|---|---|---|
| [CODECHECK](/integrations/codecheck/) | reads a `codecheck.yml` | `claims from-codecheck` | 0.7.0 |
| [CORE-Bench](/integrations/core-bench/) | reads a capsule and its task | `claims from-corebench` | 0.7.0 |
| [ClawBio](/integrations/clawbio/) | reads a skill's output folder | `claims from-clawbio` | 0.7.0 |
| [PaperDelta](/integrations/paperdelta/) | reads a `report.json` | `claims from-paperdelta` | 0.7.0 |

## Shared design

The readers fill only what the other tool's files state with certainty. A CODECHECK
configuration names an output file and not the sentence it supports, and a CORE-Bench task
states a value and not the file holding it, so each reader writes what the source states into
`repro.draft.yaml` and lists each gap as an open item in `open-items.json`.

A search hit is a candidate, never a binding. Where a reader finds a value at an address in a
file, it lists that address in the open item and never writes it into the draft.

Whatever an agent fills is marked `basis: inferred` and never counts as verified. An inferred
assertion that matches is counted apart from verified ones, and a draft holding one fails the
`strict` and `publication` policies until an author accepts it.
