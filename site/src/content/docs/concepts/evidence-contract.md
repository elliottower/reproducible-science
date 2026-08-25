---
title: The evidence contract
---


# The evidence contract

Verification runs in three stages, and each records its own result. The outcome is derived
from all three rather than asserted.

```
execution     did the check run at all?
extraction    did the address resolve to exactly one value?
comparison    did that value agree with what the manuscript prints?
```

Separating them is what lets the report distinguish a paper that is wrong from a machine that
is missing a tool. A single pass/fail cannot carry that distinction, and a reader who cannot
see it learns to treat every failure as noise.

## A claim

```yaml
claims:
  - id: primary
    text: The treatment reduced the primary outcome
    registration: confirmatory
    evidence:
      - kind: metric
        artifact: results
        name: p_value
        pointer: /primary/p
        reported: "0.031"
```

The claim names evidence. The evidence names an artifact and an address inside it. The
artifact is pinned by digest. Nothing is searched for.

## Registration

A claim declares one of three states, and `not_applicable` requires a note saying why:

| registration | meaning |
|---|---|
| `confirmatory` | the analysis was planned before the data were seen |
| `exploratory` | it was not |
| `not_applicable` | the question does not apply, and here is why |

For a confirmatory claim the tool also checks **ordering** — that the run started after the
plan it names was registered — and records who attests to that timestamp:

```
self_recorded  <  git_remote  <  osf / zenodo  <  trusted_timestamp
```

A self-recorded timestamp establishes internal consistency, not chronology: someone who can
write the plan digest and both timestamps after seeing results can manufacture an ordered
history. Recording the authority makes that limit a field rather than a caveat, and lets a
policy require better than the weakest one.

## Policies

The same report is graded differently depending on what is at stake:

| policy | unpinned artifact | unchecked evidence |
|---|---|---|
| `exploratory` | ignored | warning |
| `publication` | warning | warning, error if confirmatory |
| `strict` | error | error |

A run that evaluated nothing is never a pass. Without that rule, a project with no evidence
anywhere satisfies every other condition trivially.
