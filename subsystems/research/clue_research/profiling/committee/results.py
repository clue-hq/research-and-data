"""Committee-discovery result + config types (M8.3).

The ``discover_committee`` output and its config. The result returns **references** (contact ids +
claim ids), never claim bodies (substrate §5b), and maps 1:1 to the handoff
:class:`~clue_core.handoff.CommitteeMember` shape so M12 assembles the committee without
translation (the per-member ``profile_claims`` are filled later by M8.4).
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from clue_core import ClaimId, CommitteeMember, Confidence, CostCents, EntityId, Persona
from clue_research.profiling.committee.coverage import CommitteeCoverage
from clue_research.profiling.committee.stopping import (
    DEFAULT_COMMITTEE_STOPPING_CONFIG,
    CommitteeStoppingConfig,
)


class CommitteeConfig(BaseModel):
    """Committee-discovery knobs (policy as data; Doc C §8 — confirm against real cost data)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    # Gateway model id for role inference; ``None`` → the worker falls back to the gateway config's
    # synthesis model (a model swap is a config change behind the gateway seam).
    role_model: str | None = None
    # Candidates to request per source per consultation.
    per_source_limit: int = Field(default=25, ge=1)
    stopping: CommitteeStoppingConfig = DEFAULT_COMMITTEE_STOPPING_CONFIG
    # The promotion floor M9 uses; documented here so the gate's clamp stays below it. A role-claim
    # confidence at/below ``implausible_confidence_ceiling`` is "flagged, not promoted".
    promotion_confidence_floor: float = Field(default=0.5, ge=0.0, le=1.0)
    implausible_confidence_ceiling: float = Field(default=0.15, ge=0.0, le=1.0)
    # Confidence assigned to a deterministic title-heuristic role (used on an LLM parse failure).
    fallback_confidence: float = Field(default=0.2, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _check_floor(self) -> CommitteeConfig:
        if self.implausible_confidence_ceiling >= self.promotion_confidence_floor:
            raise ValueError(
                "implausible_confidence_ceiling must be below promotion_confidence_floor so a "
                "flagged (implausible) role is genuinely not promotable"
            )
        return self


DEFAULT_COMMITTEE_CONFIG = CommitteeConfig()


class CommitteeMemberRef(BaseModel):
    """An admitted committee member, by reference — contact id + persona + the claim ids written.

    The handoff projection (:meth:`as_committee_member`) carries an empty ``profile_claims`` tuple:
    M8.3 produces the resolved, role-tagged member; M8.4 fills the per-member ``profile_claims`` and
    M12 joins the two (overview §3)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    contact_entity_id: EntityId
    persona: Persona
    role_on_committee: str  # the persona value as a string (CommitteeMember shape)
    role_confidence: Confidence
    role_plausible: bool
    discovery_claim_id: ClaimId
    role_claim_id: ClaimId
    persona_claim_id: ClaimId
    professional_claim_ids: tuple[ClaimId, ...] = ()

    def as_committee_member(self) -> CommitteeMember:
        """Project to the handoff :class:`CommitteeMember` shape (profile_claims filled by M8.4)."""
        return CommitteeMember(
            contact_entity_id=self.contact_entity_id,
            persona=self.persona,
            role_on_committee=self.role_on_committee,
            profile_claims=(),
        )


class CommitteeResult(BaseModel):
    """The result of ``discover_committee`` — admitted members (by reference), coverage, spend, and
    the admitted/needs-review/dropped tallies (the existence-gate audit)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    account_entity_id: EntityId
    members: tuple[CommitteeMemberRef, ...] = ()
    coverage: CommitteeCoverage
    cost_cents: CostCents = Decimal(0)
    admitted: int = 0
    needs_review: int = 0
    dropped: int = 0

    @property
    def claim_refs(self) -> tuple[ClaimId, ...]:
        """Every claim id written for the committee (discovery + role + persona per member) — the
        reference set the orchestrator merges into the account run's index (never blobs)."""
        refs: list[ClaimId] = []
        for member in self.members:
            refs.extend((member.discovery_claim_id, member.role_claim_id, member.persona_claim_id))
            refs.extend(member.professional_claim_ids)
        return tuple(refs)

    def committee(self) -> tuple[CommitteeMember, ...]:
        """The handoff-shaped committee (overview §3)."""
        return tuple(member.as_committee_member() for member in self.members)
