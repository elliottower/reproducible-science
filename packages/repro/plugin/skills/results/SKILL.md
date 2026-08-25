---
name: results
description: Seal a run's inputs before computing, record outputs after, bind manuscript claims to specific runs, and verify the hash chain. Use before launching any computation whose output will appear in a paper, after a run completes, while writing a sentence that states a number, when a number in a manuscript needs tracing to its source, before submitting a draft, or when asked whether results are still what they were. Requires the `results` CLI (`uv tool install results-cli`).
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
results coverage <manuscript>           # which of a paper's numbers are bound
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

## Binding while writing

**When a number enters a manuscript, record what produced it before moving on.**

The address is on screen while the sentence is being written and gone immediately afterward.
Recovering it later is measurably hard: matching a printed value against an artifact by its
digits fails once the artifact is dense, and on one development repository a four-digit value
confirms at 94 per cent while a fabricated value of the same shape confirms at 93.8 per cent.
The values are genuinely there and the match shows nothing. What separates a match from a
coincidence is the address, and a finished paper carries none.

The plugin's hook watches edits to manuscript files in repositories that have run
`results init`. When an edit introduces a number no claim names, it says which. Answer it by
recording the claim, or by noting once that the value needs none.

A value needs no claim when it is a constant of a formula, a number quoted from another
paper, or a parameter fixed by choice rather than produced by computation. Say so once for
the document rather than each time it comes up.

## Auditing a draft

```bash
results coverage paper/paper_v23.tex        # what is bound, and what is not
results coverage paper.tex --strict         # non-zero exit if anything is unbound
```

Run it before submitting. On a real manuscript with 21 recorded claims it reported 27 per
cent of the numbers bound, and among the unbound were sample-size denominators and interval
bounds — the class of number whose errors survive review.

## When to reach for this

- Before launching any computation whose output will be reported
- After a run completes, to record what it produced
- When a number in a manuscript needs tracing to its source run
- When asked whether results are still what they were
- In CI, as `results verify --files` and `results coverage <paper> --strict`
- Before submitting, to see which numbers nothing backs

## What it will not do

It cannot prove the computation was correct. A sealed script that produces the wrong answer
passes every check here. It also cannot prove the access timeline is honest — the events are
self-reported, and the tool records them without questioning. The chain is evidence, not proof.

## Where this sits

Four tools guard four moments, and each is weak without the others. A frozen plan over
unsealed inputs proves nothing; a sealed run whose numbers never reach the manuscript proves
nothing either.

| moment | tool | what it fixes |
|---|---|---|
| before you run | `prereg freeze` | the plan cannot be rewritten around the result |
| before you compute | `results seal` | the inputs are what you say they were |
| after a run | `results run` | the outputs are recorded and hashed |
| writing a number | `results claim` | the number names the run behind it |
| writing a quotation | a `claims/` entry | the passage is in the source |
| before submitting | `prereg check`, `results verify`, `citations verify` | nothing drifted |

Every tool named here is installed by `uv tool install reproducible-science`, so the commands
above are available whatever plugins are present.

Each tool also ships its own plugin, adding a hook that speaks when its moment passes
unrecorded and a `-check` command. Those commands exist only where the matching plugin is
installed; the CLI calls in the table always work.
