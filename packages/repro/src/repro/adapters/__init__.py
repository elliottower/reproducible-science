"""One module per artifact format.

Each adapter translates a locator into the addressing its format already has, and every
one returns the same `Found` contract. Adding a format is a new module and a registry
entry, not an edit to a switchboard.
"""
