# Contributing

Four packages in one repository. Each is released separately, so a change usually touches one
of them; a change that crosses two is one commit here rather than a release dance.

## Setup

```console
uv sync --all-packages --group dev
make hooks
```

`make hooks` installs the pre-commit, pre-push and commit-msg hooks. If your git has a global
`core.hooksPath`, point it back at this repository first:

```console
git config --local core.hooksPath .git/hooks
```

## The quality ladder

Each rung is a superset of the one above. The split exists so a commit stays fast: anything
slow enough to make people bypass the hooks runs later.

| command | ~time | what it covers |
|---|---|---|
| `make format` | 5s | rewrite formatting and safe lint fixes |
| `make check` | 1s | what every commit runs |
| `make test` | 50s | the whole workspace's tests |
| `make qa` | 3m | what a pull request must pass |
| `make qa-all` | 10m+ | the deep pass, advisory tools included |
| `make release-check` | 2m | what a release must pass |

CI runs the same commands, so a green `make qa` locally means a green pull request.

## What the unusual checks are for

**`make drift`** regenerates every committed derived artifact and fails if the tree is not
clean. A generated file in the repository is a claim that running its generator reproduces it,
and that claim went untested until a path moved and `generate_figures.py` wrote an empty
section — dropping the paper's audit figures while every test stayed green.

**`repro verify`** is this repository's own product applied to itself: every number the
manuscript prints is checked against the artifact it came from.

**`lint-imports`** enforces the one architectural rule the monorepo exists to keep — the three
tools never import the verifier, so `pip install citations` does not drag in an evidence
engine.

**Conformance fixtures are pinned by digest.** Their exact bytes are the fixture, so the
formatting hooks skip them. A trailing newline breaks every pin in the corpus.

## Changes

A user-visible change gets a note under `changes/<package>/`, named for the pull request and
the kind of change:

```console
echo "Table locators accept a row predicate." > changes/repro/128.added.md
```

Kinds: `added`, `changed`, `fixed`, `removed`, `deprecated`. Documentation, tests, internal
refactors and dependency bumps need no note.

## Commits

`Co-Authored-By` trailers naming a model are rewritten to `Assisted-by` by a commit-msg hook.
The disclosure stays; the authorship claim does not. Human co-authors are left alone.

## Releases

Tags are per package: `citations-v0.2.0` publishes citations and nothing else. Leaf packages
go first, then `reproducible-science`, since it declares floors on the other three.
