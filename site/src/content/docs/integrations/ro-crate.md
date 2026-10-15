---
title: RO-Crate
description: repro export ro-crate writes the check records as an RO-Crate 1.3 metadata document.
---

`repro export ro-crate` checks every assertion in `repro.yaml` as `repro verify` does and writes
the [check records](/concepts/check-record/) as an RO-Crate 1.3 `ro-crate-metadata.json`.

RO-Crate has no terms for an address inside a file, a printed value against a stored one, or the
outcome of comparing them. Those come from the
[claim-check profile](https://reproducible.science/ro-crate/claim-check/0.1/), which is this
toolkit's own, at version `0.1-experimental`. It is not an RO-Crate community profile, and a
term in it may change before `1.0`.

## Reads

`repro.yaml` and the pinned files its assertions name, and the record of re-runs.

## Writes

`ro-crate-metadata.json`, into the directory `-o DIR` names, or to a named file or standard
output.

- Files, commands and recorded re-runs in RO-Crate 1.3 terms, and in Process Run Crate 0.6
  terms where a re-run is recorded.
- Each assertion as a check with its outcome, in the profile's terms.
- The crate reads back into the records it was written from. The same records give the same
  bytes.

## Command

```bash
repro export ro-crate -o .
```

## Refuses or never does

- Declares conformance to Process Run Crate only where a re-run is recorded.
- Refuses to read back a document that does not conform to the claim-check profile, and records
  that disagree about one thing.
- A match under an outcome word or an address kind this version does not know leaves as
  `not-checked`.
- Executes nothing, and exits 0 whatever the outcomes. A manifest with no assertions exits 2.

## Does not claim

No RO-Crate validator is run on the output. The tests check the document against what RO-Crate
1.3 and Process Run Crate 0.6 require of a root, a descriptor and a run, and that every term the
profile adds is defined on its page, but the crate has not been checked by any RO-Crate
community tool.

## The other project

[RO-Crate](https://www.researchobject.org/ro-crate/), and the
[Process Run Crate profile](https://www.researchobject.org/workflow-run-crate/profiles/process_run_crate/).
