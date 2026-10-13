"""What an assertion said each time it was checked."""

from __future__ import annotations

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
    digests: dict[str, str | None] = {}
    """Per artifact the assertion read, the digest of the bytes read. None where nothing was
    at the declared path."""
    outcome: Outcome
    reason: Reason

    checked_at: str = ""
    """When the check that first found the assertion like this started."""

    @property
    def identity(self) -> tuple[str, str, str, int]:
        return self.claim_id, self.kind, self.name, self.position

    def same_as(self, other: CheckedAssertion) -> bool:
        """Whether two checks found the assertion saying the same thing with the same outcome,
        whenever they ran."""
        return self.model_copy(update={"checked_at": ""}) == other.model_copy(
            update={"checked_at": ""}
        )


class CheckRecord(BaseModel):
    """One line of the record of checks: the assertions one `repro verify` found different
    from the last time each was recorded."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = SCHEMA_VERSION
    checked_at: str
    assertions: tuple[CheckedAssertion, ...]
