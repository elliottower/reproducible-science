---
title: Integrations
description: What each reader, export and venue draft reads and writes, and where it stops.
---

Reproducible Science reads the files other tools write, and writes its own records in formats
other tools read. Each page in this section says what one integration reads, what it writes, the
command, what it refuses, and what it does not claim. Each page describes the code on `main`;
the integrations marked 0.7.0 are on `main` and in no published release yet.

`repro mcp` serves the checks to any agent that speaks the Model Context Protocol, and is the
way an agent fills the open items the readers below leave.

None of the projects, venues or standards named here has endorsed or reviewed this toolkit, and
the toolkit is not affiliated with any of them.

| integration | direction | command | release |
|---|---|---|---|
| [MCP server](/integrations/mcp/) | serves the checks and open items to an agent | `repro mcp` | 0.7.0 |
| [CODECHECK](/integrations/codecheck/) | reads a `codecheck.yml` | `claims from-codecheck` | 0.7.0 |
| [CORE-Bench](/integrations/core-bench/) | reads a capsule and its task | `claims from-corebench` | 0.7.0 |
| [ClawBio](/integrations/clawbio/) | reads a skill's output folder | `claims from-clawbio` | 0.7.0 |
| [PaperDelta](/integrations/paperdelta/) | reads a `report.json` | `claims from-paperdelta` | 0.7.0 |
| [SciTeX Clew](/integrations/scitex-clew/) | reads an exported `claims.json` | `claims from-clew` | 0.7.0 |
| [adduce](/integrations/adduce/) | runs inside `adduce check` as a rule | `R-REPRO-001` | 0.6.1; items 0.7.0 |
| [Open items](/integrations/open-items/) | an agent fills what a reader left open | `open-items` skill, `claims open-items` | 0.7.0 |
| [repro init scaffolding](/integrations/init-scaffold/) | drafts a project's claims from its result files | `repro init` | 0.7.0 |
| [ACM Artifact Appendix](/integrations/acm-artifact-appendix/) | writes a draft appendix | `repro venue acm` | 0.7.0 |
| [ACM badging evidence map](/integrations/acm-evidence/) | writes records per badging criterion | `repro venue acm-evidence` | 0.7.0 |
| [NeurIPS and ACL checklists](/integrations/neurips-acl/) | writes draft checklists | `repro venue neurips`, `repro venue acl` | 0.7.0 |
| [SARIF and code scanning](/integrations/sarif/) | writes a SARIF 2.1.0 log | `repro export sarif` | 0.6.1; inferred matches 0.7.0 |
| [RO-Crate](/integrations/ro-crate/) | writes `ro-crate-metadata.json` | `repro export ro-crate` | 0.6.1 |
| [JSON check record](/integrations/check-record/) | writes JSON Lines | `repro export record` | 0.6.1 |
| [GitHub CI](/integrations/github-ci/) | writes workflows and badges | `repro ci`, `repro badges init` | 0.6.1 |
| [OSF registration](/integrations/osf/) | pushes a frozen plan to OSF | `prereg freeze --osf`, `prereg register` | 0.6.1 |
| [OpenTimestamps](/integrations/opentimestamps/) | dates a digest against Bitcoin | `prereg timestamp`, `results timestamp` | 0.6.1 |
| [Zotero](/integrations/zotero/) | reads an exported `.bib` | `citations audit --bib`, `citations lint --bib` | 0.6.1 |

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

## Coming in the next release

This is in an open pull request and will get a page when it merges:

- the pull-request bot
