---
title: Pinning
sidebar_position: 3
---

# Pinning

An artifact is addressed by path and identified by digest. The path says where to look; the
digest says whether what you found is what was meant.

```yaml
artifacts:
  - id: results
    path: analysis/results.json
    digest:
      algorithm: sha256
      value: 9f635f9af47215608565dd489ff7e193937cc7cde3781b89346cf811611aafa7
```

Artifacts are **pinned, not immutable.** Nothing stops a file from changing after it was
recorded — the digest is what makes the change visible. That is why `broken_pin` exists as a
distinct validity rather than an error: the comparison still runs, its result is reported, and
the report says the bytes are not the ones declared.

## Addressing a value

Locators are typed, and each format is addressed the way that format is already addressed:

| kind | addresses | example |
|---|---|---|
| `tree` | JSON and YAML, by [RFC 6901](https://datatracker.ietf.org/doc/html/rfc6901) JSON Pointer | `/metrics/accuracy` |
| `table` | CSV, TSV, by column and a key predicate | `column: accuracy, where: {model: resnet}` |
| `table_position` | a row number, reported with a warning | `row: 37` |
| `sqlite` | a table, column and key predicate | |
| `array` | `.npy` / `.npz`, by name and index | `index: [0, 1]` |

Note the pointer syntax: `/metrics/accuracy`, not `$.metrics.accuracy`. RFC 6901, not JSONPath.
Array indices carry no leading zeros, so `/xs/0` addresses a value and `/xs/00` addresses
nothing.

## Exactly one scalar

Every adapter enforces the same invariant:

```
0 matches   -> absent
1 scalar    -> resolved
2 or more   -> ambiguous
a container -> not scalar
```

No adapter takes the first match, and none falls back to searching a file for the printed
number. A search would find the number wherever it appeared and call that verification, which
is the failure the whole package exists to prevent. A format with no adapter reports
`format_unsupported` and stops.
