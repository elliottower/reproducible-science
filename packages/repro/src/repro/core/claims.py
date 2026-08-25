"""A statement a manuscript makes, and whether it was registered before the run."""

from __future__ import annotations

import enum

from pydantic import BaseModel, ConfigDict, model_validator
from repro.core.artifacts import Digest
from repro.core.evidence import Evidence

SCHEMA_VERSION = "repro/1"

_SHA256_HEX = r"^[a-f0-9]{64}$"


# ------------------------------------------------------------------------------------ claims


class Availability(enum.StrEnum):
    """Whether a claim offers anything to check. A property of the claim, not of a check."""

    OFFERED = "offered"
    NOT_OFFERED = "not_offered"


class Registration(enum.StrEnum):
    """Whether a plan could have fixed this claim's outcome in advance.

    Three states, because two conflate different things. A descriptive measurement that was
    never registered and an exhaustive count that nothing could have registered look identical
    under a boolean and are not the same claim.
    """

    CONFIRMATORY = "confirmatory"
    """Reports a preregistered outcome. The ordering check applies."""
    EXPLORATORY = "exploratory"
    """An outcome that a plan could have fixed and did not. The default: a claim that says
    nothing about registration is exploratory, never inapplicable."""
    NOT_APPLICABLE = "not_applicable"
    """No outcome was selected, so registration has nothing to bind -- an exhaustive
    deterministic measurement reports whatever it finds. Must carry a reason: this state is
    asserted, never assumed, or it is a way for any claim to opt out of being graded."""


class Claim(BaseModel):
    """A statement made in a manuscript, and the evidence offered for it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    text: str
    where: str | None = None
    registration: Registration = Registration.EXPLORATORY
    registration_note: str = ""
    """Why registration does not apply. Required when `registration` is `not_applicable`, and
    the same convention a preregistration uses for an inapplicable heading: N/A with a reason,
    never a blank."""

    evidence: tuple[Evidence, ...] = ()

    @model_validator(mode="before")
    @classmethod
    def _accept_confirmatory_flag(cls, data):
        """`confirmatory: true|false` still parses, so manifests written against the boolean
        keep working. `false` becomes `exploratory` and not `not_applicable`: a boolean never
        carried the distinction, so reading one in cannot invent it."""
        if isinstance(data, dict) and "confirmatory" in data:
            data = dict(data)
            flag = data.pop("confirmatory")
            data.setdefault(
                "registration", Registration.CONFIRMATORY if flag else Registration.EXPLORATORY
            )
        return data

    @model_validator(mode="after")
    def _not_applicable_needs_a_reason(self):
        if self.registration is Registration.NOT_APPLICABLE and not self.registration_note:
            raise ValueError(
                f"claim {self.id!r}: registration 'not_applicable' needs a registration_note "
                f"saying why no plan could have fixed this outcome"
            )
        return self

    @property
    def confirmatory(self) -> bool:
        return self.registration is Registration.CONFIRMATORY

    @property
    def availability(self) -> Availability:
        return Availability.OFFERED if self.evidence else Availability.NOT_OFFERED

    @property
    def digest(self) -> Digest:
        """Content address of the claim as evaluated.

        A decision names this so it cannot silently remain attached to text that has since
        been edited.
        """
        return Digest.of_text(f"{self.id}\x00{self.text}\x00{self.where or ''}")
