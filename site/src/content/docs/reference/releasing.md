---
title: Releasing
description: Releasing — Reproducible Science
---

{/* Generated from docs/RELEASING.md. Edit that file, not this one. */}

Every package in this workspace carries the same version and is published on the same day
from one tag. This file is the procedure, and the reason each step exists is recorded beside
it, because several of these checks were added after the thing they check for had already
happened.

## What one release consists of

| | |
|---|---|
| Distributions | `citations`, `prereg`, `results-cli`, `reproducible-science` |
| Version | one number, identical across all four |
| Trigger | a single annotated tag `vX.Y.Z` |
| Result | four workflow runs, four PyPI uploads |

Per-package tags (`citations-v*`, `prereg-v*`, `results-v*`, `repro-v*`) still work and still
publish one distribution each. They exist for a repair — republishing one package after a
partial failure — and not for an ordinary release.

## 1. Set the version

```bash
uv run python scripts/versions.py bump X.Y.Z
uv run python scripts/versions.py check
```

`bump` writes the version into all four manifests and rewrites the sibling dependency ranges
to `>=X.Y,<X.(Y+1)`. It refuses a version below one already declared, because PyPI rejects a
version that goes backwards and never permits reuse of one that goes forwards. A first
lockstep release, where the highest declared version was never published, passes `--realign`
to allow the deliberate downward move.

The range is a range rather than an exact `==`. This release is run by hand, so the four
uploads land seconds apart; an exact pin makes the set briefly uninstallable in between.

`check` runs in `make qa` and in CI. A version scheme that is documented rather than enforced
drifts: this repository shipped `pyyaml>=6` and `pydantic>=2` for months, both too low to
install on current Python, and nothing noticed until a gate resolved the declared minimum.

## 2. Write the changelog

One `CHANGELOG.md` at the workspace root, not one per package: lockstep means four files
would repeat one release four times. Entries carry a `[package]` prefix. Sections are
`Fixed`, `Added`, `Changed`, `Removed`, `Deprecated`.

Put corrections first, and say what the tool reported wrongly before it was fixed. A user
deciding whether to upgrade needs to know which of their past results are affected.

Every claim in the changelog must be checkable against the history:

```bash
git log --oneline -S "<the symbol the entry describes>" -- <path>
```

Anything that cannot be traced to a commit that changed behavior is cut. A changelog entry
asserting a fix that was never a defect is the same failure the tools exist to prevent.

## 3. Regenerate derived artifacts, in order

```bash
uv run python scripts/generate_figures.py
uv run python scripts/build_self_audit.py
```

Order matters: the self-audit manifest pins `paper/figures.json` by digest, so figures are
generated first. Reversing it produces a manifest pinning a file that no longer exists in
that form, and `repro verify --policy strict` fails on its own repository.

## 4. Run the full pre-flight

```bash
make release-check
```

This is `make qa` plus wheel building, `twine check` and `check-wheel-contents`. It must exit
0. `make qa` includes the drift check, which fails while regenerated artifacts are
uncommitted — commit them and re-run.

## 5. Push and wait for CI

```bash
git push origin main
gh run watch $(gh run list --limit 1 --json databaseId -q '.[0].databaseId') --exit-status
gh run view <id> --json jobs -q '.jobs[] | "\(.conclusion)  \(.name)"'
```

Read the per-job list rather than the overall conclusion. The tag builds from this commit, so
a red `main` produces a bad release.

## 6. Confirm trusted publishing before tagging

**This is the step that has no local equivalent and cannot be verified from a checkout.**

PyPI binds a trusted publisher to a repository, a workflow *filename*, and an environment. A
package that moved between repositories keeps its old binding, and the upload is rejected.

```text
https://pypi.org/manage/project/citations/settings/publishing/             publish-citations.yml
https://pypi.org/manage/project/prereg/settings/publishing/                publish-prereg.yml
https://pypi.org/manage/project/results-cli/settings/publishing/           publish-results.yml
https://pypi.org/manage/project/reproducible-science/settings/publishing/  publish-repro.yml
```

Each needs repository `elliottower/reproducible-science` and environment `release`.

Check all four before tagging, not after the first failure. A rejected upload does not consume
the version, so a wholly failed release is recoverable — but a *partial* one is not: if two
packages upload and two are rejected, re-pushing the tag retries the successful two and fails
on `File already exists`, and the only way forward is a new version.

## 7. Verify the version is unclaimed

```bash
git tag -l vX.Y.Z                                  # local
git ls-remote --tags origin refs/tags/vX.Y.Z       # remote
```

And on PyPI, for each of the four distributions, that `X.Y.Z` is absent from `releases`.

## 8. Check the artifacts, not the source tree

```bash
uv run --isolated --no-project \
  --with dist/citations-X.Y.Z-py3-none-any.whl \
  --with dist/prereg-X.Y.Z-py3-none-any.whl \
  --with dist/results_cli-X.Y.Z-py3-none-any.whl \
  --with dist/reproducible_science-X.Y.Z-py3-none-any.whl \
  python -c "import citations, prereg, results, repro"
```

Install all four together in a clean environment, invoke each console script, and re-run the
release's headline regression against the installed wheel rather than against `src/`. A fix
that is present in the working tree and absent from the artifact is the failure mode this
catches, and it is invisible to every test that imports from source.

Inspect what the wheels contain:

```bash
python -c "import zipfile,sys; print([n for n in zipfile.ZipFile(sys.argv[1]).namelist()])" dist/*.whl
```

Looking for: scratch directories, `.DS_Store`, coverage data, caches, credentials, private
notes. Untracked directories at the repository root cannot reach a wheel, because every
package builds from `packages/*/src/` — but confirm rather than assume.

## 9. Confirm the third-party interop claim still holds

```bash
make interop-strict
```

`repro` publishes a rule that adduce discovers through an entry point, and `docs/SPEC.md` and
the paper both claim the two interoperate. Nothing here imports adduce at runtime, so their
releases cannot break an install -- they can only falsify the claim, silently.

`[tool.interop] adduce = "..."` records the version the adapter was verified against. On an
ordinary push `make interop` reports and never fails, because a third party's release should
not redden a pull request its author cannot fix. At a release it blocks, because that is when
the claim goes out with a version number on it.

A newer adduce that still passes is a prompt: move the recorded version forward. One that
fails is a choice between capping the dependency and saying which version the adapter targets,
or fixing the adapter. Shipping neither leaves a false claim in the specification.

## 10. Tag and publish

```bash
git tag -a vX.Y.Z -m "Release all packages at X.Y.Z"
git show --no-patch --decorate vX.Y.Z
git push origin vX.Y.Z
```

Annotated, so the tag carries an author and a date. Confirm it points at the audited commit
before pushing.

## 11. Confirm the release landed

Watch all four workflow runs to completion, then confirm each distribution reports the new
version on PyPI and installs from PyPI — not from `dist/` — in a clean environment.

Only then archive or update anything downstream. A standalone repository that has been
archived while the release failed leaves no maintained source anywhere.

## What this procedure is defending against

Each entry is something that happened, not something imagined.

| Failure | Caught by |
|---|---|
| Declared dependency floors that cannot be installed | step 1, and CI's lowest-direct resolution |
| Version numbers drifting apart across packages | step 1, `versions.py check` |
| A changelog entry asserting a fix that was never a defect | step 2, tracing each claim to a commit |
| A self-audit manifest pinning a stale digest | step 3, generator ordering |
| A trusted publisher still bound to an old repository | step 6 |
| A partially published release with versions consumed | step 6, checking all four first |
| A fix present in source and absent from the wheel | step 8 |
| An interop claim falsified by someone else's release | step 9 |
