# Development

The workspace, the gates, and the release procedure. For what the tools do and how to install
them, see the [README](README.md); for what a decision means, see [docs/SPEC.md](docs/SPEC.md).

## Working on them

A [uv workspace](https://docs.astral.sh/uv/concepts/projects/workspaces/): one lockfile, one
environment, and local resolution between the packages.

```console
uv sync --all-packages     # every package, editable, in one environment
uv run pytest              # every package's tests
uv run pytest packages/citations
uv run pytest -m corpus    # tests that read repositories outside this one
```

```console
uv run python scripts/check_wheels.py   # build the wheels and install them outside the workspace
```

The workspace resolves the packages from source, so `pytest` alone never exercises the
combination a user installs. `check_wheels.py` builds them and installs them outside the
workspace. CI runs it on every push.

`uv.lock` at the root is the only lockfile. A package added under `packages/` joins the
workspace automatically.

## Releasing

Every package carries the same version and ships on the same day, from one tag:

```console
git tag -a v0.2.0 -m "Release all packages at 0.2.0" && git push origin v0.2.0
```

That tag triggers all four workflows under `.github/workflows/`, each of which runs the whole
workspace's tests before building its own distribution. Per-package tags
(`citations-v*`, `prereg-v*`, `results-v*`, `repro-v*`) publish one distribution each, which
is how a partial release gets repaired.

`scripts/versions.py` sets every version and rewrites the sibling ranges; `make versions`
fails if they drift, and runs in CI.

PyPI trusted publishing is bound to a repository *and* a workflow filename, so a package
released from here for the first time needs its publisher reconfigured on PyPI — repository
`elliottower/reproducible-science`, workflow `publish-<package>.yml`, environment `release` —
before the tag is pushed. PyPI matches on the workflow filename, so `results-cli` is
published by `publish-results.yml`. An upload from an unrecognized workflow is rejected, and a
version number is never reusable once taken.

The full procedure, and what each check is defending against, is in
[docs/RELEASING.md](docs/RELEASING.md).

## Layout

```text
packages/        the four distributions, each with its own pyproject, src and tests
packages/*/plugin/   Claude Code plugins, published as a marketplace from this repository
docs/            SPEC.md — the evidence contract
paper/           the manuscript, and its own self-audit manifest
experiments/     preregistrations and their frozen codebooks
scripts/         figure and manifest generation
```

## The Claude Code plugin

This repository is also a plugin marketplace:

```console
/plugin marketplace add elliottower/reproducible-science
```

MIT licensed.

## provenance-core

A fifth workspace package, `provenance-core`, holds primitives the four tools share: content
digests and git references. It has no CLI and nobody installs it directly. It is published
anyway, because the tools that depend on it are published separately, and a workspace path
does not survive into a wheel.
