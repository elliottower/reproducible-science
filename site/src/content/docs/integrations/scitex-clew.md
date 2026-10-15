---
title: SciTeX Clew
description: claims from-clew reads the claims.json SciTeX Clew exports into check records.
---

`claims from-clew` reads the `claims.json` SciTeX Clew exports and writes one
[check record](/concepts/check-record/) for each check Clew's stored status says ran. Clew
registers a claim against a manuscript line and a source file, records the file's sha256, and
verifies the claim by hashing the file again and walking the sessions upstream of it. Clew does
not compare the claimed value with anything.

## Reads

`.scitex/clew/runtime/claims.json`, and nothing else: not Clew's store, and no Clew code.

## Writes

JSON Lines, to standard output or to `--output`.

- An `artifact-identity` record for the source file's hash, and a `lineage-check` record where
  Clew walked the sessions upstream of it. Clew is the checker and its status is the native
  outcome.
- `claim_value` is carried as written, in a field of its own.
- Paths are written relative to `--root`, by default the folder holding `.scitex`. A path
  outside it is written as its file name, with a warning on the record.

## Command

```bash
claims from-clew .scitex/clew/runtime/claims.json --offset +09:00 -o clew.jsonl
```

## Refuses or never does

- Writes no `value-comparison` record, and never compares or parses `claim_value`.
- Refuses Clew's naive local times without `--offset`, and never reads them as UTC.
- Refuses a schema version it has not read.
- Writes no absolute path, and never writes over an existing file.
- Runs nothing and imports nothing of Clew.

## Does not claim

Clew's `verified` is not passed on as a value that held. A record from Clew says the file's hash
and its lineage were checked; it says nothing about the number the manuscript prints.

## The other project

[SciTeX Clew on GitHub](https://github.com/ywatanabe1989/scitex-clew).
