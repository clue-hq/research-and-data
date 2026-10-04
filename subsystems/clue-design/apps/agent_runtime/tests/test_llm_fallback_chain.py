"""The design agent's governed models share the platform's fallback chain and first-chunk deadline.

Founder ruling 2026-10-04: every agent model call falls back to grok-4.7, then meta/muse-spark-1.3,
when the primary fails before answering (production that day: grok-4.6 accepted requests and sent
nothing). The design runtime builds its own GatewayConfig, so it must read the same two settings
(CLUE_AGENT_FALLBACK_MODELS, CLUE_AGENT_FIRST_TOKEN_TIMEOUT_S) rather than miss them.
"""

from __future__ import annotations

import pytest

from lumen_agent import llm


@pytest.fixture(autouse=True)
def _fresh_cache():
    llm._PROVIDER_CACHE.clear()
    yield
    llm._PROVIDER_CACHE.clear()


def _provider():
    return llm._governed_provider(
        base_url="https://openrouter.example/api/v1",
        api_key="test-key",
        reasoning=None,
        provider_sort=None,
        timeout_s=60.0,
    )


def test_the_design_provider_carries_the_platform_fallback_chain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CLUE_AGENT_FALLBACK_MODELS", "x-ai/grok-4.7,meta/muse-spark-1.3")
    monkeypatch.setenv("CLUE_AGENT_FIRST_TOKEN_TIMEOUT_S", "90")
    config = _provider()._config
    assert config.fallback_models == ("x-ai/grok-4.7", "meta/muse-spark-1.3")
    assert config.first_token_timeout_s == 90.0


def test_a_changed_chain_is_a_different_provider_not_a_stale_cached_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CLUE_AGENT_FALLBACK_MODELS", "a/one")
    first = _provider()
    monkeypatch.setenv("CLUE_AGENT_FALLBACK_MODELS", "")
    monkeypatch.setenv("CLUE_AGENT_FIRST_TOKEN_TIMEOUT_S", "0")
    second = _provider()
    assert first is not second
    assert second._config.fallback_models == ()
    assert second._config.first_token_timeout_s is None
