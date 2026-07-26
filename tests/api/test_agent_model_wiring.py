from __future__ import annotations

import pytest

from clue_agents import AgentModelProvider
from clue_api.agent_model_wiring import build_agent_model_provider
from clue_config import Secrets
from clue_config.gateway import GatewayConfig
from clue_gateway import OpenRouterAgentModelProvider


def test_production_agent_model_provider_requires_openrouter_credential() -> None:
    with pytest.raises(RuntimeError, match="CLUE_OPENROUTER_API_KEY"):
        build_agent_model_provider(
            config=GatewayConfig(),
            secrets=Secrets(_env_file=None, openrouter_api_key=None),
        )


def test_production_agent_model_provider_is_injected_behind_neutral_port() -> None:
    provider = build_agent_model_provider(
        config=GatewayConfig(),
        secrets=Secrets(_env_file=None, openrouter_api_key="test-key"),
    )

    assert isinstance(provider, OpenRouterAgentModelProvider)
    assert isinstance(provider, AgentModelProvider)
