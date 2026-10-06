---
description: Has the registered plan changed since it was frozen?
---

Run `prereg check`. It takes no argument: it checks the plan governing the working
directory, or every plan below it at a repository root.
Say which file you used.

Report:

1. **Whether each frozen file still matches its freeze**: the plan, then each amendment. State
   what changed in any that does not, and whether an amendment records the change.
2. **Whether the freeze names a real commit** that exists in this repository.
3. **What follows the plan** — each amendment with its freeze date and access level, any
   reported as orphaned or written after results were seen, and what the log holds, in order.
4. **Whether a timestamp is owed or pending.**

A plan that has not been frozen is not a failed check. Say so plainly, and that
`prereg freeze` records the hash, the commit and the time beside the plan.

Do not freeze, amend or log anything unless asked. Editing a registration on the author's
behalf is the one thing this tool exists to make impossible.
