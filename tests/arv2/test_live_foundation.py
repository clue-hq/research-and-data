"""The foundation against the real network — Global Constraint 3: no replay, no mocked bodies.

Two calls prove the whole Step-0 path end to end: an unpaid public GET (the ATS board every
account's hiring signal comes from) and one paid OpenRouter completion whose cost the wrapper
reads from the provider's own metering and writes to the ledger.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path

from clue_api.arv2.calls import CallSpec, ProviderCaller, SpendEstimate
from clue_api.arv2.openrouter import (
    openrouter_chat_request,
    openrouter_cost_reader,
)
from clue_api.arv2.transport import BROWSER_USER_AGENT, HttpRequest
from clue_config import Secrets
from clue_config.gateway import GatewayConfig
from tests.arv2.conftest import require_secret

#: Zafran Security's public Ashby board (Global Constraint 11's answer key).
ASHBY_URL = "https://api.ashbyhq.com/posting-api/job-board/zafran-security?includeCompensation=true"

#: Well above the point where a reasoning model spends its whole budget before answering: at 16
#: tokens this model returns ``finish_reason=length`` with zero usage and zero reported cost, so a
#: cost assertion there would be asserting the absence of an answer.
CHAT_MAX_TOKENS = 64


def _ledger_rows(path: Path, call_id: str) -> list[dict[str, object]]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    return [row for row in rows if row["call_id"] == call_id]


def test_the_public_ats_board_is_fetched_saved_and_ledgered(
    make_caller: Callable[..., ProviderCaller], arv2_raw_root: Path
) -> None:
    """Law 1 over a real, free call: a raw record on disk and both ledger rows costing nothing.

    The browser user-agent is load-bearing: Ashby answers 403 to a default client string.
    """
    caller = make_caller()
    spec = CallSpec(
        provider="ashby",
        operation="posting-api/job-board",
        label="zafran-security",
        request=HttpRequest(
            method="GET",
            url=ASHBY_URL,
            headers={"User-Agent": BROWSER_USER_AGENT, "Accept": "application/json"},
            timeout_s=45.0,
        ),
    )

    result = caller.call(spec)

    assert result.response.status == 200
    body = result.json()
    assert isinstance(body, dict)
    assert isinstance(body.get("jobs"), list)

    assert result.raw_ref is not None
    raw_path = Path(result.raw_ref)
    assert raw_path.exists()
    record = json.loads(raw_path.read_text(encoding="utf-8"))
    assert record["response"]["status"] == 200
    assert record["request"]["url"] == ASHBY_URL

    rows = _ledger_rows(arv2_raw_root / "ledger.jsonl", record["call_id"])
    assert [row["phase"] for row in rows] == ["estimate", "result"]
    assert rows[0]["outcome"] == "estimate"
    assert rows[1]["outcome"] == "ok"
    assert Decimal(str(rows[1]["cost_usd"])) == Decimal(0)
    assert rows[1]["raw_ref"] == result.raw_ref
    assert rows[1]["over_ceiling"] is False


def test_an_openrouter_completion_records_its_real_cost_and_request_id(
    make_caller: Callable[..., ProviderCaller], arv2_raw_root: Path, live_secrets: Secrets
) -> None:
    """One paid call: the ledger row carries OpenRouter's own cost and id, not a guess."""
    require_secret(live_secrets, "openrouter_api_key")
    api_key = live_secrets.openrouter_api_key
    assert api_key is not None

    caller = make_caller()
    request = openrouter_chat_request(
        base_url=GatewayConfig().base_url,
        api_key=api_key,
        model="openai/gpt-5-mini",
        messages=[{"role": "user", "content": "Reply with the single word OK"}],
        reasoning={"effort": "minimal"},
        max_tokens=CHAT_MAX_TOKENS,
        timeout_s=180.0,
    )
    spec = CallSpec(
        provider="openrouter",
        operation="chat/completions",
        label="foundation-smoke",
        request=request,
        estimate=SpendEstimate(usd=Decimal("0.001")),
        cost_reader=openrouter_cost_reader,
    )

    result = caller.call(spec)

    assert result.response.status == 200
    assert result.cost.cost_usd is not None and result.cost.cost_usd > 0
    assert result.cost.provider_request_id is not None

    assert result.raw_ref is not None
    record = json.loads(Path(result.raw_ref).read_text(encoding="utf-8"))
    assert record["request"]["headers"]["Authorization"] == "***", "Constraint 5"

    rows = _ledger_rows(arv2_raw_root / "ledger.jsonl", record["call_id"])
    assert [row["phase"] for row in rows] == ["estimate", "result"]
    assert Decimal(str(rows[1]["cost_usd"])) == result.cost.cost_usd
    assert rows[1]["provider_request_id"] == result.cost.provider_request_id
    assert rows[1]["extras"]["cost_source"] == "metered", "OpenRouter's own metering answered"
    assert caller.totals().usd == result.cost.cost_usd

    cost = result.call_cost
    assert cost.cost_source == "metered"
    assert cost.cost_usd == result.cost.cost_usd
    assert cost.ledger_row_id == rows[1]["row_id"] == result.ledger_row_id
    assert cost.raw_ref == result.raw_ref
    assert (cost.provider, cost.operation) == ("openrouter", "chat/completions")
