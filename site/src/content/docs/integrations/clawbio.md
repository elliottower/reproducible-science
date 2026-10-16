---
title: ClawBio
description: claims from-clawbio reads a ClawBio skill's output folder into a draft manifest and the items it leaves open.
---

`claims from-clawbio` reads the output folder a ClawBio skill writes and produces a draft
manifest. The folder records which bytes the run wrote, in `reproducibility/checksums.sha256`,
or in `checksums.sha256` at the top of the folder, where older outputs keep it.
It does not record which number of `report.md` was read from which cell of which table, so
each number is left open.

## Reads

- `report.md`, `tables/`, and `reproducibility/checksums.sha256`, or `checksums.sha256` at the
  top of the folder. Which of the two it found is recorded in the open items' source.
- The digests of `reproducibility/commands.sh` and `environment.yml`, which are pinned in the
  open items' source. Neither file is run.
- Tables only through parsers that evaluate nothing: JSON, YAML with the safe loader, and
  delimited text.

## Writes

`repro.draft.yaml` and `open-items.json` in the output directory.

- Each file `checksums.sha256` lists becomes an artifact pinned to the digest ClawBio recorded.
  A file whose bytes changed since the run verifies as a broken pin.
- `report.md` becomes an artifact, pinned to its recorded digest where the checksums list it,
  and to the bytes read otherwise.
- Each number `report.md` prints outside code becomes a claim whose text is its line, with a
  quotation of that line marked `basis: inferred` and one open item: the address of the value
  in a pinned table. Up to 500 per report; the rest are counted.
- Each item lists as candidates the addresses in the pinned tables at which a check of the
  printed number would match.

## Command

```bash
claims from-clawbio output/ -o draft/
```

## Limits

- Pins the digest ClawBio recorded, never one computed now.
- Never writes a candidate into the draft.
- Refuses a folder with no `checksums.sha256`, and one with both, since nothing says which the
  run wrote. Never writes over an existing file.
- Passes over a table the checksums do not list, a label that leaves the folder, a date, a
  year, a time of day such as `14:22`, and a number inside code, each with the reason.
- Does not declare `commands.sh` as a regeneration, and runs nothing.

## Does not claim

A fresh draft verifies nothing. Its quotations are the reader's proposals, so it fails the
`strict` and `publication` policies until each value is bound and accepted. An inferred fill
that matches is counted by `claims open-items` as bound, never as verified.

## The other project

[ClawBio on GitHub](https://github.com/ClawBio/ClawBio).

Not affiliated with or endorsed by ClawBio.
