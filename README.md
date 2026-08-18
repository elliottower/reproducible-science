# reproducible-science

Claude Code plugin bundling three tools for reproducible science workflows.

## Install

```bash
/plugin marketplace add elliottower/reproducible-science
/plugin install reproducible-science@prereg
/plugin install reproducible-science@citations
/plugin install reproducible-science@results
```

Install the CLIs:

```bash
pip install prereg citations results-cli
```

## What's included

| Skill | CLI | PyPI | What it does |
|-------|-----|------|-------------|
| `prereg` | `prereg` | [`prereg`](https://pypi.org/project/prereg/) | Freeze a plan before running, record what changed after |
| `citations` | `citations` | [`citations`](https://pypi.org/project/citations/) | Verify quotations resolve in pinned source artifacts |
| `results` | `results` | [`results-cli`](https://pypi.org/project/results-cli/) | Seal inputs, record outputs, bind claims to runs, verify the chain |

## The workflow

```bash
prereg new my_experiment          # scaffold the plan
prereg freeze                     # hash it before running

results init                      # start tracking
results seal PREREG.md script.py  # hash inputs
results access "read metadata" --level "metadata only"

# run the computation

results run output.json --run-id exp_001
results claim "ICC = 0.42" --run-id exp_001 --confirmatory --location "Table 2"
results verify --files            # check everything

citations verify --claims claims/ # check all quotations
```

## Or install individually

Each tool also ships its own Claude Code plugin:

- [`elliottower/prereg`](https://github.com/elliottower/prereg)
- [`elliottower/citations`](https://github.com/elliottower/citations)
- [`elliottower/results`](https://github.com/elliottower/results)

MIT licensed.
