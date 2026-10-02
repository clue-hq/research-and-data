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
    """An admitted committee member, by reference — contact id + the claim ids written, and the
    role assignment **when one exists**.

    Discovery/identity and role judgment are separate acts (contract §5.2): a member is admitted by
    the existence gate, and a role may be inferred later — by the worker (``worker_llm``) or by the
    account agent after the fact (``agent_deferred`` + D3's write-back). So the six role-derived
    fields are optional and **all-or-none**: either the member carries the full, provenance-backed
    role set, or it carries none of it. A partial mix would be a role assertion with no claim behind
    it — precisely the unevidenced shape the contract forbids.

    ``contact_entity_id``/``discovery_claim_id``/``professional_claim_ids`` are always present: a
    roleless member is still a real, identity-resolved, evidence-backed person.

    The handoff projection (:meth:`as_committee_member`) carries an empty ``profile_claims`` tuple:
    M8.3 produces the resolved member; M8.4 fills the per-member ``profile_claims`` and M12 joins
    the two (overview §3)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    contact_entity_id: EntityId
    persona: Persona | None = None
    # the persona value as a string (CommitteeMember shape)
    role_on_committee: str | None = None
    role_confidence: Confidence | None = None
    role_plausible: bool | None = None
    discovery_claim_id: ClaimId
    role_claim_id: ClaimId | None = None
    persona_claim_id: ClaimId | None = None
    professional_claim_ids: tuple[ClaimId, ...] = ()

    @model_validator(mode="after")
    def _check_role_set(self) -> CommitteeMemberRef:
        role_fields = (
            self.persona,
            self.role_on_committee,
            self.role_confidence,
            self.role_plausible,
            self.role_claim_id,
            self.persona_claim_id,
        )
        present = [value is not None for value in role_fields]
        if any(present) and not all(present):
            raise ValueError(
                "committee member role fields are all-or-none — a member carries the complete "
                "role set (persona, role_on_committee, role_confidence, role_plausible, "
                "role_claim_id, persona_claim_id) or none of it; a partial role is an assertion "
                "without its provenance"
            )
        return self

    @property
    def has_role(self) -> bool:
        """Whether a role inference has been recorded for this member."""
        return self.persona is not None

    def as_committee_member(self) -> CommitteeMember:
        """Project to the handoff :class:`CommitteeMember` shape (profile_claims filled by M8.4).

        The handoff shape *requires* a persona, so this is defined only for a role-carrying member.
        A roleless member raises rather than inventing a persona: it stays visible through its
        discovery + professional-fact claims (and the discovered-subject projection), never through
        a fabricated committee role."""
        if self.persona is None or self.role_on_committee is None:
            raise ValueError(
                f"committee member {self.contact_entity_id} carries no role inference, so it has "
                "no handoff CommitteeMember projection — a roleless member is visible via "
                "discovery, never via the handoff committee"
            )
        return CommitteeMember(
            contact_entity_id=self.contact_entity_id,
            persona=self.persona,
            role_on_committee=self.role_on_committee,
            profile_claims=(),
        )


class CommitteeResult(BaseModel):
    """The result of ``discover_committee`` — admitted members (by reference), coverage, spend, and
    the admitted/needs-review/dropped tallies (the existence-gate audit).

    ``needs_review`` = admitted members carrying **no role inference** — the roleless members a
    human (or, after ``agent_deferred`` discovery, the account agent) still has to judge."""

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
        """Every claim id written for the committee — the reference set the orchestrator merges
        into the account run's index (never blobs).

        A member's discovery + professional-fact claims are ALWAYS included; its role/persona claim
        ids only when a role was inferred. A roleless member is a discovered person with durable
        evidence, so dropping its claims here would hide it from every downstream index."""
        refs: list[ClaimId] = []
        for member in self.members:
            refs.append(member.discovery_claim_id)
            refs.extend(
                claim_id
                for claim_id in (member.role_claim_id, member.persona_claim_id)
                if claim_id is not None
            )
            refs.extend(member.professional_claim_ids)
        return tuple(refs)

    def committee(self) -> tuple[CommitteeMember, ...]:
        """The handoff-shaped committee (overview §3) — role-carrying members only.

        The handoff ``CommitteeMember`` is a *role-tagged* shape, so a member awaiting a role
        judgment is not in it. Such a member is not lost: it is visible through its discovery and
        professional-fact claims (``claim_refs``) and through the discovered-subject projection."""
        return tuple(member.as_committee_member() for member in self.members if member.has_role)
