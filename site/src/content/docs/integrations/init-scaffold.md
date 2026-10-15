---
title: repro init scaffolding
description: repro init sets up a project's records and drafts its claims from its own result files, verifying none.
---

`repro init`, run with no name inside a project, creates whichever of four records the project
lacks: a plan, a results ledger, a citations library and a manifest. Where the project has
result files and a manuscript and no `repro.yaml`, it also drafts the project's claims in the
format the CODECHECK, CORE-Bench and ClawBio readers write. It ships in 0.7.0.

## Reads

- The top of the project: the git root, or the working directory outside a repository.
- The result files and the one manuscript that `repro verify` finds with no manifest, and the
  numbers the manuscript prints. A Markdown or text manuscript's numbers are those `repro verify`
  compares with no manifest; a LaTeX manuscript's are read from its source, so a number in a
  table or in inline math is one.

## Writes

- The missing records: `prereg new .`, `results init`, `citations init` where no library governs
  the project and an empty `claims/`, and a starter `repro.yaml` where there is nothing to
  scaffold.
- Three rules in `.gitignore`, added only where missing: the two lock sidecars and `sources/`.
- `repro.draft.yaml`: the result files and the manuscript pinned by sha256, and one claim per
  number, whose text is the sentence holding it, with no assertion.
- `open-items.json`: one item per claim asking for the address of its value, with every place
  the result files hold the number as a candidate. An item is `unique` where exactly one
  candidate passes the CORE-Bench reader's guards.

## Command

```bash
cd my-project
repro init
```

`repro init NAME` scaffolds a new experiment directory instead. `--no-scaffold` writes neither
draft file and reads no result file.

## Refuses or never does

- Never writes or edits `repro.yaml`. Where one exists, nothing is scaffolded.
- Never edits a record that exists, so a second run creates nothing.
- Never replaces `repro.draft.yaml` or `open-items.json` without `--force`, and writes no
  starter `repro.yaml` beside a draft.
- Never writes a candidate into the draft, so a fresh draft fails `strict` until each claim is
  filled.
- Writes nothing through a symbolic link, `--force` included, and never writes through a
  `.gitignore` that is one. A result file that is a symbolic link, or resolves outside the
  project, is not read and is listed as not checked.
- Declares a Git LFS pointer without a pin and does not search it.
- Writes nothing where there is neither a manuscript nor a result file.

## Does not claim

Nothing in the draft is verified. The output says so: `scaffolded, nothing verified`. An agent
fills the items with the [open-items skill](/integrations/open-items/) or the
[MCP server](/integrations/mcp/), and an author reviews the draft and renames it to
`repro.yaml`.

## The other project

None: the draft uses the toolkit's own format, the one the [open items](/integrations/open-items/)
page describes.
