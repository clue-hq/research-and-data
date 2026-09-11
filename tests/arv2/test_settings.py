"""Constraint 6: every ARV2 knob is a typed field with a default and a documented env line."""

from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import SecretStr

from clue_config import Secrets, Settings
from tests.arv2.conftest import require_secret

REPO = Path(__file__).resolve().parents[2]
ENV_EXAMPLE = REPO / ".env.example"

#: Every ARV2 setting and the default the lane ships with.
ARV2_SETTING_DEFAULTS: dict[str, object] = {
    "arv2_account_research_enabled": True,
    "arv2_ai_ark_min_gap_s": 10.5,
    "arv2_structuring_model": "openai/gpt-5-mini",
    "arv2_media_short_model": "google/gemini-3.5-flash-lite",
    "arv2_media_transcribe_model": "gemini-3.5-transcribe",
    "arv2_embedding_model": "google/gemini-embedding-2",
    "arv2_media_seconds_ceiling": 9000,
    "arv2_media_short_max_seconds": 600,
    "arv2_raw_root": ".artifacts/arv2",
    "arv2_account_max_model_rounds": 100,
    "arv2_account_max_tool_calls_per_round": 50,
    "arv2_account_max_runtime_s": 1800,
    "arv2_account_max_parallel_jobs": 4,
    "arv2_account_provider_concurrency": 4,
    "arv2_account_media_max_enclosure_mb": 200,
    "arv2_person_media_max_items": 3,
    "claim_write_lenient": True,
    "evidence_verbatim_check": "off",
    "unevidenced_row_purge_enabled": False,
    "interview_entailment_check": "off",
    "sensitivity_floor_enabled": True,
    "arv2_display_model": "openai/gpt-5.6-luna",
    "arv2_display_timeout_s": 240.0,
    "arv2_display_max_parallel": 8,
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
    "arv2_discovery_strict_count",
    "arv2_discovery_relaxed_auto",
    "arv2_discovery_criteria_gate_keys",
    "arv2_discovery_answer_model",
    "arv2_discovery_poll_interval_s",
    "arv2_discovery_wall_s",
    "arv2_discovery_websets_usd_per_credit",
)


def test_discovery_settings_defaults_and_env_names(monkeypatch: pytest.MonkeyPatch) -> None:
    # Same reason as ``unset_arv2_env``: the lane's own ``.env`` runs discovery on, so a shell that
    # sourced it would otherwise read back its value instead of the shipped default.
    for field_name in ARV2_DISCOVERY_SETTINGS:
        monkeypatch.delenv(_env_name(field_name), raising=False)
    settings = Settings(_env_file=None)
    assert settings.arv2_discovery_enabled is False
    assert settings.arv2_discovery_strict_count == 35
    assert settings.arv2_discovery_relaxed_auto is True
    # Empty on purpose: no deployment-wide gate set; the pinned ICP decides (ruling 2026-09-11).
    assert settings.arv2_discovery_criteria_gate_keys == ""
    assert settings.arv2_discovery_answer_model == "exa"
    assert settings.arv2_discovery_poll_interval_s == 15.0
    assert settings.arv2_discovery_wall_s == 1800
    assert settings.arv2_discovery_websets_usd_per_credit == Decimal("0.00449")
    monkeypatch.setenv("CLUE_ARV2_DISCOVERY_ENABLED", "true")
    monkeypatch.setenv("CLUE_ARV2_DISCOVERY_STRICT_COUNT", "12")
    monkeypatch.setenv("CLUE_ARV2_DISCOVERY_CRITERIA_GATE_KEYS", "geography")
    loaded = Settings(_env_file=None)
    assert loaded.arv2_discovery_enabled is True
    assert loaded.arv2_discovery_strict_count == 12
    assert loaded.arv2_discovery_criteria_gate_keys == "geography"


def test_every_discovery_setting_is_in_env_example() -> None:
    example = ENV_EXAMPLE.read_text(encoding="utf-8")
    for key in (
        "CLUE_ARV2_DISCOVERY_ENABLED=false",
        "CLUE_ARV2_DISCOVERY_STRICT_COUNT=35",
        "CLUE_ARV2_DISCOVERY_RELAXED_AUTO=true",
        "CLUE_ARV2_DISCOVERY_CRITERIA_GATE_KEYS=\n",
        "CLUE_ARV2_DISCOVERY_ANSWER_MODEL=exa",
        "CLUE_ARV2_DISCOVERY_POLL_INTERVAL_S=15",
        "CLUE_ARV2_DISCOVERY_WALL_S=1800",
        "CLUE_ARV2_DISCOVERY_WEBSETS_USD_PER_CREDIT=0.00449",
    ):
        assert key in example, key
