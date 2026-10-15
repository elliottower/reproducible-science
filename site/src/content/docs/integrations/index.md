---
title: Integrations
description: What each integration reads and writes, and where it stops.
---

Reproducible Science reads the files other tools write, and writes its own records in formats
other tools read. Each page in this section says what one integration reads, what it writes, the
command, what it refuses, and what it does not claim. Each page describes the code on `main`;
the integrations marked 0.7.0 are on `main` and in no published release yet.

`repro mcp` serves the checks to any agent that uses the Model Context Protocol, and is the
way an agent fills the open items the readers below leave.

None of the projects, venues or standards named here has endorsed or reviewed this toolkit, and
the toolkit is not affiliated with any of them.

## Agents

| integration | direction | command | release |
|---|---|---|---|
| [Claude Code](/agents/claude-code-plugin/) | a plugin: a skill per tool, four commands and five hooks | `/plugin install reproducible-science@reproducible-science` | 0.1.0 |
| [Codex](/start/codex/) | the same plugin, experimental | `codex plugin marketplace add elliottower/reproducible-science` | 0.7.0 |
| [MCP server](/agents/mcp/) | serves the checks and open items to an agent | `repro mcp` | 0.7.0 |
| [Open items](/integrations/open-items/) | an agent fills what a reader left open | `open-items` skill, `claims open-items` | 0.7.0 |
| [repro init scaffolding](/integrations/init-scaffold/) | drafts a project's claims from its result files | `repro init` | 0.7.0 |

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

## Records and services

| integration | direction | command | release |
|---|---|---|---|
| [SARIF and code scanning](/reference/exports/#sarif-and-code-scanning) | writes a SARIF 2.1.0 log | `repro export sarif` | 0.6.1; inferred matches 0.7.0 |
| [RO-Crate](/reference/exports/#ro-crate) | writes `ro-crate-metadata.json` | `repro export ro-crate` | 0.6.1 |
| [JSON check record](/reference/exports/#json-check-record) | writes JSON Lines | `repro export record` | 0.6.1 |
| [GitHub CI](/automation/github-ci/) | writes workflows and badges | `repro ci`, `repro badges init` | 0.6.1 |
| [OSF registration](/integrations/osf/) | pushes a frozen plan to OSF | `prereg freeze --osf`, `prereg register` | 0.6.1 |
| [OpenTimestamps](/integrations/opentimestamps/) | dates a digest against Bitcoin | `prereg timestamp`, `results timestamp` | 0.6.1 |
| [Zotero](/integrations/zotero/) | reads an exported `.bib` | `citations audit --bib`, `citations lint --bib` | 0.6.1 |

## adduce

| integration | direction | command | release |
|---|---|---|---|
| [adduce](/integrations/adduce/) | runs inside `adduce check` as a rule | `R-REPRO-001` | 0.6.1; items 0.7.0 |

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
