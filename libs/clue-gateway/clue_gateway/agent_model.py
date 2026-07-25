"""Governed OpenRouter tool-calling model construction for C6.

The legacy :class:`OpenRouterGateway` intentionally exposes only completion and embedding.  A real
deepagent needs LangChain's standard tool-call message semantics, so this narrow adapter constructs
``ChatOpenAI`` against the *same* OpenRouter base URL, credentials, timeout, and retry policy.

The adapter lives in ``clue_gateway``—the repository's sole model/provider boundary.  It is not
wired into a production agent runtime in C6.0.  Injectable HTTP clients let the compatibility
spike exercise the real parser deterministically without network access.
"""

from __future__ import annotations

from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from clue_config.gateway import GatewayConfig

__all__ = ["OpenRouterAgentModelProvider"]


class OpenRouterAgentModelProvider:
    """Build LangChain tool-calling models through the governed OpenRouter configuration."""

    def __init__(
        self,
        config: GatewayConfig,
        api_key: SecretStr,
        *,
        http_client: Any | None = None,
        http_async_client: Any | None = None,
    ) -> None:
        self._config = config
        self._api_key = api_key
        self._http_client = http_client
        self._http_async_client = http_async_client

    def build(
        self,
        *,
        model_id: str,
        timeout_s: float,
        max_retries: int,
        max_output_tokens: int,
        temperature: float,
    ) -> BaseChatModel:
        """Construct an unwired model with caller-bounded policy no looser than the gateway."""

        if not model_id.strip():
            raise ValueError("model_id must be non-empty")
        if timeout_s <= 0 or timeout_s > self._config.timeout_s:
            raise ValueError(
                "agent model timeout must be positive and no greater than gateway policy"
            )
        if max_retries < 0 or max_retries > self._config.max_retries:
            raise ValueError("agent model retries must not exceed gateway policy")
        if max_output_tokens < 1:
            raise ValueError("max_output_tokens must be positive")
        if not 0 <= temperature <= 2:
            raise ValueError("temperature must be between 0 and 2")

        # ``ChatOpenAI`` is a Pydantic model whose runtime aliases (``model``, ``api_key``,
        # ``base_url``) are intentionally friendlier than its generated static constructor.
        return ChatOpenAI(  # type: ignore[call-arg]
            model=model_id,
            api_key=self._api_key,
            base_url=self._config.base_url,
            timeout=timeout_s,
            max_retries=max_retries,
            max_completion_tokens=max_output_tokens,
            temperature=temperature,
            stream_usage=True,
            http_client=self._http_client,
            http_async_client=self._http_async_client,
        )
