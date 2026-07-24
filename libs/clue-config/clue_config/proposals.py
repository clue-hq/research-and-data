"""Versioned policy shape for Phase-C field/source proposal governance."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from clue_core.field import FieldClass


class ProposalPolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    auto_promote_tier3_sources: bool = False
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
        return self


DEFAULT_PROPOSAL_POLICY = ProposalPolicy()

__all__ = ["DEFAULT_PROPOSAL_POLICY", "ProposalPolicy"]
