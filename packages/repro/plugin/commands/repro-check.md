---
description: Does every record this project keeps still hold -- claims, plan, ledger, citations and re-runs?
argument-hint: [repro.yaml or project directory]
---

Run `repro verify $1 --format json`, defaulting to `paper/repro.yaml` or the nearest manifest
in this repository. Say which file or directory you used. For the claims alone, quickly,
`claims verify $1` is the same check of the manifest without the other records.

The report has one section per record, and `project.checks` gives each one's verdict:
`passed`, `failed` or `not used`. Name every section that is `not used` as not used, never as
passing: nothing was checked there.

For the claims (`report`), report the three outcomes apart, because they mean different things:

1. **Resolved.** The value at the stated address matches what the manuscript claims. Give
   the count rather than the list.
2. **Mismatched.** The address resolved and the value differs. Quote the claim, the address,
   the expected value and the value found. This is the finding.
3. **Unresolved.** The address could not be reached -- a missing file, a broken pin, a locator
   naming nothing. Say which, and never report it as a mismatch: an artifact that cannot be
   read has not disagreed with anything.

Report any assertion whose artifact digest no longer matches what was pinned before the
results, since a broken pin invalidates every claim drawn from that file.

For `prereg`, `results` and `citations`, give the outcome and, where it is not `passed`, what
the tool's own output says failed. For `staleness`, name each declared command that is stale,
never rerun or undetermined. Report anything under `cross_tool`.

If there is no manifest and no other record, say that `repro init` scaffolds them. Change
nothing unless asked.
