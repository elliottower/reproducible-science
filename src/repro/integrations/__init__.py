"""Adapters that surface repro's verification inside other tools.

Each module here is imported by the host tool through an entry point, never by repro itself,
so the host is guaranteed to be installed whenever one of these runs and importing its API at
module level is safe.
"""
