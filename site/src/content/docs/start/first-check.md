---
title: Your first check
---

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

```text
repro.yaml

  unpinned    results

  ok    primary      metric   /primary/p = 0.031  <unpinned_artifact>

  1 verified
  policy publication: passed  (0 errors, 1 warnings)
```

It passes, and warns. The last section of this page is about that warning.

## Now break it

Change `reported` to `"0.051"` and run it again:

```text
  MISS  primary      metric   p: manuscript prints 0.051, results.json holds 0.031  <unpinned_artifact>

  1 mismatch
  policy publication: FAILED  (1 errors, 1 warnings)
```

The artifact was read, the address resolved, and the values disagree. That is a `mismatch`.

Now instead point at something that is not there — change the pointer to `/primary/q`:

```text
  GONE  primary      metric   /primary/q does not resolve in results.json  <unpinned_artifact>

  1 not_found
  policy publication: FAILED  (1 errors, 1 warnings)
```

Not a mismatch. Nothing was compared, so nothing disagreed. Silence is not contradiction: a
file with no such key asserts nothing about the value.

## Pin it

The manifest above declares no digest, so the verifier read a file it cannot prove is the one
you meant. Add one:

```yaml title="repro.yaml"
artifacts:
  - id: results
    path: results.json
    digest:
      algorithm: sha256
      value: a6d08b3fbffc...        # shasum -a 256 results.json
```

Now edit `results.json` by hand and re-run:

```text
  BROKEN PIN  results: pinned a6d08b3fbffc, found b99e750d8995

  ok    primary      metric   /primary/p = 0.031  <broken_pin>

  1 verified
  policy publication: FAILED  (1 errors, 0 warnings)
```

Every number still agrees, and the report fails anyway — because they agreed with a document
nobody pinned.
