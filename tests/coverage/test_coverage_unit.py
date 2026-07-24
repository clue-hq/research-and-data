from __future__ import annotations

import json
from decimal import Decimal

import pytest
from pydantic import ValidationError

from clue_config.coverage import ResearchLoopPolicy
from clue_core import Completion, EmbeddingResult, Message, ResearchTerminalStatus
from clue_research.coverage import DEFAULT_STRATEGIES, GoalJudge, GoalJudgeCall
from clue_research.coverage.golden import GOLDEN_CASES


class _Gateway:
    def __init__(self, text: str) -> None:
        self.text = text

    def complete(self, *, model: str, messages: list[Message], **opts: object) -> Completion:
        return Completion(model=model, text=self.text, cost_cents=Decimal("0.25"))

    def embed(self, *, model: str, inputs: list[str]) -> EmbeddingResult:
        raise AssertionError("goal judge never embeds")


def _judge(gateway: _Gateway) -> GoalJudgeCall:
    return GoalJudge(gateway, model="judge/test").judge(
        planned_fields=["account.recent_funding"],
        current_claim_refs={"account.recent_funding": []},
        prior_attempts=[],
        current_round_attempts=[
            {
                "field_key": "account.recent_funding",
                "strategy_key": "deterministic_exact",
                "outcome": "no_hit",
            }
        ],
        remaining_budget_cents="5",
        hard_round_cap=4,
    )


def test_goal_judge_parses_only_the_typed_shape() -> None:
    payload = {
        "assessments": [
            {
                "field_key": "account.recent_funding",
                "meaningful_gap_remaining": True,
                "recommendation": "continue",
                "warning_codes": ["insufficient_evidence"],
                "rationale": "The goal still lacks evidence for this field.",
            }
        ],
        "sufficient_for_goal": False,
    }
    call = _judge(_Gateway(f"prefix\n{json.dumps(payload)}\ntrailing"))
    assert call.valid is True
    assert call.result is not None
    assert call.result.assessments[0].meaningful_gap_remaining is True
    assert call.result.assessments[0].recommendation.value == "continue"
    assert call.cost_cents == Decimal("0.25")


@pytest.mark.parametrize(
    "text",
    [
        "not json",
        '{"assessments":[{"field_key":"account.recent_funding",'
        '"meaningful_gap_remaining":true,"recommendation":"continue",'
        '"warning_codes":[],"rationale":"x","recommended_strategy_key":'
        '"official_site_exact"}],"sufficient_for_goal":false}',
        '{"assessments":"wrong","sufficient_for_goal":false}',
        '{"assessments":[{"field_key":"account.unplanned",'
        '"meaningful_gap_remaining":true,"recommendation":"continue",'
        '"warning_codes":[],"rationale":"x"}],"sufficient_for_goal":false}',
    ],
)
def test_malformed_or_injected_goal_judge_output_fails_closed(text: str) -> None:
    call = _judge(_Gateway(text))
    assert call.valid is False
    assert call.result is None


def test_research_loop_policy_validates_caps_and_catalog() -> None:
    with pytest.raises(ValidationError):
        ResearchLoopPolicy(max_rounds_by_tier={"high": 0})
    policy = ResearchLoopPolicy()
    with pytest.raises(ValueError, match="unknown strategy"):
        policy.validate_strategy_catalog(frozenset({"deterministic_exact"}))
    policy.validate_strategy_catalog(frozenset(item.key for item in DEFAULT_STRATEGIES))


def test_every_retry_transition_changes_a_stable_dimension() -> None:
    strategies = {item.key: item for item in DEFAULT_STRATEGIES}
    policy = ResearchLoopPolicy()
    for current, next_keys in policy.strategy_transitions.items():
        for next_key in next_keys:
            assert strategies[current].dimensions != strategies[next_key].dimensions


def test_golden_cases_cover_useful_retry_and_honest_stop() -> None:
    assert {case.case_id for case in GOLDEN_CASES} == {
        "official_miss_widens",
        "last_strategy_stops_honestly",
    }
    terminal = next(case for case in GOLDEN_CASES if case.expected_terminal_reason)
    assert terminal.expected_next is None
    assert terminal.expected_terminal_reason == "strategies_exhausted"


def test_terminal_status_is_distinct_from_discovery_coverage() -> None:
    assert ResearchTerminalStatus.FILLED.value == "filled"
