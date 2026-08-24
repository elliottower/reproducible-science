"""Ways of presenting a report.

A renderer reads a `VerificationReport` and an `Assessment` and produces bytes. None computes
anything: two renderers over one report always say the same thing in different formats, which
is the property that makes it safe to add a third.
"""

from repro.renderers.sarif import to_sarif

__all__ = ["to_sarif"]
