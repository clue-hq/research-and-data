"""The Exa Agent surface against the real API — R1's Global Constraint 3: no replay, no mocked
bodies. One ``low``-effort run (~$0.025, under two minutes) against the company-overview schema
proves create → poll → completed, the structured output, the grounding and the metered cost.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import SecretStr

from clue_api.arv2.exa_client import ExaClient
from clue_api.arv2.onboarding_requests import (
    COMPANY_OVERVIEW_SYSTEM_PROMPT,
    company_overview_output_schema,
    company_overview_query,
)
from tests.arv2.conftest import require_secret


def test_a_low_effort_agent_run_completes_with_structured_output(live_secrets, make_caller) -> None:
    key = require_secret(live_secrets, "exa_api_key")
    client = ExaClient(make_caller(), SecretStr(key))

    run = client.agent_run(
        query=company_overview_query("Insight Health (insighthealth.ai)"),
        output_schema=company_overview_output_schema(),
        effort="low",
        system_prompt=COMPANY_OVERVIEW_SYSTEM_PROMPT,
        label="exa-agent-live-overview",
        timeout_s=600.0,
    )

    assert run.status == "completed", (run.status, run.error_code, run.error_message)
    assert run.run_id and run.run_id.startswith("agent_run_")
    assert isinstance(run.structured, dict)
    assert set(run.structured) >= {
        "facts",
        "sections",
        "competitors",
        "named_customers",
        "not_found",
    }
    assert set(run.structured["sections"]) == {
        "origin_story",
        "business_model",
        "positioning",
        "market_position",
        "customer_segments",
        "leadership",
        "recent_context",
    }
    assert run.grounding, "a completed run carries field-level grounding"
    assert run.cost.cost_source == "metered"
    assert run.cost_usd is not None and Decimal("0.005") <= run.cost_usd <= Decimal("0.10")
    assert run.polls >= 1
