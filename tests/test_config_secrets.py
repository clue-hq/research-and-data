"""M0.4 — secrets & redaction tests (ENG-120).

Covers the secrets acceptance criteria of docs/specs/M00 §M0.4:
* no secret value appears in repr/str (SecretStr wrapping);
* the redaction helper masks a known key pattern;
* the DB DSN env var is CLUE_DATABASE_URL;
* keys are read from the environment, not committed.
"""

from __future__ import annotations

import pytest
from pydantic import SecretStr

from clue_research.config import (
    DB_DSN_ENV_VAR,
    Secrets,
    is_secret_name,
    redact,
    redact_mapping,
)


def test_db_dsn_env_var_is_clue_database_url() -> None:
    """The shared DB DSN env var name (owned/documented here; db/ M0.3 reads the same one)."""
    assert DB_DSN_ENV_VAR == "CLUE_DATABASE_URL"


def test_secrets_read_db_dsn_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLUE_DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/db")
    # _env_file=None so the loader does not pick up a developer's local .env during the test.
    secrets = Secrets(_env_file=None)  # type: ignore[call-arg]
    assert secrets.database_url is not None
    assert secrets.database_url.get_secret_value().endswith("/db")


def test_secrets_read_provider_keys_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLUE_EXA_API_KEY", "exa-secret-value-123456")
    monkeypatch.setenv("CLUE_FIRECRAWL_API_KEY", "fc-secret-value-7890")
    secrets = Secrets(_env_file=None)  # type: ignore[call-arg]
    assert secrets.exa_api_key is not None
    assert secrets.exa_api_key.get_secret_value() == "exa-secret-value-123456"
    assert secrets.firecrawl_api_key is not None


def test_secrets_default_none_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every key is optional; missing is normal in dev/CI (no live integration in M0)."""
    for var in (
        "CLUE_DATABASE_URL",
        "CLUE_CLAY_API_KEY",
        "CLUE_APOLLO_API_KEY",
        "CLUE_ZOOMINFO_API_KEY",
        "CLUE_BUILTWITH_API_KEY",
        "CLUE_EXA_API_KEY",
        "CLUE_PARALLEL_API_KEY",
        "CLUE_FIRECRAWL_API_KEY",
        "CLUE_CRM_API_KEY",
    ):
        monkeypatch.delenv(var, raising=False)
    secrets = Secrets(_env_file=None)  # type: ignore[call-arg]
    assert secrets.database_url is None
    assert secrets.clay_api_key is None
    assert secrets.crm_api_key is None


def test_secret_value_not_in_repr_or_str(monkeypatch: pytest.MonkeyPatch) -> None:
    """A secret never leaks via repr/str — SecretStr masks it (no plaintext in logs)."""
    monkeypatch.setenv("CLUE_APOLLO_API_KEY", "super-secret-apollo-key")
    secrets = Secrets(_env_file=None)  # type: ignore[call-arg]
    assert "super-secret-apollo-key" not in repr(secrets)
    assert "super-secret-apollo-key" not in str(secrets)


def test_redact_masks_secretstr() -> None:
    assert redact(SecretStr("anything")) == "***REDACTED***"


def test_redact_masks_known_key_pattern() -> None:
    """A known key-pattern value is masked (acceptance criterion)."""
    assert redact("sk-1234567890ABCDEFabcdef") == "***REDACTED***"  # sk- prefix
    assert redact("ghp_aBcDeFgHiJkLmNoPqRsTuVwXyZ012345") == "***REDACTED***"  # GH token
    # A DSN with embedded credentials is masked.
    assert redact("postgresql://user:password@host:5432/db") == "***REDACTED***"
    # A long opaque token is masked.
    assert redact("a" * 40) == "***REDACTED***"


def test_redact_passes_through_non_secret() -> None:
    assert redact("hello") == "hello"
    assert redact("account.recent_funding") == "account.recent_funding"
    assert redact(42) == "42"


def test_is_secret_name() -> None:
    assert is_secret_name("CLUE_DATABASE_URL")
    assert is_secret_name("apollo_api_key")
    assert is_secret_name("auth_token")
    assert is_secret_name("password")
    assert not is_secret_name("entity_id")
    assert not is_secret_name("field_key")


def test_redact_mapping_masks_by_name_and_value() -> None:
    out = redact_mapping(
        {
            "field_key": "account.recent_funding",  # passthrough (name + value safe)
            "api_key": "short",  # masked by NAME even though the value looks innocuous
            "note": "sk-deadbeefdeadbeefdeadbeef",  # masked by VALUE shape
        }
    )
    assert out["field_key"] == "account.recent_funding"
    assert out["api_key"] == "***REDACTED***"
    assert out["note"] == "***REDACTED***"
