---
description: Has the registered plan changed since it was frozen?
argument-hint: [preregistration-file]
---

Run `prereg check $1`, defaulting to the preregistration nearest this repository's root.
Say which file you used.

Report:

1. **Whether the plan still matches its freeze.** A plan that changed after freezing is a
   deviation. State what changed, and check the log for whether the deviation was recorded.
2. **Whether the freeze names a real commit** that exists in this repository.
3. **What the log holds** — amendments and deviations, in order.

A plan that has not been frozen is not a failed check. Say so plainly, and that
`prereg freeze` records the commit and hash.

Do not freeze, amend or log anything unless asked. Editing a registration on the author's
behalf is the one thing this tool exists to make impossible.
