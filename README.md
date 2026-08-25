<div align="center">

# reproducible-science

**Command-line tools and a Claude Code plugin that check whether a manuscript's claims match
its artifacts.**

[![CI](https://img.shields.io/github/actions/workflow/status/elliottower/reproducible-science/ci.yml?branch=main&logo=github&label=CI)](https://github.com/elliottower/reproducible-science/actions?query=branch%3Amain+workflow%3ACI)
[![docs](https://img.shields.io/badge/docs-live-blue)](https://elliottower.github.io/reproducible-science/)
[![pypi](https://img.shields.io/pypi/v/reproducible-science?label=%20)](https://pypi.org/project/reproducible-science/)
[![python](https://img.shields.io/pypi/pyversions/reproducible-science)](https://pypi.org/project/reproducible-science/)
[![license](https://img.shields.io/pypi/l/reproducible-science)](LICENSE)

[Documentation](https://elliottower.github.io/reproducible-science/) ·
[Specification](docs/SPEC.md) ·
[Try it in the browser](https://elliottower.github.io/reproducible-science/demo/)

</div>

---

`repro verify` reads a manifest of claims, resolves each one to a typed address in a
hash-pinned artifact, and compares. A quotation is checked against the source it cites; a
reported number against the file that holds it.

```console
$ repro verify
  Table 2, "ICC = 0.42"          verified   results.json /icc = 0.42
  Section 3, "p < 0.05"          MISMATCH   the source reads p = 0.051
  Appendix B, "n = 60"           unchecked  results.json is not there
  1 of 3 assertions failed, 1 could not be checked.
```

A check that could not run reports `unchecked`. It is never counted as a pass.

## The toolkit

- **[`repro`](packages/repro)** — verifies declared evidence against hash-pinned artifacts.
  `pip install reproducible-science`
- **[`citations`](packages/citations)** — checks that quotations resolve in the sources they
  cite, page numbers included. `pip install citations`
- **[`results`](packages/results)** — seals inputs, records outputs, binds manuscript claims to
  runs, in a hash-chained ledger. `pip install results-cli`
- **[`prereg`](packages/prereg)** — freezes a plan before running and records what changed
  after. `pip install prereg`

Installing one never drags in the others. Preregistration is optional: a claim is confirmatory,
exploratory, or not applicable, and only the first needs a plan.

## Getting started

```bash
pip install reproducible-science     # all four tools
repro init my-paper
```

```console
$ prereg freeze                                    # lock the plan; names a git commit
$ results seal analysis.py data.csv                # hash the inputs, before the run
$ results run output.json --run-id exp_001         # hash the outputs, after it
$ results claim "ICC = 0.42" --run-id exp_001 --location "Table 2"
$ repro verify
```

The [browser notebook](https://elliottower.github.io/reproducible-science/demo/) runs the
published packages with nothing installed.

## What it addresses

JSON, YAML, CSV/TSV, SQLite, and NumPy `.npy`/`.npz`. Parquet, HDF5, NetCDF and XLSX report
`format_unsupported` and stop, because addressing them by guesswork would report a result
nobody checked.

## Resources

- [Documentation](https://elliottower.github.io/reproducible-science/) — guides and reference
- [Specification](docs/SPEC.md) — what a decision means, and its limits
- [Development](DEVELOPMENT.md) — the workspace, the gates, the release procedure
- [Contributing](CONTRIBUTING.md) · [Code of conduct](CODE_OF_CONDUCT.md) · [Security](SECURITY.md)

## Claude Code

```
/plugin marketplace add elliottower/reproducible-science
```

MIT licensed.
