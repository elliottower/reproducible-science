---
title: Outcomes and reasons
sidebar_position: 2
---

# Outcomes and reasons

A decision carries three independent fields. Collapsing them loses the distinction the tool
exists to draw.

## Outcome — what the check concluded

| outcome | meaning |
|---|---|
| `verified` | the artifact holds what the manuscript says |
| `mismatch` | the artifact was read and it disagrees |
| `not_found` | the address resolved to nothing, or to more than one thing |
| `unchecked` | no comparison ran |
| `error` | the tool failed |
| `not_offered` | the claim declared no evidence |

The gap between `mismatch` and `unchecked` is the point. A contradicted number and a missing
extractor are both failures of a build, and they are not the same fact about a paper. A tool
that reports them identically teaches its users to ignore it.

## Reason — why

Nineteen machine-readable codes, so a tool can route by cause:

```
passage_present   value_match        passage_absent      value_mismatch
pointer_absent    column_absent      row_absent          row_ambiguous
row_selector_invalid                 selector_not_scalar format_unsupported
wrong_page        value_not_numeric  extractor_missing   artifact_missing
artifact_unreadable                  artifact_undeclared backend_defect
not_offered
```

Four of those produce `unchecked` and three produce `not_found`. Without the reason,
`artifact_undeclared` — a mistake in your manifest — is indistinguishable from
`artifact_missing`, a file that is genuinely absent. One is a defect in the declaration; the
other is a fact about the work.

## Validity — whether the decision describes the declared artifact

| validity | meaning |
|---|---|
| `authoritative` | the bytes read are the bytes pinned |
| `unpinned_artifact` | no digest was recorded, so the file read may not be the file meant |
| `broken_pin` | the file read is provably not the file that was pinned |
| `artifact_absent` | nothing exists at the declared path |

A comparison against a changed file still runs, and its result is still reported — a
diagnostic is more useful than a blank — but it is marked non-authoritative. Every number can
agree and the report still fail, because they agreed with a document nobody pinned.
