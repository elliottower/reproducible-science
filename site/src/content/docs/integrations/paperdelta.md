---
title: PaperDelta
description: claims from-paperdelta reads a PaperDelta report into one check record per occurrence.
---

`claims from-paperdelta` reads a PaperDelta `report.json`, with the `paperdelta.yaml` it was
made from, and writes PaperDelta's answers as [check records](/concepts/check-record/).
PaperDelta is the checker named in each record; this reader translates and does not check
again unless asked with `--rerun`.

## Reads

- The `report.json`.
- The `paperdelta.yaml` given with `--config`, which carries the display and rounding mode the
  report does not.

## Writes

JSON Lines, one check record per occurrence and per comparative claim, to standard output or to
`--output`.

- `pass` is `match` and `mismatch` is `mismatch`. `unknown` is placed by its error code, and a
  code this reader does not list is `not-checked`.
- A derived metric, a statistic other than the mean, and a comparative claim are check type
  `other`.
- A `pass` under a project-level finding such as `INPUT_CHANGED`, or under an exit code the
  items' findings do not account for, is `not-checked`, with the finding named.
- No file is pinned in PaperDelta, so each file read is `unpinned_artifact`, with the digest
  the report records.
- With `--rerun`, each comparison PaperDelta completed is also put to this toolkit's rule
  (printed precision, half-even, either neighbor on a tie). The outcome stays PaperDelta's;
  the second answer is under `rerun`, and the text output says where the two rules disagree.

## Command

```bash
claims from-paperdelta report.json --config paperdelta.yaml --rerun -o paperdelta.jsonl
```

## Limits

- Refuses the configuration unless the report records its sha256 and it matches, and refuses a
  report that records none.
- Refuses a report schema it has not read, and a time with no UTC offset unless `--offset` is
  given.
- Never guesses an `unknown` into a mismatch, and never reads a derived metric or a comparative
  claim as a comparison of values.
- Writes no absolute path, and never writes over an existing file.
- Runs nothing, imports no PaperDelta code, and exits 0 whatever the outcomes.

## Does not claim

The records state what PaperDelta found. They are not a second verification of the paper,
except for the `rerun` field where `--rerun` was asked for.

## The other project

[PaperDelta on GitHub](https://github.com/amos689/paperdelta).

Not affiliated with or endorsed by PaperDelta.
