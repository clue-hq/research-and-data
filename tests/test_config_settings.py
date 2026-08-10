"""M0.4 — deploy-time settings (non-secret env) tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from clue_config import (
    DEFAULT_SYNTHESIS_MODEL,
    get_config,
    load_settings,
)
from clue_config.gateway import default_gateway_config


def test_synthesis_model_default_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CLUE_SYNTHESIS_MODEL", raising=False)
    settings = load_settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.synthesis_model == DEFAULT_SYNTHESIS_MODEL
    assert settings.synthesis_model == "openai/gpt-5.6-terra"


def test_synthesis_model_read_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLUE_SYNTHESIS_MODEL", "openai/gpt-4o")
    settings = load_settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.synthesis_model == "openai/gpt-4o"


def test_gateway_config_picks_up_env_synthesis_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLUE_SYNTHESIS_MODEL", "openai/gpt-4o-mini")
    assert default_gateway_config().synthesis_model == "openai/gpt-4o-mini"


def test_verification_is_default_on_and_can_be_disabled_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CLUE_VERIFICATION_ENABLED", raising=False)
    assert load_settings(_env_file=None).verification_enabled is True  # type: ignore[call-arg]

    monkeypatch.setenv("CLUE_VERIFICATION_ENABLED", "false")
    assert load_settings(_env_file=None).verification_enabled is False  # type: ignore[call-arg]


def test_exa_account_deep_controls_are_independent_bounded_and_default_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = load_settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.exa_account_deep_acquisition_enabled is False
    assert settings.exa_account_deep_search_type == "deep-reasoning"
    assert settings.exa_account_deep_max_results == 50
    assert settings.exa_account_deep_max_additional_queries == 10

    monkeypatch.setenv("CLUE_EXA_ACCOUNT_DEEP_ACQUISITION_ENABLED", "true")
    monkeypatch.setenv("CLUE_EXA_ACCOUNT_DEEP_SEARCH_TYPE", "deep")
    monkeypatch.setenv("CLUE_EXA_ACCOUNT_DEEP_MAX_RESULTS", "20")
    monkeypatch.setenv("CLUE_EXA_ACCOUNT_DEEP_MAX_ADDITIONAL_QUERIES", "4")
    configured = load_settings(_env_file=None)  # type: ignore[call-arg]
    assert configured.exa_account_deep_acquisition_enabled is True
    assert configured.exa_account_deep_search_type == "deep"
    assert configured.exa_account_deep_max_results == 20
    assert configured.exa_account_deep_max_additional_queries == 4


def test_get_config_gateway_uses_env_synthesis_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLUE_SYNTHESIS_MODEL", "anthropic/claude-3.5-sonnet")
    assert get_config("acme").gateway.synthesis_model == "anthropic/claude-3.5-sonnet"


def test_c7_activation_controls_are_independently_default_off() -> None:
    settings = load_settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.c7_research_view_read_enabled is False
    assert settings.c7_snapshot_compose_enabled is False
    assert settings.c7_evidence_actions_enabled is False
    assert settings.c7_recheck_enabled is False
    assert settings.c7_production_handoff_enabled is False
    assert settings.c7_legacy_dossier_alias_enabled is False
    assert settings.c7_governance_shadow_compare_enabled is False


def test_c7_activation_controls_load_from_independent_environment_flags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    names = (
        "C7_RESEARCH_VIEW_READ_ENABLED",
        "C7_SNAPSHOT_COMPOSE_ENABLED",
        "C7_EVIDENCE_ACTIONS_ENABLED",
        "C7_RECHECK_ENABLED",
        "C7_PRODUCTION_HANDOFF_ENABLED",
        "C7_LEGACY_DOSSIER_ALIAS_ENABLED",
        "C7_GOVERNANCE_SHADOW_COMPARE_ENABLED",
    )
    for name in names:
        monkeypatch.setenv(f"CLUE_{name}", "true")
    settings = load_settings(_env_file=None)  # type: ignore[call-arg]
    assert all(
        (
            settings.c7_research_view_read_enabled,
            settings.c7_snapshot_compose_enabled,
            settings.c7_evidence_actions_enabled,
            settings.c7_recheck_enabled,
            settings.c7_production_handoff_enabled,
            settings.c7_legacy_dossier_alias_enabled,
            settings.c7_governance_shadow_compare_enabled,
        )
    )


def test_agent_workspace_allowlist_accepts_a_json_array(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLUE_AGENT_WORKSPACE_ALLOWLIST", '["ws-a", "ws-b"]')
    settings = load_settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.agent_workspace_allowlist == ("ws-a", "ws-b")


def test_agent_workspace_allowlist_accepts_a_comma_separated_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The shell-safe spelling: `set -a; source .env` strips the JSON string quotes."""

    monkeypatch.setenv("CLUE_AGENT_WORKSPACE_ALLOWLIST", " ws-a , ws-b ,")
    settings = load_settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.agent_workspace_allowlist == ("ws-a", "ws-b")


def test_agent_workspace_allowlist_empty_value_is_an_empty_allowlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CLUE_AGENT_WORKSPACE_ALLOWLIST", "  ")
    settings = load_settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.agent_workspace_allowlist == ()


def test_agent_workspace_allowlist_names_itself_and_both_formats_when_unparseable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A malformed allowlist fails as this one field, not as the whole settings object."""

    monkeypatch.setenv("CLUE_AGENT_WORKSPACE_ALLOWLIST", "[ws-a]")
    monkeypatch.setenv("CLUE_SYNTHESIS_MODEL", "openai/gpt-4o")
    with pytest.raises(ValidationError) as error:
        load_settings(_env_file=None)  # type: ignore[call-arg]
    message = str(error.value)
    assert "agent_workspace_allowlist" in message
    assert "CLUE_AGENT_WORKSPACE_ALLOWLIST" in message
    assert '["ws-a","ws-b"]' in message
    assert "ws-a,ws-b" in message
    assert error.value.error_count() == 1


def test_agent_workspace_allowlist_accepts_one_bare_workspace_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CLUE_AGENT_WORKSPACE_ALLOWLIST", "ws-a")
    settings = load_settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.agent_workspace_allowlist == ("ws-a",)


def test_auth_local_fixture_mode_is_forbidden_in_production() -> None:
    with pytest.raises(ValidationError, match="local fixture auth is forbidden"):
        load_settings(
            _env_file=None,
            auth_environment="production",
            auth_mode="local_fixture",
        )


def test_auth_clerk_authorized_parties_accept_shell_safe_list() -> None:
    settings = load_settings(
        _env_file=None,
        auth_environment="production",
        auth_mode="clerk",
        projections_auth_mode="authenticated_principal",
        auth_clerk_authorized_parties="https://app.example, http://localhost:3000",
    )
    assert settings.auth_clerk_authorized_parties == (
        "https://app.example",
        "http://localhost:3000",
    )


def test_enabled_auth_requires_explicit_environment() -> None:
    with pytest.raises(ValidationError, match="CLUE_AUTH_ENVIRONMENT must be set explicitly"):
        load_settings(_env_file=None, auth_enabled=True)


def test_production_auth_refuses_local_header_workspace_authority() -> None:
    with pytest.raises(ValidationError, match="forbids the local-header"):
        load_settings(
            _env_file=None,
            auth_enabled=True,
            auth_environment="production",
            auth_mode="clerk",
            projections_auth_mode="local_header",
        )


def test_declared_production_refuses_local_header_even_before_auth_flip() -> None:
    with pytest.raises(ValidationError, match="forbids the local-header"):
        load_settings(
            _env_file=None,
            auth_enabled=False,
            auth_environment="production",
            auth_mode="clerk",
            projections_auth_mode="local_header",
        )
