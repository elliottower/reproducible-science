---
title: Your first check
sidebar_position: 2
---

# Your first check

Two files. A result, and a manifest describing what the manuscript says about it.

```json title="results.json"
{ "primary": { "p": 0.031 } }
```

```yaml title="repro.yaml"
schema_version: repro/1
project: first-check

artifacts:
  - id: results
    path: results.json

claims:
  - id: primary
    text: The primary analysis reports p = 0.031
    evidence:
      - kind: metric
        artifact: results
        name: p
        pointer: /primary/p
        reported: "0.031"
```

Run it:

```bash
repro verify repro.yaml
```

```
  ok    primary metric   /primary/p = 0.031
  policy exploratory: passed  (0 errors, 0 warnings)
```

## Now break it

Change `reported` to `"0.051"` and run it again:

```
  MISMATCH  primary metric: manuscript prints 0.051, file holds 0.031
```

The artifact was read, the address resolved, and the values disagree. That is a `mismatch`.

Now instead point at something that is not there — change the pointer to `/primary/q`:

```
  NOT FOUND  primary metric: /primary/q does not resolve in results.json
```

Not a mismatch. Nothing was compared, so nothing disagreed. Silence is not contradiction: a
file with no such key asserts nothing about the value.

## Pin it

The manifest above declares no digest, so the verifier read a file it cannot prove is the one
you meant. Add one:

```bash
repro pin repro.yaml
```

Now edit `results.json` by hand and re-run. Every number still agrees, and the report fails
anyway — because they agreed with a document nobody pinned.
