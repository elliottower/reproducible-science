"""The evidence contract, one module per concept.

Split out of a single 1,000-line `models.py` that held five unrelated groups: the artifacts a
manifest declares, the evidence a claim offers, the verdict vocabulary, the manifest itself,
and what a run reports. Each is now its own module.

Nothing is re-exported here. `repro.models` is the public path and names every type; importing
`repro.core.outcomes` directly is for code inside this package that wants one group.
"""
