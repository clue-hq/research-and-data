"""`clue_gateway` — the shared LLM gateway client (OpenRouter), M0.4 / conventions §4.

The concrete egress for every *direct* LLM call. The protocol + value types live in
:mod:`clue_core.gateway` (the shared-contracts package); **this** package holds the live
OpenRouter client, the deterministic CI stub, the :class:`TracingGateway` that emits the
``llm.gateway_call`` span, and :func:`build_gateway` (the stub/live toggle behind the seam). It sits
**above** the ``obs → config → core`` shared base, so it may import ``obs`` to trace; the ``openai``
SDK is imported **only** here (import-linter Rule 4b), so a model swap — or OpenRouter → another
OpenAI-compatible gateway — is a config change, never a caller change.

**Carve-out (conventions §2):** Exa Deep / Parallel Task (M11) are tier-4 research-product
*resolvers* with their own keys — **not** gateway calls.

Implements the LLM-gateway deliverable of ENG-120
(docs/specs/M00-foundations-and-shared-contracts.md §M0.4).
"""

from __future__ import annotations

from clue_gateway.agent_model import OpenRouterAgentModelProvider
from clue_gateway.factory import build_gateway
from clue_gateway.metadata import (
    ANSWERING_MODEL_KEY,
    COST_CENTS_KEY,
    COST_SOURCE_KEY,
    CostSource,
)
from clue_gateway.openrouter import GatewayError, OpenRouterGateway
from clue_gateway.stub import StubGateway
from clue_gateway.tracing import EVENT_MODEL_CALL_USAGE, TracingGateway

__all__ = [
    "ANSWERING_MODEL_KEY",
    "COST_CENTS_KEY",
    "COST_SOURCE_KEY",
    "CostSource",
    "build_gateway",
    "EVENT_MODEL_CALL_USAGE",
    "OpenRouterAgentModelProvider",
    "OpenRouterGateway",
    "StubGateway",
    "TracingGateway",
    "GatewayError",
]
