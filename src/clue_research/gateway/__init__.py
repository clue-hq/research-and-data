"""`clue_research.gateway` — the shared LLM gateway client (OpenRouter), M0.4 / conventions §4.

The concrete egress for every *direct* LLM call. The protocol + value types live in
:mod:`clue_research.core.gateway` (the shared-contracts package); **this** package holds the live
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

from clue_research.gateway.factory import build_gateway
from clue_research.gateway.openrouter import GatewayError, OpenRouterGateway
from clue_research.gateway.stub import StubGateway
from clue_research.gateway.tracing import TracingGateway

__all__ = [
    "build_gateway",
    "OpenRouterGateway",
    "StubGateway",
    "TracingGateway",
    "GatewayError",
]
