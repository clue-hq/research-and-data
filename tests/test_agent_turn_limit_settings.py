"""Deep Agent turn limits are operator settings (founder ruling 2026-09-27): they ship defaults,
honour their env names, are documented in ``.env.example`` with exactly those defaults, and share
the runtime's own round ceiling so a value the runtime would refuse is refused at start-up."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from clue_agents.execution import MAX_RUNTIME_MODEL_ROUNDS
from clue_config import Settings

REPO = Path(__file__).resolve().parents[1]
ENV_EXAMPLE = REPO / ".env.example"

TURN_LIMIT_DEFAULTS: dict[str, object] = {
    "arv2_account_max_model_rounds": 350,
    "arv2_account_max_runtime_s": 0,
    "head_of_abm_max_model_rounds": 350,
    "head_of_abm_turn_timeout_s": 0,
    "agent_long_turn_alert_s": 3600,
}


def _env_name(field_name: str) -> str:
    return f"CLUE_{field_name.upper()}"


def test_turn_limit_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in TURN_LIMIT_DEFAULTS:
        monkeypatch.delenv(_env_name(name), raising=False)
    settings = Settings(_env_file=None)
    for name, default in TURN_LIMIT_DEFAULTS.items():
        assert getattr(settings, name) == default, name


def test_turn_limits_come_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLUE_HEAD_OF_ABM_MAX_MODEL_ROUNDS", "420")
    monkeypatch.setenv("CLUE_ARV2_ACCOUNT_MAX_MODEL_ROUNDS", "200")
    monkeypatch.setenv("CLUE_AGENT_LONG_TURN_ALERT_S", "0")
    settings = Settings(_env_file=None)
    assert settings.head_of_abm_max_model_rounds == 420
    assert settings.arv2_account_max_model_rounds == 200
    assert settings.agent_long_turn_alert_s == 0


@pytest.mark.parametrize(
    "field_name", ["arv2_account_max_model_rounds", "head_of_abm_max_model_rounds"]
)
def test_round_settings_share_the_runtime_ceiling(
    monkeypatch: pytest.MonkeyPatch, field_name: str
) -> None:
    monkeypatch.setenv(_env_name(field_name), str(MAX_RUNTIME_MODEL_ROUNDS))
    assert getattr(Settings(_env_file=None), field_name) == MAX_RUNTIME_MODEL_ROUNDS
    monkeypatch.setenv(_env_name(field_name), str(MAX_RUNTIME_MODEL_ROUNDS + 1))
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_every_turn_limit_is_documented_with_its_default() -> None:
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    for field_name, default in TURN_LIMIT_DEFAULTS.items():
        documented = re.search(rf"^{_env_name(field_name)}=(.*)$", text, re.MULTILINE)
        assert documented is not None, f"absent from .env.example: {_env_name(field_name)}"
        assert float(documented.group(1).strip()) == float(default), field_name  # type: ignore[arg-type]
