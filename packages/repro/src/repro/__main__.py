"""`python -m repro`.

The process boundary, and the only place in this package that exits.
"""
from repro.cli import main

raise SystemExit(main())
