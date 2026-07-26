"""C6.2 production composition for the governed tool-calling model provider."""

from __future__ import annotations

from clue_agents import AgentModelProvider
from clue_config import Secrets
from clue_config.gateway import GatewayConfig
from clue_gateway import OpenRouterAgentModelProvider

__all__ = ["build_agent_model_provider"]


def build_agent_model_provider(
    *,
    config: GatewayConfig,
    secrets: Secrets,
) -> AgentModelProvider:
    """Build the live provider or fail before agent construction when credentials are absent."""

    api_key = secrets.openrouter_api_key
    if api_key is None:
        raise RuntimeError("CLUE_OPENROUTER_API_KEY is required for the production deepagent model")
    return OpenRouterAgentModelProvider(config, api_key)
