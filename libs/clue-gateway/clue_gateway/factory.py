"""``build_gateway`` (M0.4) — the stub/live toggle behind the ``LLMGateway`` seam (decision #3).

One construction point for the injected gateway. It returns the **deterministic stub** when
``config.stub`` is set **or** no ``OPENROUTER_API_KEY`` is available — so CI (which sets no key)
never makes a live call — and the **live OpenRouter client** otherwise. Either backend is wrapped in
:class:`~clue_gateway.tracing.TracingGateway`, so every call emits the ``llm.gateway_call``
span regardless of which path is taken.
"""

from __future__ import annotations

from pydantic import SecretStr

from clue_config.gateway import GatewayConfig
from clue_core.gateway import LLMGateway
from clue_gateway.openrouter import OpenRouterGateway
from clue_gateway.stub import StubGateway
from clue_gateway.tracing import TracingGateway


def build_gateway(config: GatewayConfig, api_key: SecretStr | None = None) -> LLMGateway:
    """Build the injected :class:`~clue_core.gateway.LLMGateway` (traced; stub or live)."""
    inner: LLMGateway
    if config.stub or api_key is None:
        inner = StubGateway(config)
    else:
        inner = OpenRouterGateway(config, api_key)
    return TracingGateway(inner)
