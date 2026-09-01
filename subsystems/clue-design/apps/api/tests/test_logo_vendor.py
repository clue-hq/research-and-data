"""Brandfetch vendor rung: settings, parsing, cell mapping, network driver."""

from __future__ import annotations


def test_brandfetch_settings_fields_exist_with_safe_defaults(monkeypatch):
    # Fresh Settings instance so developer .env values don't leak into assertions.
    from py_lumen_config.config import Settings

    for var in (
        "BRANDFETCH_API_KEY",
        "BRANDFETCH_CLIENT_ID",
        "BRANDFETCH_API_BASE_URL",
        "BRANDFETCH_TIMEOUT_S",
    ):
        monkeypatch.delenv(var, raising=False)
    fresh = Settings(_env_file=None)
    assert fresh.brandfetch_api_key == ""
    assert fresh.brandfetch_client_id == ""
    assert fresh.brandfetch_api_base_url == "https://api.brandfetch.io"
    assert fresh.brandfetch_timeout_s == 20.0


def test_brandfetch_settings_load_from_env(monkeypatch):
    from py_lumen_config.config import Settings

    monkeypatch.setenv("BRANDFETCH_API_KEY", "bf_test_key")
    monkeypatch.setenv("BRANDFETCH_CLIENT_ID", "idTESTCLIENT")
    monkeypatch.setenv("BRANDFETCH_TIMEOUT_S", "5.5")
    fresh = Settings(_env_file=None)
    assert fresh.brandfetch_api_key == "bf_test_key"
    assert fresh.brandfetch_client_id == "idTESTCLIENT"
    assert fresh.brandfetch_timeout_s == 5.5
