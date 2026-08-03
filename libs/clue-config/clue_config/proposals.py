"""Versioned policy shape for Phase-C field/source proposal governance."""

from __future__ import annotations

import re
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from clue_core.field import FieldClass


class ClientFieldPromotionMode(StrEnum):
    """The versioned authority posture for tenant-local Client-KB extensions."""

    PROPOSAL_ONLY = "proposal_only"
    HUMAN_CONFIRM = "human_confirm"
    SAFE_AUTO_PROMOTE = "safe_auto_promote"


class ProposalPolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    auto_promote_tier3_sources: bool = False
    client_field_mode: ClientFieldPromotionMode = ClientFieldPromotionMode.HUMAN_CONFIRM
    client_field_policy_version: str = "dynamic-client-kb-v1"
    # Safe-auto is fail-closed on a policy-owned semantic contract. The proposing model can describe
    # sensitivity/authority, but it cannot add a hash to this set: only trusted configuration can
    # pre-authorize the exact field meaning/schema/use contract for autonomous promotion.
    safe_auto_client_field_contract_hashes: frozenset[str] = Field(default_factory=frozenset)
    max_client_field_schema_bytes: int = Field(default=4_096, ge=128, le=65_536)
    max_client_field_evidence_refs: int = Field(default=8, ge=1, le=64)
    human_field_classes: frozenset[FieldClass] = Field(
        default_factory=lambda: frozenset({FieldClass.CONTACT, FieldClass.CONTACT_FACET})
    )
    human_source_tiers: frozenset[int] = Field(default_factory=lambda: frozenset({1, 2}))
    min_observations_for_yield: int = Field(default=10, ge=1)
    demotion_yield_floor: float = Field(default=0.1, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _check_safety_floor(self) -> ProposalPolicy:
        required_classes = {FieldClass.CONTACT, FieldClass.CONTACT_FACET}
        if not required_classes.issubset(self.human_field_classes):
            raise ValueError("human_field_classes must include contact and contact.facet")
        if not {1, 2}.issubset(self.human_source_tiers):
            raise ValueError("human_source_tiers must include tiers 1 and 2")
        if any(tier < 1 or tier > 4 for tier in self.human_source_tiers):
            raise ValueError("human_source_tiers entries must be in 1..4")
        if not self.client_field_policy_version.strip():
            raise ValueError("client_field_policy_version must not be blank")
        if any(
            re.fullmatch(r"[0-9a-f]{64}", digest) is None
            for digest in self.safe_auto_client_field_contract_hashes
        ):
            raise ValueError("safe-auto client field contract hashes must be lowercase SHA-256")
        return self


DEFAULT_PROPOSAL_POLICY = ProposalPolicy()

__all__ = ["ClientFieldPromotionMode", "DEFAULT_PROPOSAL_POLICY", "ProposalPolicy"]
