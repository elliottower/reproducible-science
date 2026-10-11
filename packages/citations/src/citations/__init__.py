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

A name is imported from its module the first time it is asked for, and not when the package
is. Checking a quotation needs the PDF and spreadsheet readers, which take most of a second to
load, and a command that reads no source -- `citations lint`, `citations add`, the question
`prereg freeze` asks -- paid for them all the same, because importing any module here imports
this one first. `from citations import check_one` reads as it always did.
"""

from __future__ import annotations

import importlib
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _version
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
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
    from citations.paperclip import (
        Document,
        PaperclipUnavailableError,
        Provenance,
        Resolution,
        resolve_document,
    )
    from citations.readers import Extraction
    from citations.services import SERVICES, Candidate, Service
    from citations.verify import (
        OMISSION,
        Gap,
        Match,
        Omission,
        Pin,
        Report,
        Result,
        available_extractors,
        check_derived,
        check_one,
        check_pin,
        clear_caches,
        extract,
        extract_uncached,
        is_paginated,
        omission,
        reading,
        reading_with,
        resolve_in,
        sha256,
        single_out,
    )

try:
    __version__ = _version("citations")
except PackageNotFoundError:  # a source tree with nothing installed
    __version__ = "0+unknown"

#: Where each exported name is defined. `__all__` below is the same set of names, and a test
#: holds the two together, and holds both to the imports a type checker reads above.
_DEFINED_IN: dict[str, tuple[str, ...]] = {
    "citations.config": (
        "LibraryConfig",
        "PaperConfig",
    ),
    "citations.exceptions": (
        "CitationsError",
        "ClaimFileError",
        "LibraryNotFoundError",
        "PinBrokenError",
        "SourceUnreadableError",
    ),
    "citations.models": (
        "CitedBy",
        "Claim",
        "ClaimFile",
        "ClaimSource",
        "Quote",
        "Record",
        "load_claim_file",
        "load_record",
    ),
    "citations.paperclip": (
        "Document",
        "PaperclipUnavailableError",
        "Provenance",
        "Resolution",
        "resolve_document",
    ),
    "citations.readers": ("Extraction",),
    "citations.services": (
        "Candidate",
        "SERVICES",
        "Service",
    ),
    "citations.verify": (
        "Gap",
        "Match",
        "OMISSION",
        "Omission",
        "Pin",
        "Report",
        "Result",
        "available_extractors",
        "check_derived",
        "check_one",
        "check_pin",
        "clear_caches",
        "extract",
        "extract_uncached",
        "is_paginated",
        "omission",
        "reading",
        "reading_with",
        "resolve_in",
        "sha256",
        "single_out",
    ),
}
_MODULE_OF = {name: module for module, names in _DEFINED_IN.items() for name in names}

#: The modules that were attributes of this package when it imported them all on import, so
#: `import citations` followed by `citations.verify.check_one` still reads.
_SUBMODULES = frozenset(
    {
        "config",
        "exceptions",
        "extraction_cache",
        "extractors",
        "models",
        "paperclip",
        "paths",
        "readers",
        "services",
        "text",
        "verify",
    }
)


def __getattr__(name: str) -> Any:
    """Import the module that defines `name`, once, and keep the name here afterwards."""
    if name in _SUBMODULES:
        return importlib.import_module(f"{__name__}.{name}")
    module = _MODULE_OF.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(importlib.import_module(module), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted({*globals(), *__all__})


__all__ = [
    "OMISSION",
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
    # a source fetched through Paperclip and pinned locally
    "Document",
    # what read the source
    "Extraction",
    "Gap",
    # library configuration
    "LibraryConfig",
    "LibraryNotFoundError",
    "Match",
    "Omission",
    "PaperConfig",
    # checking
    "PaperclipUnavailableError",
    "Pin",
    "PinBrokenError",
    "Provenance",
    "Quote",
    "Record",
    "Report",
    "Resolution",
    "Result",
    "Service",
    "SourceUnreadableError",
    "__version__",
    "available_extractors",
    "check_derived",
    "check_one",
    "check_pin",
    "clear_caches",
    "extract",
    "extract_uncached",
    "is_paginated",
    "load_claim_file",
    "load_record",
    "omission",
    "reading",
    "reading_with",
    "resolve_document",
    "resolve_in",
    "sha256",
    "single_out",
]
