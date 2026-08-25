---
description: Does every declared claim in the manuscript resolve in the artifact it names?
argument-hint: [repro.yaml]
---

Run `repro verify $1`, defaulting to `paper/repro.yaml` or the nearest contract in this
repository. Say which file you used.

Report the three outcomes apart, because they mean different things:

1. **Resolved.** The value at the stated address matches what the manuscript claims. Give
   the count rather than the list.
2. **Mismatched.** The address resolved and the value differs. Quote the claim, the address,
   the expected value and the value found. This is the finding.
3. **Unresolved.** The address could not be reached — a missing file, a broken pin, a locator
   naming nothing. Say which, and never report it as a mismatch: an artifact that cannot be
   read has not disagreed with anything.

Report any assertion whose artifact digest no longer matches what was pinned before the
results, since a broken pin invalidates every claim drawn from that file.

If there is no contract, say that `repro init` scaffolds one. Change nothing unless asked.
