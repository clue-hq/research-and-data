"""Custom-domain publishing S1 Task 1: the public-pages settings ship their defaults and are
documented."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from clue_config import Secrets, Settings

REPO = Path(__file__).resolve().parents[1]
ENV_EXAMPLE = REPO / ".env.example"

PAGES_SETTING_DEFAULTS: dict[str, object] = {
    "pages_system_suffix": "pages.cluehq.ai",
    "pages_legacy_system_suffixes": "pages.cluehq.ai",
    "pages_public_scheme": "https",
    "pages_public_port": None,
    "pages_trust_host_header": False,
    "pages_origin_port": 8040,
    "pages_cname_target": "pages.cluehq.ai",
    "cloudflare_zone_id": None,
}
PAGES_SECRET_FIELDS = ("pages_edge_secret", "cloudflare_api_token")


def _env_name(field_name: str) -> str:
    return f"CLUE_{field_name.upper()}"


@pytest.fixture
def unset_pages_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in [*PAGES_SETTING_DEFAULTS, *PAGES_SECRET_FIELDS]:
        monkeypatch.delenv(_env_name(name), raising=False)


def test_every_pages_setting_ships_its_default(unset_pages_env: None) -> None:
    settings = Settings(_env_file=None)
    for field_name, default in PAGES_SETTING_DEFAULTS.items():
        assert getattr(settings, field_name) == default, field_name


def test_the_edge_secret_is_optional(unset_pages_env: None) -> None:
    secrets = Secrets(_env_file=None)  # type: ignore[call-arg]
    for field_name in PAGES_SECRET_FIELDS:
        assert field_name in Secrets.model_fields
        assert getattr(secrets, field_name) is None


def test_every_pages_env_name_is_documented_with_its_default() -> None:
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    for field_name, default in PAGES_SETTING_DEFAULTS.items():
        documented = re.search(rf"^{_env_name(field_name)}=(.*)$", text, re.MULTILINE)
        assert documented is not None, f"absent from .env.example: {_env_name(field_name)}"
        value = documented.group(1).strip()
        shipped = (
            ""
            if default is None
            else (str(default).lower() if isinstance(default, bool) else str(default))
        )
        assert value == shipped, field_name
    for field_name in PAGES_SECRET_FIELDS:
        assert re.search(rf"^{_env_name(field_name)}=$", text, re.MULTILINE), field_name


def test_an_empty_public_port_means_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """``source .env`` exports ``CLUE_PAGES_PUBLIC_PORT=`` as the empty string; it must load as
    None."""
    monkeypatch.setenv("CLUE_PAGES_PUBLIC_PORT", "")
    assert Settings(_env_file=None).pages_public_port is None
