"""M0.4 — deploy-time settings (non-secret env) tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from clue_config import (
    DEFAULT_SYNTHESIS_MODEL,
    Settings,
    get_config,
    load_settings,
)
from clue_config.gateway import default_gateway_config
from tests._model_ids import assert_well_formed_model_id


@pytest.fixture(autouse=True)
def _hermetic_product_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """Assert the *code* defaults, not the operator's deployment posture.

    ``CLUE_PRODUCT_PATH=integration_pilot`` applies an overlay of default flag values, and the repo
    workflow (``set -a; source .env; set +a``) exports it — so without this, a pilot shell flips the
    default-off/default-on assertions below and the product-path tests stop testing the default
    path. Every test here that *wants* a product path sets it after this cleanup.
    """
    monkeypatch.delenv("CLUE_PRODUCT_PATH", raising=False)


def test_synthesis_model_default_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CLUE_SYNTHESIS_MODEL", raising=False)
    settings = load_settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.synthesis_model == DEFAULT_SYNTHESIS_MODEL
    assert_well_formed_model_id(settings.synthesis_model)


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
        metrics_exporter="otlp",
        metrics_otlp_endpoint="https://otel.example/v1/metrics",
    )
    assert settings.auth_clerk_authorized_parties == (
        "https://app.example",
        "http://localhost:3000",
    )


def test_enabled_auth_requires_explicit_environment() -> None:
    with pytest.raises(ValidationError, match="CLUE_AUTH_ENVIRONMENT must be set explicitly"):
        load_settings(_env_file=None, auth_enabled=True)


def test_production_requires_a_real_metrics_exporter_and_otlp_requires_endpoint() -> None:
    with pytest.raises(ValidationError, match="production requires CLUE_METRICS_EXPORTER=otlp"):
        load_settings(
            _env_file=None,
            auth_environment="production",
            auth_mode="clerk",
            projections_auth_mode="authenticated_principal",
        )
    with pytest.raises(ValidationError, match="CLUE_METRICS_OTLP_ENDPOINT"):
        load_settings(_env_file=None, metrics_exporter="otlp")


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


def test_stage0_official_site_crawl_is_bounded_and_default_off() -> None:
    settings = load_settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.stage0_official_site_crawl_mode == "off"
    assert settings.stage0_official_site_crawl_workspace_allowlist == ()
    assert settings.stage0_page_fetcher == "firecrawl"
    assert settings.stage0_crawl_max_depth == 2
    assert settings.stage0_crawl_fast_deadline_seconds == 40
    assert_well_formed_model_id(settings.stage0_extraction_model)
    assert settings.stage0_extraction_concurrency == 4


def test_stage0_official_site_shadow_requires_and_parses_allowlist() -> None:
    settings = load_settings(
        _env_file=None,
        stage0_official_site_crawl_mode="shadow",
        stage0_official_site_crawl_workspace_allowlist="ws-a, ws-b",
    )
    assert settings.stage0_official_site_crawl_workspace_allowlist == ("ws-a", "ws-b")

    with pytest.raises(ValidationError, match="requires an explicit workspace allowlist"):
        load_settings(_env_file=None, stage0_official_site_crawl_mode="shadow")


@pytest.mark.parametrize(
    ("updates", "message"),
    (
        (
            {"stage0_crawl_fast_page_ceiling": 11, "stage0_crawl_total_page_ceiling": 10},
            "FAST_PAGE_CEILING",
        ),
        (
            {"stage0_crawl_worker_concurrency": 2, "stage0_crawl_per_host_concurrency": 3},
            "PER_HOST_CONCURRENCY",
        ),
        (
            {"stage0_crawl_lease_ttl_seconds": 40, "stage0_crawl_heartbeat_seconds": 20},
            "heartbeat intervals",
        ),
    ),
)
def test_stage0_official_site_crawl_rejects_unsafe_bounds(
    updates: dict[str, int], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        load_settings(_env_file=None, **updates)


def test_default_product_path_changes_no_default() -> None:
    """CLUE_PRODUCT_PATH is default:'default' and the conservative defaults are untouched."""
    s = load_settings(_env_file=None)  # type: ignore[call-arg]
    assert s.product_path == "default"
    assert s.exa_account_deep_acquisition_enabled is False
    assert s.sumble_committee_acquisition_enabled is False


def test_integration_pilot_overlay_resolves_the_required_capability_state() -> None:
    """Contract §9: the integration product path resolves acquisition, research, committee,
    contact-deep, runtime, chat, and frontend-read to ON, and verification/budget to OFF —
    from checked-in defaults, not terminal state."""
    s = load_settings(_env_file=None, product_path="integration_pilot")  # type: ignore[call-arg]
    assert s.exa_websets_lifecycle_enabled is True
    assert s.exa_websets_acquisition_enabled is True
    assert s.exa_account_deep_acquisition_enabled is True
    assert s.sumble_account_gap_enrichment_enabled is True
    assert s.sumble_committee_acquisition_enabled is True
    assert s.exa_contact_deep_acquisition_enabled is True
    assert s.entity_research_runtime_enabled is True
    assert s.chat_enabled is True
    assert s.frontend_read_enabled is True
    assert s.verification_enabled is False
    assert s.budget_controls_enabled is False
    # Slice F/G extend the overlay; asserting the current phase honestly:
    assert s.contact_channel_enrichment_enabled is False
    assert s.frontend_contact_email_lookup_enabled is True
    assert s.c7_research_view_read_enabled is False


def test_explicit_env_value_beats_the_overlay() -> None:
    s = load_settings(  # type: ignore[call-arg]
        _env_file=None, product_path="integration_pilot", exa_account_deep_acquisition_enabled=False
    )
    assert s.exa_account_deep_acquisition_enabled is False


def test_compaction_and_continuation_defaults() -> None:
    s = load_settings(_env_file=None)
    assert s.agent_context_window_tokens is None
    assert s.agent_compact_trigger_fraction == 0.90
    assert s.agent_compact_keep_fraction == 0.10
    assert s.agent_compact_trigger_tokens == 170_000
    assert s.agent_compact_keep_messages == 6
    assert s.head_of_abm_continuation_enabled is True


def test_a_blank_context_window_line_loads_as_unknown() -> None:
    """The documented ``CLUE_AGENT_CONTEXT_WINDOW_TOKENS=`` line must load (env-parity rule)."""
    assert (
        load_settings(_env_file=None, agent_context_window_tokens="").agent_context_window_tokens
        is None
    )


def test_discovery_top_ups_default_and_bounds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CLUE_ARV2_DISCOVERY_MAX_TOPUPS", raising=False)
    assert load_settings(_env_file=None).arv2_discovery_max_topups == 3  # type: ignore[call-arg]
    monkeypatch.setenv("CLUE_ARV2_DISCOVERY_MAX_TOPUPS", "16")
    with pytest.raises(ValidationError):
        load_settings(_env_file=None)  # type: ignore[call-arg]


def test_the_retired_discovery_settings_are_gone() -> None:
    fields = Settings.model_fields
    assert "arv2_discovery_criteria_gate_keys" not in fields
    assert "arv2_discovery_relaxed_auto" not in fields


def test_phase_2_retention_settings_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """F3 Phase 2 (AW-24, amended 2026-10-23: the sweep is daily, not hourly)."""

    for name in (
        "CLUE_AGENT_WORKSPACE_RAW_RETENTION_S",
        "CLUE_AGENT_WORKSPACE_WORKING_RETENTION_S",
        "CLUE_AGENT_WORKSPACE_RETENTION_SWEEP_INTERVAL_S",
    ):
        monkeypatch.delenv(name, raising=False)
    settings = load_settings(_env_file=None)  # type: ignore[call-arg]
    assert (
        settings.agent_workspace_raw_retention_s,
        settings.agent_workspace_working_retention_s,
        settings.agent_workspace_retention_sweep_interval_s,
    ) == (172800.0, 604800.0, 86400.0)


@pytest.mark.parametrize(
    "field",
    [
        "agent_workspace_raw_retention_s",
        "agent_workspace_working_retention_s",
        "agent_workspace_retention_sweep_interval_s",
    ],
)
def test_phase_2_retention_settings_refuse_zero(field: str) -> None:
    """A zero retention would expire every file the moment it is written."""

    with pytest.raises(ValidationError):
        load_settings(_env_file=None, **{field: 0.0})  # type: ignore[call-arg]
