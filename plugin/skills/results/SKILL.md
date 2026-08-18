---
name: results
description: Seal a run's inputs before computing, record outputs after, bind manuscript claims to specific runs, and verify the hash chain. Use before launching any computation whose output will appear in a paper, after a run completes, when a number in a manuscript needs tracing to its source, or when asked whether results are still what they were. Requires the `results` CLI (`uv tool install results-cli`).
---

# results

Seal a run, record what it produced, and verify the chain.

## The rule that matters

**Seal before you run. Claim after you verify.**

A number in a manuscript is trustworthy when it names the run that produced it, the run names the
inputs that were sealed before it started, and the chain from input to claim has not been broken.
Every way this fails is a version of the result moving without a trace — a script edited after
the seal, an output overwritten between the run and the claim, a claim attached to a run that
no longer exists.

## Commands

```bash
results init                            # start tracking results here
results seal <file>... [--role input]   # hash inputs before a run
results access <note> [--level ...]     # record a data-access event
results run <file>... --run-id <id>     # record outputs after a run
results claim <text> --run-id <id>      # bind a manuscript claim to a run
results verify [--files]                # check the chain and every hash it names
```

## The workflow, in order

1. **`results init`** in the experiment directory.
2. **`results seal prereg.md script.py data.csv`** — hash every input before computing.
3. **`results access "downloaded zenodo metadata" --level "metadata only"`** — record what
   was seen and when. This is the data-access taint the chain uses to distinguish confirmatory
   from exploratory.
4. **Run the computation.**
5. **`results run output.json --run-id exp_001`** — hash the outputs.
6. **`results claim "ICC = 0.42" --run-id exp_001 --confirmatory --location "Table 2"`** —
   bind the manuscript claim to the run.
7. **`results verify --files`** — check everything.

## Data-access levels

Four levels, in order of exposure:

| level | meaning |
|---|---|
| `nothing seen` | no target data touched |
| `metadata only` | structure, region names, sample sizes — not outcomes |
| `structure seen` | data shape and distributions, but not the target variable |
| `outcomes seen` | the dependent variable was observed |

An analysis registered after `outcomes seen` is retrospective, not confirmatory. The level is
recorded, not judged — log the honest one even when it is the damaging one.

## Reading `results verify`

The chain check is pass/fail:

| | |
|---|---|
| `chain intact` | every event's prev_hash matches the hash of the line before it |
| `CHAIN BROKEN` | a line was edited, inserted, or deleted after it was written |

With `--files`, every sealed input and recorded output is re-hashed against its current state:

| | |
|---|---|
| `ok` | file matches its recorded hash |
| `CHANGED` | file was modified since it was sealed or recorded |
| `MISSING` | file no longer exists at the recorded path |

**`CHAIN BROKEN` means the ledger was tampered with.** It does not mean the results are wrong —
it means the evidence that they are right was damaged. Restore from git history.

## Claims

A claim names a run. A run names its outputs. The outputs were hashed when they were recorded.
This is the whole chain: manuscript → claim → run → output file → hash. `verify` walks it.

`--confirmatory` marks the claim as backed by a pre-registered hypothesis. Without it, the claim
is exploratory. The distinction is recorded, not enforced — the access timeline is what makes it
verifiable.

## When to reach for this

- Before launching any computation whose output will be reported
- After a run completes, to record what it produced
- When a number in a manuscript needs tracing to its source run
- When asked whether results are still what they were
- In CI, as `results verify --files`

## What it will not do

It cannot prove the computation was correct. A sealed script that produces the wrong answer
passes every check here. It also cannot prove the access timeline is honest — the events are
self-reported, and the tool records them without questioning. The chain is evidence, not proof.
