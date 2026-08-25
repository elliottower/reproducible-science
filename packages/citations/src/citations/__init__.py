"""A library of quotations checked against the sources they came from.

The point is not to find text faster. It is to accumulate quotations that have been verified
against a pinned artifact, so later work quotes from the library instead of from memory.

Everything a caller needs is exported here, so importing from a private module path is never
necessary, and every entry point returns a value rather than printing one:

    from citations import load_claim_file, check_one, check_pin, CitationsError

    claims = load_claim_file(path)
    pin = check_pin(claims.artifact(), claims.source.sha256)
    for claim in claims.claims.values():
        for quote in claim.quotes:
            result = check_one(quote.text, claims.artifact(), quote.page)

Nothing in this package calls `sys.exit` or raises `SystemExit`; failures raise
`CitationsError`, so importing it into another program -- an agent skill, a test, a notebook
-- cannot take the host process down.
"""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _version

from citations.config import LibraryConfig, PaperConfig
from citations.exceptions import (
    CitationsError,
    ClaimFileError,
    LibraryNotFoundError,
    PinBrokenError,
    SourceUnreadableError,
)
from citations.models import (
    CitedBy,
    Claim,
    ClaimFile,
    ClaimSource,
    Quote,
    Record,
    load_claim_file,
    load_record,
)
from citations.readers import Extraction
from citations.readers import available as available_readers
from citations.services import SERVICES, Candidate, Service
from citations.verify import (
    Pin,
    Report,
    Result,
    check_one,
    check_pin,
    clear_caches,
    extract,
    is_paginated,
    reading,
    sha256,
)

try:
    __version__ = _version("citations")
except PackageNotFoundError:  # a source tree with nothing installed
    __version__ = "0+unknown"

__all__ = [
    # identifier lookup
    "SERVICES",
    "Candidate",
    # errors
    "CitationsError",
    "CitedBy",
    # shapes on disk
    "Claim",
    "ClaimFile",
    "ClaimFileError",
    "ClaimSource",
    # what read the source
    "Extraction",
    # library configuration
    "LibraryConfig",
    "LibraryNotFoundError",
    "PaperConfig",
    # checking
    "Pin",
    "PinBrokenError",
    "Quote",
    "Record",
    "Report",
    "Result",
    "Service",
    "SourceUnreadableError",
    "__version__",
    "available_readers",
    "check_one",
    "check_pin",
    "clear_caches",
    "extract",
    "is_paginated",
    "load_claim_file",
    "load_record",
    "reading",
    "sha256",
]
