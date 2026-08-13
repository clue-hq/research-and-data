"""P3.2 live probe #2 (PD-part3 delta 6): the OpenRouter economics passthrough, for real.

Verifies against the live provider what the offline tests can only assert about the wire
shape:

  1. the Responses endpoint ACCEPTS `extra_body = {provider: {sort}, usage: {include}}`
     (no 400) — the knobs ride config, and OpenRouter honors them on this endpoint;
  2. two consecutive calls sharing a long identical prefix produce
     `cached_prompt_tokens > 0` on the second call — the design runtime's cached-prefill
     economics, now measurable through the governed wrapper (TokenUsage contract-delta);
  3. the role label rides `response_metadata.clue_role` and the `model_call_usage`
     record on live calls;
  4. `supports_image_input` answers from the real catalog for the design trio's model.

Run (billed — two mid-size calls + one catalog GET):
    set -a; source ../damascus/.env; set +a
    uv run python scripts/p32_probe_economics.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import SecretStr

from clue_config.gateway import GatewayConfig
from clue_gateway.agent_model import OpenRouterAgentModelProvider

MODEL_ID = os.environ.get("P32_PROBE_MODEL", "openai/gpt-5.6-terra")

# A stable prefix comfortably past provider auto-caching floors (~1024 tokens).
_PREFIX = (
    "You are the design orchestrator for an ABM creative platform. "
    "House rules, restated verbatim for every turn: honor the brand kit's tokens; "
    "never invent hex values; propose before applying; cite the artboard by id; "
    "keep typography on the kit's faces; QR codes come from the governed generator; "
    "reference imagery is advisory, never pasted; exports go through preflight. "
) * 60


async def main() -> int:
    key = os.environ.get("CLUE_OPENROUTER_API_KEY") or os.environ.get("OPENROUTER_API_KEY")
    if not key:
        print("NO KEY: source a workspace .env with CLUE_OPENROUTER_API_KEY first")
        return 2

    provider = OpenRouterAgentModelProvider(
        GatewayConfig(
            timeout_s=120.0,
            openrouter_provider_sort="throughput",
            openrouter_usage_include=True,
        ),
        SecretStr(key),
    )
    model = provider.build(
        model_id=MODEL_ID,
        timeout_s=110.0,
        max_retries=1,
        max_output_tokens=64,
        temperature=0.0,
        role="design_author",
    )

    verdicts: dict[str, str] = {}

    first = await model.ainvoke(
        [SystemMessage(content=_PREFIX), HumanMessage(content="Say READY.")]
    )
    usage1, _, _ = model._usage_and_cost(first)
    verdicts["1_extra_body_accepted"] = "PASS"  # a 400 would have raised before this line
    verdicts["3_role_metadata"] = (
        "PASS" if first.response_metadata.get("clue_role") == "design_author" else "FAIL"
    )

    second = await model.ainvoke(
        [SystemMessage(content=_PREFIX), HumanMessage(content="Say STEADY.")]
    )
    usage2, _, _ = model._usage_and_cost(second)
    verdicts["2_cached_prefill_on_second_call"] = (
        f"PASS (cached {usage2.cached_prompt_tokens}/{usage2.prompt_tokens})"
        if usage2.cached_prompt_tokens > 0
        else f"FAIL (cached=0 of {usage2.prompt_tokens}; "
        f"first call cached={usage1.cached_prompt_tokens})"
    )

    capability = provider.supports_image_input(MODEL_ID)
    verdicts["4_capability_catalog"] = (
        "PASS (vision=True)" if capability is True else f"UNEXPECTED ({capability!r})"
    )

    print(json.dumps({"model": MODEL_ID, "verdicts": verdicts}, indent=2))
    return 0 if all(v.startswith("PASS") for v in verdicts.values()) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
