"""Versioned policy for the bounded Phase-C research loop."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ResearchLoopPolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    max_rounds_by_tier: dict[str, int] = Field(default_factory=lambda: {"*": 4})
    max_gap_fields_per_round: int = Field(default=8, ge=1)
    marginal_yield_floor: float = Field(default=0.0, ge=0.0, le=1.0)
    strategy_transitions: dict[str, tuple[str, ...]] = Field(
        default_factory=lambda: {
            "deterministic_exact": ("official_site_exact",),
            "official_site_exact": ("tier3_web_widened",),
            "tier3_web_widened": ("tier4_research_product",),
            "tier4_research_product": (),
        }
    )

    @model_validator(mode="after")
    def _valid_rounds(self) -> ResearchLoopPolicy:
        if not self.max_rounds_by_tier:
            raise ValueError("max_rounds_by_tier must not be empty")
        if any(value < 1 for value in self.max_rounds_by_tier.values()):
            raise ValueError("every max-round value must be at least one")
        return self

    def max_rounds_for(self, tier: str) -> int:
        value = self.max_rounds_by_tier.get(tier, self.max_rounds_by_tier.get("*"))
        if value is None:
            raise ValueError(f"no research-loop max rounds configured for tier {tier!r}")
        return value

    def validate_strategy_catalog(self, keys: frozenset[str]) -> None:
        mentioned = set(self.strategy_transitions)
        mentioned.update(k for values in self.strategy_transitions.values() for k in values)
        unknown = mentioned - keys
        if unknown:
            raise ValueError(f"strategy_transitions names unknown strategy keys: {sorted(unknown)}")


DEFAULT_RESEARCH_LOOP_POLICY = ResearchLoopPolicy()

__all__ = ["ResearchLoopPolicy", "DEFAULT_RESEARCH_LOOP_POLICY"]
