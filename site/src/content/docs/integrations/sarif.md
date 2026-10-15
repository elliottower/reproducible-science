---
title: SARIF and code scanning
description: repro export sarif writes the check records as a SARIF 2.1.0 log for GitHub code scanning.
---

`repro export sarif` checks every assertion in `repro.yaml` as `repro verify` does and writes a
SARIF 2.1.0 log built from the [check records](/concepts/check-record/). Uploaded to GitHub code
scanning, each assertion that does not hold appears as an alert, and on a pull request where its
line is in the diff.

## Reads

`repro.yaml` and the pinned files its assertions name.

## Writes

A SARIF 2.1.0 log, to standard output or to `--output`.

- A result for each mismatch, not-found and error, placed at the sentence the claim quotes where
  that falls on one line, and at the assertion's line in the manifest otherwise.
- A notification for each assertion that was not checked.
- Each result carries its files' digests, a fingerprint that follows the assertion rather than
  its line, and the whole record in its property bag.
- With `--include-matches`, a `pass` result for each assertion that matched. GitHub shows each
  as a warning alert, so this is not for an upload.

## Command

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

## Refuses or never does

- An assertion that was not checked is a notification, never a result.
- An outcome word this version does not know is never shown as a pass.
- An inferred match is never shown as a pass.
- Nothing is dropped past GitHub's limit of 5,000 results per run; the export warns instead.
- Executes nothing, and exits 0 whatever the outcomes: `repro verify` is the check that fails.

## Does not claim

SARIF is a lossy projection for display. An alert is not a verdict on the paper, and the absence
of alerts does not mean every assertion was checked: assertions not checked are notifications.

## The other project

GitHub's documentation on
[uploading a SARIF file](https://docs.github.com/en/code-security/code-scanning/integrating-with-code-scanning/uploading-a-sarif-file-to-github),
and the [SARIF 2.1.0 standard](https://docs.oasis-open.org/sarif/sarif/v2.1.0/sarif-v2.1.0.html).
