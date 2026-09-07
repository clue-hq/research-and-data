"""Constraint 6: every ARV2 knob is a typed field with a default and a documented env line."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from pydantic import SecretStr

from clue_config import Secrets, Settings

REPO = Path(__file__).resolve().parents[2]
ENV_EXAMPLE = REPO / ".env.example"

#: Every ARV2 setting and the default the lane ships with.
ARV2_SETTING_DEFAULTS: dict[str, object] = {
    "arv2_account_research_enabled": False,
    "arv2_ai_ark_min_gap_s": 10.5,
    "arv2_structuring_model": "openai/gpt-5-mini",
    "arv2_media_short_model": "google/gemini-3.5-flash-lite",
    "arv2_media_transcribe_model": "gemini-3.5-transcribe",
    "arv2_embedding_model": "google/gemini-embedding-2",
    "arv2_media_seconds_ceiling": 9000,
    "arv2_media_short_max_seconds": 600,
    "arv2_raw_root": ".artifacts/arv2",
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


def test_the_lane_flag_ships_off() -> None:
    """It flips to True only after the R2 exit gate passes (founder instruction 2026-09-07)."""
    assert Settings.model_fields["arv2_account_research_enabled"].default is False


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
        shipped = str(default).lower() if isinstance(default, bool) else str(default)
        assert documented.group(1).strip() == shipped, field_name
