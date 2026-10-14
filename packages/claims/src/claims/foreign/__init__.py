"""Other checkers' results, read into check records.

Each module reads one tool's own output files and imports nothing of that tool. It writes one
`claims.record.ExportRecord` per check the other tool reports, with that tool as the checker and
its own words in `native_outcome` and `native_reason`, and never runs the other tool.
"""
