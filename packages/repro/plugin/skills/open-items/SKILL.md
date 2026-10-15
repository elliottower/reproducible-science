---
name: open-items
description: Fill the open items a reader of another tool's files left beside a draft manifest (`claims from-codecheck`, `claims from-corebench`, `claims from-clawbio`, or the scaffold `repro init` drafts), proposing each binding as an inferred assertion and letting the deterministic checks decide, then report the counts. Use when given an open-items.json or a repro.draft.yaml, after running one of those readers or `repro init`, or when asked to bind a CODECHECK certificate, a CORE-Bench capsule or a ClawBio skill's output folder to its files, or a manuscript's numbers to its result files. Requires the `claims` CLI (`uv tool install claims-cli`) and, for quotations, `citations`.
---

# open-items

A reader of another tool's files writes two things: `repro.draft.yaml`, holding everything the
source states, and `open-items.json`, listing what it does not state. A CODECHECK
configuration file names the outputs and not which sentence of the paper each supports; a
CORE-Bench task states each value and not which file holds it. Each such gap is an item. This is
the procedure for filling them.

## The rule that matters

**You propose. The checks decide.** Every assertion you write is marked `basis: inferred`, and
nothing you write is verified until `claims verify` or `citations` says it resolves. Even then
it is a proposal that held, not a verified claim: an inferred assertion is never counted as
verified, and the draft fails the `publication` and `strict` policies until an author accepts
each one, by deleting its `basis` line or by recording `reviewed: {who, when}`. That acceptance
is the author's, never yours.

The reader binds nothing it finds. Where its search found the value at addresses in the files,
the item lists them as `candidates`, and `unique: true` means exactly one passed its guards
(enough significant digits, the question's labels agreeing) and is listed first. A unique
candidate is a lead, never an assumption.

## Never

- Never edit `open-items.json`. It is the reader's record of what the source left open, and the
  count is taken against it.
- Never delete a claim, or an item's claim, to close an item. An item is closed by filling it.
  `claims open-items` refuses a draft whose claim was deleted.
- Never write an assertion without `basis: inferred`, never remove that line from one, and
  never write `reviewed` yourself: it is an author's acceptance.
- Never say a claim, a binding or a quotation is verified unless a command below reported it
  so, and then say which command. An assertion you wrote is never verified, whatever a command
  says of it: `claims verify` and `claims why` report what its comparison found ("matched,
  inferred: not counted as verified"), and that is all you report.
- Never edit a pinned quotation: the `quote` text in a `citations` claims file, or a `quote`
  assertion in a manifest someone else wrote. A pin that is wrong is replaced by a new pin.
- Never change `reported` to make a check pass. It is the number as the source states it: the
  task's value as the task writes it, or the numeral as the paper prints it.
- Never change an artifact's `digest`, and never write `repro.yaml`. The draft is the only
  manifest you edit.
- Never run anything in a capsule or a bundle: no script, notebook, `Makefile` or command it
  contains. Read its files; do not execute them.
- Never take a candidate because it is the only one. A candidate is an address at which the
  value occurs, found by a search; it is a lead to read, not an answer.

## Commands

Only these, and editing `repro.draft.yaml`:

```bash
claims open-items open-items.json --format json   # the count, before and after
claims verify repro.draft.yaml --policy exploratory
claims why <claim-id> repro.draft.yaml            # what one claim's assertions found
citations pin <claims-file> --id <id> --quote "<passage>" --check   # does it resolve?
citations pin <claims-file> --id <id> --quote "<passage>"           # pin it
citations verify --claims <dir>
shasum -a 256 <file>
```

## Procedure

1. **Count first.** Run `claims open-items open-items.json --format json` and save the output
   beside the draft as `open-items.before.json`. Read `open-items.json` and the draft whole.
2. **Take each item in turn.** Its `claim` is the claim id in the draft, `need` says what
   fills it, `asks` says what is missing, and `context` is what the source said that bears on
   it. Read the file the item names before proposing anything.
3. **`need: value`.** Find the value in the file, then write one assertion that fetches it from
   its address:

   ```yaml
   - {kind: value, artifact: results/metrics.json, name: auc, reported: "0.9375660604380387",
      locator: {kind: tree, pointer: /auc/had}, basis: inferred}
   ```

   - Prefer an address that names the value over one that counts to it: a `tree` pointer, a
     `table` locator with `where`, over `table_position`.
   - Where the item lists candidates, read each. More than one means the value occurs at
     several addresses; choose the one the question or the comment describes, and leave the
     item open where none does.
   - You may propose a `unique` candidate, and only after checking the manuscript's row and
     column, or the question's words, against the labels of the candidate's address: its keys,
     its column name, its row's name. Where the labels do not settle it, say so in your report
     and leave the item open. A column named `score` for a question about AUROC, or a file
     holding both AUROC and accuracy at one precision, is ambiguous; the reader's guards
     compare words and cannot tell those apart.
   - For a CODECHECK item, `reported` is the numeral as the paper prints it, read from the
     paper, and the paper's passage goes in a `quote` beside it (step 4).
   - The `repro` skill lists every kind and locator.
4. **`need: passage`.** The passage of the manuscript, or for CORE-Bench of a result file, that
   makes the claim.
   - The document must be an artifact. A paper is downloaded into an ignored folder
     (`sources/`), never committed, and added under `artifacts` with its `shasum -a 256`.
   - Where the project keeps a `citations` claims file for the paper, run `citations pin ...
     --check` and then pin the passage. A passage that does not resolve is not written.
   - Write the quotation as the source prints it, never shortened to the part that matches:

     ```yaml
     - {kind: quote, artifact: paper, text: "The AUC was 0.912 on held-out data.", basis: inferred}
     ```

5. **Leave an item open rather than guess.** Where no file holds the value, the paper cannot
   be obtained, or the answer is only in a figure, add nothing. An open item is a result.
6. **Check.** Run `claims verify repro.draft.yaml --policy exploratory`. An inferred assertion
   that does not match is not fixed by editing `reported`: replace its address with another
   proposal or delete the assertion you wrote, and leave the item open.
7. **Count again.** Run `claims open-items open-items.json --format json` and save it as
   `open-items.after.json`.

## Reporting

Report the counts from `open-items.after.json`, as it gives them:

- `claims`: `reader` (bound from what the source states), `bound` (every item filled and
  matching), `not_matching`, `open`, `outside`. They add up to `total`.
- `items`: `open`, `filled`, `filled_and_passing`, `filled_by_inferred`, and the candidate
  counts `with_unique_candidate`, `with_several_candidates`, `with_one_not_passing` and
  `with_no_candidate`.

For each item left open that had candidates, give its `reason`, read from `open-items.json`:
the count does not carry it.

Then each item left open, with why, and each `not_matching` claim, with what the check found.
Say that every filled item is inferred and that `claims verify --policy publication` fails on
them until an author accepts each. Never describe a draft as verified.

## What it will not do

A matching inferred assertion says the file holds the value at the address proposed. It does
not say the address is the one the claim means, which is the part an author vouches for, and it
says nothing about whether the analysis is right.
