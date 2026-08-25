# Exposure notebook

Dated record of occasions when an agent in the analysis loop saw something a
preregistration says it should not have, and what was done about it.

This file is the evidence base for `SPEC.md`. It is a lab notebook, not prose: entries
are written when the thing happens, not reconstructed later. An entry that had to be
reconstructed says so.

## How to write an entry

One entry per exposure. Classification follows `SPEC.md` §3.2.

```markdown
## YYYY-MM-DD — <study or repo>

**What was exposed.** The file, and what it contained.
**How.** Which tool call, and whether the agent was asked to or did it unprompted.
**Who saw it.** Agent context only / printed to transcript / human read it.
**Plan digest predates exposure?** yes/no, with the prereg id.
**Downstream authoring edge?** Did any context that saw it later author, modify, or
select the analysis?
**Action.** Quarantined / scoped demotion / no action, and why.
**Log reference.** Line in `exposure.jsonl`, if the hook was running.
```

The last field matters more than it looks. An entry with no log reference is a
reconstruction, and the paper must report reconstructions separately from observations —
they are exactly the class of evidence the mechanism exists to replace.

## Rules

- **Write the entry before deciding the action.** Recording what happened and then
  deciding is a different epistemic act from deciding and then recording a justification.
- **Log the ones where the answer was demotion.** A notebook containing only exonerations
  is not evidence, and §6 of the spec commits to showing a case where the rule bit.
- **Never edit an entry.** Corrections are appended and dated, with the original left in
  place. The file is provenance.
- **Reconstructed entries are marked** `RECONSTRUCTED` in the heading.

---

## Entries

*(none yet — the hook was installed 2026-08-24)*
