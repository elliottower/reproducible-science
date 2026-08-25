# Repository checks

Each script backs a `make` target and a CI job. None of them reads anything outside this
repository.

| script | checks | make target |
|---|---|---|
| `versions.py` | one version across every package, failing when they drift | `versions` |
| `check_publishable.py` | every cross-package dependency is publishable, not merely resolvable from the workspace | `publishable` |
| `check_wheels.py` | the built wheels install and work together outside the workspace | `wheels` |
| `check_deps.py` | declared dependencies match what the code imports, one package at a time | `deps` |
| `check_interop.py` | the adduce integration still holds for the adduce people install | `interop` |
| `commit_msg_attribution.py` | AI co-authorship trailers are rewritten as disclosure | commit-msg hook |
| `coverage_hook` | subprocess coverage measurement, since most suites drive a CLI | `coverage` |

The scripts that produced the manuscript's figures moved to `reproducible-science-paper`, and
the addressability corpus to `reproducible-science-evaluations`. Both read repositories other
than this one, which is why a push here no longer waits on a filesystem scan.
