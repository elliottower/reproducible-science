---
title: GitHub CI
description: repro ci runs each check as one workflow step, repro ci init writes the workflows, and repro badges init keeps count badges current.
---

There is no reusable GitHub Action: the repository has no `action.yml`. Instead, `repro ci init`
writes ordinary workflow files into the project, each running one pinned `repro ci` command, and
`repro badges init` writes one workflow that keeps count badges current.

## Reads

- `repro ci init`: which records the project keeps (frozen plans, a ledger, a manifest, claims
  files, recorded re-runs) and the `origin` remote, for the badge address.
- `repro ci <check>`, in the job: that tool's own check. `prereg`, `results` and `citations` run
  the tool's check, `claims` runs what `repro verify` and `repro stale` run, and `reruns` checks
  that a re-run of each declared command is on record.
- `repro badges init`: the same checks, and `.repro/citations-verified.json`, which
  `repro badges --record` writes on the author's machine, because a clone does not hold the cited
  sources.

## Writes

- `repro ci init`: `.github/workflows/prereg.yml`, `results.yml`, `claims.yml`, `citations.yml`,
  each where the project keeps that record, and `reruns.yml` where the manifest declares a
  command and a re-run is on record. It prints two badge lines per workflow, or puts them in
  `README.md` with `--readme`.
- Each `repro ci` command appends a Markdown summary to the file `GITHUB_STEP_SUMMARY` names.
- `repro badges init`: `.github/workflows/repro.yml`, which on each push to the default branch
  writes one shields.io endpoint file per check and force-pushes them as the only commit of a
  `badges` branch, and a badge block in `README.md` that reads those files.

## Command

```bash
repro ci init --readme
repro badges init
```

A workflow `repro ci init` writes runs one step after checkout and uv setup, pinned to the
version that wrote it:

```yaml
- run: uvx --from reproducible-science==0.6.1 repro ci claims
```

## Refuses or never does

- `repro ci init` never replaces a workflow it did not write, and replaces its own only with
  `--force`. `--prefix` writes beside an existing file instead.
- Each workflow has read-only `contents` permission, checks out with
  `persist-credentials: false`, and pins `actions/checkout` and `astral-sh/setup-uv` by commit.
- `repro ci init` outside a git repository exits 2 and writes nothing.
- A `repro ci` summary is appended, never replaced, and an outcome other than verified is never
  counted as verified.
- `repro badges init` pushes only to the `badges` branch, never to the default branch, and never
  rewrites its workflow or the README block without `--force`.

## Does not claim

A badge is a count from one check run, such as `76/76 verified`. It is not a certificate and not
a review. The badges `repro badges init` keeps current are served from raw.githubusercontent.com,
so they draw for a public repository only.

## The other project

[GitHub Actions documentation](https://docs.github.com/en/actions), and shields.io's
[endpoint badge](https://shields.io/badges/endpoint-badge).
