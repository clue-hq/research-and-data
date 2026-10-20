"""CRM integration (Phase 1): the Composio keys are documented, with their defaults."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from clue_config import Secrets, Settings

REPO = Path(__file__).resolve().parents[1]

DEFAULTS = {
    "crm_integration_enabled": True,
    "composio_base_url": "https://backend.composio.dev/api/v3.1",
    "composio_hubspot_auth_config_id": "",
    "composio_salesforce_auth_config_id": "",
    "composio_hubspot_toolkit_version": "20261020_01",
    "composio_salesforce_toolkit_version": "20261018_00",
    "crm_salesforce_api_share_pct": 10,
}

EXAMPLE_LINES = (
    r"^CLUE_COMPOSIO_API_KEY=$",
    r"^CLUE_CRM_INTEGRATION_ENABLED=true$",
    r"^CLUE_COMPOSIO_BASE_URL=https://backend\.composio\.dev/api/v3\.1$",
    r"^CLUE_COMPOSIO_HUBSPOT_AUTH_CONFIG_ID=$",
    r"^CLUE_COMPOSIO_SALESFORCE_AUTH_CONFIG_ID=$",
    r"^CLUE_COMPOSIO_HUBSPOT_TOOLKIT_VERSION=20261020_01$",
    r"^CLUE_COMPOSIO_SALESFORCE_TOOLKIT_VERSION=20261018_00$",
    r"^CLUE_CRM_SALESFORCE_API_SHARE_PCT=10$",
)


def test_crm_settings_have_their_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for field in DEFAULTS:
        monkeypatch.delenv(f"CLUE_{field.upper()}", raising=False)
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    for field, default in DEFAULTS.items():
        assert getattr(settings, field) == default, field


def test_the_composio_key_is_an_optional_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CLUE_COMPOSIO_API_KEY", raising=False)
    assert "composio_api_key" in Secrets.model_fields
    assert Secrets(_env_file=None).composio_api_key is None  # type: ignore[call-arg]


def test_the_salesforce_share_is_a_percentage(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLUE_CRM_SALESFORCE_API_SHARE_PCT", "0")
    with pytest.raises(ValueError):
        Settings(_env_file=None)  # type: ignore[call-arg]


def test_env_example_documents_every_crm_key() -> None:
    text = (REPO / ".env.example").read_text(encoding="utf-8")
    for pattern in EXAMPLE_LINES:
        assert re.search(pattern, text, re.MULTILINE), pattern
