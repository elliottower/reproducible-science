# reproducible-science

All four tools in one plugin: preregistration, citation verification, results provenance,
and the checks that tie them together.

`packages/*/plugin/` hold the same material split one plugin per tool, for anyone who wants
only one of them. This directory is the combined form.

## What it adds

**Four hooks**, which speak when a moment passes unrecorded and are silent otherwise.

| hook | fires when |
|---|---|
| `frozen_plan_changed.py` | a preregistration no longer matches the digest it was frozen with |
| `unverified_quotations.py` | a quotation enters a manuscript that no claim file pins to a source |
| `unbound_numbers.py` | a number enters a manuscript that no recorded claim names |
| `unfrozen_plan_before_run.py` | an analysis is about to run under a plan that was never frozen |

**Three skills**, so the model reaches for the right tool without being told.

**Three commands**, named alike so there is nothing to remember:
`/prereg-check`, `/citations-check`, `/results-check`.

## What it expects

The CLIs, installed separately:

```bash
uv tool install reproducible-science   # prereg, citations, results, repro
```

Every hook stays silent in a project that has not opted in — no ledger, no claims directory,
no frozen plan means nothing to check and nothing said.

## Checking that the hooks run

Three properties, checked three ways. They fail independently, and a green result on one says
nothing about the others.

**The manifest loads.** `hooks.json` files its matchers under a top-level `hooks` key. Events
placed at the root parse as valid JSON and register nothing:

```bash
claude plugin validate packages/repro/plugin
claude plugin list | grep reproducible-science     # ✔ enabled, not ✘ failed to load
```

Reading the manifest yourself is not this check. A test that walks its structure and confirms
every script it names exists passes on a file the runtime discards — see `RD-020` in
`docs/DEFECTS.md`, which is that defect, found after four releases.

**The hook speaks when it should.** Each hook reads a payload on stdin and is runnable
directly, which is the fastest way to see its output and the only way that does not depend on
a session:

```bash
echo '{"tool_name":"Write","tool_input":{"file_path":"draft.md","content":"..."},"cwd":"."}' \
  | python3 packages/citations/plugin/hooks/unverified_quotations.py
```

Silence is the correct answer more often than not. `unverified_quotations.py` says nothing
where no `claims/` directory governs the file, and its plain-quote pattern requires the passage
on one line. Construct the case deliberately: a `claims/` directory that pins something else,
and a quotation of at least 40 characters unbroken by a newline.

**A session dispatches it.** Plugins load when a session starts, so a plugin installed or
repaired mid-session is not the one that session is running. Confirming dispatch takes a fresh
session and an edit that meets a hook's conditions. Neither of the two checks above establishes
it, and the difference is not academic: every release through 0.4.1 passed a manifest read and
dispatched nothing.
