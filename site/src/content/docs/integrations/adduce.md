---
title: adduce
description: The rule R-REPRO-001 runs repro verify inside adduce check, with one item per checked assertion.
---

adduce scores a repository for reproducibility across categories. Installing the `adduce`
extra registers one rule with it, `R-REPRO-001`, "Declared evidence assertions verify", so a
repository that declares a `repro.yaml` has its assertions checked as part of `adduce check`.
adduce is not a dependency of this toolkit, and this toolkit is not a dependency of adduce.

## Reads

The `repro.yaml` at the repository root. Where there is none at the root, the one manifest
outside folders named `test`, `tests`, `fixture`, `fixtures`, `example`, `examples` or
`conformance`. It then checks every assertion as `repro verify` does.

## Writes

- One finding for the manifest: `PASS` where every assertion holds against pinned files,
  `PARTIAL` where some hold or where all hold but an artifact carries no digest, and `FAIL`
  where none holds or a pinned artifact changed or is absent, naming it.
- Under the finding, one item per checked assertion, up to adduce's envelope of 10,000: its id
  (claim, kind, name, position), a status read from its check record, the printed and stored
  values, the comparison rule, the validity of each file read, and the manifest line and files
  it read. An item that did not hold names `repro why` for its claim as the remedy.
- The full report, in every case, to `.adduce/repro-report.json`.

Item status follows the check record: `PASS` for a match, `FAIL` for a mismatch or an address
holding no value, `UNKNOWN` where nothing was compared or the tool failed.

## Command

```bash
pip install "reproducible-science[adduce]"
adduce check .
```

The extra asks for `adduce>=0.2`, the first release with finding items.

## Refuses or never does

- Never chooses among several manifests: more than one outside fixture folders, and none at the
  root, is `UNKNOWN`, with the list.
- A manifest that cannot be verified is `UNKNOWN`, not `FAIL`: a missing toolchain is not the
  repository's fault.
- A repository with no manifest, or a manifest declaring no assertions, is out of scope, not
  failing.
- An item is never `PARTIAL`, and items never change the finding's status or weight.
- Writes nothing outside its sidecar file.

## Does not claim

The rule reports whether the declared assertions hold against their pinned files. adduce's
score and weights are adduce's; the rule adds no score of its own.

## The other project

[adduce on GitHub](https://github.com/QHarshil/adduce).
