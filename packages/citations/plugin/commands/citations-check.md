---
description: Do the quotations in this project resolve in the sources they cite?
argument-hint: [claims-directory]
---

Run `citations verify --claims $1`, defaulting to the `claims/` directory nearest this
repository's root if no path is given. Say which directory you used.

Report in this order, and keep the three kinds apart because they mean different things:

1. **Pins.** Sources whose file changed since the quotations were taken (`broken`), and
   sources with no hash recorded (`unpinned`). A broken pin invalidates every quotation
   drawn from that source, so report it before any result.
2. **Passages not found.** The source was read and the passage is not in it. Quote the
   passage and name the source. This is the finding.
3. **Passages unchecked.** The source could not be read, so nothing was measured. Never
   report these as failures, and never report them as verified — say which source could not
   be read and why. A `pdftotext` `extract_cmd` written without `{} -` prints nothing and
   sends every quotation against that source here.

Give the `found` count when summarizing. It is the only number saying a source was read, and
a run that measured nothing exits non-zero and says `nothing was measured`.

Then the warnings on passages that were found: `short`, `truncated`, `normalized`, `page`.

If `citations` is not installed, say `uv tool install citations`. If no claims directory
exists, say that `citations init` starts one, and do not invent quotations to check.
