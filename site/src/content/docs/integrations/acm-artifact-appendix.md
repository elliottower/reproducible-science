---
title: ACM Artifact Appendix
description: repro venue acm drafts an Artifact Appendix from the repository's records, every field marked DRAFT or TODO.
---

`repro venue acm` drafts an Artifact Appendix in the layout of the Unified Artifact Appendix
template that ACM conferences use for artifact evaluation. The field labels are the template's,
copied into the package with the commit of the template they were read at.

## Reads

The repository's records: the claims in `repro.yaml` and its `regenerations`, the record of
re-runs in `.repro/reproductions.jsonl`, the ledger, plans frozen with `prereg` (outside folders
of tests, fixtures and examples, or the one named with `--plan`), `CITATION.cff`,
`codemeta.json`, `LICENSE`, the lockfiles at the top of the project, a `Dockerfile`, and the
`origin` remote.

## Writes

A draft appendix in Markdown, LaTeX in the template's layout, or JSON, to standard output or to
`--output`.

- A field a record bears on carries one line per fact, each naming its record, and is marked
  DRAFT.
- Every other field is marked TODO and left for the authors.
- Three yes-or-no fields are answered Yes where a record settles them with no judgment, marked
  DRAFT with the record named. Archived: a DOI or Software Heritage ID among the project's own
  identifiers. Publicly available: those, or the project's own code repository, with "author:
  confirm this repository is public". Workflow automation framework used: a declared command.
- Re-runs are reported as `repro stale` decides them, so a stale re-run is not called current.

## Command

```bash
repro venue acm --format latex -o artifact-appendix.tex
```

## Refuses or never does

- Never writes over the `--output` file without `--force`.
- Reaches no network.
- Settles no yes or no that needs judgment: a license on disk settles no choice, a GitHub or
  GitLab address alone does not answer Archived, and a placeholder DOI settles nothing.
- Shows the remote without credentials, query or fragment.
- Never counts a claim naming no recorded run as bound.

## Does not claim

The draft is not an authored appendix and not an evaluation result. Every answer drawn from a
record says so, and the authors fill or confirm the rest.

## The other project

The [Unified Artifact Appendix template](https://github.com/ctuning/artifact-evaluation), and
ACM's [Artifact Review and Badging](https://www.acm.org/publications/policies/artifact-review-and-badging-current)
policy.
