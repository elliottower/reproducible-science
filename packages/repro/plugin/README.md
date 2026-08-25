# reproducible-science

All four tools in one plugin: preregistration, citation verification, results provenance,
and the checks that tie them together.

`packages/*/plugin/` hold the same material split one plugin per tool, for anyone who wants
only one of them. This directory is the combined form.

## What it adds

**Three hooks**, which speak when a moment passes unrecorded and are silent otherwise.

| hook | fires when |
|---|---|
| `frozen_plan_changed.py` | a preregistration no longer matches the digest it was frozen with |
| `unverified_quotations.py` | a quotation enters a manuscript that no claim file pins to a source |
| `unbound_numbers.py` | a number enters a manuscript that no recorded claim names |

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
