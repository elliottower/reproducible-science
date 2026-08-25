---
description: Report how many of a manuscript's numbers are bound to a recorded run
argument-hint: [path/to/paper.tex]
---

Run `results coverage $1`. With no argument, find the newest manuscript source in this
repository and use that, saying which file you chose.

Report, in this order:

1. The bound and unbound counts, as counts and as a share.
2. The unbound numbers that state a result, quoted with the line they sit on. Group them by
   what they are: sample sizes and denominators first, since an error there survives review;
   then reported statistics and intervals; then everything else.
3. The unbound numbers that need no claim, named once as a group rather than listed.

For each unbound result, say what would have to be recorded to bind it, naming the run if
the ledger already holds one that produced it. Do not record any claim unless asked.

If the repository has no ledger, say so and that `results init` starts one.
