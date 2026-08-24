# Review request: a four-package uv workspace, and what the migration broke

Four separately published Python packages were merged into one repository as a uv workspace.
It is on a branch, not merged. I ran my own review first; five defects are below, all found
and fixed before this packet. What I want is the sixth I have not found.

## What it looks like now

```text
reproducible-science/
├── pyproject.toml          workspace root — no [project] table, members + shared tooling only
├── uv.lock                 the only lockfile
├── packages/
│   ├── repro/              → reproducible-science 0.3.0   src/repro
│   ├── citations/          → citations 0.1.0              src/citations
│   ├── results/            → results-cli 0.3.0            src/results
│   └── prereg/             → prereg 0.1.1                 src/prereg
├── .claude-plugin/         Claude Code marketplace → ./packages/*/plugin
├── .github/workflows/      publish-repro.yml, publish-citations.yml, publish-results.yml, publish-prereg.yml
├── docs/ paper/ experiments/ scripts/
```

`repro` depends on the other three. Development resolution is `[tool.uv.sources] { workspace =
true }`; published resolution is PyPI. Releases are tag-scoped (`citations-v0.2.0`), and each
workflow runs the whole workspace's tests before building one distribution.

History was brought in with `git subtree add`, not by copying: 71 commits, and
`git log packages/citations` still shows that project's 34.

**349 tests pass** in one environment — 170 repro, 101 citations, 42 results, 36 prereg.

## Five defects the migration introduced, found and fixed

1. **`pytest` could not collect.** Three packages each have `tests/test_cli.py`; the default
   import mode derives a module name from the path relative to rootdir, so they collided.
   Fixed with `--import-mode=importlib` rather than scattering `__init__.py`.
2. **A cwd-relative constant.** `test_sarif.py` held `CASES = "tests/conformance/cases"`,
   which resolved against the old root. Now derived from `__file__`.
3. **A figure generator that crashed.** `generate_figures.py` read
   `ROOT / "tests/conformance/cases"`, which no longer exists.
4. **A figure generator that did *not* crash — the bad one.** The same script read the metric
   corpus from `ROOT / "tests/corpus"` behind an `if cp.is_file():` guard. After the move that
   guard was false, so it emitted an empty section: the paper's audit figures (39/39 on one
   external repository, 9/10 mismatches on another) silently vanished from `figures.json`
   while every test still passed. Caught by diffing the regenerated file against the committed
   one. The guard now raises.
5. **A stale `sys.path` hack** pointing at the old `src/`, which the workspace makes
   unnecessary.

Two documentation references also went stale and were repaired. Because `docs/SPEC.md` is
pinned by digest from a preregistration in this repository, editing it required re-pinning;
that pin and two others verify.

## A defect that predates the migration and is not fixed

`repro` declares its three siblings with **no version floors**:

```toml
dependencies = ["pydantic>=2.0", "PyYAML>=6.0", "prereg", "citations", "results-cli"]
```

Worse, two of them have been rewritten without a version bump, so the same version number
names different code:

| distribution | local | PyPI | |
|---|---|---|---|
| citations | 0.1.0 | 0.1.0 | same number, substantially different code |
| prereg | 0.1.1 | 0.1.1 | same number, different code |
| results-cli | 0.3.0 | 0.1.0 | |
| reproducible-science | 0.3.0 | 0.1.0 | |

I built the wheel and installed it into a clean environment with dependencies resolved from
PyPI only. It works — `repro verify` runs, the self-audit passes 31/31 under the strict
profile, the quote backend's `check_one` call is compatible. But that is luck, not design: the
workspace resolves siblings locally, so the test suite never exercises the combination a user
actually installs. PyPI versions are permanent and cannot be re-uploaded.

## What I want from you

1. **The version-floor fix.** Bump all four and add floors (`citations>=0.2.0`)? Pin exact
   (`citations==0.2.0`)? Something else? The two packages whose code changed under a fixed
   version number are the awkward part — the bad releases cannot be withdrawn.
2. **Should CI test against the lowest declared versions**, not only the workspace? If so,
   what is the least-effort way to express that for four mutually dependent packages?
3. **Tag-scoped releases with a shared workflow that runs all tests.** Right or wasteful? A
   citations release currently blocks on repro's corpus tests.
4. **The workspace root has no `[project]` table.** Correct for a virtual root, but at least
   one downstream tool now reports "no dependency manifest found" while looking straight at
   `pyproject.toml`. Is a virtual root the right call, or should the root be a thin metapackage?
5. **Anything about the subtree merge that will bite later** — `git subtree push` back to the
   original repositories, bisect across the grafted histories, or blame through the moves.
6. **What is the sixth defect?** Five surfaced from a careful pass. Migrations of this shape
   usually leave more.

Do not be polite about it. If the workspace is wrong for four packages this size, say so.
