---
title: "Exports: JSON, SARIF, RO-Crate"
description: The three formats repro writes its records in, for other tools to read.
---

## JSON check record

`repro export record` checks every assertion in `repro.yaml` as `repro verify` does and writes
one JSON object per assertion. It is the format the other exports are built from, and the one
the PaperDelta and SciTeX Clew readers write. [The check record](/concepts/check-record/)
describes every field.

### Reads

`repro.yaml` and the pinned files its assertions name.

### Writes

JSON Lines, one record per assertion, to standard output or to `--output`. Each record names its
version in the `record` field:

```text
reproducible.science/claim-check/0.1-experimental
```

The JSON Schema is published at the URL its `$id` names,
<https://reproducible.science/schemas/claim-check-0.1-experimental.schema.json>.

### Command

```bash
repro export record -o records.jsonl
```

`claims export record` writes the same output.

### Refuses or never does

- Refuses a record under any version other than the current one and the 0.5.6 name
  `repro.check/0.1-experimental`, which is read and never written.
- A `match` under a version this reader does not know is read as `not-checked`.
- An outcome or a check type with no mapping is refused, never defaulted.
- Refuses records no check could have produced, such as a `mismatch` with no stored value.
- Executes nothing, and exits 0 whatever the outcomes: `repro verify` is the check that fails.

### Does not claim

A record states what was observed and no verdict. The format is experimental, and a field may
change before `1.0`. It is the toolkit's own format, not a community standard.

### The other project

None: the format is defined in section
[7.10](/reference/spec/#710-the-check-record) of the specification.

## SARIF and code scanning

`repro export sarif` checks every assertion in `repro.yaml` as `repro verify` does and writes a
SARIF 2.1.0 log built from the [check records](/concepts/check-record/). Uploaded to GitHub code
scanning, each assertion that does not hold appears as an alert, and on a pull request where its
line is in the diff.

### Reads

`repro.yaml` and the pinned files its assertions name.

### Writes

A SARIF 2.1.0 log, to standard output or to `--output`.

- A result for each mismatch, not-found and error, placed at the sentence the claim quotes where
  that falls on one line, and at the assertion's line in the manifest otherwise.
- A notification for each assertion that was not checked.
- Each result carries its files' digests, a fingerprint that follows the assertion rather than
  its line, and the whole record in its property bag.
- With `--include-matches`, a `pass` result for each assertion that matched. GitHub shows each
  as a warning alert, so this is not for an upload.

### Command

The SARIF log is uploaded with GitHub's own action. This repository's
`.github/workflows/code-scanning.yml` does it in two steps:

```yaml
- run: uv run repro export sarif -o repro.sarif
- uses: github/codeql-action/upload-sarif@24c54180a607b1449ed407dd24f251e4e9147c8d  # v4.38.3
  with:
    sarif_file: repro.sarif
    category: repro
```

The job needs `security-events: write`. `repro ci init` does not write this workflow.

### Refuses or never does

- An assertion that was not checked is a notification, never a result.
- An outcome word this version does not know is never shown as a pass.
- An inferred match (an assertion marked `basis: inferred`) is never shown as a pass. This
  ships in 0.7.0; 0.6.1 has no inferred assertions.
- Nothing is dropped past GitHub's limit of 5,000 results per run; the export warns instead.
- Executes nothing, and exits 0 whatever the outcomes: `repro verify` is the check that fails.

### Does not claim

SARIF is a lossy projection for display. An alert is not a verdict on the paper, and the absence
of alerts does not mean every assertion was checked: assertions not checked are notifications.

### The other project

GitHub's documentation on
[uploading a SARIF file](https://docs.github.com/en/code-security/code-scanning/integrating-with-code-scanning/uploading-a-sarif-file-to-github),
and the [SARIF 2.1.0 standard](https://docs.oasis-open.org/sarif/sarif/v2.1.0/sarif-v2.1.0.html).

Not affiliated with or endorsed by GitHub or OASIS.

## RO-Crate

`repro export ro-crate` checks every assertion in `repro.yaml` as `repro verify` does and writes
the [check records](/concepts/check-record/) as an RO-Crate 1.3 `ro-crate-metadata.json`.

RO-Crate has no terms for an address inside a file, a printed value against a stored one, or the
outcome of comparing them. Those come from the
[claim-check profile](https://reproducible.science/ro-crate/claim-check/0.1/), which is this
toolkit's own, at version `0.1-experimental`. It is not an RO-Crate community profile, and a
term in it may change before `1.0`.

### Reads

`repro.yaml` and the pinned files its assertions name, and the record of re-runs.

### Writes

`ro-crate-metadata.json`, into the directory `-o DIR` names, or to a named file or standard
output.

- Files, commands and recorded re-runs in RO-Crate 1.3 terms, and in Process Run Crate 0.6
  terms where a re-run is recorded.
- Each assertion as a check with its outcome, in the profile's terms.
- The crate reads back into the records it was written from. The same records give the same
  bytes.

### Command

```bash
repro export ro-crate -o .
```

### Refuses or never does

- Declares conformance to Process Run Crate only where a re-run is recorded.
- Refuses to read back a document that does not conform to the claim-check profile, and records
  that disagree about one thing.
- A match under an outcome word or an address kind this version does not know leaves as
  `not-checked`.
- Executes nothing, and exits 0 whatever the outcomes. A manifest with no assertions exits 2.

### Does not claim

No RO-Crate validator is run on the output. The tests check the document against what RO-Crate
1.3 and Process Run Crate 0.6 require of a root, a descriptor and a run, and that every term the
profile adds is defined on its page, but the crate has not been checked by any RO-Crate
community tool.

### The other project

[RO-Crate](https://www.researchobject.org/ro-crate/), and the
[Process Run Crate profile](https://www.researchobject.org/workflow-run-crate/profiles/process_run_crate/).

Not affiliated with or endorsed by the RO-Crate community.
