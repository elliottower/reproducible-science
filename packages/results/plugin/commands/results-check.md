---
description: Does the results chain verify, and is every number in the manuscript bound to a run?
argument-hint: [manuscript]
---

Two checks, reported together.

**The chain.** Run `results verify --files`. Report any event whose hash no longer matches,
any claim naming a run that is not in the ledger, and any output file that has changed since
it was recorded. A broken chain is reported before anything else, since it invalidates what
follows.

**The manuscript.** Run `results coverage $1`, defaulting to the newest manuscript source in
this repository and saying which you chose. Report:

- how many of the author's own numbers are bound to a run, as a count and a share;
- the unbound ones that state a result, grouped by line, sample sizes and denominators
  first — an error there survives review;
- how many sit beside a citation and so belong to the work cited;
- how many owe no claim at all, named once as a group.

For each unbound result, say what would bind it, naming the run if the ledger already holds
one that produced it. Record nothing unless asked.

If there is no ledger, say that `results init` starts one.
