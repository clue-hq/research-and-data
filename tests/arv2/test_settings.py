"""Constraint 6: every ARV2 knob is a typed field with a default and a documented env line."""

from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import SecretStr

from clue_config import Secrets, Settings
from tests._model_ids import assert_well_formed_model_id
from tests.arv2.conftest import require_secret

REPO = Path(__file__).resolve().parents[2]
ENV_EXAMPLE = REPO / ".env.example"

#: Which model a step uses is an env setting, never a test expectation: these entries are
#: checked for a well-formed id, not for a particular model (``tests/_model_ids.py``).
MODEL_ID = object()
#: The model fields that are OpenRouter-routed (``vendor/model``); the transcription model is
#: addressed provider-natively, without a vendor segment.
ROUTED_MODEL_FIELDS: dict[str, bool] = {
    "arv2_structuring_model": True,
    "arv2_media_short_model": True,
    "arv2_media_transcribe_model": False,
    "arv2_embedding_model": True,
    "arv2_display_model": True,
}

#: Every ARV2 setting and the default the lane ships with.
ARV2_SETTING_DEFAULTS: dict[str, object] = {
    "arv2_account_research_enabled": True,
    "arv2_ai_ark_min_gap_s": 10.5,
    "arv2_drain_outside_slot": True,
    "arv2_recover_on_success": False,
    "arv2_upload_outside_lock": False,
    "arv2_page_guide_version": "v2",
    "arv2_structuring_model": MODEL_ID,
    "arv2_media_short_model": MODEL_ID,
    "arv2_media_transcribe_model": MODEL_ID,
    "arv2_embedding_model": MODEL_ID,
    "arv2_media_seconds_ceiling": 9000,
    # Recipe 26 research context (docs/superpowers/plans/2026-10-07-research-cost-phase1.md).
    "arv2_research_clear_trigger_tokens": 100_000,
    "arv2_research_clear_target_tokens": 50_000,
    "arv2_research_compact_trigger_tokens": 150_000,
    "arv2_research_compact_keep_messages": 40,
    "arv2_media_short_max_seconds": 600,
    "arv2_raw_root": ".artifacts/arv2",
    "arv2_account_max_model_rounds": 350,
    "arv2_account_max_tool_calls_per_round": 50,
    "arv2_account_max_runtime_s": 0,
    "arv2_account_max_parallel_jobs": 4,
    "arv2_account_provider_concurrency": 4,
    "arv2_account_media_max_enclosure_mb": 200,
    "arv2_person_media_max_items": 3,
    "claim_write_lenient": True,
    "evidence_verbatim_check": "off",
    "unevidenced_row_purge_enabled": False,
    "interview_entailment_check": "off",
    "sensitivity_floor_enabled": True,
    "arv2_display_model": MODEL_ID,
    "arv2_display_timeout_s": 240.0,
    "arv2_display_max_parallel": 30,
    "arv2_display_client_pitch": (
        "AI-native ABM: account and committee research, personalised content, "
        "brand-aligned artifacts, scaled per account"
    ),
    "arv2_display_generate_on_read": True,
    "arv2_fit_high_threshold": 0.70,
    "arv2_fit_medium_threshold": 0.40,
}

ARV2_SECRET_FIELDS = ("ai_ark_api_key", "gemini_api_key")


def _env_name(field_name: str) -> str:
    return f"CLUE_{field_name.upper()}"


@pytest.fixture
def unset_arv2_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Assert the *shipped* defaults, not whatever the developer's shell exported.

    These tests run with the repo ``.env`` sourced (the live-test contract), so the ARV2 variables
    are in ``os.environ`` and ``_env_file=None`` alone would not reach the field defaults.
    """
    for field_name in (*ARV2_SETTING_DEFAULTS, *ARV2_SECRET_FIELDS):
        monkeypatch.delenv(_env_name(field_name), raising=False)


def test_every_arv2_setting_has_its_shipped_default(unset_arv2_env: None) -> None:
    settings = Settings(_env_file=None)
    for field_name, expected in ARV2_SETTING_DEFAULTS.items():
        if expected is MODEL_ID:
            assert_well_formed_model_id(
                getattr(settings, field_name), routed=ROUTED_MODEL_FIELDS[field_name]
            )
            continue
        assert getattr(settings, field_name) == expected, field_name


def test_the_lane_flag_ships_on_after_r2() -> None:
    """Default True since the R2 exit gate passed on 2026-09-08 (founder instruction 2026-09-07)."""
    assert Settings.model_fields["arv2_account_research_enabled"].default is True


def test_the_new_provider_keys_are_optional_secrets(unset_arv2_env: None) -> None:
    secrets = Secrets(_env_file=None)
    for field_name in ARV2_SECRET_FIELDS:
        assert field_name in Secrets.model_fields
        assert getattr(secrets, field_name) is None


def test_the_new_provider_keys_resolve_through_for_auth_ref() -> None:
    """A source manifest names an env var; ``for_auth_ref`` is the only name→field mapping."""
    secrets = Secrets(
        _env_file=None,
        ai_ark_api_key=SecretStr("ark-value"),
        gemini_api_key=SecretStr("gemini-value"),
    )
    resolved = secrets.for_auth_ref("CLUE_AI_ARK_API_KEY")
    assert resolved is not None and resolved.get_secret_value() == "ark-value"
    resolved = secrets.for_auth_ref("CLUE_GEMINI_API_KEY")
    assert resolved is not None and resolved.get_secret_value() == "gemini-value"


def test_every_new_env_name_is_documented_in_env_example() -> None:
    """The parity rule: a knob the code reads that no operator can see is a defect."""
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    expected = [_env_name(name) for name in ARV2_SETTING_DEFAULTS]
    expected += [_env_name(name) for name in ARV2_SECRET_FIELDS]
    missing = [name for name in expected if not re.search(rf"^{name}=", text, re.MULTILINE)]
    assert not missing, f"absent from .env.example: {missing}"


def test_env_example_documents_each_setting_with_its_default() -> None:
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    for field_name, default in ARV2_SETTING_DEFAULTS.items():
        documented = re.search(rf"^{_env_name(field_name)}=(.*)$", text, re.MULTILINE)
        assert documented is not None, field_name
        # dotenv semantics: one pair of matching surrounding quotes is not part of the value
        # (a value with spaces must be quoted for ``source .env`` to stay shell-sourceable).
        value = documented.group(1).strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if default is MODEL_ID:
            # The example documents whatever the code default is today, and both are well-formed;
            # neither this test nor the example pins which model that is.
            code_default = Settings.model_fields[field_name].default
            assert_well_formed_model_id(value, routed=ROUTED_MODEL_FIELDS[field_name])
            assert value == code_default, field_name
            continue
        shipped = str(default).lower() if isinstance(default, bool) else str(default)
        assert value == shipped, field_name


def test_the_on_off_checks_load_from_their_env_strings(monkeypatch: pytest.MonkeyPatch) -> None:
    """CLAUDE.md: a Literal that rejects its own documented env form is a bug."""
    monkeypatch.setenv("CLUE_EVIDENCE_VERBATIM_CHECK", "on")
    monkeypatch.setenv("CLUE_INTERVIEW_ENTAILMENT_CHECK", "on")
    settings = Settings(_env_file=None)
    assert settings.evidence_verbatim_check == "on"
    assert settings.interview_entailment_check == "on"


def test_require_secret_returns_a_live_key() -> None:
    """The helper is a pure function over a ``Secrets``; it needs no double to exercise."""
    secrets = Secrets(_env_file=None, ai_ark_api_key=SecretStr("ark-value"))
    assert require_secret(secrets, "ai_ark_api_key") == "ark-value"


def test_require_secret_treats_an_unset_key_as_a_skip() -> None:
    secrets = Secrets(_env_file=None, ai_ark_api_key=None)
    with pytest.raises(pytest.skip.Exception) as excinfo:
        require_secret(secrets, "ai_ark_api_key")
    assert "CLUE_AI_ARK_API_KEY" in str(excinfo.value)


def test_require_secret_treats_a_blank_key_as_a_skip() -> None:
    """``CLUE_AI_ARK_API_KEY=`` — what ``.env.example`` ships — loads as ``SecretStr('')``.

    Without this the helper would hand an empty key to a real provider and the test would fail on
    the provider's 401 instead of skipping with the name of the variable nobody filled in.
    """
    for blank in ("", "   ", "\n"):
        secrets = Secrets(_env_file=None, ai_ark_api_key=SecretStr(blank))
        with pytest.raises(pytest.skip.Exception) as excinfo:
            require_secret(secrets, "ai_ark_api_key")
        assert "CLUE_AI_ARK_API_KEY" in str(excinfo.value)


#: R4 discovery knobs. Kept out of :data:`ARV2_SETTING_DEFAULTS` deliberately: the two checks below
#: assert the same two properties (shipped default, ``.env.example`` parity) against the *exact*
#: strings the R4 spec fixes, so the R4 block is pinned by its own spec rather than by a generic
#: ``str(default)`` rendering.
ARV2_DISCOVERY_SETTINGS = (
    "arv2_discovery_enabled",
    "arv2_discovery_max_topups",
    "arv2_discovery_answer_model",
    "arv2_discovery_poll_interval_s",
    "arv2_discovery_wall_s",
    "arv2_discovery_websets_usd_per_credit",
    "arv2_discovery_verify_concurrency",
    "brandfetch_client_id",
)


def test_discovery_settings_defaults_and_env_names(monkeypatch: pytest.MonkeyPatch) -> None:
    # Same reason as ``unset_arv2_env``: the lane's own ``.env`` runs discovery on, so a shell that
    # sourced it would otherwise read back its value instead of the shipped default.
    for field_name in ARV2_DISCOVERY_SETTINGS:
        monkeypatch.delenv(_env_name(field_name), raising=False)
    settings = Settings(_env_file=None)
    assert settings.arv2_discovery_enabled is False
    # At most three top-up searches after the first (spec 2026-09-30 §4).
    assert settings.arv2_discovery_max_topups == 3
    assert settings.arv2_discovery_answer_model == "exa"
    assert settings.arv2_discovery_poll_interval_s == 15.0
    assert settings.arv2_discovery_wall_s == 1800
    assert settings.arv2_discovery_websets_usd_per_credit == Decimal("0.00449")
    # One cap for every Answer call a run has in flight (spec §2): candidates verify in a pool
    # and one candidate's gates are asked together, all under this semaphore.
    assert settings.arv2_discovery_verify_concurrency == 4
    # Empty on purpose: no Brandfetch fallback until a Logo API client id is configured.
    assert settings.brandfetch_client_id == ""
    monkeypatch.setenv("CLUE_ARV2_DISCOVERY_ENABLED", "true")
    monkeypatch.setenv("CLUE_ARV2_DISCOVERY_MAX_TOPUPS", "1")
    monkeypatch.setenv("CLUE_ARV2_DISCOVERY_VERIFY_CONCURRENCY", "2")
    loaded = Settings(_env_file=None)
    assert loaded.arv2_discovery_enabled is True
    assert loaded.arv2_discovery_max_topups == 1
    assert loaded.arv2_discovery_verify_concurrency == 2


def test_the_fixed_provider_ask_setting_is_gone() -> None:
    """Founder ruling 2026-09-28: the first search asks Exa for exactly the number the human wants,
    so a fixed provider ask (the old 35) would be a second, conflicting answer to that question."""
    assert "arv2_discovery_strict_count" not in Settings.model_fields
    assert "CLUE_ARV2_DISCOVERY_STRICT_COUNT" not in ENV_EXAMPLE.read_text(encoding="utf-8")


def test_the_relaxed_and_gate_key_settings_are_gone() -> None:
    """Spec 2026-09-30 §8: the agent writes the brief, so no deployment-wide gate set and no
    automatic relaxed search remain."""
    for field_name in ("arv2_discovery_relaxed_auto", "arv2_discovery_criteria_gate_keys"):
        assert field_name not in Settings.model_fields
    example = ENV_EXAMPLE.read_text(encoding="utf-8")
    assert "CLUE_ARV2_DISCOVERY_RELAXED_AUTO" not in example
    assert "CLUE_ARV2_DISCOVERY_CRITERIA_GATE_KEYS" not in example


def test_every_discovery_setting_is_in_env_example() -> None:
    example = ENV_EXAMPLE.read_text(encoding="utf-8")
    for key in (
        "CLUE_ARV2_DISCOVERY_ENABLED=false",
        "CLUE_ARV2_DISCOVERY_MAX_TOPUPS=3",
        "CLUE_ARV2_DISCOVERY_ANSWER_MODEL=exa",
        "CLUE_ARV2_DISCOVERY_POLL_INTERVAL_S=15",
        "CLUE_ARV2_DISCOVERY_WALL_S=1800",
        "CLUE_ARV2_DISCOVERY_WEBSETS_USD_PER_CREDIT=0.00449",
        "CLUE_ARV2_DISCOVERY_VERIFY_CONCURRENCY=4",
        "CLUE_BRANDFETCH_CLIENT_ID=\n",
    ):
        assert key in example, key
