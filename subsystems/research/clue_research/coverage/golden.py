"""Small offline C1 golden set: useful retry and honest terminal stopping."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class CoverageGoldenCase(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    case_id: str
    prior_strategy: str
    prior_outcome: str
    allowed_next: tuple[str, ...]
    expected_next: str | None
    expected_terminal_reason: str | None


GOLDEN_CASES = (
    CoverageGoldenCase(
        case_id="official_miss_widens",
        prior_strategy="official_site_exact",
        prior_outcome="no_hit",
        allowed_next=("tier3_web_widened",),
        expected_next="tier3_web_widened",
        expected_terminal_reason=None,
    ),
    CoverageGoldenCase(
        case_id="last_strategy_stops_honestly",
        prior_strategy="tier4_research_product",
        prior_outcome="no_hit",
        allowed_next=(),
        expected_next=None,
        expected_terminal_reason="strategies_exhausted",
    ),
)

__all__ = ["CoverageGoldenCase", "GOLDEN_CASES"]
