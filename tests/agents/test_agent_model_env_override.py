"""Environment-first agent model selection (founder ruling 2026-08-31).

``<ROLE>_AGENT_MODEL`` names an agent's model at registry resolution and
``<ROLE>_AGENT_MODEL_EFFORT`` names its reasoning effort at the gateway — a model change
is a deployment setting, never a new reviewed profile version. Blank/unset preserves the
catalog pin and the per-model reasoning baseline exactly, which is what keeps this suite
(and historical replay) deterministic on machines with no environment.
"""

from __future__ import annotations

import pytest

from clue_agents.contracts import AgentRole, ModelPolicy
from clue_agents.registry import _env_model_policy
from clue_config.gateway import GatewayConfig
from clue_gateway.agent_model import _reasoning_request

_PINNED = ModelPolicy(
    model_id="openai/gpt-5.6-terra",
    timeout_s=120.0,
    max_retries=2,
    max_output_tokens=16_384,
    temperature=0.2,
)


@pytest.fixture(autouse=True)
def _no_deployment_timeout_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """The deployment-wide timeout override (2026-09-08) rides the same seam; a sourced repo
    ``.env`` sets it, so every test here starts from the profile pin unless it sets it itself."""
    monkeypatch.delenv("CLUE_AGENT_MODEL_TIMEOUT_S", raising=False)


def test_deployment_timeout_env_overrides_every_role_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("HEAD_OF_ABM_AGENT_MODEL", raising=False)
    monkeypatch.setenv("CLUE_AGENT_MODEL_TIMEOUT_S", "60")
    raised = _env_model_policy(AgentRole.HEAD_OF_ABM, _PINNED)
    assert raised.timeout_s == 60.0
    assert raised.model_id == _PINNED.model_id
    assert (raised.max_retries, raised.max_output_tokens, raised.temperature) == (
        _PINNED.max_retries,
        _PINNED.max_output_tokens,
        _PINNED.temperature,
    )
    monkeypatch.setenv("CLUE_AGENT_MODEL_TIMEOUT_S", str(_PINNED.timeout_s))
    assert _env_model_policy(AgentRole.HEAD_OF_ABM, _PINNED) is _PINNED


def test_env_var_overrides_the_profile_pin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HEAD_OF_ABM_AGENT_MODEL", "x-ai/grok-4.6")
    resolved = _env_model_policy(AgentRole.HEAD_OF_ABM, _PINNED)
    assert resolved.model_id == "x-ai/grok-4.6"
    # The environment names the MODEL; the reviewed profile keeps owning the envelope.
    assert resolved.timeout_s == _PINNED.timeout_s
    assert resolved.max_retries == _PINNED.max_retries
    assert resolved.max_output_tokens == _PINNED.max_output_tokens
    assert resolved.temperature == _PINNED.temperature


def test_blank_or_unset_env_keeps_the_profile_pin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HEAD_OF_ABM_AGENT_MODEL", raising=False)
    assert _env_model_policy(AgentRole.HEAD_OF_ABM, _PINNED) is _PINNED
    monkeypatch.setenv("HEAD_OF_ABM_AGENT_MODEL", "   ")
    assert _env_model_policy(AgentRole.HEAD_OF_ABM, _PINNED) is _PINNED


def test_each_role_reads_its_own_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REVIEWER_AGENT_MODEL", "x-ai/grok-4.6")
    monkeypatch.delenv("RESEARCH_AGENT_MODEL", raising=False)
    assert _env_model_policy(AgentRole.REVIEWER, _PINNED).model_id == "x-ai/grok-4.6"
    assert _env_model_policy(AgentRole.RESEARCH, _PINNED) is _PINNED


def test_effort_env_overrides_the_reasoning_baseline(monkeypatch: pytest.MonkeyPatch) -> None:
    config = GatewayConfig()
    # A model with no reasoning baseline gains exactly the requested effort.
    monkeypatch.setenv("HEAD_OF_ABM_AGENT_MODEL_EFFORT", "low")
    assert _reasoning_request(config, model_id="x-ai/grok-4.6", role="head_of_abm") == {
        "effort": "low"
    }
    # A model WITH a baseline has its effort replaced, nothing else invented.
    assert _reasoning_request(config, model_id="openai/gpt-5.6-terra", role="head_of_abm") == {
        "effort": "low"
    }


def test_blank_effort_env_preserves_the_baseline(monkeypatch: pytest.MonkeyPatch) -> None:
    config = GatewayConfig()
    monkeypatch.delenv("HEAD_OF_ABM_AGENT_MODEL_EFFORT", raising=False)
    assert _reasoning_request(config, model_id="openai/gpt-5.6-terra", role="head_of_abm") == {
        "effort": "high"
    }
    assert _reasoning_request(config, model_id="x-ai/grok-4.6", role="head_of_abm") is None
    # A roleless call (fleet compositions that predate the pattern) never reads the env.
    monkeypatch.setenv("HEAD_OF_ABM_AGENT_MODEL_EFFORT", "low")
    assert _reasoning_request(config, model_id="x-ai/grok-4.6", role=None) is None
