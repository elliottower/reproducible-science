---
title: JSON check record
description: repro export record writes one JSON object per checked assertion, for another program to read.
---

`repro export record` checks every assertion in `repro.yaml` as `repro verify` does and writes
one JSON object per assertion. It is the format the other exports are built from, and the one
the PaperDelta and SciTeX Clew readers write. [The check record](/concepts/check-record/)
describes every field.

## Reads

`repro.yaml` and the pinned files its assertions name.

## Writes

JSON Lines, one record per assertion, to standard output or to `--output`. Each record names its
version in the `record` field:

```text
reproducible.science/claim-check/0.1-experimental
```

The JSON Schema is published at the URL its `$id` names,
<https://reproducible.science/schemas/claim-check-0.1-experimental.schema.json>.

## Command

```bash
repro export record -o records.jsonl
```

`claims export record` writes the same output.

## Refuses or never does

- Refuses a record under any version other than the current one and the 0.5.6 name
  `repro.check/0.1-experimental`, which is read and never written.
- A `match` under a version this reader does not know is read as `not-checked`.
- An outcome or a check type with no mapping is refused, never defaulted.
- Refuses records no check could have produced, such as a `mismatch` with no stored value.
- Executes nothing, and exits 0 whatever the outcomes: `repro verify` is the check that fails.

## Does not claim

A record states what was observed and no verdict. The format is experimental, and a field may
change before `1.0`. It is the toolkit's own format, not a community standard.

## The other project

None: the format is defined in section
[7.10](/reference/spec/#710-the-check-record) of the specification.
