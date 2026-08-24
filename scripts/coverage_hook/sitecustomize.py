"""Start coverage in subprocesses.

Several test suites here drive a CLI the way a user does -- `python -m results.cli ...` in a
real subprocess -- because an in-process call cannot catch an entry point that crashes on
import or a command that writes to the wrong stream. Coverage measures the process it starts
and no other, so those 269 statements in `results/cli.py` reported 0% while 31 tests exercised
them. A floor set on that number would have been a floor on a fiction.

Python imports `sitecustomize` at startup if it is on the path, which is how the measurement
reaches a child process. `process_startup()` is a no-op unless `COVERAGE_PROCESS_START` is
set, so this file costs nothing outside a coverage run.
"""

from __future__ import annotations

try:
    import coverage
except ImportError:  # coverage is a dev dependency; a plain run must not fail here
    pass
else:
    coverage.process_startup()
