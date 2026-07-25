"""A tiny deterministic stub gold set for the scaffold + CI (M0.6).

Enough to exercise every rubric and the judge end-to-end with no live calls. Deliberately includes:
one wrong value (factual_accuracy < 1.0, proving the scorer actually scores), and one tier-4 claim
whose value is NOT in its evidence span (so StubJudge and GroundedStubJudge
disagree — the regression-on-swap demonstration). The real hand-verified gold set lands with M9/M11.
"""

from __future__ import annotations

from clue_core import (
    Claim,
    EntityType,
    ExtractionMethod,
    ResearchMode,
    account_claim,
    new_entity_id,
    new_run_id,
)
from clue_research.evals.models import GoldClaim, GoldEntity, GoldSet


def stub_gold_set() -> tuple[GoldSet, list[Claim]]:
    """Return a (gold_set, produced_claims) pair for the scaffold harness run."""
    account = new_entity_id()
    run = new_run_id()

    gold = GoldSet(
        name="stub",
        entities=(
            GoldEntity(
                entity_id=account,
                entity_type=EntityType.ACCOUNT,
                claims=(
                    GoldClaim(
                        field_key="core.employee_count",
                        expected_value=500,
                        max_source_tier=1,
                        requires_evidence_span=False,
                    ),
                    GoldClaim(
                        field_key="account.recent_funding",
                        expected_value={"round": "B", "amount_usd": 1_000_000},
                        max_source_tier=3,
                    ),
                    GoldClaim(
                        field_key="account.operational_pain",
                        expected_value="slow onboarding",
                        max_source_tier=4,
                    ),
                ),
            ),
        ),
    )

    produced = [
        # wrong value (gold expects 500) -> factual_accuracy will not be perfect
        account_claim(
            entity_id=account,
            field_key="core.employee_count",
            value_json=480,
            source_tier=1,
            extraction_method=ExtractionMethod.API,
            confidence=0.99,
            run_id=run,
            research_mode=ResearchMode.ACCOUNT_PROFILING,
            source_url="https://api.example.com/firmographics",
        ),
        account_claim(
            entity_id=account,
            field_key="account.recent_funding",
            value_json={"round": "B", "amount_usd": 1_000_000},
            source_tier=2,
            extraction_method=ExtractionMethod.SCRAPE,
            confidence=0.9,
            run_id=run,
            research_mode=ResearchMode.ACCOUNT_PROFILING,
            source_url="https://news.example.com/acme-series-b",
            evidence_span="Acme raised a $1M Series B",
        ),
        # tier-4 synthesis: span present, but the value text is NOT in the span -> the two stub
        # judges disagree (regression-on-swap)
        account_claim(
            entity_id=account,
            field_key="account.operational_pain",
            value_json="slow onboarding",
            source_tier=4,
            extraction_method=ExtractionMethod.LLM_SYNTHESIS,
            confidence=0.7,
            run_id=run,
            research_mode=ResearchMode.ACCOUNT_PROFILING,
            source_url="https://exa.example.com/synthesis",
            evidence_span="employees report it takes weeks to ramp up",
        ),
    ]
    return gold, produced
