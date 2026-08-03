"""M0.4 — deploy-time settings (non-secret env) tests."""

from __future__ import annotations

import pytest

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
