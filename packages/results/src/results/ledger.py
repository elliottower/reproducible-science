"""Append-only JSONL ledger: every event is one line, hash-chained to the previous.

**Threat model.** The chain detects accidental damage and casual editing: a crashed write, a
bad sync, a file opened in an editor, a line changed by hand. It does not defend against an
adversary who can write to the directory, because such an adversary can rewrite the anchor as
readily as the ledger. Defending against that needs an external anchor, and the head digest here
is what is published to one: `results timestamp` sends it to the OpenTimestamps calendars, and
`results.stamps` reads the proofs back against the chain.

Saying this plainly matters more than the mechanism. A hash chain is often read as proof of
tamper-resistance when it delivers tamper-*evidence*, and only against a party who does not
hold the pen.

**What the anchor buys.** A chain of `prev_hash` links proves each line follows the one before
it. It does not prove that the last line is the last line ever written: cut the file at any
line boundary and the remainder is a valid chain. Recording the length and head digest
separately turns truncation from undetectable into detected, and turns silent deletion of the
whole ledger into a reported error rather than a clean run.
"""

from __future__ import annotations

# Re-exported under the names this module has always used: `ledger.sha256_of_file` and
# `ledger.ZERO` are its surface, and callers should not have to know where they moved.
from provenance_core import ZERO as ZERO
from provenance_core import sha256_of_file as sha256_of_file
from provenance_core import sha256_of_text

# The chain itself is `provenance_core.chain`, which the record of checks `repro verify` keeps
# is written with too. Every name it had here it still has here, and is the same object.
from provenance_core.chain import ANCHOR as ANCHOR
from provenance_core.chain import CANON_VERSION as CANON_VERSION
from provenance_core.chain import ChainError as ChainError
from provenance_core.chain import ChainStatus as ChainStatus
from provenance_core.chain import _append_locked as _append_locked
from provenance_core.chain import _lines as _lines
from provenance_core.chain import _verify_locked as _verify_locked
from provenance_core.chain import anchor_path as anchor_path
from provenance_core.chain import append_event as append_event
from provenance_core.chain import canonical as canonical
from provenance_core.chain import last_hash as last_hash
from provenance_core.chain import line_hashes as line_hashes
from provenance_core.chain import now_iso as now_iso
from provenance_core.chain import read_anchor as read_anchor
from provenance_core.chain import read_ledger as read_ledger
from provenance_core.chain import reanchor as reanchor
from provenance_core.chain import verify as verify
from provenance_core.chain import verify_chain as verify_chain
from provenance_core.chain import write_anchor as write_anchor

LEDGER = "ledger.jsonl"


class ResultsError(Exception):
    """Base for every error this package raises, but for `ChainError`.

    `ChainError` is raised by the chain's writer and reader, which `provenance_core.chain`
    holds, so it is defined there and is not a subclass of this. The command catches both.
    """


class NoLedgerRootError(ResultsError):
    """No `.results/` directory governs this location.

    Raised rather than exited, so importing this package into a test, a notebook or an agent
    hook cannot take the host process down. Only the CLI turns it into an exit code.
    """

    def __init__(self, directory: str = "") -> None:
        self.directory = directory
        super().__init__(
            f"no .results/ in {directory or 'this directory'} or above; `results init` makes one"
        )


def sha256_of_str(s: str) -> str:
    """The shared text hasher, under the name this module has always used."""
    return sha256_of_text(s)
