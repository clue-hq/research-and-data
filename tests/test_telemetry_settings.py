"""Lane 3 slice 2, Task 1: the telemetry roots' settings ship their defaults and are documented."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from clue_config import Secrets, Settings

REPO = Path(__file__).resolve().parents[1]
ENV_EXAMPLE = REPO / ".env.example"

#: Every slice 2 setting and the default it ships with (plus the three metrics settings the code
#: already read but .env.example did not document — closed by the same parity sweep).
TELEMETRY_SETTING_DEFAULTS: dict[str, object] = {
    "metrics_exporter": "memory",
    "metrics_otlp_endpoint": None,
    "metrics_export_interval_ms": 10_000,
    "otel_traces_endpoint": None,
    "otel_instrument_fastapi": True,
    "otel_instrument_httpx": True,
    "sentry_enabled": False,
    "sentry_environment": "lane-san-salvador",
    "release": None,
    # lane 3 slice 3
    "langfuse_enabled": True,
    "langfuse_host": "https://cloud.langfuse.com",
    "langfuse_environment": "default",
}
TELEMETRY_SECRET_FIELDS = (
    "sentry_dsn",
    "otel_traces_headers",
    "langfuse_public_key",
    "langfuse_secret_key",
)


def _env_name(field_name: str) -> str:
    return f"CLUE_{field_name.upper()}"


@pytest.fixture
def unset_telemetry_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in [*TELEMETRY_SETTING_DEFAULTS, *TELEMETRY_SECRET_FIELDS]:
        monkeypatch.delenv(_env_name(name), raising=False)


def test_every_telemetry_setting_ships_its_default(unset_telemetry_env: None) -> None:
    settings = Settings(_env_file=None)
    for field_name, default in TELEMETRY_SETTING_DEFAULTS.items():
        assert getattr(settings, field_name) == default, field_name


def test_the_telemetry_secrets_are_optional(unset_telemetry_env: None) -> None:
    secrets = Secrets(_env_file=None)  # type: ignore[call-arg]
    for field_name in TELEMETRY_SECRET_FIELDS:
        assert field_name in Secrets.model_fields
        assert getattr(secrets, field_name) is None


def test_every_telemetry_env_name_is_documented_with_its_default() -> None:
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    for field_name, default in TELEMETRY_SETTING_DEFAULTS.items():
        documented = re.search(rf"^{_env_name(field_name)}=(.*)$", text, re.MULTILINE)
        assert documented is not None, f"absent from .env.example: {_env_name(field_name)}"
        value = documented.group(1).strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        shipped = (
            ""
            if default is None
            else (str(default).lower() if isinstance(default, bool) else str(default))
        )
        assert value == shipped, field_name
    for field_name in TELEMETRY_SECRET_FIELDS:
        assert re.search(rf"^{_env_name(field_name)}=$", text, re.MULTILINE), field_name


def test_an_empty_endpoint_string_means_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """``source .env`` exports ``CLUE_OTEL_TRACES_ENDPOINT=`` as the empty string; the roots
    treat empty as "no exporter", so the setting must load without error."""
    monkeypatch.setenv("CLUE_OTEL_TRACES_ENDPOINT", "")
    monkeypatch.setenv("CLUE_SENTRY_ENABLED", "false")
    assert not Settings(_env_file=None).otel_traces_endpoint


def test_langfuse_environment_is_a_langfuse_legal_name() -> None:
    """Langfuse refuses environments outside ``^(?!langfuse)[a-z0-9-_]+$``; the shipped
    default must be legal so enabling it never fails on the name."""
    default = Settings.model_fields["langfuse_environment"].default
    assert re.fullmatch(r"(?!langfuse)[a-z0-9-_]+", default), default
