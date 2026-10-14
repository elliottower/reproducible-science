---
title: The check record
---

A check record is one checked assertion written out for another program to read. It states
what was observed and no verdict: which checker, at which version, read which file, with which
digest, at which address, obtained which value, compared it with the value the manuscript
prints under which rule, and returned which outcome. It is computed by the same functions as
`repro verify`, from the manifest and the files, when the export runs; nothing is stored.

## Version

Every record names the version it was written under, in its `record` field:

```text
reproducible.science/claim-check/0.1-experimental
```

The format is experimental, and a field may change before `1.0`. Version 0.5.6 wrote the same
format under the name `repro.check/0.1-experimental`. Releases in the 0.6 series read a record
under either name, and the next minor release reads only the new one. A program that compares
the `record` field with the old string has to accept the new one too.

A record under any other version is refused by `claims.record.validate`. Where a program reads
one without validating it, a `match` it carries is read as `not-checked`: every exporter reads
the outcome through `claims.record.read_outcome`, and a version this reader does not know may
mean something else by any field.

## Schema

The JSON Schema is generated from the model and kept in the repository as
`docs/schemas/claim-check-0.1-experimental.schema.json`. It is published at the URL its `$id`
names:

<https://reproducible.science/schemas/claim-check-0.1-experimental.schema.json>

Its `record` field accepts both version strings. A schema says which fields a record may hold;
`claims.record.validate` also refuses records no check could have produced, such as a
`mismatch` with no stored value.

## Writing one

```bash
repro export record                  # JSON Lines on standard output, one record per assertion
repro export record -o records.jsonl
repro export ro-crate -o .           # ./ro-crate-metadata.json beside repro.yaml
repro export sarif -o repro.sarif    # a SARIF 2.1.0 log for GitHub code scanning
```

`claims export` takes the same targets and writes the same output. Each command exits 0
whatever the outcomes, because `repro verify` is the check that fails.

The RO-Crate export is a projection of the records and loses none of them: it reads back into
the records it was written from. RO-Crate has no terms for an address inside a file, a printed
value against a stored one, or the outcome of comparing them, so those come from the
[claim-check profile](https://reproducible.science/ro-crate/claim-check/0.1/), which defines
each term. The SARIF log is a lossy projection for display, and carries the whole record in
each result's properties.

## What a record holds

| field | holds |
|---|---|
| `record`, `checker`, `checked_at` | the version, the tool's name, version and URL, and when the check ran |
| `manifest` | its path and the sha256 of its bytes |
| `claim`, `assertion` | the claim's id, text and digest, and which of its assertions this is |
| `check_type` | which proposition was checked, such as `value-comparison` or `passage-presence` |
| `reads` | each file read: its path, `validity`, pinned digest, digest on disk, the address, the value stored there, and the `origin` where the manifest declares one |
| `printed`, `comparison` | the value the manuscript prints, and the rule it was compared under |
| `outcome`, `native_outcome` | one of `match`, `mismatch`, `not-found`, `not-checked` and `error`, and the word `repro verify` prints beside it |

A reader that meets an outcome, a check type or an address kind it does not know keeps it as
written and never counts it as a `match`. Section
[7.10](/reference/spec/#710-the-check-record) of the specification defines every field,
[7.11](/reference/spec/#711-ro-crate-export) the RO-Crate export, and
[7.12](/reference/spec/#712-origins) origins.
