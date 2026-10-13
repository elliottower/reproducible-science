"""What an assertion said each time it was checked."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from repro.core.outcomes import Outcome, Reason

SCHEMA_VERSION = "repro/1"


class CheckedAssertion(BaseModel):
    """One assertion as `repro verify` found it: what it declared, the bytes it was checked
    against, and the outcome.

    An assertion is the same assertion across edits where `claim_id`, `kind`, `name` and
    `position` are the same. A claim given another id, an assertion given another name, and
    two assertions of one kind and name that trade places each start a new history.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    claim_id: str
    kind: str
    name: str = ""
    position: int = 0
    """Which of the claim's assertions of this kind and name it is, from 0. A `quote` has no
    name, so two quotations in one claim are told apart by this alone."""

    claim_digest: str
    """`Claim.digest`: the claim's id, text and `where` as they were."""
    printed: str | None = None
    """The `reported` value, or the passage a quotation asserts."""
    address: str = ""
    """Where the assertion looked. Both sides of a `correspondence`, each with its name."""
    conversion: str = ""
    """The conversion declared between the stored value and the printed one, where there is
    one. Each side's, with its name, for a `correspondence`."""
    digests: dict[str, str | None] = {}
    """Per artifact the assertion read, the digest of the bytes read. None where nothing was
    at the declared path."""
    outcome: Outcome
    reason: Reason

    checked_at: str = ""
    """When the check that first found the assertion like this appended it. Read from the
    entry that holds it and not stored on the assertion."""
    verifiable: bool = True
    """False where the record this was read from does not verify at or before the entry
    holding it. The entry is shown as it reads; the chain no longer vouches for it."""

    @property
    def identity(self) -> tuple[str, str, str, int]:
        return self.claim_id, self.kind, self.name, self.position

    def same_as(self, other: CheckedAssertion) -> bool:
        """Whether two checks found the assertion saying the same thing with the same outcome,
        whenever they ran."""
        unset = {"checked_at": "", "verifiable": True}
        return self.model_copy(update=unset) == other.model_copy(update=unset)


class CheckRecord(BaseModel):
    """One entry of a record of checks: the assertions one `repro verify` found different from
    the last time each was recorded.

    The last three fields are the chain's, under the names the `results` ledger gives them:
    the entry's position from 0, when it was appended, and the SHA-256 of the entry before it
    as stored, or of nothing for the first.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = SCHEMA_VERSION
    assertions: tuple[CheckedAssertion, ...]
    seq: int
    timestamp: str
    prev_hash: str


class RecordState(BaseModel):
    """One record of checks as `repro why` found it: where it is and whether its chain holds."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["local", "tracked"]
    """`local` is the one in the repository's git directory, written by every `repro verify`
    and never committed. `tracked` is `.repro/checks.jsonl` in the working tree, written
    where `repro verify --record` asks."""
    path: str
    entries: int
    status: str
    """The `results` ledger's word for a chain: `intact`, `edited`, `reordered`, `corrupt`,
    `truncated`, `extended` or `no_anchor`."""
    problems: tuple[str, ...] = ()
    """Each fault found, naming its entry by its line in the file, from 1."""
    unverifiable_from: int | None = None
    """The first entry the chain does not vouch for. None where every entry present follows
    from the one before it."""
    diverges_at: int | None = None
    """Of the tracked record: the first entry that is not the local record's entry at that
    position. None where one record is the other's beginning."""
