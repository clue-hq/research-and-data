"""Contact-profiling result + config types (M8.4).

``profile_contact`` returns **references** + the per-claim handoff views; ``profile_claims`` is
built directly to the handoff :class:`~clue_core.handoff.ProfileClaimView` shape (value,
evidence_span, source_tier, identity_binding, use_class) so M12 assembles the committee member's
``profile_claims`` without translation (overview §3)."""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from clue_core import (
    ClaimId,
    CostCents,
    EntityId,
    IdentityBinding,
    ProfileClaimView,
    UseClass,
)


class ContactProfileConfig(BaseModel):
    """Contact-profiling knobs (policy as data; Doc C §8)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    # A list-valued facet with at least this many values is "rich" enough to warrant a facet
    # sub-worker (the level-2 fan-out, Doc C §3) — when the per-tier recursion budget allows.
    facet_subworker_min_values: int = Field(default=3, ge=1)


DEFAULT_CONTACT_PROFILE_CONFIG = ContactProfileConfig()


class ContactProfileResult(BaseModel):
    """The result of ``profile_contact`` — the per-claim handoff views + coverage tallies + the
    facet sub-worker requests the M7 orchestrator routes through its spawn guard."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    contact_entity_id: EntityId
    account_entity_id: EntityId
    profile_claims: tuple[ProfileClaimView, ...] = ()
    cost_cents: CostCents = Decimal(0)
    fields_filled: int = 0
    fields_empty: int = 0
    # Facet sub-worker requests (level-2 fan-out) for the orchestrator; M8.4 self-limits to the
    # tier's recursion budget, the M7 SpawnGuard is the hard cap. Each: {aspect, field_keys, depth}.
    facet_requests: tuple[dict[str, JsonValue], ...] = ()

    @property
    def claim_refs(self) -> tuple[ClaimId, ...]:
        """Every written claim id (references only — the orchestrator never re-reads bodies)."""
        return tuple(view.claim_id for view in self.profile_claims)

    @property
    def strong_binding_count(self) -> int:
        return sum(1 for v in self.profile_claims if v.identity_binding is IdentityBinding.STRONG)

    @property
    def weak_binding_count(self) -> int:
        return sum(1 for v in self.profile_claims if v.identity_binding is IdentityBinding.WEAK)

    @property
    def sensitive_count(self) -> int:
        return sum(1 for v in self.profile_claims if v.use_class is UseClass.SENSITIVE)
